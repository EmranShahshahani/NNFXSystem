"""Pending stop-market orders through the shared loop (Strategy Builder ticket 02, ADR 09 §4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.brokers.costs import CostModel
from nnfx.brokers.paper import PaperBroker
from nnfx.brokers.sim import BacktestBroker, SimBroker
from nnfx.engine.core import Decision
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    AccountState,
    CancelIntent,
    EngineState,
    OpenIntent,
    PendingOrderIntent,
    PositionView,
)
from nnfx.harness.loop import TradingLoop
from nnfx.instruments import crypto_spec
from nnfx.journal.journal import Journal
from tests.helpers import config, hist

SYM = "BTC/USDT"
# Spot pricing (last-price stops) with shorting allowed, so both directions are testable.
BTC = crypto_spec(SYM, "crypto_spot").model_copy(update={"can_short": True})
CFG = config(**{"risk.risk_per_position": 0.01})


def bars(rows: Sequence[tuple[float, float, float, float]]) -> SymbolHistory:
    """15-minute bars from (open, high, low, close) rows."""
    a = np.asarray(rows, dtype="float64")
    n = len(a)
    idx = pd.date_range("2024-01-01 00:15", periods=n, freq="15min", tz="UTC")
    outputs = hist([100.0] * n, instrument=BTC, symbol=SYM).outputs
    return SymbolHistory(
        SYM, BTC, idx, a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.ones(n), outputs, n - 1
    )


def pending(
    key: str,
    *,
    direction: int = 1,
    trigger: float = 105.0,
    buffer: float = 0.0,
    stop: float = 95.0,
    target: float | None = None,
    invalidation: float | None = None,
    expires: int = 10,
    oco: str | None = None,
) -> PendingOrderIntent:
    return PendingOrderIntent(
        symbol=SYM,
        direction=direction,
        leg="single",
        leg_index=0,
        entry_type="standard",
        signal_time=key,
        atr=1.0,
        risk_fraction=0.01,
        idempotency_key=key,
        trigger=trigger,
        buffer=buffer,
        stop=stop,
        target=target,
        invalidation=invalidation,
        expires_after_bars=expires,
        oco_group=oco,
    )


class Scripted:
    """An engine that emits fixed intents after given bars and records what it saw."""

    def __init__(self, script: Mapping[int, Sequence[Any]]) -> None:
        self.script = script
        self.seen: list[AccountState] = []

    def decide(
        self,
        history: Mapping[str, SymbolHistory],
        open_positions: Sequence[PositionView],
        account_state: AccountState,
        config: Any,
        state: EngineState | None = None,
    ) -> Decision:
        self.seen.append(account_state)
        i = history[SYM].end
        return Decision(list(self.script.get(i, [])), state or EngineState(), [])


def broker() -> BacktestBroker:
    return BacktestBroker({SYM: BTC}, CostModel.zero(), 10_000.0)


def drive(h: SymbolHistory, script: Mapping[int, Sequence[Any]], b: SimBroker | None = None):
    b = b or broker()
    eng = Scripted(script)
    journal = Journal()
    loop = TradingLoop(CFG, {SYM: BTC}, b, journal, engine=eng)
    for i in range(h.end + 1):
        loop.feed_bar(h.at(i), {})
        loop.decide(h.index[i], {SYM: h.at(i)})
    return b, eng, journal


def kinds(b: SimBroker) -> list[tuple[str, str]]:
    return [(e["e"], e.get("reason", "")) for e in b.s.events]


# ---------------------------------------------------------------- fills
def test_long_stop_fills_at_trigger_plus_buffer_when_the_bar_trades_through():
    h = bars([(100, 101, 99, 100), (100, 103, 99, 102), (102, 107, 101, 106)])
    b, eng, _ = drive(h, {0: [pending("k", trigger=105.0, buffer=0.5, stop=95.0)]})
    assert kinds(b) == [("place", ""), ("fill", "")]
    (p,) = b.s.positions.values()
    assert p.entry_price == 105.5 and p.stop == 95.0 and p.entry_time == h.index[2].isoformat()
    # Sized on the distance from the entry level to the stop.
    assert p.units * (105.5 - 95.0) == pytest.approx(100.0, rel=0.02)
    # The engine saw the order resting after placement, and not after the fill.
    assert [len(a.pending_orders) for a in eng.seen] == [0, 1, 0]
    assert eng.seen[1].pending_orders[0].level == 105.5


def test_a_gap_through_the_trigger_fills_at_the_open():
    h = bars([(100, 101, 99, 100), (108, 110, 107, 109)])
    b, _, _ = drive(h, {0: [pending("k", trigger=105.0)]})
    (p,) = b.s.positions.values()
    assert p.entry_price == 108.0


def test_short_stop_fills_at_min_of_trigger_and_open():
    h = bars([(100, 101, 99, 100), (99, 100, 94, 95), (92, 93, 90, 91)])
    b, _, _ = drive(
        h,
        {
            0: [pending("a", direction=-1, trigger=96.0, stop=104.0)],
            1: [pending("b", direction=-1, trigger=94.0, stop=104.0)],
        },
    )
    assert sorted(p.entry_price for p in b.s.positions.values()) == [92.0, 96.0]


def test_stop_and_target_inside_one_bar_assume_the_stop_first():
    h = bars([(100, 101, 99, 100), (101, 106, 100, 105), (105, 112, 94, 100)])
    b, _, _ = drive(h, {0: [pending("k", trigger=105.0, stop=95.0, target=110.0)]})
    (t,) = b.trades
    assert t.exit_reason == "stop" and t.exit_price == 95.0


def test_a_fill_bar_that_also_reaches_the_stop_closes_at_the_stop():
    h = bars([(100, 101, 99, 100), (100, 106, 94, 98)])
    b, _, _ = drive(h, {0: [pending("k", trigger=105.0, stop=95.0)]})
    (t,) = b.trades
    assert t.entry_price == 105.0 and t.exit_reason == "stop"


# --------------------------------------------------------- cancellations
def test_a_close_beyond_invalidation_cancels_before_any_fill():
    h = bars([(100, 101, 99, 100), (100, 101, 96, 97), (97, 110, 96, 109)])
    b, _, _ = drive(h, {0: [pending("k", trigger=105.0, stop=95.0, invalidation=98.0)]})
    assert kinds(b) == [("place", ""), ("cancel", "invalidated")]
    assert not b.s.positions


def test_a_wick_through_invalidation_without_a_close_keeps_the_order():
    h = bars([(100, 101, 99, 100), (100, 101, 96, 99), (99, 106, 98, 105)])
    b, _, _ = drive(h, {0: [pending("k", trigger=105.0, stop=95.0, invalidation=98.0)]})
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
                pending("up", trigger=105.0, stop=95.0, oco="box"),
                pending("down", direction=-1, trigger=95.0, stop=105.0, oco="box"),
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


def test_resubmitting_a_pending_key_is_a_duplicate_not_a_second_order():
    h = bars([(100, 101, 99, 100)] * 3)
    b, _, journal = drive(h, {0: [pending("k")], 1: [pending("k")]})
    assert kinds(b) == [("place", "")]
    second = list(journal.records("cycle"))[1]["submitted"][0]
    assert second["status"] == "duplicate"


def test_invalid_pending_orders_are_refused_at_construction():
    with pytest.raises(ValueError, match="stop"):
        pending("k", trigger=105.0, stop=110.0)  # long stop above the entry
    with pytest.raises(ValueError, match="expires"):
        pending("k", expires=0)


# ------------------------------------------------------- journal, parity
SCRIPT = {
    0: [
        pending("up", trigger=105.0, buffer=0.5, stop=95.0, target=115.0, oco="box"),
        pending("down", direction=-1, trigger=95.0, stop=105.0, oco="box"),
    ],
    3: [pending("late", trigger=130.0, expires=2)],
    6: [pending("inv", trigger=140.0, stop=100.0, invalidation=110.0)],
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
