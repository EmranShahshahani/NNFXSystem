"""The risk governor of Strategy Documents (Strategy Builder ticket 06, ADR 10 §10).

Two steps per bar. ``update_state`` advances what must be remembered (the
sizing base, a loss-limit halt, the performance cut) from the account the
broker reports; the state travels in ``EngineState`` and is journaled, so a
restarted run resumes it exactly. ``govern`` then decides each candidate:

1. base risk: ``risk_per_trade`` (fixed) or ``tiers[score]`` (tiered), <= 1%;
2. halts refuse the entry: five losses in a row (48 h from the latest), the
   daily loss limit (24 h from the bar it is reached, open losses included),
   the weekly loss limit (until Monday 00:00 UTC);
3. cuts lower its risk (the lowest applies): three losses in a row, and the
   performance cut (rolling win rate below 40% over 50 trades, or drawdown
   beyond 6%), which holds until equity makes a new high;
4. risk is sized on the base, which moves only when equity moves +/-10% from
   it, and never on more than the equity the account has.

Losses and wins are closed positions (all their exits, after costs); a
scratch trade (net zero) neither extends nor breaks a streak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from nnfx.engine.types import AccountState, GovernorState, TradeOutcome
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.document import RiskSection


@dataclass(frozen=True)
class RiskDecision:
    base_risk: float  # the tier (or fixed risk) before cuts
    risk: float  # after cuts, as a fraction of the sizing equity
    risk_fraction: float  # the same risk as a fraction of current equity (the broker sizes on it)
    sizing_equity: float
    blocked: list[str] = field(default_factory=list)  # halts
    cuts: list[str] = field(default_factory=list)  # cuts that lowered the risk

    @property
    def allowed(self) -> bool:
        return not self.blocked

    def record(self) -> dict[str, object]:
        return {
            "base_risk": self.base_risk,
            "risk": self.risk,
            "risk_fraction": self.risk_fraction,
            "sizing_equity": self.sizing_equity,
            "cuts": list(self.cuts),
        }


def next_base(base: float, equity: float, step: float | None) -> float:
    """The sizing base after this bar: it follows equity only on moves of +/-``step``."""
    if step is None or base <= 0:
        return equity
    if equity >= base * (1 + step) or equity <= base * (1 - step):
        return equity
    return base


def _exit_time(o: TradeOutcome) -> pd.Timestamp:
    return pd.Timestamp(o.exit_time)


def loss_streak(outcomes: tuple[TradeOutcome, ...]) -> list[TradeOutcome]:
    """The current run of losses, oldest first (scratch trades skipped)."""
    run: list[TradeOutcome] = []
    for o in reversed(outcomes):
        if o.net_pnl > 0:
            break
        if o.net_pnl < 0:
            run.append(o)
    return run[::-1]


def _period_loss(account: AccountState, start: pd.Timestamp) -> float:
    """Loss since ``start`` (closed and open) as a fraction of that period's starting balance."""
    closed = sum(o.net_pnl for o in account.recent_outcomes if _exit_time(o) >= start)
    start_balance = account.balance - closed
    return (account.equity - start_balance) / start_balance if start_balance > 0 else 0.0


def _poor_win_rate(risk: RiskSection, account: AccountState) -> bool:
    pg = risk.performance
    decided = [o for o in account.recent_outcomes if o.net_pnl != 0][-pg.window :]
    return (
        len(decided) >= pg.window
        and sum(o.net_pnl > 0 for o in decided) / len(decided) < pg.min_win_rate
    )


