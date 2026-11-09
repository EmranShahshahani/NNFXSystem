"""Levels, touches, boxes and breakout confirmation (Strategy Builder ticket 11).

Boxes are hand-built on 15m bars: swings are strict so every one confirms, and
all timeframe roles are M15 unless a test says otherwise.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.instruments import crypto_spec
from nnfx.journal.journal import Journal
from nnfx.strategy import StrategyData, validate_document
from nnfx.strategy.blocks import SetupCandidate
from nnfx.strategy.levels import LevelBook, track_boxes
from nnfx.strategy.library import (
    BodyCloseParams,
    BoxBreakout,
    BoxBreakoutParams,
    BoxExtremes,
    BoxExtremesParams,
    BoxVolumeDryUp,
    BreakoutBodyClose,
    BreakoutRange,
    BreakoutRangeParams,
    ConsecutiveCloses,
    ConsecutiveParams,
    DryUpParams,
    LevelLocation,
    LevelLocationParams,
    TouchCount,
    TouchCountParams,
)
from nnfx.strategy.run import backtest_document
from nnfx.strategy.series import atr
from tests.test_strategy_engine import BTC, DOC, SYM, frame

Row = tuple[float, float, float, float]
ROLES = {"hwc": "M15", "mwc": "M15", "lwc": "M15", "management": "M15"}


def leg(a: float, b: float, bars: int) -> list[Row]:
    """``bars`` bars moving linearly from ``a`` to ``b``; every turn is a strict swing."""
    rows, c = [], a
    for k in range(bars):
        o, c = c, a + (b - a) * (k + 1) / bars
        rows.append((o, c + 0.2, o - 0.05, c) if c > o else (o, o + 0.05, c - 0.2, c))
    return rows


def box(
    cycles: int,
    top: float = 110.0,
    bottom: float = 100.0,
    bars: int = 4,
    lead: int = 2,
    start: float | None = None,
) -> list[Row]:
    """A lead-in, then ``cycles`` swings to the top and back to the bottom."""
    rows = leg((top + bottom) / 2 if start is None else start, bottom, lead)
    for _ in range(cycles):
        rows += leg(rows[-1][3], top, bars) + leg(top, bottom, bars)
    return rows


def tracked(rows: list[Row], **kw: Any):
    a = np.asarray(rows)
    args: dict[str, Any] = dict(
        pivot_bars=2, lookback=60, tolerance_atr=0.5, min_top=3, min_bottom=2,
        min_height_atr=1.0, max_height_atr=8.0, min_bars=8, window=12,
    )  # fmt: skip
    args.update(kw)
    rng = atr(a[:, 1], a[:, 2], a[:, 3], 14)
    return track_boxes(a[:, 0], a[:, 1], a[:, 2], a[:, 3], rng, **args)


UP_BREAK = [*box(3), *leg(100, 110, 4), *leg(110, 118, 4)]  # the 3rd top, then a break at bar 30


# ----------------------------------------------------------------- boxes
def test_a_box_needs_three_touches_on_the_top_and_two_on_the_bottom():
    t = tracked(box(3))
    assert t.in_box[23] and (t.top[23], t.bottom[23]) == (110.0, 100.0) and t.start[23] == 5
    assert not t.in_box[:23].any()  # the third top is only confirmed two bars after it
    assert not tracked(box(2)).in_box.any()  # two tops are not a box
    assert tracked([*box(2), *leg(100, 104, 3)], min_top=2).in_box.any()  # a parameter
    assert not tracked(box(3), max_height_atr=1.0).in_box.any()  # too tall
    assert not tracked(box(3), min_bars=500).in_box.any()  # too young


def test_a_breakout_stands_from_its_first_close_beyond_the_edge_for_a_window():
    t = tracked(UP_BREAK, window=3)
    up = np.flatnonzero(t.direction)
    assert up.tolist() == [30, 31, 32]  # the window ends it
    assert (t.anchor[up] == 30).all() and (t.edge[up] == 110.0).all()
    assert (t.opposite[up] == 100.0).all() and (t.touches[up] == 3).all()
    assert t.trigger[30] == UP_BREAK[30][1]  # the breakout bar's high
    assert not t.in_box[30]  # the box is gone once it breaks


def test_a_wick_through_the_edge_is_a_sweep_not_a_breakout():
    sweep: Row = (109.0, 113.0, 108.5, 109.5)  # pierces the top, closes inside
    t = tracked([*box(3), *leg(100, 109, 4), sweep, *leg(109.5, 104, 3)])
    assert not t.direction.any()


def test_a_close_back_inside_ends_the_breakout():
    back = [*box(3), *leg(100, 110, 4), *leg(110, 113, 2), *leg(113, 108, 2)]
    t = tracked(back)
    hit = np.flatnonzero(t.direction)
    close = np.asarray(back)[:, 3]
    assert hit.size and (close[hit] > 110.0).all()  # it stood while the closes stayed beyond
    assert close[hit[-1] + 1] <= 110.0 and not t.direction[hit[-1] + 1 :].any()  # then it fell back


def test_down_breakouts_mirror_up_breakouts():
    down = [(200 - o, 200 - lo, 200 - h, 200 - c) for o, h, lo, c in UP_BREAK]
    t = tracked(down, min_top=2, min_bottom=3)
    assert t.direction[30] == -1 and t.edge[30] == 90.0 and t.opposite[30] == 100.0


def test_boxes_never_look_ahead():
    full = tracked(UP_BREAK)
    for n in range(10, len(UP_BREAK)):
        part = tracked(UP_BREAK[:n])
        assert np.array_equal(part.direction, full.direction[:n])
        assert np.array_equal(part.in_box, full.in_box[:n])
        assert np.array_equal(part.anchor, full.anchor[:n])


# ---------------------------------------------------------------- levels
def book(rows: list[Row], **kw: Any) -> LevelBook:
    a = np.asarray(rows)
    args: dict[str, Any] = dict(pivot_bars=2, tolerance_atr=0.5, half_life=20.0, max_age=1000)
    args.update(kw)
    return LevelBook(a[:, 0], a[:, 1], a[:, 2], a[:, 3], atr(a[:, 1], a[:, 2], a[:, 3], 14), **args)


def test_levels_are_single_prices_calibrated_to_candle_bodies():
    lv = book(box(3)).at(len(box(3)) - 1)
    prices = sorted(x.price for x in lv)
    assert prices == [100.0, 110.0]  # body tops and bottoms, not the wick tips
    top = next(x for x in lv if x.price == 110.0)
    assert len(top.touches) == 3 and not top.flipped


def test_recent_touches_weigh_more_than_old_ones():
    rows = box(4)
    top = next(x for x in book(rows).at(len(rows) - 1) if x.price == 110.0)
    # Four touches decayed by their age (half-life 20), fewer than four whole touches.
    assert 0 < top.weight < 4
    aged = next(x for x in book(rows, half_life=2.0).at(len(rows) - 1) if x.price == 110.0)
    assert aged.weight < top.weight
    assert not [x for x in book(rows, half_life=2.0).at(len(rows) - 1, min_weight=1.5)]


def test_a_level_touched_as_resistance_and_as_support_has_flipped():
    rows = [*box(2), *leg(100, 112, 6), *leg(112, 110, 3), *leg(110, 115, 3), *leg(115, 110.5, 4)]
    flipped = [x for x in book(rows).at(len(rows) - 1) if x.flipped]
    assert flipped and any(abs(x.price - 110.0) < 1.0 for x in flipped)


def test_levels_are_read_only_as_confirmed_and_stale_levels_drop_out():
    rows = box(3)
    full = book(rows)
    # The 3rd top (bar 21) confirms at bar 23: before that the level has two touches.
    before = next(x for x in full.at(22) if x.price == 110.0)
    assert len(before.touches) == 2
    assert len(next(x for x in full.at(23) if x.price == 110.0).touches) == 3
    assert not book(rows, max_age=1).at(len(rows) - 1)  # nothing touched that recently


# ------------------------------------------------------ the Blocks on boxes
def data(rows: list[Row], roles: dict[str, str] | None = None) -> StrategyData:
    return StrategyData.build(frame(rows), roles or ROLES, BTC, SessionConfig())


LOOSE = dict(min_touches=3, min_bottom_touches=2, tolerance_atr=0.5)


def breakout_at(
    rows: list[Row], block: Any = None, bar: int = 30
) -> tuple[SetupCandidate, StrategyData]:
    d = data(rows)
    out = (block or BoxBreakout(BoxBreakoutParams(timeframe="lwc"))).compute(d)
    cand = SetupCandidate.at(out, d, "box_breakout", 1, bar)
    assert cand is not None
    return cand, d


def test_the_box_breakout_candidate_has_its_trigger_edge_and_structural_stop():
    cand, d = breakout_at(UP_BREAK)
    assert cand.direction == 1
    assert cand.trigger == UP_BREAK[30][1]  # the breakout bar's high
    assert cand.invalidation == 110.0  # a close back below the top cancels the order
    assert cand.stop == 100.0  # the opposite box edge
    assert cand.fact("touches") == 3 and cand.fact("level") == 110.0
    assert cand.fact("anchor") == 30 and cand.fact("start") == 5
    assert "box_breakout" in cand.tags
    out = BoxBreakout(BoxBreakoutParams(timeframe="lwc")).compute(d)
    assert np.flatnonzero(out.direction).tolist() == list(range(30, 34))


def test_a_close_beyond_a_slower_levels_timeframe_is_not_a_breakout():
    # Hourly boxes from 15m bars: each leg is 16 bars (4 hours).
    rows = box(3, bars=16, lead=4)
    roles = {"hwc": "H1", "mwc": "H1", "lwc": "M15", "management": "H1"}
    block = BoxBreakout(BoxBreakoutParams(timeframe="mwc", min_bars=4, lookback=40))
    climb = leg(100.0, 109.0, 8)  # two hours up, still inside the box
    # A 15m bar closes at 113 (beyond the top) mid-hour, but the hour closes back inside.
    spike: list[Row] = [
        (109.0, 113.3, 108.9, 113.0),
        (113.0, 113.1, 108.9, 109.0),
        (109.0, 109.1, 108.9, 109.0),
        (109.0, 109.1, 108.9, 109.0),
    ]
    d = data([*rows, *climb, *spike], roles)
    assert not block.compute(d).direction.any()  # the 15m close at 113 means nothing to the hour
    # An hourly close beyond the level does count, on the 15m bar where that hour closes.
    real: list[Row] = [
        (109.0, 110.5, 108.9, 110.2),
        (110.2, 112.0, 110.0, 111.5),
        (111.5, 113.0, 111.0, 112.5),
        (112.5, 113.5, 112.4, 113.2),
    ]
    d2 = data([*rows, *climb, *real], roles)
    hits = np.flatnonzero(block.compute(d2).direction)
    assert hits.tolist() == [len(d2) - 1]  # only the hour's closing 15m bar
    assert d2.base.index[hits[0]].minute == 0


def test_volume_dry_up_inside_the_box_is_a_separate_check():
    rows = UP_BREAK
    cand, d = breakout_at(rows)
    block = BoxVolumeDryUp(DryUpParams(timeframe="lwc"))
    v = np.ones(len(d))
    v[5:17] = 2.0  # busy first half
    v[17:30] = 0.5  # quiet second half
    dry = StrategyData.build(with_volume(d.base, v), ROLES, BTC, SessionConfig())
    assert block.check(cand, dry).outcome == "pass"
    v[17:30] = 3.0
    loud = StrategyData.build(with_volume(d.base, v), ROLES, BTC, SessionConfig())
    assert block.check(cand, loud).outcome == "fail"
    none = StrategyData.build(with_volume(d.base, v, kind="none"), ROLES, BTC, SessionConfig())
    assert block.check(cand, none).outcome == "na"


def with_volume(f, v, kind: str = "traded"):
    import pandas as pd

    from nnfx.data.bars import BarFrame

    df = pd.DataFrame(
        {"open": f.open, "high": f.high, "low": f.low, "close": f.close, "volume": v}, index=f.index
    )
    return BarFrame(df, f.symbol, timeframe=f.timeframe, volume_kind=kind, price_venue="x")  # type: ignore[arg-type]


def test_the_body_close_rule_separates_a_whole_body_from_a_late_open():
    cand, d = breakout_at(UP_BREAK)
    assert BreakoutBodyClose(BodyCloseParams(timeframe="lwc")).check(cand, d).outcome == "fail"
    # The fixture's breakout bar opens inside the box (open 110) and closes at 112.
    loose = BreakoutBodyClose(BodyCloseParams(timeframe="lwc", full_body=False))
    assert loose.check(cand, d).outcome == "pass"
    gap = [*box(3), *leg(100, 110, 4), (111.0, 113.2, 110.9, 113.0)]
    cand2, d2 = breakout_at(gap)
    full = BreakoutBodyClose(BodyCloseParams(timeframe="lwc"))
    assert (
        full.check(cand2, d2).outcome == "pass"
        and "whole body beyond" in full.check(cand2, d2).reason
    )


def test_the_range_filter_wants_a_big_breakout_candle():
    cand, d = breakout_at(UP_BREAK)
    block = BreakoutRange(BreakoutRangeParams(timeframe="lwc", bars=6, factor=1.5))
    # The breakout candle spans ~2.45 against ~2.35 for the legs: not 1.5x.
    assert block.check(cand, d).outcome == "fail"
    big = [*box(3), *leg(100, 110, 4), (110.0, 118.0, 109.9, 117.5)]
    cand2, d2 = breakout_at(big)
    assert block.check(cand2, d2).outcome == "pass"
    young, dy = breakout_at(UP_BREAK)
    assert (
        BreakoutRange(BreakoutRangeParams(timeframe="lwc", bars=60)).check(young, dy).outcome
        == "na"
    )


def test_consecutive_closes_count_bars_beyond_the_level_by_timeframe():
    rows = [*UP_BREAK, *leg(118, 125, 6)]
    d = data(rows)
    block = ConsecutiveCloses(ConsecutiveParams(timeframe="lwc"))
    out = BoxBreakout(BoxBreakoutParams(timeframe="lwc", window=12)).compute(d)
    first = SetupCandidate.at(out, d, "box_breakout", 1, 30)
    assert first is not None
    assert block.check(first, d).outcome == "fail"  # 1 close beyond, M15 needs 8
    held = SetupCandidate.at(out, d, "box_breakout", 1, 37)
    assert held is not None and block.check(held, d).outcome == "pass"  # the 8th
    assert block.check(held, d).reason.startswith("8 closes")
    # Four are enough when asked; H4 and D1 have defaults, H1 does not.
    four = ConsecutiveCloses(ConsecutiveParams(timeframe="lwc", bars=4))
    assert four.check(SetupCandidate.at(out, d, "box_breakout", 1, 33), d).outcome == "pass"  # type: ignore[arg-type]
    h1 = data(rows, {"hwc": "H1", "mwc": "H1", "lwc": "M15", "management": "H1"})
    assert ConsecutiveCloses(ConsecutiveParams(timeframe="mwc")).check(first, h1).outcome == "na"


def test_the_touch_rule_refuses_the_first_touch_and_asks_more_of_the_second():
    one = tracked([*box(1), *leg(100, 104, 8)], min_top=1, min_bottom=1, min_bars=2)
    assert one.in_box.any()
    rows = lambda cycles: [*box(cycles), *leg(100, 110, 4), *leg(110, 118, 4)]  # noqa: E731

    def cand(cycles: int, **kw: Any):
        params = BoxBreakoutParams(
            timeframe="lwc", min_touches=cycles, min_bottom_touches=1, min_bars=2, **kw
        )
        r = rows(cycles)
        d = data(r)
        out = BoxBreakout(params).compute(d)
        hit = np.flatnonzero(out.direction)
        assert hit.size, cycles
        return SetupCandidate.at(out, d, "box_breakout", 1, int(hit[0])), d

    rule = TouchCount(TouchCountParams(timeframe="lwc"))
    c1, d1 = cand(1)
    assert c1 is not None and c1.fact("touches") == 1
    first = rule.check(c1, d1)
    assert first.outcome == "fail" and "first touch" in first.reason
    c2, d2 = cand(2)
    assert c2 is not None and c2.fact("touches") == 2
    # Second touch with no trend and a breakout candle without an absorption wick: refused.
    assert rule.check(c2, d2).outcome == "fail"
    assert (
        TouchCount(TouchCountParams(timeframe="lwc", second_touch="allow")).check(c2, d2).outcome
        == "pass"
    )
    assert (
        TouchCount(TouchCountParams(timeframe="lwc", second_touch="refuse")).check(c2, d2).outcome
        == "fail"
    )
    c3, d3 = cand(3)
    assert c3 is not None and rule.check(c3, d3).outcome == "pass"
    capped = TouchCount(TouchCountParams(timeframe="lwc", max_touches=2))
    assert capped.check(c3, d3).outcome == "fail"
    assert rule.check(replace_meta(c3), d3).outcome == "na"


def replace_meta(c: SetupCandidate) -> SetupCandidate:
    from dataclasses import replace

    return replace(c, meta=())


def test_a_second_touch_passes_with_an_absorption_wick_or_the_higher_trend():
    base = [*box(2), *leg(100, 110, 4)]
    wick: Row = (110.0, 113.0, 104.0, 112.5)  # a long lower wick: buyers absorbed the sellers
    d = data([*base, wick])
    params = BoxBreakoutParams(timeframe="lwc", min_touches=2, min_bottom_touches=1, min_bars=2)
    out = BoxBreakout(params).compute(d)
    cand = SetupCandidate.at(out, d, "box_breakout", 1, len(d) - 1)
    assert cand is not None and cand.fact("touches") == 2
    r = TouchCount(TouchCountParams(timeframe="lwc")).check(cand, d)
    assert r.outcome == "pass" and "absorption wick" in r.reason


# ----------------------------------------------------------- level location
def test_a_candle_setup_at_a_recent_level_passes_the_location_check():
    rows = box(3)
    d = data(rows)
    c = rows[-1][3]
    at_level = SetupCandidate(SYM, "candle_setup", 1, len(d) - 1, "", 1, 110.3, 109.4, 109.4)
    away = SetupCandidate(SYM, "candle_setup", 1, len(d) - 1, "", 1, 105.3, 104.9, 104.9)
    block = LevelLocation(LevelLocationParams(timeframe="lwc"))
    hit = block.check(at_level, d)
    assert hit.outcome == "pass" and "3 touches" in hit.reason, hit
    assert block.check(away, d).outcome == "fail"
    flip_only = LevelLocation(LevelLocationParams(timeframe="lwc", flipped_only=True))
    assert flip_only.check(at_level, d).outcome == "fail"  # never flipped
    assert block.check(replace_bar(at_level, 2), d).outcome in {"na", "fail"}
    assert c  # keep the fixture's last close referenced


def replace_bar(c: SetupCandidate, bar: int) -> SetupCandidate:
    from dataclasses import replace

    return replace(c, bar=bar)


# ------------------------------------------------------------------ harness
def doc(*confirmations: dict[str, Any], **params: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["timeframes"] = {"hwc": "M15", "mwc": "M15", "lwc": "M15"}
    raw["blocks"] = [
        {"kind": "setup", "type": "box_breakout", "params": {"timeframe": "lwc", **params}},
        *confirmations,
        {"kind": "execution", "type": "stop_market", "params": {"buffer_pct": 0, "expiry_bars": 4}},
        {"kind": "stop", "type": "structural_stop", "params": {"buffer_pct": 0}},
        {"kind": "exit", "type": "fixed_r", "params": {"r": 2.0}},
    ]
    return raw


def conf(btype: str, **params: Any) -> dict[str, Any]:
    return {"kind": "confirmation", "type": btype, "params": {"timeframe": "lwc", **params}}


PERP = crypto_spec(SYM, "crypto_perp", stop_trigger_price="last")  # shorts, no mark prices


def run(rows: list[Row], raw: dict[str, Any], spec: Any = BTC, journal: Journal | None = None):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return backtest_document(
        res.document, {SYM: frame(rows)}, {SYM: spec}, journal=journal or Journal()
    )


def test_a_confirmed_box_breakout_is_placed_and_fills_through_the_harness():
    rows = [*UP_BREAK, *leg(118, 125, 8), *leg(125, 160, 14)]
    raw = doc(
        conf("breakout_body_close", full_body=False),
        conf("consecutive_closes", bars=3, hard=True),
        conf("touch_count"),
        window=6,
    )
    out = run(rows, raw)
    placed = [c for c in out.candidates if c["decision"] == "placed"]
    assert placed and placed[0]["time"] == frame(rows).index[32].isoformat()  # the 3rd close beyond
    assert [c["time"] for c in out.candidates[:2]] == [
        frame(rows).index[30].isoformat(),
        frame(rows).index[31].isoformat(),
    ]
    assert all(c["reasons"] == ["confirmation:consecutive_closes#2"] for c in out.candidates[:2])
    assert out.result.trades  # the order triggered and ran to its 2R target
    assert out.result.trades[0].exit_reason == "target"


def test_a_first_touch_breakout_is_refused_through_the_harness():
    rows = [*box(1), *leg(100, 110, 4), *leg(110, 118, 4)]  # one earlier top, one more climb
    raw = doc(conf("touch_count"), min_touches=1, min_bottom_touches=1, min_bars=2)
    out = run(rows, raw)
    first = out.candidates[0]
    assert first["decision"] == "refused" and first["reasons"] == ["confirmation:touch_count#1"]
    assert not out.result.trades


def test_a_sweep_makes_no_candidate_through_the_harness():
    sweep: Row = (109.0, 113.0, 108.5, 109.5)
    rows = [*box(3), *leg(100, 109, 4), sweep, *leg(109.5, 104, 3)]
    assert run(rows, doc(conf("touch_count"))).candidates == []


def test_every_new_block_is_registered():
    from nnfx.strategy import REGISTRY

    assert {
        "box_breakout",
        "box_extremes",
        "level_location",
        "touch_count",
        "breakout_body_close",
        "breakout_range",
        "consecutive_closes",
        "box_volume_dryup",
    } <= set(REGISTRY)
    assert BoxExtremes and BoxExtremesParams
    assert pytest


# ----------------------------------------------------------- the two-way box
def two_way_doc() -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["timeframes"] = {"hwc": "M15", "mwc": "M15", "lwc": "M15"}
    side = lambda side: {  # noqa: E731
        "kind": "setup",
        "type": "box_extremes",
        "params": {"timeframe": "lwc", "side": side, "min_bars": 4, "refresh_bars": 4},
    }
    raw["blocks"] = [
        {"kind": "context", "type": "wave_cycles", "params": {"two_way_box": True}},
        side("long"),
        side("short"),
        {
            "kind": "execution",
            "type": "stop_market",
            "params": {"buffer_pct": 0.05, "expiry_bars": 4, "oco": True},
        },
        {"kind": "stop", "type": "structural_stop", "params": {"buffer_pct": 0.05}},
        {"kind": "exit", "type": "profit_chain"},
    ]
    raw["risk"] = {"risk_per_trade": 0.005, "max_positions_per_symbol": 2}
    return raw


def test_the_two_way_box_places_a_stop_buy_and_a_stop_sell_that_cancel_each_other():
    rows = box(5)
    out = run(rows, two_way_doc(), PERP)
    placed = [c for c in out.candidates if c["decision"] == "placed"]
    sides = {c["direction"] for c in placed}
    assert sides == {1, -1}  # a pair stands at once
    long_ = next(c for c in placed if c["direction"] == 1)
    short = next(c for c in placed if c["direction"] == -1)
    assert long_["time"] == short["time"] and "counter_trend" in long_["tags"]
    assert long_["trigger"] == 110.0 and long_["stop"] == 100.0  # the top edge / the bottom edge
    assert short["trigger"] == 100.0 and short["stop"] == 110.0
    journal = Journal()
    run(rows, two_way_doc(), PERP, journal)
    events = [e for r in journal.records("cycle") for e in r["orders"]]
    fills = [e for e in events if e["e"] == "fill"]
    oco = [e for e in events if e["e"] == "cancel" and e.get("reason") == "oco"]
    assert fills and oco  # one side filled and its twin was cancelled, not filled
    assert len(fills) < len([e for e in events if e["e"] == "place"])


def test_the_two_way_box_is_off_without_the_box_context():
    raw = two_way_doc()
    raw["blocks"][0] = {"kind": "context", "type": "wave_cycles"}  # two_way_box left off
    assert not [c for c in run(box(5), raw, PERP).candidates if c["decision"] == "placed"]


# --------------------------------------------------- gates on box-rich data
def rich() -> list[Row]:
    """Four boxes, two broken up, one down, one never: every box rule fires."""
    rows = box(3) + leg(100, 110, 4) + leg(110, 120, 6) + leg(120, 130, 4)
    rows += box(3, top=140.0, bottom=130.0, start=130.0)
    rows += leg(130, 140, 4) + leg(140, 152, 6)
    rows += box(3, top=160.0, bottom=150.0, start=152.0)
    rows += leg(150, 140, 4) + leg(140, 128, 6)
    rows += box(4, top=135.0, bottom=125.0, start=128.0)
    return rows


@pytest.mark.parametrize("which", ["box_breakout", "box_extremes"])
def test_box_setups_never_look_ahead_are_deterministic_and_scale_free(which: str):
    rows = rich()
    cls, params = (
        (BoxBreakout, BoxBreakoutParams)
        if which == "box_breakout"
        else (BoxExtremes, BoxExtremesParams)
    )
    block = cls(params(timeframe="lwc", min_bars=4))
    d = data(rows)
    full = block.compute(d)
    assert np.count_nonzero(full.direction) >= 6, "the fixture must produce candidates to gate"
    for n in (60, 97, len(rows) - 11):
        part = block.compute(d.head(n))
        assert np.array_equal(part.direction, full.direction[:n])
        for name in ("trigger", "invalidation", "stop"):
            assert np.array_equal(getattr(part, name), getattr(full, name)[:n], equal_nan=True)
        for name, arr in part.meta.items():
            assert np.array_equal(arr, full.meta[name][:n], equal_nan=True), name
    again = block.compute(data(rows))
    assert np.array_equal(again.direction, full.direction)
    scale = 1000.0
    big = block.compute(d.scaled(scale))
    assert np.array_equal(big.direction, full.direction)
    assert np.allclose(big.trigger, full.trigger * scale, equal_nan=True)
    assert np.allclose(big.meta["level"], full.meta["level"] * scale, equal_nan=True)
    if "anchor" in full.meta:
        assert np.array_equal(big.meta["anchor"], full.meta["anchor"], equal_nan=True)


def test_the_confirmations_never_look_ahead_on_box_candidates():
    rows = rich()
    d = data(rows)
    out = BoxBreakout(BoxBreakoutParams(timeframe="lwc", min_bars=4, window=12)).compute(d)
    cands = [SetupCandidate.at(out, d, "box_breakout", 1, i) for i in np.flatnonzero(out.direction)]
    assert len(cands) >= 6
    checks = [
        TouchCount(TouchCountParams(timeframe="lwc")),
        BreakoutBodyClose(BodyCloseParams(timeframe="lwc")),
        BreakoutRange(BreakoutRangeParams(timeframe="lwc")),
        ConsecutiveCloses(ConsecutiveParams(timeframe="lwc")),
        BoxVolumeDryUp(DryUpParams(timeframe="lwc")),
        LevelLocation(LevelLocationParams(timeframe="lwc")),
    ]
    outcomes = set()
    for c in cands:
        assert c is not None
        for chk in checks:
            now = chk.check(c, d.head(c.bar + 1))
            assert now == chk.check(c, d)
            outcomes.add((chk.type, now.outcome))
    assert ("touch_count", "pass") in outcomes and ("consecutive_closes", "fail") in outcomes
    assert ("consecutive_closes", "pass") in outcomes and ("breakout_range", "fail") in outcomes
