"""Pending stop-market orders through the shared loop (Strategy Builder ticket 02, ADR 09 §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nnfx.brokers.costs import CostModel
from nnfx.brokers.paper import PaperBroker
from nnfx.brokers.sim import BacktestBroker
from nnfx.engine.types import CancelIntent, OpenIntent
from nnfx.harness.loop import TradingLoop
from nnfx.journal.journal import Journal
from tests.scripted import BTC, CFG, SYM, Scripted, bars, drive, kinds, pending


# ---------------------------------------------------------------- fills
def test_long_stop_fills_at_trigger_plus_buffer_when_the_bar_trades_through():
    h = bars([(100, 101, 99, 100), (100, 103, 99, 102), (102, 107, 101, 106)])
    b, eng, _ = drive(h, {0: [pending("k", level=105.0, buffer=0.5, stop=95.0)]})
    assert kinds(b) == [("place", ""), ("fill", "")]
    (p,) = b.s.positions.values()
    assert p.entry_price == 105.5 and p.stop == 95.0 and p.entry_time == h.index[2].isoformat()
    # Sized on the distance from the entry level to the stop.
    assert p.units * (105.5 - 95.0) == pytest.approx(100.0, rel=0.02)
    # The engine saw the order resting after placement, and not after the fill.
    assert [len(a.pending_orders) for a in eng.seen] == [0, 1, 0]
    resting = eng.seen[1].pending_orders[0]
    assert (resting.level, resting.trigger) == (105.0, 105.5)


def test_a_gap_through_the_trigger_fills_at_the_open():
    h = bars([(100, 101, 99, 100), (108, 110, 107, 109)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0)]})
    (p,) = b.s.positions.values()
    assert p.entry_price == 108.0


def test_short_stop_fills_at_min_of_trigger_and_open():
    h = bars([(100, 101, 99, 100), (99, 100, 94, 95), (92, 93, 90, 91)])
    b, _, _ = drive(
        h,
        {
            0: [pending("a", direction=-1, level=96.0, stop=104.0)],
            1: [pending("b", direction=-1, level=94.0, stop=104.0)],
        },
    )
    assert sorted(p.entry_price for p in b.s.positions.values()) == [92.0, 96.0]


def test_stop_and_target_inside_one_bar_assume_the_stop_first():
    h = bars([(100, 101, 99, 100), (101, 106, 100, 105), (105, 112, 94, 100)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0, stop=95.0, target=110.0)]})
    (t,) = b.trades
    assert t.exit_reason == "stop" and t.exit_price == 95.0


def test_a_fill_bar_that_also_reaches_the_stop_closes_at_the_stop():
    h = bars([(100, 101, 99, 100), (100, 106, 94, 98)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0, stop=95.0)]})
    (t,) = b.trades
    assert t.entry_price == 105.0 and t.exit_reason == "stop"


# --------------------------------------------------------- cancellations
def test_a_close_beyond_invalidation_cancels_before_any_fill():
    h = bars([(100, 101, 99, 100), (100, 101, 96, 97), (97, 110, 96, 109)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0, stop=95.0, invalidation=98.0)]})
    assert kinds(b) == [("place", ""), ("cancel", "invalidated")]
    assert not b.s.positions


def test_a_wick_through_invalidation_without_a_close_keeps_the_order():
    h = bars([(100, 101, 99, 100), (100, 101, 96, 99), (99, 106, 98, 105)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0, stop=95.0, invalidation=98.0)]})
    assert kinds(b) == [("place", ""), ("fill", "")]


def test_an_unfilled_order_expires_after_its_bars():
    h = bars([(100, 101, 99, 100)] * 5)
    b, _, _ = drive(h, {0: [pending("k", expires=3)]})
    assert kinds(b) == [("place", ""), ("cancel", "expired")]
    cancel = b.s.events[1]
    assert cancel["time"] == h.index[3].isoformat()


def test_the_engine_can_cancel_a_resting_order():
    h = bars([(100, 101, 99, 100)] * 3 + [(100, 110, 99, 109)])
    b, _, _ = drive(
        h,
        {0: [pending("k")], 1: [CancelIntent(symbol=SYM, order_key="k", reason="setup_gone")]},
    )
    assert kinds(b) == [("place", ""), ("cancel", "setup_gone")]
    assert not b.s.positions


def test_oco_first_fill_cancels_the_other():
    h = bars([(100, 101, 99, 100), (100, 106, 99, 105), (105, 106, 90, 91)])
    b, _, _ = drive(
        h,
        {
            0: [
                pending("up", level=105.0, stop=95.0, oco="box"),
                pending("down", direction=-1, level=95.0, stop=105.0, oco="box"),
            ]
        },
    )
    # The short never fills although bar 2 trades through 95; the long stops out there.
    assert kinds(b) == [
        ("place", ""),
        ("place", ""),
        ("fill", ""),
        ("cancel", "oco"),
        ("close", "stop"),
    ]
    assert b.s.events[3]["key"] == "down"
    assert all(t.direction == 1 for t in b.trades)


def test_oco_a_gap_at_the_open_beats_a_leg_reached_later_in_the_bar():
    # The short is placed second but gaps through at the open: it was certainly first.
    h = bars([(100, 101, 99, 100), (94, 106, 93, 100)])
    b, _, _ = drive(
        h,
        {
            0: [
                pending("up", level=105.0, stop=95.0, oco="box"),
                pending("down", direction=-1, level=95.0, stop=105.0, oco="box"),
            ]
        },
    )
    fill, cancel = b.s.events[2], b.s.events[3]
    assert (fill["e"], fill["key"], fill["price"]) == ("fill", "down", 94.0)
    assert (cancel["e"], cancel["key"], cancel["reason"]) == ("cancel", "up", "oco")


def test_resubmitting_a_pending_key_is_a_duplicate_not_a_second_order():
    h = bars([(100, 101, 99, 100)] * 3)
    b, _, journal = drive(h, {0: [pending("k")], 1: [pending("k")]})
    assert kinds(b) == [("place", "")]
    second = list(journal.records("cycle"))[1]["submitted"][0]
    assert second["status"] == "duplicate"


def test_invalid_pending_orders_are_refused_at_construction():
    with pytest.raises(ValueError, match="stop"):
        pending("k", level=105.0, stop=110.0)  # long stop above the entry
    with pytest.raises(ValueError, match="expires"):
        pending("k", expires=0)


# ------------------------------------------------------- journal, parity
SCRIPT = {
    0: [
        pending("up", level=105.0, buffer=0.5, stop=95.0, target=115.0, oco="box"),
        pending("down", direction=-1, level=95.0, stop=105.0, oco="box"),
    ],
    3: [pending("late", level=130.0, expires=2)],
    6: [pending("inv", level=140.0, stop=100.0, invalidation=110.0)],
}
ROWS = [
    (100, 101, 99, 100),
    (100, 103, 99, 102),
    (102, 107, 101, 106),
    (106, 112, 105, 111),
    (111, 113, 110, 112),
    (112, 117, 111, 116),
    (116, 117, 112, 113),
    (113, 114, 108, 109),
]


def test_every_order_event_is_journaled_in_its_cycle():
    b, _, journal = drive(bars(ROWS), SCRIPT)
    logged = [e for r in journal.records("cycle") for e in r["orders"]]
    assert logged == b.s.events
    assert [(e["e"], e.get("reason", "")) for e in logged] == [
        ("place", ""),
        ("place", ""),
        ("fill", ""),
        ("cancel", "oco"),
        ("place", ""),
        ("close", "target"),
        ("cancel", "expired"),
        ("place", ""),
        ("cancel", "invalidated"),
    ]


def test_paper_broker_restarted_every_bar_matches_the_backtest(tmp_path: Path):
    h = bars(ROWS)
    bt, _, bt_journal = drive(h, SCRIPT)

    state = tmp_path / "paper.json"
    journal = Journal()
    eng = Scripted(SCRIPT)
    for i in range(h.end + 1):
        # A fresh broker from disk and a fresh loop every bar, as in live paper mode.
        paper = PaperBroker({SYM: BTC}, CostModel.zero(), 10_000.0, state_path=state)
        loop = TradingLoop(CFG, {SYM: BTC}, paper, journal, engine=eng)
        loop.feed_bar(h.at(i), {})
        loop.decide(h.index[i], {SYM: h.at(i)})
    assert paper.s.events == bt.s.events
    assert [t.__dict__ for t in paper.trades] == [t.__dict__ for t in bt.trades]
    strip = ("time", "orders", "positions", "submitted", "rejected", "equity")
    assert [{k: r[k] for k in strip} for r in journal.records("cycle")] == [
        {k: r[k] for k in strip} for r in bt_journal.records("cycle")
    ]


def test_a_crash_between_bar_and_journal_loses_no_order_events(tmp_path: Path):
    h = bars(ROWS)
    state, jpath = tmp_path / "paper.json", tmp_path / "journal.jsonl"
    eng = Scripted(SCRIPT)
    for i in range(h.end + 1):
        paper = PaperBroker({SYM: BTC}, CostModel.zero(), 10_000.0, state_path=state)
        loop = TradingLoop(CFG, {SYM: BTC}, paper, Journal(jpath), engine=eng)
        loop.feed_bar(h.at(i), {})
        if i == 2:
            continue  # crash: the bar (and its fill) persisted, the cycle was never journaled
        loop.decide(h.index[i], {SYM: h.at(i)})
    logged = [e for r in Journal(jpath).records("cycle") for e in r["orders"]]
    assert logged == paper.s.events


def test_paper_matches_backtest_with_real_costs(tmp_path: Path):
    costs = CostModel.from_venue("config/venues/backtest.yaml")
    h = bars(ROWS)
    bt, _, _ = drive(h, SCRIPT, BacktestBroker({SYM: BTC}, costs, 10_000.0))
    state = tmp_path / "paper.json"
    eng = Scripted(SCRIPT)
    for i in range(h.end + 1):
        paper = PaperBroker({SYM: BTC}, costs, 10_000.0, state_path=state)
        loop = TradingLoop(CFG, {SYM: BTC}, paper, Journal(), engine=eng)
        loop.feed_bar(h.at(i), {})
        loop.decide(h.index[i], {SYM: h.at(i)})
    assert paper.s.events == bt.s.events
    assert bt.trades and [t.__dict__ for t in paper.trades] == [t.__dict__ for t in bt.trades]
    assert any(t.commission > 0 for t in bt.trades)


def test_market_open_intents_still_fill_at_the_next_open():
    h = bars([(100, 101, 99, 100), (102, 103, 101, 102)])
    market = OpenIntent(
        symbol=SYM,
        direction=1,
        leg="single",
        leg_index=0,
        entry_type="standard",
        signal_time="m",
        atr=1.0,
        stop_distance=5.0,
        target_distance=None,
        risk_fraction=0.01,
        idempotency_key="m",
    )
    b, _, _ = drive(h, {0: [market]})
    (p,) = b.s.positions.values()
    assert p.entry_price == 102.0 and p.stop == 97.0
    assert kinds(b) == [("fill", "")]
