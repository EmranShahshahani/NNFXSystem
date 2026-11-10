"""Fibonacci (Strategy Builder ticket 19): causal anchors, log scale, confluence, targets."""

from __future__ import annotations

import math

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, SetupCandidate, StrategyData
from nnfx.strategy.fibonacci import (
    EXTENSIONS,
    FibConfluence,
    FibConfluenceParams,
    FibReclaim,
    FibReclaimParams,
    confluence,
    extension,
    fib_track,
    retracement,
)
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from tests.test_strategy_blocks import position
from tests.test_strategy_engine import BTC, frame
from tests.test_strategy_oscillators import ROLES, cand

Row = tuple[float, float, float, float]
A, B = 100.0, 130.0
L382 = B * (A / B) ** 0.382  # 117.6: the 38.2% retracement on a log scale
LEG_END = 30  # the bar of the impulse high; its swing is confirmed two bars later
SWEEP = 55


def legs(points: dict[int, float], n: int) -> list[Row]:
    """Rows from turning points, linear between them; a wick only on the side a bar moves
    toward, so every turn is a strict swing."""
    bars = sorted(points)
    closes = np.interp(np.arange(n), bars, [points[b] for b in bars])
    rows, prev = [], float(closes[0])
    for c in map(float, closes):
        top, bottom = (c + 0.2, prev) if c >= prev else (prev, c - 0.2)
        rows.append((prev, top, bottom, c))
        prev = c
    return rows


def uptrend(extra: dict[int, float] | None = None, n: int = 80) -> list[Row]:
    """An impulse 100 -> 130, a pullback to ~118 that rests just above the 38.2% line, then
    ``extra`` turning points."""
    pts = {0: 108.0, 10: A, LEG_END: B, 44: 118.2, 54: 118.2, n - 1: 118.2, **(extra or {})}
    return legs(pts, n)


def level(d: StrategyData, ratio: float = 0.382) -> float:
    """The retracement level of the leg the data holds at the sweep (anchors are the wicks)."""
    t = fib_track(d, "lwc", 2, 1.0)
    return retracement(float(t.a[SWEEP]), float(t.b[SWEEP]), ratio)


def sweep(rows: list[Row], low: float = 116.0, close: float = 118.1) -> list[Row]:
    out = list(rows)
    out[SWEEP] = (118.2, 118.4, low, close)  # wicks under 117.6 and closes back over it
    return out


def build(rows: list[Row], roles: dict[str, str] | None = None) -> StrategyData:
    return StrategyData.build(frame(rows), roles or ROLES, BTC, SessionConfig())


# ------------------------------------------------------------------ the maths
def test_retracements_are_measured_on_a_log_scale():
    arithmetic = B - 0.5 * (B - A)
    assert retracement(A, B, 0.5) == pytest.approx(math.sqrt(A * B))
    assert retracement(A, B, 0.5) < arithmetic
    assert retracement(A, B, 0.382) == pytest.approx(L382)
    assert retracement(A, B, 0) == pytest.approx(B) and retracement(A, B, 1) == pytest.approx(A)
    # a down-leg retraces upward
    assert retracement(B, A, 0.5) == pytest.approx(math.sqrt(A * B))


def test_extensions_project_the_leg_from_c_on_a_log_scale():
    c = 118.0
    assert EXTENSIONS == (1.0, 1.272, 1.618, 2.0)
    assert extension(A, B, c, 1.0) == pytest.approx(c * B / A)
    assert extension(A, B, c, 1.618) == pytest.approx(c * (B / A) ** 1.618)
    assert extension(B, A, 150.0, 1.0) == pytest.approx(150.0 * A / B)  # a down-leg goes down


def test_the_levels_are_the_same_proportions_at_any_price():
    k = 7.5
    assert retracement(A * k, B * k, 0.382) == pytest.approx(L382 * k)
    assert extension(A * k, B * k, 118 * k, 1.272) == pytest.approx(extension(A, B, 118, 1.272) * k)


# ------------------------------------------------------------------ the leg
def test_the_blocks_have_the_right_kinds():
    assert REGISTRY["fib_reclaim"].kind == BlockKind.SETUP
    assert REGISTRY["fib_confluence"].kind == BlockKind.CONFIRMATION


def test_a_leg_exists_only_once_the_impulse_has_ended():
    d = build(uptrend())
    t = fib_track(d, "lwc", 2, 1.0)
    assert not t.direction[: LEG_END + 2].any()  # the high is not confirmed before bar 32
    assert t.direction[LEG_END + 2] == 1
    assert (
        t.a[LEG_END + 2] == pytest.approx(d.base.low[10])
        and t.b[LEG_END + 2] == d.base.high[LEG_END]
    )


