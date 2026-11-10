"""Trendlines (Strategy Builder ticket 19): third touch, second-swing anchor, window, slopes."""

from __future__ import annotations

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, StrategyData
from nnfx.strategy.trendlines import (
    MAX_SLOPE,
    MIN_SLOPE,
    TrendlineBounce,
    TrendlineBreak,
    TrendParams,
    degrees_to_atr_per_bar,
    trend_track,
)
from tests.test_strategy_engine import BTC, frame
from tests.test_strategy_oscillators import ROLES

Row = tuple[float, float, float, float]
# Rising lows on the line 100 + 0.1 * (bar - 10); highs between them. Prices are the wicks'
# extremes, so a swing low sits exactly on the line and its close 0.2 above it.
LOWS = {10: 100.0, 30: 102.0, 50: 104.0, 70: 106.0, 90: 108.0}
HIGHS = {20: 112.0, 40: 114.0, 60: 116.0, 80: 118.0, 100: 120.0}
WIDE = TrendParams(min_slope=0.005, max_slope=1.0)  # the test chart is not at default scale


def path(points: dict[int, float], n: int) -> list[Row]:
    """Rows from turning points (bar -> low/high extreme), linear in between."""
    points = {0: 108.0, n - 1: 112.0, **points}  # the chart opens and closes mid-swing
    bars = sorted(points)
    closes = np.interp(np.arange(n), bars, [points[b] for b in bars])
    rows, prev = [], float(closes[0])
    for k, c in enumerate(closes):
        c = float(c)
        low_pt = k in LOWS and points.get(k) == LOWS[k]
        # A wick only on the side the bar moves toward, so every turn is a strict swing.
        top, bottom = (c + 0.2, prev) if c >= prev else (prev, c - 0.2)
        if low_pt:
            bottom = c  # the swing's wick is exactly the line
            c += 0.2
        rows.append((prev, top, bottom, c))
        prev = c
    return rows


def build(rows: list[Row]) -> StrategyData:
    return StrategyData.build(frame(rows), ROLES, BTC, SessionConfig())


def mirror(rows: list[Row], k: float = 220.0) -> list[Row]:
    """The same chart upside down (price -> k - price): lines stay straight."""
    return [(k - o, k - lo, k - h, k - c) for o, h, lo, c in rows]


def series(lows: dict[int, float], highs: dict[int, float] | None = None, n: int = 110):
    return build(path({**lows, **(highs or HIGHS)}, n))


def test_the_blocks_are_setups():
    assert REGISTRY["trendline_bounce"].kind == BlockKind.SETUP
    assert REGISTRY["trendline_break"].kind == BlockKind.SETUP


# ------------------------------------------------------------- slope bounds
def test_degrees_become_atr_per_bar_on_the_reference_chart():
    assert degrees_to_atr_per_bar(45) == pytest.approx(0.2)
    assert (
        pytest.approx(0.073, abs=1e-3) == MIN_SLOPE and pytest.approx(0.346, abs=1e-3) == MAX_SLOPE
    )
    assert TrendParams().min_slope == MIN_SLOPE and TrendParams().max_slope == MAX_SLOPE
    # a wider window squeezes the same angle into fewer ATR per bar
    assert degrees_to_atr_per_bar(45, window=400) < degrees_to_atr_per_bar(45)
    with pytest.raises(ValueError):
        TrendParams(min_slope=0.5, max_slope=0.1)


def test_a_line_inside_the_slope_bounds_is_kept_and_outside_it_is_not():
    d = series(LOWS)
    slope = trend_track(d, WIDE).support.slope
    s = float(slope[~np.isnan(slope)][0])
    assert 0.01 < s < 0.2
    tight_min = TrendParams(min_slope=s * 1.2, max_slope=1.0)
    tight_max = TrendParams(min_slope=0.001, max_slope=s * 0.8)
    assert not np.isfinite(trend_track(d, tight_min).support.value).any()
    assert not np.isfinite(trend_track(d, tight_max).support.value).any()


