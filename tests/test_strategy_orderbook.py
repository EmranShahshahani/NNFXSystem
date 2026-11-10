"""Order-book Blocks: wall trigger, shielded stop and wall targets (Strategy Builder ticket 21)."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
from nnfx.orderbook import FixtureOrderBook, OrderBookSnapshot, RecordedOrderBook, append_snapshot
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, SetupCandidate, StrategyData
from nnfx.strategy.book import BookData
from nnfx.strategy.orderbook_blocks import (
    WallShieldedStop,
    WallStopParams,
    WallTargets,
    WallTargetsParams,
    WallTrigger,
    WallTriggerParams,
)
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, SYM, TO_TARGET, frame, run
from tests.test_strategy_oscillators import ROLES

T = pd.Timestamp("2024-03-01 02:45", tz="UTC")  # the close of the SETUP bar (bar 10)
BAR = 10


def book(
    t: int,
    mid: float = 111.2,
    asks: tuple[tuple[float, float], ...] = (),
    bids: tuple[tuple[float, float], ...] = (),
    scale: float = 1.0,
) -> OrderBookSnapshot:
    """A book of 1-unit levels every 0.1 around ``mid`` plus walls, ``t`` seconds after T."""
    ask_lv = {round(mid + 0.1 * k, 2): 1.0 for k in range(1, 61)} | dict(asks)
    bid_lv = {round(mid - 0.1 * k, 2): 1.0 for k in range(1, 61)} | dict(bids)
    return OrderBookSnapshot.of(
        SYM,
        T + pd.Timedelta(seconds=t),
        [(p, z * scale) for p, z in bid_lv.items()],
        [(p, z * scale) for p, z in ask_lv.items()],
        last_trade=mid,
    )


def standing(asks=(), bids=(), scale: float = 1.0) -> list[OrderBookSnapshot]:
    """The same walls in three snapshots up to T: persistent."""
    return [book(t, asks=asks, bids=bids, scale=scale) for t in (-40, -20, 0)]


def data_with(snaps: list[OrderBookSnapshot], volumes: list[float] | None = None) -> StrategyData:
    f = frame([*RISE, SETUP])
    if volumes is not None:
        df = f.df.copy()
        df["volume"] = volumes
        f = BarFrame(df, SYM, timeframe="M15", volume_kind="traded", price_venue="x")
    source = BookData(FixtureOrderBook(snaps)) if snaps else BookData()
    return StrategyData.build(f, ROLES, BTC, SessionConfig(), book=source)


def cand(
    data: StrategyData, direction: int = 1, trigger: float = 111.3, stop: float = 106.0
) -> SetupCandidate:
    return SetupCandidate(
        SYM, "candle_setup", 0, BAR, data.base.index[BAR].isoformat(), direction,
        trigger, stop, stop,
    )  # fmt: skip


def trigger_block(**kw) -> WallTrigger:
    return WallTrigger(WallTriggerParams(buffer_pct=0.0, window_pct=10.0, **kw))


def levels(block: WallTrigger, data: StrategyData, **kw) -> list[float]:
    return [o.level for o in block.orders(cand(data, **kw), data)]


# ---------------------------------------------------------------- registry
def test_the_order_book_blocks_are_registered_in_their_kinds():
    assert REGISTRY["wall_trigger"].kind == BlockKind.EXECUTION
    assert REGISTRY["wall_shielded_stop"].kind == BlockKind.STOP
    assert REGISTRY["wall_targets"].kind == BlockKind.EXIT


# ----------------------------------------------------------------- trigger
def test_a_long_trigger_moves_just_beyond_the_largest_ask_wall():
    data = data_with(standing(asks=((111.6, 50.0), (112.0, 80.0))))
    assert levels(trigger_block(), data) == [pytest.approx(112.0 * 1.0005)]


def test_a_short_trigger_moves_just_beyond_the_bid_wall_below():
    data = data_with(standing(bids=((110.6, 60.0),)))
    assert levels(trigger_block(), data, direction=-1) == [pytest.approx(110.6 * 0.9995)]


def test_a_wall_in_the_wrong_side_or_too_far_leaves_the_plain_order():
    far = data_with(standing(asks=((113.0, 80.0),)))  # 1.5% above the trigger: over max_distance
    assert levels(trigger_block(), far) == [111.3]
    behind = data_with(standing(bids=((110.6, 80.0),)))  # a bid wall is no obstacle to a long
    assert levels(trigger_block(), behind) == [111.3]


def test_a_wall_seen_in_too_few_snapshots_is_not_persistent():
    data = data_with([book(t, asks=((112.0, 80.0),)) for t in (-20, 0)])
    assert levels(trigger_block(), data) == [111.3]


def test_wall_size_is_relative_to_the_books_own_depth():
    thin = data_with(standing(asks=((112.0, 80.0),)))
    thick = data_with(standing(asks=((112.0, 80.0),), scale=1000.0))
    assert levels(trigger_block(), thin) == levels(trigger_block(), thick) != [111.3]
    flat = data_with(standing(asks=((112.0, 2.0),)))  # only twice a level: not a wall
    assert levels(trigger_block(), flat) == [111.3]


def test_a_wall_that_vanished_as_price_approached_never_moves_the_order():
    walled = [book(t, asks=((112.0, 80.0),)) for t in (-60, -40, -20)]
    assert levels(trigger_block(), data_with(walled)) == [pytest.approx(112.0 * 1.0005)]
    pulled = [*walled, book(0, mid=111.5)]  # the wall is gone and price is closer: a spoof
    assert levels(trigger_block(), data_with(pulled)) == [111.3]


def test_a_wall_back_at_a_level_that_spoofed_is_left_alone():
    first = [book(t, asks=((112.0, 80.0),)) for t in (-90, -80, -70)]
    pulled = [book(-60, mid=111.5)]
    again = [book(t, asks=((112.0, 80.0),)) for t in (-30, -10, 0)]
    assert levels(trigger_block(), data_with([*first, *pulled, *again])) == [111.3]


def test_nothing_later_than_the_candidate_is_seen():
    ahead = [book(t, asks=((112.0, 80.0),)) for t in (10, 20, 30)]
    assert levels(trigger_block(), data_with(ahead)) == [111.3]


def test_a_stale_book_is_no_book():
    old = [book(t, asks=((112.0, 80.0),)) for t in (-400, -380, -360)]
    assert levels(trigger_block(), data_with(old)) == [111.3]
    assert levels(trigger_block(max_age_seconds=600), data_with(old)) == [
        pytest.approx(112.0 * 1.0005)
    ]


def test_without_a_book_the_trigger_is_the_plain_stop_market_order():
    data = data_with([])
    plain = REGISTRY["stop_market"](trigger_block().p).orders(cand(data), data)
    assert trigger_block().orders(cand(data), data) == plain


# ------------------------------------------------------------------- abort
QUIET = [1.0] * 5 + [1.0, 1.0, 1.0] + [0.4, 0.4, 0.4]  # last three bars: volume dried up
BUSY = [1.0] * 11


def test_a_breakout_into_a_heavy_wall_on_falling_volume_is_aborted():
    near = standing(asks=((111.4, 80.0),))  # 0.18% above the close: price is at the wall
    assert trigger_block().orders(cand(data_with(near, QUIET)), data_with(near, QUIET)) == []


def test_the_abort_needs_contracting_volume_and_a_wall_close_by():
    near = standing(asks=((111.4, 80.0),))
    busy = data_with(near, BUSY)
    assert levels(trigger_block(), busy) == [pytest.approx(111.4 * 1.0005)]  # moved, not aborted
    far = data_with(standing(asks=((112.0, 80.0),)), QUIET)  # 0.7% away: not "approaching"
    assert levels(trigger_block(), far) == [pytest.approx(112.0 * 1.0005)]
    off = data_with(near, QUIET)
    assert levels(trigger_block(abort_on_contraction=False), off) == [pytest.approx(111.4 * 1.0005)]


# -------------------------------------------------------------------- stop
def stop_block(**kw) -> WallShieldedStop:
    return WallShieldedStop(WallStopParams(buffer_pct=0.0, window_pct=10.0, **kw))


def stop_of(snaps, direction: int = 1, trigger: float = 111.3, stop: float = 106.0, **kw) -> float:
    data = data_with(snaps)
    return stop_block(**kw).initial_stop(cand(data, direction, trigger, stop), data)


def test_the_stop_goes_behind_the_bid_wall_nearest_the_entry():
    snaps = standing(bids=((109.0, 60.0), (108.0, 90.0)))
    assert stop_of(snaps) == pytest.approx(109.0 * 0.9995)  # the nearer one shields first


def test_a_short_stop_goes_behind_the_ask_wall_above():
    snaps = standing(asks=((113.0, 60.0),))
    assert stop_of(snaps, direction=-1, trigger=111.3, stop=118.0) == pytest.approx(113.0 * 1.0005)


def test_walls_outside_the_stop_to_entry_stretch_change_nothing():
    below = standing(bids=((105.8, 60.0),))  # beyond the structural stop
    assert stop_of(below) == 106.0
    at_entry = standing(bids=((111.28, 60.0),))  # glued to the trigger
    assert stop_of(at_entry) == 106.0
    ask = standing(asks=((109.0, 60.0),))  # a long is not shielded by asks
    assert stop_of(ask) == 106.0


def test_spoofed_walls_never_shield_the_stop():
    walled = [book(t, bids=((109.0, 60.0),)) for t in (-60, -40, -20)]
    pulled = [*walled, book(0, mid=110.9)]  # price fell toward it and the wall vanished
    assert stop_of(walled) == pytest.approx(109.0 * 0.9995)
    assert stop_of(pulled) == 106.0


def test_without_a_book_the_stop_is_the_structural_one():
    assert stop_of([]) == 106.0


# ----------------------------------------------------------------- targets
def targets_block(**kw) -> WallTargets:
    return WallTargets(WallTargetsParams(window_pct=20.0, **kw))


def r_of(snaps, **kw) -> list[float]:
    data = data_with(snaps)
    plan = targets_block(**kw).plan(cand(data, stop=109.0), data, 109.0)
    return [s.r for s in plan.steps]


def test_targets_sit_just_in_front_of_the_walls_that_would_stop_them():
    snaps = standing(asks=((116.5, 50.0), (125.0, 80.0)))
    risk = 111.3 - 109.0
    assert r_of(snaps) == [
        2.0,  # 115.9 is below the first wall
        pytest.approx((116.5 * 0.9995 - 111.3) / risk, abs=1e-6),
        pytest.approx((125.0 * 0.9995 - 111.3) / risk, abs=1e-6),
    ]


def test_a_wall_nearer_than_the_two_r_floor_does_not_pull_a_target_below_it():
    assert r_of(standing(asks=((114.0, 50.0),))) == [2.0, 5.0, 10.0]


def test_the_ladder_keeps_its_fractions_runner_and_order():
    data = data_with(standing(asks=((116.5, 50.0), (125.0, 80.0))))
    plan = targets_block().plan(cand(data, stop=109.0), data, 109.0)
    assert [s.fraction for s in plan.steps] == [0.35, 0.40, 0.15] and plan.runner == 0.10
    rs = [s.r for s in plan.steps]
    assert rs == sorted(rs) and len(set(rs)) == 3


def test_without_a_book_the_plan_is_the_plain_profit_chain():
    data = data_with([])
    plain = REGISTRY["profit_chain"](targets_block().p).plan(cand(data, stop=109.0), data, 109.0)
    assert targets_block().plan(cand(data, stop=109.0), data, 109.0) == plain


def test_targets_mirror_for_shorts():
    data = data_with(standing(bids=((106.0, 50.0),)))
    plan = targets_block().plan(cand(data, -1, 111.3, 113.6), data, 113.6)
    r = (111.3 - 106.0 * 1.0005) / 2.3  # just above the bid wall
    assert [s.r for s in plan.steps][:2] == [2.0, pytest.approx(r, abs=1e-6)]


# ----------------------------------------------------------- whole document
def book_doc() -> dict:
    raw = copy.deepcopy(DOC)
    raw["blocks"][2] = {
        "kind": "execution", "type": "wall_trigger",
        "params": {"buffer_pct": 0.0, "window_pct": 10.0},
    }  # fmt: skip
    raw["blocks"][3] = {
        "kind": "stop", "type": "wall_shielded_stop",
        "params": {"buffer_pct": 0.0, "window_pct": 10.0},
    }  # fmt: skip
    raw["blocks"][4] = {"kind": "exit", "type": "wall_targets", "params": {"window_pct": 10.0}}
    return raw


ROWS = [*RISE, SETUP, FILL, *TO_TARGET]


def candidate_of(journal) -> dict:
    (ev,) = [e for r in journal.records("cycle") for e in r["evaluations"]]
    return ev


def test_a_run_with_recorded_snapshots_uses_the_walls_and_is_complete(tmp_path: Path):
    for s in standing(asks=((112.0, 80.0),), bids=((109.0, 60.0),)):
        append_snapshot(tmp_path, s)
    out, journal = run(ROWS, book_doc(), book_data=BookData(RecordedOrderBook(tmp_path)))
    ev = candidate_of(journal)
    (intent,) = ev["intents"]
    assert intent["level"] == pytest.approx(112.0 * 1.0005)
    assert intent["stop"] == pytest.approx(109.0 * 0.9995)
    assert ev["values"]["book_missing"] == [] and ev["blocked"] == []
    assert not out.incomplete and out.incomplete_blocks == []
    assert len(out.result.trades) >= 1


def test_a_run_without_snapshots_trades_plainly_and_is_flagged_incomplete():
    out, journal = run(ROWS, book_doc())
    ev = candidate_of(journal)
    (intent,) = ev["intents"]
    assert (intent["level"], intent["stop"]) == (111.3, 106.0)  # the plain order and stop
    names = ["wall_trigger#2", "wall_shielded_stop#3", "wall_targets#4"]
    assert ev["values"]["book_missing"] == names
    assert out.incomplete and out.incomplete_blocks == sorted(names)
    assert out.book_missing_candidates == 1 and out.result.trades  # still traded
    (gap,) = out.book_gaps  # no snapshot anywhere: the whole run is one gap
    assert gap["symbol"] == SYM and pd.Timestamp(gap["start"]) < pd.Timestamp(gap["end"])


def test_the_run_reports_the_periods_that_lacked_book_data():
    snaps = standing(asks=((112.0, 80.0),))  # only around the setup
    out, _ = run(ROWS, book_doc(), book_data=BookData(FixtureOrderBook(snaps)))
    first, last = out.result.equity.index[0], out.result.equity.index[-1]
    starts = [g["start"] for g in out.book_gaps]
    ends = [g["end"] for g in out.book_gaps]
    assert len(out.book_gaps) == 2
    assert pd.Timestamp(starts[0]) <= first + pd.Timedelta(minutes=15)
    assert pd.Timestamp(ends[0]) == T - pd.Timedelta(seconds=40)
    assert pd.Timestamp(starts[1]) == T and pd.Timestamp(ends[1]) >= last - pd.Timedelta(minutes=15)


def test_a_document_without_order_book_blocks_has_no_gaps_and_no_book_key():
    out, journal = run(ROWS)
    assert out.book_gaps == [] and "book_missing" not in candidate_of(journal)["values"]
    assert np.isfinite(out.result.initial_equity)
