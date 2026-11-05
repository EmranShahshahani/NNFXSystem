"""The risk governor of Strategy Documents (Strategy Builder ticket 06).

Pure functions of the document's Risk section, the account the broker
reports, and the bar's time; no hidden state, so a restarted run governs
exactly like an uninterrupted one. In order:

1. base risk: ``risk_per_trade`` (fixed) or ``tiers[score]`` (tiered), capped at 1%;
2. halts (refuse the entry): five losses in a row (48 h), the daily loss limit
   (24 h from the breach), the weekly loss limit (until Monday 00:00 UTC);
3. cuts (the lowest applies): three losses in a row, a rolling win rate below
   40% over 50 trades, a drawdown deeper than 6% (until a new equity high);
4. size on equity resized only at +/-10% milestones.

Losses and wins are closed positions (all their exits, after costs);
a scratch trade (net zero) neither extends nor breaks a streak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from nnfx.engine.types import AccountState, TradeOutcome
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.document import CEILING, RiskSection


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    risk: float  # fraction of the sizing equity
    risk_fraction: float  # fraction of current equity (what the broker sizes on)
    tier: float  # the base risk before governors
    sizing_equity: float
    blocked: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # cuts that applied

    def record(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "risk": self.risk,
            "risk_fraction": self.risk_fraction,
            "sizing_equity": self.sizing_equity,
            "notes": list(self.notes),
        }


def sizing_equity(equity: float, initial: float | None, pct: float | None) -> float:
    """The milestone risk is sized on: it moves only when equity crosses +/-``pct`` steps.

    Milestones sit at initial x (1 + pct)^k above and initial x (1 - pct)^k below;
    the base is the last one crossed on the way out from the initial equity, so
    a small loss or gain does not resize anything.
    """
    if pct is None or not initial or equity <= 0:
        return equity
    if equity >= initial:
        k = math.floor(math.log(equity / initial) / math.log(1 + pct) + 1e-9)
        return initial * (1 + pct) ** k
    k = math.floor(math.log(equity / initial) / math.log(1 - pct) + 1e-9)
    return initial * (1 - pct) ** k


def _t(o: TradeOutcome) -> pd.Timestamp:
    return pd.Timestamp(o.exit_time)


def _streak(outcomes: tuple[TradeOutcome, ...]) -> list[TradeOutcome]:
    """The current run of losses, oldest first (scratch trades skipped)."""
    run: list[TradeOutcome] = []
    for o in reversed(outcomes):
        if o.net_pnl > 0:
            break
        if o.net_pnl < 0:
            run.append(o)
    return run[::-1]


def _breach(
    outcomes: tuple[TradeOutcome, ...], start: pd.Timestamp, balance: float, limit: float
) -> pd.Timestamp | None:
    """When realised losses since ``start`` first reached ``limit`` of that period's start balance."""
    period = [o for o in outcomes if _t(o) >= start]
    start_balance = balance - sum(o.net_pnl for o in period)
    if start_balance <= 0:
        return None
    running = 0.0
    for o in period:
        running += o.net_pnl
        if running <= -limit * start_balance:
            return _t(o)
    return None


def govern(risk: RiskSection, account: AccountState, now: pd.Timestamp, score: int) -> RiskDecision:
    tier = (
        risk.risk_per_trade
        if risk.sizing == "fixed"
        else risk.tiers[min(score, len(risk.tiers) - 1)]
    )
    used = min(tier, CEILING)
    blocked: list[str] = []
    notes: list[str] = []
    outs = account.recent_outcomes

    st = risk.streak
    if st.enabled:
        run = _streak(outs)
        if len(run) >= st.halt_after:
            until = _t(run[st.halt_after - 1]) + pd.Timedelta(hours=st.halt_hours)
            if now < until:
                blocked.append("streak_halt")
        if len(run) >= st.reduce_after and st.reduced_risk < used:
            used, notes = st.reduced_risk, [*notes, "streak_reduced"]

    ll = risk.loss_limits
    if ll.daily is not None:
        # The breach may be yesterday's: a 24 h halt crosses midnight.
        for day in (now.floor("D") - pd.Timedelta(days=1), now.floor("D")):
            hit = _breach(
                tuple(o for o in outs if _t(o) < day + pd.Timedelta(days=1)),
                day,
                account.balance
                - sum(o.net_pnl for o in outs if _t(o) >= day + pd.Timedelta(days=1)),
                ll.daily,
            )
            if hit is not None and now < hit + pd.Timedelta(hours=ll.daily_halt_hours):
                blocked.append("daily_loss_limit")
                break
    if ll.weekly is not None:
        week = now.floor("D") - pd.Timedelta(days=now.weekday())
        if _breach(outs, week, account.balance, ll.weekly) is not None:
            blocked.append("weekly_loss_limit")

    pg = risk.performance
    if pg.enabled:
        decided = [o for o in outs if o.net_pnl != 0][-pg.window :]
        poor = (
            len(decided) >= pg.window
            and sum(o.net_pnl > 0 for o in decided) / len(decided) < pg.min_win_rate
        )
        deep = account.drawdown_from_peak > pg.max_drawdown
        if (poor or deep) and pg.reduced_risk < used:
            used = pg.reduced_risk
        if poor:
            notes.append("performance_win_rate")
        if deep:
            notes.append("performance_drawdown")

    base = sizing_equity(account.equity, account.initial_equity, risk.milestone_pct)
    fraction = used * base / account.equity if account.equity > 0 else 0.0
    return RiskDecision(not blocked, used, fraction, tier, base, blocked, notes)


def leverage_problem(
    risk: RiskSection, inst: InstrumentSpec, entry: float, stop: float
) -> str | None:
    """Why the Leverage Governor refuses this entry, or None (spot instruments are exempt)."""
    if inst.max_leverage <= 1.0:
        return None
    lev = risk.leverage.leverage
    stop_pct = abs(entry - stop) / entry
    cap = 1.0 / (stop_pct * risk.leverage.safety) if stop_pct > 0 else math.inf
    if lev >= cap:
        return f"leverage_governor: {lev:g}x >= 1 / ({stop_pct:.2%} x {risk.leverage.safety:g}) = {cap:.1f}x"
    if lev > inst.max_leverage:
        return f"leverage_governor: {lev:g}x above the venue's {inst.max_leverage:g}x"
    long_ = stop < entry
    gap = 1.0 / lev - inst.maintenance_margin_rate
    liq = entry * (1 - gap) if long_ else entry * (1 + gap)
    if (long_ and liq >= stop) or (not long_ and liq <= stop):
        return f"liquidation_before_stop: liquidation {liq:.6g} comes before the stop {stop:.6g}"
    return None
