"""Bollinger rules (Strategy Builder ticket 18): fire / no-fire fixtures per rule."""

from __future__ import annotations

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY
from nnfx.strategy.bands import (
    BbHtfTouch,
    BbRunway,
    BbRunwayParams,
    BbSqueeze,
    BbSqueezeParams,
    BbTouchParams,
    bandwidth,
    runway_lost,
    runway_state,
)
from nnfx.strategy.blocks import BlockKind, StrategyData
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from tests.test_strategy_engine import BTC, frame
from tests.test_strategy_oscillators import FLAT, ROLES, cand, outcomes, ramp, rows_of


def build(rows: list[list[float]]) -> StrategyData:
    return StrategyData.build(frame([tuple(r) for r in rows]), ROLES, BTC, SessionConfig())


def zigzag(waves: int, sign: int = 1) -> list[float]:
    """Three steps with the trend, two against: a Dow trend with pullbacks."""
    path, v = [], 100.0
    for _ in range(waves):
        for s in (3, 3, 3, -2, -2):
            v += sign * s
            path.append(v)
    return path


def rows(closes: list[float]) -> list[list[float]]:
    return [list(r) for r in rows_of(closes)]


TOUCH = BbHtfTouch(BbTouchParams(htf_role="lwc", mode="touch"))
CROSS = BbHtfTouch(BbTouchParams(htf_role="lwc", mode="cross"))


def test_the_new_blocks_are_registered_with_the_right_kinds():
    kinds = {
        "bb_htf_touch": BlockKind.SETUP,
        "bb_squeeze": BlockKind.SETUP,
        "bb_runway": BlockKind.CONFIRMATION,
    }
    for t, kind in kinds.items():
        assert REGISTRY[t].kind == kind


# ------------------------------------------------------------------ touch
def test_a_lower_band_rejection_in_an_up_trend_is_a_long():
    r = rows(zigzag(20))
    r[80][2] -= 40  # the low pierces the lower band; the close stays where it was
    d = build(r)
    assert d.dow("lwc", 2)[80] == 1
    out = TOUCH.compute(d)
    assert list(np.flatnonzero(out.direction)) == [80] and out.direction[80] == 1
    assert out.trigger[80] == d.base.high[80] and out.stop[80] == d.base.low[80]


def test_the_same_touch_in_a_down_trend_is_no_long_and_a_flat_state_gives_nothing():
    # Up-trend touch of the UPPER band is a short only in a down-trend: never against it.
    r = rows(zigzag(20))
    r[80][1] += 40
    assert 80 not in np.flatnonzero(TOUCH.compute(build(r)).direction)
    flat = rows(FLAT + FLAT)
    flat[30][2] -= 40
    d = build(flat)
    assert d.dow("lwc", 2)[30] == 0
    assert not TOUCH.compute(d).direction.any()


def test_a_down_trend_mirrors_it_with_a_short_at_the_upper_band():
    r = rows(zigzag(20, -1))
    r[80][1] += 40
    d = build(r)
    out = TOUCH.compute(d)
    assert d.dow("lwc", 2)[80] == -1 and out.direction[80] == -1
    assert out.trigger[80] == d.base.low[80]


def test_a_close_back_over_the_middle_line_is_a_cross_long_in_an_up_trend():
    path = zigzag(14)
    path = [*path, path[-1] - 25, path[-1] - 30, path[-1] - 27, path[-1] + 5]
    d = build(rows(path))
    out = CROSS.compute(d)
    assert d.dow("lwc", 2)[-1] == 1
    assert list(np.flatnonzero(out.direction)) == [len(d) - 1]
    assert not TOUCH.compute(d).direction[-1]  # touch mode wants a pierced band, not this
    either = BbHtfTouch(BbTouchParams(htf_role="lwc"))
    assert either.compute(d).direction[-1] == 1


def test_the_htf_role_is_the_one_that_directs():
    r = rows(zigzag(20))
    r[80][2] -= 40
    d = build(r)  # all roles are M15 here, so hwc agrees with lwc
    assert BbHtfTouch(BbTouchParams(mode="touch")).compute(d).direction[80] == 1


# ---------------------------------------------------------------- squeeze
def squeeze_path(breakout: float) -> list[float]:
    wide = [100.0 + (4.0 if k % 2 else -4.0) for k in range(120)]
    narrow = [100.0 + (0.1 if k % 2 else -0.1) for k in range(25)]
    return [*wide, *narrow, 100.0 + breakout]


SQUEEZE = BbSqueeze(BbSqueezeParams())