def test_the_anchor_is_the_lowest_swing_since_the_previous_high_not_an_inner_wick():
    pts = {0: 108.0, 5: 112.0, 10: A, 16: 108.0, 20: 104.0, 24: 112.0, LEG_END: B}
    d = build(legs({**pts, 44: 118.2, 79: 118.2}, 80))
    t = fib_track(d, "lwc", 2, 1.0)
    assert t.a[LEG_END + 2] == pytest.approx(d.base.low[10])  # not the higher low at 20


def test_a_tiny_swing_is_no_impulse():
    d = build(uptrend())
    assert not fib_track(d, "lwc", 2, 40.0).direction.any()


def test_the_retracement_low_c_appears_only_when_confirmed_and_inside_the_leg():
    d = build(uptrend())
    t = fib_track(d, "lwc", 2, 1.0)
    assert not np.isfinite(t.c[: 44 + 2]).any()
    assert np.isfinite(t.c[60]) and t.c[60] == pytest.approx(d.base.low[44], abs=0.3)


def test_a_close_beyond_the_start_kills_the_leg():
    d = build(uptrend({60: 97.0, 79: 97.0}))
    t = fib_track(d, "lwc", 2, 1.0)
    assert t.direction[55] == 1 and t.direction[75] == 0


def test_a_higher_high_moves_the_end_and_forgets_c():
    d = build(uptrend({60: 140.0, 66: 128.0, 79: 128.0}))
    t = fib_track(d, "lwc", 2, 1.0)
    assert t.b[58] == d.base.high[LEG_END] and np.isfinite(t.c[58])
    assert t.b[63] == pytest.approx(d.base.high[60]) and not np.isfinite(t.c[63])


def test_the_fib_track_is_causal():
    d = build(sweep(uptrend()))
    full = fib_track(d, "lwc", 2, 1.0)
    for n in (33, 47, 56, 70):
        part = fib_track(d.head(n), "lwc", 2, 1.0)
        for name in ("direction", "a", "b", "c"):
            assert np.array_equal(getattr(part, name), getattr(full, name)[:n], equal_nan=True)


# --------------------------------------------------------------- the reclaim
NEAR = {"sma_fast": 3, "sma_slow": 5, "tol_atr": 1.5}  # short averages resting on the level


def reclaim(**kw: object) -> FibReclaim:
    return FibReclaim(FibReclaimParams(min_impulse_atr=1.0, **kw))


def test_a_sweep_below_the_382_that_closes_back_over_it_is_a_long():
    d = build(sweep(uptrend()))
    out = reclaim(**NEAR, min_confluence=1).compute(d)
    assert list(np.flatnonzero(out.direction)) == [SWEEP]
    assert out.trigger[SWEEP] == d.base.high[SWEEP] and out.stop[SWEEP] == d.base.low[SWEEP]
    assert out.meta["level"][SWEEP] == pytest.approx(level(d))


def test_closing_under_the_level_is_a_failed_pullback_not_a_reclaim():
    d = build(sweep(uptrend(), close=117.0))
    assert not reclaim(**NEAR, min_confluence=1).compute(d).direction.any()


def test_a_lone_fib_level_never_produces_a_candidate():
    with pytest.raises(ValueError):
        FibReclaimParams(min_confluence=0)  # the rule cannot be switched off
    d = build(sweep(uptrend()))
    assert not reclaim().compute(d).direction.any()  # the default asks for two other factors
    assert not reclaim(min_confluence=2).compute(d).direction.any()


def test_with_other_factors_on_the_level_the_reclaim_stands():
    d = build(sweep(uptrend()))
    # The pullback rested just over the level: two short SMAs sit on it.
    out = reclaim(sma_fast=3, sma_slow=5, tol_atr=1.5).compute(d)
    assert out.direction[SWEEP] == 1
    # a level, SMA 3 and SMA 5 are the most there are: a fourth factor is never met
    assert (
        not reclaim(sma_fast=3, sma_slow=5, tol_atr=1.5, min_confluence=4)
        .compute(d)
        .direction.any()
    )


def test_the_mirror_down_leg_gives_a_short():
    k = 10_000.0
    rows = [(k / o, k / lo, k / h, k / c) for o, h, lo, c in sweep(uptrend())]
    d = build(rows)
    out = reclaim(**NEAR, min_confluence=1).compute(d)
    assert out.direction[SWEEP] == -1 and out.trigger[SWEEP] == d.base.low[SWEEP]
    assert out.meta["level"][SWEEP] == pytest.approx(level(d))