# ------------------------------------------------------- third touch, anchor
def test_a_line_is_active_only_from_its_third_touch_confirmation():
    d = series(LOWS)
    t = trend_track(d, WIDE).support
    live = np.flatnonzero(np.isfinite(t.value))
    # touches at 30, 50 and 70 (the swing at 10 is the impulse); the third confirms at 72
    assert live[0] == 72 and (t.touches[live] >= 3).all()
    assert t.anchor[72] == 30
    assert t.value[72] == pytest.approx(100.0 + 0.1 * 62, abs=0.2)


def test_the_first_swing_of_the_window_is_never_an_anchor():
    two = {k: v for k, v in LOWS.items() if k in (10, 30, 50)}
    d = series(two, {k: v for k, v in HIGHS.items() if k <= 60})
    assert not np.isfinite(trend_track(d, WIDE).support.value).any()  # 3 swings, one is the impulse


def test_a_line_older_than_the_window_expires():
    d = series(LOWS)
    short = TrendParams(min_slope=0.005, max_slope=1.0, window=45)
    assert not np.isfinite(trend_track(d, short).support.value).any()  # <3 swings fit the window
    kept = trend_track(d, WIDE).support
    assert np.isfinite(kept.value[100])


def test_a_falling_support_is_no_uptrend_line():
    falling = {10: 110.0, 30: 108.0, 50: 106.0, 70: 104.0, 90: 102.0}
    d = build(path({**falling, **{k: v + 12 for k, v in falling.items() if False}}, 100))
    assert not np.isfinite(trend_track(d, WIDE).support.value).any()


def test_the_trendlines_are_causal():
    d = series(LOWS)
    full = trend_track(d, WIDE).support
    for n in (60, 73, 95, 105):
        part = trend_track(d.head(n), WIDE).support
        assert np.array_equal(part.value, full.value[:n], equal_nan=True)
        assert np.array_equal(part.bounce, full.bounce[:n])


# ----------------------------------------------------------------- bounce
def test_a_touch_that_holds_is_a_long_at_the_bar_extremes():
    d = series(LOWS)
    out = TrendlineBounce(WIDE).compute(d)
    assert out.direction[90] == 1 and not out.direction[:72].any()
    assert out.trigger[90] == d.base.high[90] and out.stop[90] == d.base.low[90]
    assert out.meta["touches"][90] == 3
    assert out.meta["level"][90] == pytest.approx(108.0, abs=0.2)


def test_a_resistance_mirror_gives_the_short():
    rows = mirror(path({**LOWS, **HIGHS}, 110))
    d = build(rows)
    out = TrendlineBounce(WIDE).compute(d)
    t = trend_track(d, WIDE).resistance
    assert np.isfinite(t.value[-1]) and t.slope[72] < 0  # a falling line
    assert out.direction[90] == -1 and out.trigger[90] == d.base.low[90]


# ------------------------------------------------------------------ break
def test_a_close_through_the_line_is_a_short_and_the_line_is_gone():
    rows = path({**LOWS, **HIGHS}, 110)
    rows[95] = (rows[94][3], rows[94][3] + 0.1, 100.0, 100.5)  # a close far under the line
    d = build(rows)
    t = trend_track(d, WIDE).support
    out = TrendlineBreak(WIDE).compute(d)
    assert t.broke[95] and out.direction[95] == -1
    assert out.trigger[95] == d.base.low[95]
    assert out.stop[95] == out.invalidation[95] == pytest.approx(t.break_level[95])
    assert out.meta["touches"][95] == 4  # the swing at 90 was confirmed at 92
    assert not np.isfinite(t.value[95]) and not t.broke[96:].any()  # one break per line


def test_a_wick_through_the_line_that_recovers_is_a_sweep_not_a_break():
    rows = path({**LOWS, **HIGHS}, 110)
    o, h, _lo, c = rows[85]
    rows[85] = (o, h, 95.0, c)
    d = build(rows)
    assert not trend_track(d, WIDE).support.broke.any()
    assert not TrendlineBreak(WIDE).compute(d).direction.any()


def test_resistance_breaks_upward_into_a_long():
    rows = mirror(path({**LOWS, **HIGHS}, 110))
    o, h, lo, _c = rows[95]
    rows[95] = (o, h * 1.2, lo, h * 1.15)
    d = build(rows)
    out = TrendlineBreak(WIDE).compute(d)
    assert out.direction[95] == 1 and out.trigger[95] == d.base.high[95]