def test_a_close_outside_the_band_after_a_squeeze_is_an_expansion_trade():
    d = build(rows(squeeze_path(+2.0)))
    out = SQUEEZE.compute(d)
    assert list(np.flatnonzero(out.direction)) == [len(d) - 1] and out.direction[-1] == 1
    down = SQUEEZE.compute(build(rows(squeeze_path(-2.0))))
    assert down.direction[-1] == -1


def test_a_break_without_a_squeeze_or_a_stale_squeeze_is_nothing():
    wide = [100.0 + (4.0 if k % 2 else -4.0) for k in range(150)]
    assert not SQUEEZE.compute(build(rows([*wide, 112.0]))).direction.any()
    stale = [*squeeze_path(0.0)[:-1], *[100.0 + (4.0 if k % 2 else -4.0) for k in range(25)]]
    out = BbSqueeze(BbSqueezeParams(squeeze_bars=2)).compute(build(rows([*stale, 112.0])))
    assert out.direction[-1] == 0


def test_bandwidth_is_a_fraction_of_price_so_it_is_scale_free():
    c = np.array([100.0 + (1.0 if k % 2 else -1.0) for k in range(30)])
    assert np.allclose(bandwidth(c, 20, 2.0)[25:], bandwidth(c * 50, 20, 2.0)[25:])


# ----------------------------------------------------------------- runway
def test_a_steady_trend_closes_inside_the_runway_between_one_and_two_deviations():
    d = build(rows(ramp(60, 100.0, 1.0)))
    assert set(runway_state(d, "lwc", 20, 1.0, 2.0)[19:]) == {1}
    run = BbRunway()
    assert outcomes(run, d, 1)[-3:] == ["pass"] * 3
    assert outcomes(run, d, -1)[-3:] == ["fail"] * 3
    assert outcomes(run, build(rows(FLAT)), 1)[-1] == "fail"  # inside the 1 SD band
    assert run.check(cand(d, 5), d).outcome == "na"


def test_a_stretched_close_beyond_two_deviations_is_not_in_the_runway():
    d = build(rows([*ramp(60, 100.0, 1.0), 170.0]))
    result = BbRunway().check(cand(d, 60), d)
    assert result.outcome == "fail" and "not in" in result.reason


def test_several_bars_must_all_ride_the_runway():
    d = build(rows([*ramp(60, 100.0, 1.0), 150.0, 160.0]))  # a dip, then back on the runway
    assert BbRunway(BbRunwayParams(bars=2)).check(cand(d, 61), d).outcome == "fail"
    assert BbRunway(BbRunwayParams(bars=1)).check(cand(d, 61), d).outcome == "pass"


def test_the_inner_band_must_be_inside_the_outer_one():
    with pytest.raises(ValueError, match="باند"):
        BbRunwayParams(inner=2.0, outer=1.0)


# ------------------------------------------------------------- the exit
def fall_after_ramp() -> list[float]:
    return [*ramp(60, 100.0, 1.0), *[158.0 - 2.0 * k for k in range(10)]]


def test_the_runway_is_lost_when_riding_candles_fall_back_inside_the_inner_band():
    d = build(rows(fall_after_ramp()))
    kw = {"period": 20, "inner": 1.0, "outer": 2.0, "bars": 5}
    assert not runway_lost(d, "lwc", 59, 1, **kw)  # still riding
    assert any(runway_lost(d, "lwc", m, 1, **kw) for m in range(60, 70))
    assert not any(runway_lost(d, "lwc", m, -1, **kw) for m in range(60, 70))


def test_riding_off_the_runway_beyond_two_deviations_is_not_lost():
    d = build(rows([*ramp(60, 100.0, 1.0), 170.0]))
    assert not runway_lost(d, "lwc", 60, 1, period=20, inner=1.0, outer=2.0, bars=5)


def test_the_profit_chain_closes_on_a_lost_runway_only_after_the_first_step():
    from tests.test_strategy_blocks import position

    d = build(rows(fall_after_ramp()))
    on = ProfitChain(ProfitChainParams(runway_exit=True))
    off = ProfitChain()

    def reasons(block: ProfitChain, filled: int, direction: int = 1) -> set[str]:
        pv = position(block, cand(d, 55, direction), d, filled)
        return {getattr(block.manage(pv, d, j), "reason", "") for j in range(58, len(d))}

    assert "bb_runway_lost" in reasons(on, 1)
    assert "bb_runway_lost" not in reasons(on, 0)  # the 2R floor
    assert "bb_runway_lost" not in reasons(off, 1)


def test_the_profit_chain_rejects_an_inverted_runway():
    with pytest.raises(ValueError, match="مسیر"):
        ProfitChainParams(runway_inner=2.0, runway_outer=1.0)
