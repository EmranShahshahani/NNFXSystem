"""Trend health (Strategy Builder ticket 17): fire / no-fire fixtures per metric."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, StrategyData, block_catalogue
from nnfx.strategy.health import (
    METRICS,
    HealthParams,
    TrendHealth,
    TrendHealthParams,
    weakness,
)
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from tests.test_strategy_engine import BTC, SYM
from tests.test_strategy_oscillators import ROLES, cand, data

P = HealthParams()


def legs(points: list[tuple[float, int]], start: float) -> list[float]:
    """Closes running in straight lines to each (price, bars) turning point in turn."""
    out, prev = [start], start
    for price, bars in points:
        out += [prev + (price - prev) * (k + 1) / bars for k in range(bars)]
        prev = price
    return out


def mirror(closes: list[float]) -> list[float]:
    return [200.0 - c for c in closes]


def flagged(
    closes: list[float], metric: str, p: HealthParams = P, down: bool = False
) -> np.ndarray:
    w = weakness(data(closes), "lwc", p)
    return (w.down if down else w.up)[metric]


def exact(rows: list[tuple[float, float, float, float]]) -> StrategyData:
    """Bars exactly as given (open, high, low, close)."""
    a = np.asarray(rows)
    idx = pd.date_range(
        pd.Timestamp("2024-03-01", tz="UTC") + pd.Timedelta(minutes=15),
        periods=len(a),
        freq="15min",
    )
    df = pd.DataFrame(
        {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": 1.0},
        index=idx,
    )
    f = BarFrame(df, SYM, timeframe="M15", volume_kind="traded", price_venue="x")
    return StrategyData.build(f, ROLES, BTC, SessionConfig())


def flagged_exact(rows, metric: str, p: HealthParams = P, down: bool = False) -> np.ndarray:
    w = weakness(exact(rows), "lwc", p)
    return (w.down if down else w.up)[metric]


# -------------------------------------------------------------- the registry
def test_the_trend_health_block_is_a_flat_context_block():
    cls = REGISTRY["trend_health"]
    assert cls.kind == BlockKind.CONTEXT and not cls.oscillator
    schema = {b["type"]: b for b in block_catalogue()}["trend_health"]["params"]
    assert "$defs" not in schema
    assert all(p.get("description") for p in schema["properties"].values())
    assert set(METRICS) == {"amplitude", "duration", "body", "close_placement", "color", "channel"}


def test_parameters_are_validated():
    with pytest.raises(ValidationError):
        TrendHealthParams(metrics=[])
    with pytest.raises(ValidationError):
        TrendHealthParams(metrics=["body", "body"])
    with pytest.raises(ValidationError):
        TrendHealthParams(metrics=["body"], min_signals=2)  # one metric can never give two


# ------------------------------------------------------------ swing amplitude
SHRINKING = legs([(100, 5), (110, 6), (105, 6), (111, 6), (109.5, 6), (111.5, 6), (108, 6)], 105.0)
GROWING = legs([(100, 5), (110, 6), (105, 6), (118, 6), (112, 6), (130, 6), (122, 6)], 105.0)


def test_successive_impulse_legs_that_shrink_flag_the_uptrend():
    # legs of 10, 6 and 2 points (blueprint: +10%, +6%, +2%)
    up = flagged(SHRINKING, "amplitude")
    assert up[-1] and not up[:30].any()
    assert not flagged(SHRINKING, "amplitude", down=True).any()


def test_growing_legs_are_healthy_and_the_mirror_flags_the_downtrend():
    assert not flagged(GROWING, "amplitude").any()
    assert flagged(mirror(SHRINKING), "amplitude", down=True)[-1]
    assert not flagged(mirror(SHRINKING), "amplitude").any()


def test_the_amplitude_flag_waits_for_the_third_swing_to_be_confirmed():
    up = flagged(SHRINKING, "amplitude")
    third_high = 5 + 6 + 6 + 6 + 6 + 6  # the bar of the last swing high before the final pullback
    first = int(np.flatnonzero(up)[0])
    assert first >= third_high + P.pivot_bars  # only once confirmed, never at the swing itself


# ------------------------------------------------------------ impulse / correction
SLOW_CORRECTION = legs([(100, 5), (110, 8), (101, 12), (112, 8), (102, 12), (104, 3)], 105.0)
HEALTHY_WAVES = legs(
    [(100, 5), (115, 15), (110, 4), (130, 15), (124, 4), (145, 15), (140, 4)], 105.0
)
SLOWING_IMPULSES = legs(
    [(100, 5), (110, 6), (106, 4), (118, 6), (114, 4), (130, 16), (126, 4)], 105.0
)


def test_a_pullback_as_long_as_the_impulse_flags_weakness():
    up = flagged(SLOW_CORRECTION, "duration")
    assert up[-1]
    assert not flagged(HEALTHY_WAVES, "duration").any()  # 15 bars up, 4 down


def test_an_impulse_taking_twice_as_long_as_the_one_before_flags_weakness():
    up = flagged(SLOWING_IMPULSES, "duration")
    assert up[-1]
    loose = HealthParams(dur_slowdown=3.5, dur_correction=3.0)
    assert not flagged(SLOWING_IMPULSES, "duration", loose).any()
    assert flagged(mirror(SLOW_CORRECTION), "duration", down=True)[-1]


# ----------------------------------------------------------- body to range
def bar(o: float, c: float, wick: float = 1.0) -> tuple[float, float, float, float]:
    return (o, max(o, c) + wick, min(o, c) - wick, c)


STRONG = [bar(100 + 2 * k, 101.8 + 2 * k) for k in range(8)]  # body 1.8 of a 3.8 range: 0.47
FADING_BODIES = [bar(116 + 2 * k, 116.1 + 2 * k + 1.9, wick=1.0) for k in range(3)]


def test_candles_with_ever_smaller_bodies_in_an_advance_flag_weakness():
    solid = [bar(100 + 2 * k, 101.9 + 2 * k, wick=0.05) for k in range(8)]  # body share 0.97
    thin = [bar(116 + 2 * k, 116.0 + 2 * k + 2.0, wick=9.0) for k in range(3)]  # share 2/20
    rows = solid + thin
    up = flagged_exact(rows, "body")
    assert up[-1] and not up[:8].any()
    assert not flagged_exact(solid, "body").any()
    assert not flagged_exact(rows, "body", down=True).any()  # a downtrend flag needs a decline


def test_small_bodies_in_a_decline_flag_the_downtrend_only():
    solid = [bar(200 - 2 * k, 198.1 - 2 * k, wick=0.05) for k in range(8)]
    thin = [bar(184 - 2 * k, 182.0 - 2 * k, wick=9.0) for k in range(3)]
    rows = solid + thin
    assert flagged_exact(rows, "body", down=True)[-1]
    assert not flagged_exact(rows, "body").any()


# ---------------------------------------------------------- close placement
def placed(lows: list[float], places: list[float], height: float = 2.0):
    return [(lo, lo + height, lo, lo + p * height) for lo, p in zip(lows, places, strict=True)]


def test_closes_sliding_down_their_candles_while_price_edges_up_flag_weakness():
    rows = placed([100, 101, 102, 103], [0.9, 0.7, 0.5, 0.3])
    assert flagged_exact(rows, "close_placement")[-1]
    held = placed([100, 101, 102, 103], [0.9, 0.85, 0.9, 0.88])
    assert not flagged_exact(held, "close_placement").any()
    low_but_steady = placed([100, 101, 102, 103], [0.4, 0.4, 0.4, 0.4])
    assert not flagged_exact(low_but_steady, "close_placement").any()  # not worsening


def test_close_placement_mirrors_for_a_decline_and_needs_the_advance():
    # a down bar that closes ever higher in its range while price drifts down
    rows = [
        (lo + 2, lo + 2, lo, lo + 2 - p * 2)
        for lo, p in zip([103, 102, 101, 100], [0.9, 0.7, 0.5, 0.3], strict=True)
    ]
    assert flagged_exact(rows, "close_placement", down=True)[-1]
    flat = placed([100, 100, 100, 100], [0.9, 0.7, 0.5, 0.3])
    assert not flagged_exact(flat, "close_placement").any()  # price is not advancing


# ------------------------------------------------------------- colour ratio
def coloured(pattern: list[float]) -> list[tuple[float, float, float, float]]:
    out, prev = [], 100.0
    for step in pattern:
        c = prev + step
        out.append((prev, max(prev, c) + 0.1, min(prev, c) - 0.1, c))
        prev = c
    return out


def test_many_opposite_candles_in_an_advance_flag_weakness():
    mixed = ([2.0, -0.5] * 10) * 2  # half the candles are red, yet price climbs
    healthy = ([2.0, 2.0, 2.0, 2.0, -0.5] * 4) * 2  # one red in five
    assert flagged_exact(coloured(mixed), "color")[-1]
    assert not flagged_exact(coloured(healthy), "color").any()
    assert not flagged_exact(coloured(mixed), "color", down=True).any()


def test_the_colour_flag_mirrors_in_a_decline_and_needs_the_full_window():
    mixed = ([-2.0, 0.5] * 10) * 2
    assert flagged_exact(coloured(mixed), "color", down=True)[-1]
    assert not flagged_exact(coloured(mixed[:15]), "color", down=True).any()


# ------------------------------------------------------------------ channel
def noisy_trend(n: int, slope: float) -> list[float]:
    return [100.0 + slope * k + (0.4 if k % 2 else -0.4) for k in range(n)]


def test_a_close_through_the_over_side_of_the_channel_flags_exhaustion():
    trend = noisy_trend(70, 0.5)
    spike = [*trend, trend[-1] + 0.5 + 6.0]
    assert flagged(spike, "channel")[-1]
    assert not flagged([*trend, trend[-1] + 0.5], "channel").any()  # on the line: healthy
    assert not flagged(spike, "channel", down=True).any()


def test_the_channel_needs_its_slope_to_agree_and_mirrors():
    falling = noisy_trend(70, -0.5)
    spike_up = [*falling, falling[-1] - 0.5 + 6.0]  # a pop up in a falling channel
    assert not flagged(spike_up, "channel").any()
    assert flagged(
        mirror([*noisy_trend(70, 0.5), noisy_trend(70, 0.5)[-1] + 6.5]), "channel", down=True
    )[-1]
    assert not flagged(noisy_trend(30, 0.5), "channel").any()  # fewer bars than the window


def test_the_channel_uses_only_the_bars_before_the_close():
    base = noisy_trend(70, 0.5)
    a = flagged([*base, base[-1] + 6.5], "channel")
    b = flagged([*base, base[-1] + 6.5, 50.0, 400.0], "channel")
    assert a[70] == b[70]  # what comes after the bar cannot change its flag


# ------------------------------------------------------------------- block
def test_trend_health_disables_continuation_entries_with_enough_signals():
    d = data(SHRINKING)
    one = TrendHealth(TrendHealthParams(role="lwc", metrics=["amplitude"], min_signals=1)).compute(
        d
    )
    assert one.short_ok.all() and not one.long_ok[-1] and one.long_ok[:30].all()
    assert one.flags["health_up"][-1] == 1 and one.flags["health_down"].max() == 0
    assert one.allows(len(d) - 1, -1) and not one.allows(len(d) - 1, 1)
    two = TrendHealth(
        TrendHealthParams(role="lwc", metrics=["amplitude", "channel"], min_signals=2)
    )
    assert two.compute(d).long_ok.all()  # a single weakness does not halt entries


def test_the_mirror_halts_shorts_only():
    d = data(mirror(SHRINKING))
    out = TrendHealth(TrendHealthParams(role="lwc", metrics=["amplitude"], min_signals=1)).compute(
        d
    )
    assert out.long_ok.all() and not out.short_ok[-1]


def test_a_higher_role_is_read_only_once_it_has_closed():
    roles = {"hwc": "M15", "mwc": "H1", "lwc": "M15", "management": "H1"}
    closes = (
        legs([(100, 30), (140, 60), (120, 40), (150, 60), (140, 40), (155, 60), (140, 40)], 120.0)
        * 2
    )
    d = StrategyData.build(data(closes).base, roles, BTC, SessionConfig())
    out = TrendHealth(TrendHealthParams(role="mwc", min_signals=1)).compute(d)
    full = TrendHealth(TrendHealthParams(role="mwc", min_signals=1)).compute(d.head(len(d) - 50))
    n = len(full.long_ok)
    assert np.array_equal(out.long_ok[:n], full.long_ok) and np.array_equal(
        out.short_ok[:n], full.short_ok
    )


# ------------------------------------------------------------ the profit exit
def exit_reasons(params: ProfitChainParams, closes: list[float], filled: int, direction: int = 1):
    from tests.test_strategy_blocks import position

    d = data(closes)
    block = ProfitChain(params)
    pv = position(block, cand(d, 30, direction), d, filled)
    return {getattr(block.manage(pv, d, j), "reason", "") for j in range(35, len(d))}


def test_trend_health_closes_after_a_step_tightens_always_and_is_off_by_default():
    path = SHRINKING
    close = ProfitChainParams(health_exit="close", health_min_signals=1, metrics=["amplitude"])
    tighten = ProfitChainParams(health_exit="tighten", health_min_signals=1, metrics=["amplitude"])
    assert "trend_health" in exit_reasons(close, path, 1)
    assert "trend_health" not in exit_reasons(close, path, 0)  # the 2R floor
    assert "trend_health_tighten" in exit_reasons(tighten, path, 0)  # a tighter stop is safe
    assert "trend_health" not in exit_reasons(tighten, path, 1)  # and never a close
    assert not exit_reasons(
        ProfitChainParams(metrics=["amplitude"], health_min_signals=1), path, 1
    ) & {"trend_health"}
    assert "trend_health" not in exit_reasons(close, path, 1, -1)  # a short does not sell the top
    both = ProfitChainParams(health_exit="both", health_min_signals=1, metrics=["amplitude"])
    assert {"trend_health", "trend_health_tighten"} & exit_reasons(both, path, 1)


def test_single_bar_flags_are_held_so_different_metrics_can_coincide():
    trend = noisy_trend(70, 0.5)
    after = [trend[-1] + 0.5 * k for k in range(2, 6)]  # back inside the channel
    path = [*trend, trend[-1] + 6.5, *after]
    held = flagged(path, "channel")
    brief = flagged(path, "channel", HealthParams(hold_bars=1))
    assert brief[70] and not brief[71:].any()
    assert held[70:73].all() and not held[73:].any()


def test_the_profit_chain_refuses_more_signals_than_metrics():
    with pytest.raises(ValidationError):
        ProfitChainParams(metrics=["body"], health_min_signals=2)