# ------------------------------------------------------------- the confluence
def test_confluence_counts_levels_and_averages_at_the_price():
    base = [100.0 + (1.0 if k % 2 else -1.0) for k in range(60)]
    path = {k: v for k, v in enumerate(base)}
    path.update({k: 110.0 for k in (10, 22, 34)})  # three swing highs at 110
    rows = legs(path, 60)
    d = build(rows)
    p = FibConfluenceParams(sma_fast=5, sma_slow=9, tol_atr=0.5)
    found = confluence(d, p, 59, 110.0)
    assert "level" in found
    assert confluence(d, p, 59, 150.0) == []
    near = confluence(d, p, 59, float(d.sma("lwc", 5)[59]))
    assert "sma5" in near


def candidate(d: StrategyData, direction: int = 1) -> SetupCandidate:
    c = cand(d, SWEEP, direction)
    return SetupCandidate(
        c.symbol, c.setup, c.block_index, c.bar, c.time, direction, 118.4, 116.0, 116.0
    )


def test_the_confirmation_passes_with_enough_factors_and_fails_a_lone_line():
    d = build(sweep(uptrend()))
    ok = FibConfluence(
        FibConfluenceParams(min_impulse_atr=1.0, sma_fast=3, sma_slow=5, tol_atr=1.5)
    )
    alone = FibConfluence(FibConfluenceParams(min_impulse_atr=1.0))
    assert ok.check(candidate(d), d).outcome == "pass"
    res = alone.check(candidate(d), d)
    assert res.outcome == "fail" and "alone" in res.reason


def test_the_confirmation_wants_a_level_in_range_and_a_leg_with_the_trade():
    d = build(sweep(uptrend()))
    p = FibConfluenceParams(
        min_impulse_atr=1.0, min_confluence=1, sma_fast=3, sma_slow=5, tol_atr=1.5
    )
    block = FibConfluence(p)
    assert block.check(candidate(d), d).outcome == "pass"
    assert block.check(candidate(d, -1), d).outcome == "fail"  # the leg runs against a short
    c = candidate(d)
    far = SetupCandidate(c.symbol, c.setup, c.block_index, c.bar, c.time, 1, 126.0, 124.0, 124.0)
    assert block.check(far, d).outcome == "fail"  # no retracement level is in the range


def test_without_a_leg_the_confirmation_is_na():
    d = build(uptrend())
    c = cand(d, 5)
    assert FibConfluence(FibConfluenceParams()).check(c, d).outcome == "na"


# --------------------------------------------------------------- the target
def reasons(block: ProfitChain, d: StrategyData, filled: int, direction: int = 1) -> set[str]:
    pv = position(block, cand(d, SWEEP, direction), d, filled)
    return {getattr(block.manage(pv, d, j), "reason", "") for j in range(SWEEP + 1, len(d))}


def test_the_extension_target_closes_what_remains_after_the_first_step():
    target = extension(A, B, 118.0, 1.0)  # ~153
    d = build(uptrend({66: target + 3, 72: target - 3, 79: target - 3}))
    on = ProfitChain(ProfitChainParams(fib_target="1.0", fib_min_impulse_atr=1.0))
    assert "fib_ext_1.0" in reasons(on, d, 1)
    assert "fib_ext_1.0" not in reasons(on, d, 0)  # the 2R floor
    assert "fib_ext_1.0" not in reasons(ProfitChain(), d, 1)
    far = ProfitChain(ProfitChainParams(fib_target="2.0", fib_min_impulse_atr=1.0))
    assert not any(r.startswith("fib_ext") for r in reasons(far, d, 1))


def test_no_target_without_a_validated_retracement():
    rows = legs({0: 108.0, 10: A, LEG_END: B, 36: 128.0, 79: 128.0}, 80)
    o, _, lo, c = rows[36]
    rows[36] = (o, 500.0, lo, c)  # a spike far past any target, before the retracement is known
    d = build(rows)
    t = fib_track(d, "lwc", 2, 1.0)
    assert t.direction[36] == 1 and not np.isfinite(t.c[36])
    on = ProfitChain(ProfitChainParams(fib_target="1.0", fib_min_impulse_atr=1.0))
    pv = position(on, cand(d, 33), d, 1)
    assert not getattr(on.manage(pv, d, 36), "reason", "").startswith("fib_ext")