def update_state(
    risk: RiskSection, account: AccountState, now: pd.Timestamp, g: GovernorState
) -> GovernorState:
    """Advance the governor's memory by one bar."""
    base = g.risk_base if g.risk_base is not None else (account.initial_equity or account.equity)
    base = next_base(base, account.equity, risk.milestone_pct)

    halted_until, reason = g.halted_until, g.halt_reason
    if halted_until is not None and now >= pd.Timestamp(halted_until):
        halted_until = reason = None
    ll = risk.loss_limits
    if (
        halted_until is None
        and ll.daily is not None
        and _period_loss(account, now.floor("D")) <= -ll.daily
    ):
        halted_until = (now + pd.Timedelta(hours=ll.daily_halt_hours)).isoformat()
        reason = "daily_loss_limit"
    if halted_until is None and ll.weekly is not None:
        week = now.floor("D") - pd.Timedelta(days=now.weekday())
        if _period_loss(account, week) <= -ll.weekly:
            halted_until, reason = (week + pd.Timedelta(days=7)).isoformat(), "weekly_loss_limit"

    pg = risk.performance
    cut = g.performance_cut
    if pg.enabled:
        if _poor_win_rate(risk, account) or account.drawdown_from_peak > pg.max_drawdown:
            cut = True
        elif account.equity >= account.peak_equity:
            cut = False  # equity recovered to a new high
    else:
        cut = False
    return GovernorState(
        risk_base=base, halted_until=halted_until, halt_reason=reason, performance_cut=cut
    )


def govern(
    risk: RiskSection, account: AccountState, now: pd.Timestamp, score: int, g: GovernorState
) -> RiskDecision:
    """The risk for one candidate, or why it is refused."""
    base_risk = (
        risk.risk_per_trade
        if risk.sizing == "fixed"
        else risk.tiers[min(score, len(risk.tiers) - 1)]
    )
    applied, blocked, cuts = base_risk, [], []

    st = risk.streak
    if st.enabled:
        run = loss_streak(account.recent_outcomes)
        if len(run) >= st.halt_after and now < _exit_time(run[-1]) + pd.Timedelta(
            hours=st.halt_hours
        ):
            blocked.append("streak_halt")
        if len(run) >= st.reduce_after and st.reduced_risk < applied:
            applied = st.reduced_risk
            cuts.append("streak")
    if g.halted_until is not None and now < pd.Timestamp(g.halted_until) and g.halt_reason:
        blocked.append(g.halt_reason)
    if g.performance_cut and risk.performance.reduced_risk < applied:
        applied = risk.performance.reduced_risk
        cuts.append("performance")

    base = g.risk_base if g.risk_base is not None else account.equity
    sizing = min(base, account.equity)  # never size on equity the account no longer has
    fraction = applied * sizing / account.equity if account.equity > 0 else 0.0
    return RiskDecision(base_risk, applied, fraction, sizing, blocked, cuts)


def leverage_problem(
    risk: RiskSection, inst: InstrumentSpec, entry: float, stop: float
) -> tuple[str, str] | None:
    """(reason code, detail) if the Leverage Governor refuses; None if fine or spot."""
    if inst.max_leverage <= 1.0:
        return None
    lev, safety = risk.leverage.leverage, risk.leverage.safety
    stop_pct = abs(entry - stop) / entry
    cap = 1.0 / (stop_pct * safety) if stop_pct > 0 else math.inf
    if lev >= cap:
        return "leverage_governor", f"{lev:g}x >= 1 / ({stop_pct:.2%} x {safety:g}) = {cap:.1f}x"
    if lev > inst.max_leverage:
        return "leverage_governor", f"{lev:g}x above the venue's {inst.max_leverage:g}x"
    long_ = stop < entry
    gap = 1.0 / lev - inst.maintenance_margin_rate
    liq = entry * (1 - gap) if long_ else entry * (1 + gap)
    if (long_ and liq >= stop) or (not long_ and liq <= stop):
        return "liquidation_before_stop", f"liquidation {liq:.6g} comes before the stop {stop:.6g}"
    return None


def margin(risk: RiskSection, risk_cash: float, entry: float, stop: float) -> float:
    """Margin the position ties up: notional / leverage (leverage never changes risk)."""
    stop_pct = abs(entry - stop) / entry
    return risk_cash / stop_pct / risk.leverage.leverage if stop_pct > 0 else 0.0
