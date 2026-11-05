"""The risk governor of Strategy Documents (Strategy Builder ticket 06)."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.data.bars import BarFrame
from nnfx.engine.types import AccountState, TradeOutcome
from nnfx.instruments import crypto_spec
from nnfx.journal.journal import Journal
from nnfx.strategy import validate_document
from nnfx.strategy.document import RiskSection
from nnfx.strategy.risk import govern, leverage_problem, sizing_equity
from nnfx.strategy.run import backtest_document
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, SYM, TO_STOP, TO_TARGET

T0 = pd.Timestamp("2024-03-04 00:00", tz="UTC")  # a Monday


def outcome(hours: float, pnl: float, risk: float = 50.0, sym: str = SYM) -> TradeOutcome:
    t = (T0 + pd.Timedelta(hours=hours)).isoformat()
    return TradeOutcome(
        position_id=f"{sym}#{hours}", symbol=sym, exit_time=t, net_pnl=pnl, risk_cash=risk
    )


def account(*outcomes: TradeOutcome, equity: float = 10_000.0, dd: float = 0.0) -> AccountState:
    realised = sum(o.net_pnl for o in outcomes)
    return AccountState(
        equity=equity,
        balance=equity,
        peak_equity=max(equity, 10_000.0 + max(0.0, realised)),
        initial_equity=10_000.0,
        drawdown_from_peak=dd,
        recent_outcomes=tuple(outcomes),
    )


def at(hours: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(hours=hours)


# ------------------------------------------------------------ the section
def test_the_risk_section_has_the_blueprint_defaults_and_a_one_percent_ceiling():
    r = RiskSection()
    assert (r.sizing, r.risk_per_trade, r.tiers) == ("fixed", 0.005, (0.0025, 0.005, 0.0075, 0.01))
    assert (
        r.streak.reduce_after,
        r.streak.reduced_risk,
        r.streak.halt_after,
        r.streak.halt_hours,
    ) == (
        3,
        0.0025,
        5,
        48,
    )
    assert (r.loss_limits.daily, r.loss_limits.daily_halt_hours, r.loss_limits.weekly) == (
        0.015,
        24,
        None,
    )
    assert (r.performance.window, r.performance.min_win_rate, r.performance.max_drawdown) == (
        50,
        0.40,
        0.06,
    )
    assert r.milestone_pct == 0.10 and r.leverage.leverage == 1.0 and r.leverage.safety == 1.5
    with pytest.raises(ValueError):
        RiskSection(tiers=(0.0025, 0.005, 0.0075, 0.02))
    with pytest.raises(ValueError):
        RiskSection(tiers=(0.005, 0.0025))  # tiers rise with conviction


# ------------------------------------------------------------------ tiers
def test_tiered_sizing_follows_the_confluence_score_and_never_passes_one_percent():
    r = RiskSection(sizing="tiered")
    assert [govern(r, account(), at(1), score=k).risk for k in range(6)] == [
        0.0025,
        0.005,
        0.0075,
        0.01,
        0.01,
        0.01,
    ]
    assert govern(RiskSection(), account(), at(1), score=3).risk == 0.005  # fixed ignores the score


# ----------------------------------------------------------------- streak
def test_three_losses_cut_risk_and_a_win_restores_it():
    r = RiskSection()
    losses = [outcome(h, -50) for h in (1, 2, 3)]
    d = govern(r, account(*losses), at(4), score=0)
    assert d.allowed and d.risk == 0.0025 and "streak_reduced" in d.notes
    assert govern(r, account(*losses, outcome(4, 120)), at(5), score=0).risk == 0.005
    assert govern(r, account(*losses[:2]), at(4), score=0).risk == 0.005


def test_five_losses_halt_for_48_hours_then_trade_at_reduced_risk():
    r = RiskSection(loss_limits={"daily": None})
    five = [outcome(h, -50) for h in (1, 2, 3, 4, 5)]
    d = govern(r, account(*five), at(6), score=0)
    assert not d.allowed and d.blocked == ["streak_halt"]
    assert not govern(r, account(*five), at(5 + 47.9), score=0).allowed
    after = govern(r, account(*five), at(5 + 48), score=0)
    assert after.allowed and after.risk == 0.0025  # still in the streak until a win


def test_streak_rules_can_be_switched_off_or_retuned():
    five = [outcome(h, -50) for h in (1, 2, 3, 4, 5)]
    off = RiskSection(streak={"enabled": False}, loss_limits={"daily": None})
    assert govern(off, account(*five), at(6), score=0).risk == 0.005
    loose = RiskSection(streak={"reduce_after": 6, "halt_after": 8}, loss_limits={"daily": None})
    assert govern(loose, account(*five), at(6), score=0).allowed


# ------------------------------------------------------------ loss limits
def test_the_daily_loss_limit_halts_for_24_hours_from_the_breach():
    r = RiskSection(streak={"enabled": False})
    # -1.6% of the day's starting balance, crossed by the second loss at 10:00.
    day = [outcome(9, -80), outcome(10, -80)]
    acct = account(*day, equity=9_840.0)
    assert govern(r, acct, at(10.5), score=0).blocked == ["daily_loss_limit"]
    assert govern(r, acct, at(33.9), score=0).blocked == ["daily_loss_limit"]  # next day, < 24h
    assert govern(r, acct, at(34), score=0).allowed
    assert govern(r, account(outcome(9, -80), equity=9_920.0), at(10), score=0).allowed  # -0.8%


def test_a_weekly_loss_limit_halts_until_the_next_week():
    r = RiskSection(streak={"enabled": False}, loss_limits={"daily": None, "weekly": 0.03})
    week = [outcome(h, -110) for h in (2, 26, 50)]  # Mon, Tue, Wed: -3.3% this week
    acct = account(*week, equity=9_670.0)
    assert govern(r, acct, at(51), score=0).blocked == ["weekly_loss_limit"]
    assert govern(r, acct, at(24 * 7 - 1), score=0).blocked == ["weekly_loss_limit"]
    assert govern(r, acct, at(24 * 7), score=0).allowed  # Monday 00:00


# ------------------------------------------------------------ performance
def test_poor_rolling_win_rate_or_deep_drawdown_cut_risk():
    r = RiskSection(streak={"enabled": False}, loss_limits={"daily": None})
    poor = [outcome(h, 60 if h % 5 == 0 else -50) for h in range(50)]  # 20% winners
    assert govern(r, account(*poor), at(60), score=0).risk == 0.0025
    fine = [outcome(h, 60 if h % 2 == 0 else -50) for h in range(50)]  # 50% winners
    assert govern(r, account(*fine), at(60), score=0).risk == 0.005
    assert govern(r, account(*poor[:49]), at(60), score=0).risk == 0.005  # not 50 trades yet
    deep = govern(r, account(dd=0.065), at(1), score=0)
    assert deep.risk == 0.0025 and "performance_drawdown" in deep.notes


# ------------------------------------------------------------- milestones
def test_risk_is_resized_only_at_ten_percent_equity_milestones():
    assert sizing_equity(10_900.0, 10_000.0, 0.10) == 10_000.0
    assert sizing_equity(11_050.0, 10_000.0, 0.10) == pytest.approx(11_000.0)
    assert sizing_equity(12_200.0, 10_000.0, 0.10) == pytest.approx(12_100.0)
    assert sizing_equity(9_500.0, 10_000.0, 0.10) == 10_000.0  # a small loss resizes nothing
    assert sizing_equity(8_900.0, 10_000.0, 0.10) == pytest.approx(9_000.0)  # the -10% step
    assert sizing_equity(9_500.0, 10_000.0, None) == 9_500.0
    d = govern(RiskSection(), account(equity=10_900.0), at(1), score=0)
    assert d.risk_fraction == pytest.approx(0.005 * 10_000.0 / 10_900.0)


# --------------------------------------------------------------- leverage
def test_the_leverage_governor_and_the_liquidation_check():
    perp = crypto_spec(SYM, "crypto_perp")
    r = RiskSection(leverage={"leverage": 10.0})
    # stop 2% away: max leverage 1 / (0.02 x 1.5) = 33x, liquidation ~9.5% away: fine.
    assert leverage_problem(r, perp, entry=100.0, stop=98.0) is None
    # stop 8% away: max 8.3x, so 10x is refused.
    assert "leverage_governor" in str(leverage_problem(r, perp, entry=100.0, stop=92.0))
    tight = RiskSection(leverage={"leverage": 10.0, "safety": 1.0})
    assert "liquidation_before_stop" in str(leverage_problem(tight, perp, entry=100.0, stop=90.2))
    assert leverage_problem(r, crypto_spec(SYM, "crypto_spot"), entry=100.0, stop=92.0) is None


# ======================================================== harness level
def frame(
    rows: list[tuple[float, float, float, float]], symbol: str = SYM, mark: bool = False
) -> BarFrame:
    a = np.asarray(rows)
    idx = pd.date_range(pd.Timestamp("2024-03-01 00:15", tz="UTC"), periods=len(a), freq="15min")
    cols: dict[str, Any] = {
        "open": a[:, 0],
        "high": a[:, 1],
        "low": a[:, 2],
        "close": a[:, 3],
        "volume": 1.0,
    }
    if mark:
        cols.update(mark_high=a[:, 1], mark_low=a[:, 2], mark_close=a[:, 3])
    return BarFrame(
        pd.DataFrame(cols, index=idx),
        symbol,
        timeframe="M15",
        volume_kind="traded",
        price_venue="x",
    )


def losing_cycles(n: int) -> list[tuple[float, float, float, float]]:
    """``n`` repeats of rise, Candle Setup, fill, stop-out (each loses 1R)."""
    return [*RISE, SETUP, FILL, *TO_STOP] * n


def run(rows, raw: dict[str, Any], frames=None, instruments=None):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    journal = Journal()
    out = backtest_document(
        res.document, frames or {SYM: frame(rows)}, instruments or {SYM: BTC}, journal=journal
    )
    evs = [ev for r in journal.records("cycle") for ev in r["evaluations"]]
    return out, evs


def doc(**risk: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["risk"] = {"risk_per_trade": 0.005, **risk}
    return raw


def test_harness_a_losing_streak_drops_risk_and_then_halts():
    out, evs = run(losing_cycles(7), doc(loss_limits={"daily": None}))
    risks = [round(t.risk_cash / out.result.initial_equity, 4) for t in out.result.trades]
    # Trades 1-3 at the base 0.5%; 4 and 5 at 0.25%; then the 48h halt refuses the rest.
    assert risks[:3] == [0.005, 0.005, 0.005] and all(abs(r - 0.0025) < 3e-4 for r in risks[3:5])
    assert len(out.result.trades) == 5
    assert [e["blocked"] for e in evs[5:]] == [["streak_halt"], ["streak_halt"]]
    assert evs[3]["values"]["risk"]["notes"] == ["streak_reduced"]


def test_harness_the_daily_loss_limit_refuses_further_entries():
    out, evs = run(losing_cycles(5), doc(risk_per_trade=0.01, streak={"enabled": False}))
    # Two 1% losses breach -1.5%: the third setup the same day is refused.
    assert len(out.result.trades) == 2 and evs[2]["blocked"] == ["daily_loss_limit"]


def test_harness_resting_orders_count_against_the_open_risk_cap():
    rows = [*RISE, SETUP, FILL, *TO_TARGET]
    frames = {SYM: frame(rows), "ETH/USDT": frame(rows, "ETH/USDT")}
    inst = {SYM: BTC, "ETH/USDT": crypto_spec("ETH/USDT", "crypto_spot")}
    _, evs = run(rows, doc(max_open_risk=0.006), frames, inst)
    blocked = {e["symbol"]: e["blocked"] for e in evs}
    # BTC's resting order already holds 0.5% of the 0.6% budget, so ETH's is refused.
    assert blocked == {SYM: [], "ETH/USDT": ["open_risk_cap"]}


def test_harness_the_leverage_governor_refuses_and_journals():
    perp = crypto_spec(SYM, "crypto_perp")
    rows = [*RISE, SETUP, FILL, *TO_TARGET]
    out, evs = run(
        rows, doc(leverage={"leverage": 20.0}), {SYM: frame(rows, mark=True)}, {SYM: perp}
    )
    # The setup's stop is 4.8% away: 20x would liquidate first, and exceeds 1/(4.8% x 1.5) = 13.9x.
    assert out.result.trades == [] and evs[0]["blocked"][0].startswith("leverage_governor")


def test_harness_an_entry_without_a_stop_is_refused():
    from nnfx.strategy.library import StructuralStop

    original = StructuralStop.initial_stop
    StructuralStop.initial_stop = lambda self, c, d: float("nan")  # type: ignore[method-assign]
    try:
        out, evs = run([*RISE, SETUP, FILL, *TO_TARGET], doc())
    finally:
        StructuralStop.initial_stop = original  # type: ignore[method-assign]
    assert out.result.trades == [] and evs[0]["blocked"] == ["no_stop"]


def test_resting_orders_count_against_the_risk_managers_exposure_caps():
    from nnfx.config import RiskConfig
    from nnfx.engine.types import OpenIntent, PendingOrderView
    from nnfx.risk.manager import RiskManager, SizedOrder

    syms = ["BTC/USDT", "BTC/USDC", "BTC/DAI"]
    inst = {s: crypto_spec(s, "crypto_spot") for s in syms}

    def resting(sym: str) -> PendingOrderView:
        return PendingOrderView(
            order_id=sym, key=sym, symbol=sym, direction=1, level=100.0, trigger=100.0, stop=95.0,
            target=None, invalidation=None, expires_after_bars=4, bars_active=1, oco_group=None,
            placed_time="2024-03-01T00:00:00+00:00", risk_cash=50.0,
        )  # fmt: skip

    intent = OpenIntent(
        symbol="BTC/DAI", direction=1, leg="single", leg_index=0, entry_type="setup",
        signal_time="s", atr=1.0, stop_distance=5.0, target_distance=None,
        risk_fraction=0.005, idempotency_key="k",
    )  # fmt: skip
    sized = SizedOrder(intent, 10.0, 50.0, 50.0)
    mgr = RiskManager(RiskConfig(max_positions_per_ccy=2))
    free = AccountState(equity=10_000.0, balance=10_000.0, peak_equity=10_000.0)
    assert mgr.approve(sized, inst["BTC/DAI"], free, [], inst).approved
    two_resting = free.model_copy(
        update={"pending_orders": (resting("BTC/USDT"), resting("BTC/USDC"))}
    )
    dec = mgr.approve(sized, inst["BTC/DAI"], two_resting, [], inst)
    assert not dec.approved and "exposure_cap" in dec.reason
