"""Market structure and wave cycles (Strategy Builder ticket 09)."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from nnfx.journal.journal import Journal
from nnfx.strategy import validate_document
from nnfx.strategy.run import backtest_document
from nnfx.strategy.structure import WaveBias, dow_states, wave_bias
from tests.test_strategy_engine import BTC, DOC, SYM, frame

Row = tuple[float, float, float, float]


def path(*points: float, start: float = 100.0, per: float = 1.0) -> list[Row]:
    """Bars walking ``per`` a bar through ``points``; every turn is a strict swing."""
    rows: list[Row] = []
    c = start
    for target in points:
        step = per if target > c else -per
        while (target - c) * step > 1e-9:
            o, c = c, c + step
            rows.append((o, c + 0.1, o - 0.05, c) if step > 0 else (o, o + 0.05, c - 0.1, c))
    return rows


def states(rows: list[Row], n: int = 2) -> np.ndarray:
    a = np.asarray(rows)
    return dow_states(a[:, 2], a[:, 1], a[:, 3], n)


# ------------------------------------------------------------------ Dow
def test_higher_highs_and_higher_lows_make_an_uptrend():
    rows = path(110, 105, 115, 110, 120)  # swing lows 105 then 110 (a higher low)
    s = states(rows)
    assert s[0] == 0 and s[-1] == 1
    # It turns up on the first close above the last confirmed swing high (115).
    first = int(np.argmax(s == 1))
    peak = [r[3] for r in rows].index(115.0)
    assert rows[first][3] > 115 and all(r[3] <= 115 for r in rows[peak:first])


def test_a_trend_ends_only_on_a_failed_peak_and_a_neckline_break():
    up = path(110, 105, 115, 110, 120, 113)
    deep = states(up + path(126, 108, 130, start=113))  # breaks the 113 low, highs still rise
    assert deep[-1] == 1  # a deep pullback alone never ends the trend
    failed = up + path(118, 111, start=113)  # lower high 118, then below the 113 neckline
    s = states(failed)
    end = int(np.argmax(s[len(up) :] != 1)) + len(up)
    assert s[len(up) + 5] == 1 and s[end] == 0 and failed[end][3] < 113
    # The trend ended there (range); the lower high plus the broken swing low then
    # make it a downtrend on the next bar (Dow: LH and LL).
    assert s[end + 1] == -1 and s[-1] == -1


def test_an_equal_high_is_a_failed_peak():
    rows = path(110, 105, 115, 110, 120, 113, 120, 112)
    assert states(rows)[-1] == 0


def test_swings_are_used_only_once_confirmed():
    rows = path(110, 105, 115, 110, 120, 113, 118, 111)
    full = states(rows)
    for n in range(10, len(rows)):
        assert np.array_equal(states(rows[:n]), full[:n])


def test_downtrends_mirror_uptrends():
    rows = [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in path(110, 105, 115, 110, 120)]
    assert states(rows)[-1] == -1


# --------------------------------------------------------------- waves
def bias(h: list[int], m: list[int], lo: list[int], **kw: bool) -> WaveBias:
    return wave_bias(np.array(h), np.array(m), np.array(lo), **kw)


def test_the_hwc_sets_the_direction_and_an_lwc_downtrend_is_never_shorted():
    b = bias([1, 1, 1], [1, 1, 1], [1, -1, -1])
    assert b.long_ok.tolist() == [True] * 3 and b.short_ok.tolist() == [False] * 3
    assert not b.counter_long.any() and not b.counter_short.any()
    m = bias([-1, -1], [-1, -1], [1, 1])
    assert m.short_ok.all() and not m.long_ok.any()


def test_the_hwc_turns_flat_only_after_the_lwc_and_then_the_mwc():
    # LWC turns first (bar 1), then the MWC (bar 2): from bar 2 the HWC is flat.
    b = bias([1, 1, 1, 1], [1, 1, -1, -1], [1, -1, -1, 1])
    assert b.hwc_effective.tolist() == [1, 1, 0, 0]
    # The flat HWC follows the MWC's new downtrend: shorts, as secondary waves.
    assert b.short_ok.tolist() == [False, False, True, True]
    assert b.counter_short.tolist() == [False, False, True, True]
    # The MWC back with the trend restores the HWC bias.
    back = bias([1, 1, 1, 1], [1, -1, 1, 1], [-1, -1, 1, 1])
    assert back.hwc_effective.tolist() == [1, 0, 1, 1]


def test_an_mwc_change_without_the_lwc_first_does_not_flip_the_hwc():
    b = bias([1, 1, 1], [1, -1, -1], [1, 1, 1])
    assert b.hwc_effective.tolist() == [1, 1, 1] and not b.short_ok.any()
    # The MWC first and the LWC after is the wrong order: still no flip.
    late = bias([1, 1, 1, 1], [1, -1, -1, -1], [1, 1, -1, -1])
    assert late.hwc_effective.tolist() == [1, 1, 1, 1] and not late.short_ok.any()
    # Both on the same bar counts.
    same = bias([1, 1], [1, -1], [1, -1])
    assert same.hwc_effective.tolist() == [1, 0]


def test_dow_states_skip_nan_bars_and_need_a_positive_pivot_window():
    rows = path(110, 105, 115, 110, 120, 113, 118, 111)
    a = np.asarray(rows, dtype=float)
    a[len(path(110, 105, 115, 110, 120)) + 3, 2] = np.nan  # a NaN low in the neckline span
    s = dow_states(a[:, 2], a[:, 1], a[:, 3], 2)
    assert s[-1] != 1  # the failed peak still ends the trend
    with pytest.raises(ValueError):
        dow_states(a[:, 2], a[:, 1], a[:, 3], 0)


def test_the_hwc_ending_its_own_trend_makes_it_flat():
    b = bias([1, 0, 0], [1, 1, 0], [1, 1, 1], two_way_box=True)
    assert b.hwc_effective.tolist() == [1, 0, 0]
    assert b.long_ok.tolist() == [True, True, True] and b.short_ok.tolist() == [False, False, True]
    assert b.box.tolist() == [False, False, True]  # HWC flat and MWC ranging
    assert b.counter_long.tolist() == [False, False, True]  # box trades take 2R-3R


def test_two_way_box_is_off_by_default_and_follow_mwc_can_be_disabled():
    assert not bias([0, 0], [0, 0], [0, 0]).long_ok.any()
    b = bias([1, 0], [1, -1], [1, -1], follow_mwc_when_flat=False)
    assert b.short_ok.tolist() == [False, False]


# ------------------------------------------------------------- harness
FLAT: list[Row] = [(100.0, 100.5, 99.5, 100.0)] * 12
FLAT_SETUP: Row = (100.05, 100.35, 95.0, 100.25)  # SMA 7 (100.04) inside the lower wick
FILL: Row = (100.25, 101.0, 100.2, 100.9)
TRIGGER, STOP = 100.35, 95.0
TO_2R = [(100.9, 104.0, 100.8, 103.9), (103.9, 106.5, 103.8, 106.4), (106.4, 111.5, 106.3, 111.4)]


def document(context: dict[str, Any], exit_params: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["timeframes"] = {"hwc": "M15", "mwc": "M15", "lwc": "M15"}
    raw["blocks"][0] = context
    if exit_params is not None:
        raw["blocks"][-1] = {"kind": "exit", "type": "profit_chain", "params": exit_params}
    return raw


def run(rows: list[Row], raw: dict[str, Any]):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return backtest_document(res.document, {SYM: frame(rows)}, {SYM: BTC}, journal=Journal())


def test_a_two_way_box_trade_is_tagged_counter_trend_and_closes_at_2r():
    ctx = {"kind": "context", "type": "wave_cycles", "params": {"two_way_box": True}}
    out = run([*FLAT, FLAT_SETUP, FILL, *TO_2R], document(ctx, {}))  # tagged by default
    (c,) = out.candidates
    assert c["decision"] == "placed" and "counter_trend" in c["tags"]
    (t,) = out.result.trades  # no ladder, no Runner: everything at 2R
    assert t.exit_price == pytest.approx(TRIGGER + 2 * (TRIGGER - STOP))


def test_without_the_box_a_ranging_market_is_not_traded():
    ctx = {"kind": "context", "type": "wave_cycles"}
    out = run([*FLAT, FLAT_SETUP, FILL, *TO_2R], document(ctx))
    (c,) = out.candidates
    assert c["reasons"] == ["context:wave_cycles#0"] and out.result.trades == []


def _trend_then(rows_after: list[Row]) -> list[Row]:
    return [*path(110, 105, 115, 110, 120), *rows_after]


def test_dow_trend_allows_longs_in_an_uptrend_and_refuses_them_after_a_failed_peak():
    ctx = {"kind": "context", "type": "dow_trend", "params": {"timeframe": "lwc"}}
    # In the uptrend: a Candle Setup at 120 (SMA 7 = 117 inside the wick).
    setup: Row = (120.0, 120.3, 112.0, 120.2)
    up = run(_trend_then([setup, (120.2, 121.0, 120.1, 120.9)]), document(ctx))
    assert up.candidates[-1]["decision"] == "placed"
    assert up.candidates[-1]["checklist"][0]["outcome"] == "pass"
    # After a failed peak (lower high 118) and a break of the 113 neckline: range.
    failed = path(113, 118, 111, 114, start=120)
    c = failed[-1][3]
    late: Row = (c, c + 0.3, c - 6.0, c + 0.2)
    out = run(_trend_then([*failed, late, (c + 0.2, c + 1, c + 0.1, c + 0.9)]), document(ctx))
    assert out.candidates[-1]["reasons"] == ["context:dow_trend#0"]


def test_wave_cycles_never_look_ahead_on_a_fixture_with_hwc_trends():
    # The registry gate's daily HWC never trends on 40 days; here every rule fires.
    from nnfx.config import SessionConfig
    from nnfx.data.synthetic import intraday_walk
    from nnfx.instruments import crypto_spec
    from nnfx.strategy import StrategyData
    from nnfx.strategy.library import WaveCycles, WaveCyclesParams

    roles = {"hwc": "H4", "mwc": "H1", "lwc": "M15"}
    d = StrategyData.build(
        intraday_walk(96 * 40, seed=3, symbol=SYM), roles, crypto_spec(SYM), SessionConfig()
    )
    block = WaveCycles(WaveCyclesParams(two_way_box=True, pivot_bars=1))
    full = block.compute(d)
    assert set(np.unique(full.flags["hwc_state"])) == {-1, 0, 1}
    assert full.tags["counter_trend"][0].any() and full.tags["counter_trend"][1].any()
    assert full.flags["box"].any() and (full.flags["hwc_effective"] != full.flags["primary"]).any()
    for n in (500, 1700, 3001):
        part = block.compute(d.head(n))
        assert np.array_equal(part.long_ok, full.long_ok[:n])
        assert np.array_equal(part.short_ok, full.short_ok[:n])
        for k in (0, 1):
            assert np.array_equal(part.tags["counter_trend"][k], full.tags["counter_trend"][k][:n])


def test_every_wave_rule_through_the_harness_on_three_real_timeframes():
    """H4 / H1 / M15 on a trending synthetic series: each candidate's journaled
    decision follows the wave rules, and every rule is exercised."""
    from nnfx.data.synthetic import intraday_walk

    raw = document({"kind": "context", "type": "wave_cycles", "params": {"two_way_box": True}})
    raw["timeframes"] = {"hwc": "H4", "mwc": "H1", "lwc": "M15"}
    raw["risk"]["max_positions_per_symbol"] = 100
    res = validate_document(raw)
    assert res.document is not None, res.render()
    bars = intraday_walk(96 * 40, seed=3, symbol=SYM)
    out = backtest_document(res.document, {SYM: bars}, {SYM: BTC}, journal=Journal())
    from nnfx.config import SessionConfig
    from nnfx.strategy import StrategyData
    from nnfx.strategy.library import WaveCycles, WaveCyclesParams

    d = StrategyData.build(bars, raw["timeframes"], BTC, SessionConfig())
    ctx = WaveCycles(WaveCyclesParams(two_way_box=True)).compute(d)
    at = {t.isoformat(): i for i, t in enumerate(d.base.index)}
    seen: set[str] = set()
    for c in out.candidates:
        i, side = at[c["time"]], c["direction"]
        allowed = ctx.allows(i, side)
        assert (c["checklist"][0]["outcome"] == "pass") == allowed
        assert ("counter_trend" in c["tags"]) == ctx.tags_for(i, side).__contains__("counter_trend")
        eff, mwc = int(ctx.flags["hwc_effective"][i]), int(ctx.flags["mwc_state"][i])
        lwc = int(ctx.flags["lwc_state"][i])
        if eff != 0 and side == -eff:
            assert not allowed
            seen.add("against_hwc_refused" + ("_lwc_with_side" if lwc == side else ""))
        if eff != 0 and side == eff:
            assert allowed and "counter_trend" not in c["tags"]
            seen.add("with_hwc")
        if eff == 0 and ctx.flags["primary"][i] != 0 and ctx.flags["hwc_state"][i] != 0:
            seen.add("bottom_up_flat")
        if bool(ctx.flags["box"][i]):
            assert allowed and "counter_trend" in c["tags"]
            seen.add("box")
        if eff == 0 and mwc != 0 and side == mwc and side == -ctx.flags["primary"][i]:
            assert "counter_trend" in c["tags"]
            seen.add("secondary_wave")
    assert {"against_hwc_refused", "with_hwc", "bottom_up_flat", "box"} <= seen, seen
    # Secondary-wave and box trades are really placed, tagged for the Profit Chain.
    tagged = {
        c["time"]
        for c in out.candidates
        if "counter_trend" in c["tags"] and c["decision"] == "placed"
    }
    assert tagged
