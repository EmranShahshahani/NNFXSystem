"""End-to-end scenarios of the TCP Azizpour Template on hand-built 15m tapes (ticket 12).

The Template runs as shipped. A tape is built from straight legs (an uptrend with
daily and 4H pullbacks, a sideways chop, a box) and a few hand-made bars (the Candle
Setup, its fill, a stop-out). Each scenario states the one thing the Template must do.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.data.bars import BarFrame
from nnfx.journal.journal import Journal
from nnfx.strategy import get_template, validate_document
from nnfx.strategy.run import DocumentRun, backtest_document
from tests.test_strategy_engine import BTC, SYM

DAY = 96  # 15m bars in a day


class Tape:
    """A 15m price path made of legs and hand-placed bars. Prices start at ``start``."""

    def __init__(self, start: float = 100.0) -> None:
        self.rows: list[tuple[float, float, float, float, float]] = []  # o, h, l, c, volume
        self.p = start
        self.marks: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self.rows)

    def mark(self, name: str) -> int:
        self.marks[name] = len(self.rows)
        return len(self.rows)

    def leg(self, bars: int, pct: float, volume: float = 1000.0, turn: bool = True) -> Tape:
        """A straight move of ``pct`` over ``bars`` bars; its last bar is a swing (a wick past)."""
        closes = np.linspace(self.p, self.p * (1 + pct), bars + 1)[1:]
        prev = self.p
        for k, c in enumerate(closes):
            o = prev
            h, lo = max(o, c) * 1.0003, min(o, c) * 0.9997
            if turn and k == bars - 1:  # the turn: a spike so the swing is strict
                h, lo = (h * 1.002, lo) if pct > 0 else (h, lo * 0.998)
            self.rows.append((o, h, lo, float(c), volume))
            prev = float(c)
        self.p = prev
        return self

    def bar(self, o: float, h: float, lo: float, c: float, volume: float = 1000.0) -> Tape:
        """One hand-made bar, as multiples of the current price."""
        p = self.p
        self.rows.append((p * o, p * h, p * lo, p * c, volume))
        self.p = p * c
        return self

    def frame(self, start: str = "2024-01-01") -> BarFrame:
        a = np.asarray(self.rows)
        idx = pd.date_range(
            pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=15), periods=len(a), freq="15min"
        )
        df = pd.DataFrame(
            {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": a[:, 4]},
            index=idx,
        )
        return BarFrame(df, SYM, timeframe="M15", volume_kind="traded", price_venue="x")


def warmup() -> Tape:
    """Five daily-scale cycles (six days up, three down): the HWC, MWC and LWC all trend up."""
    t = Tape()
    for _ in range(5):
        t.leg(6 * DAY, 0.06).leg(3 * DAY, -0.02)
    return t.leg(4 * DAY, 0.04)


def setup_bar(t: Tape, depth: float = 0.006, volume: float = 500.0) -> Tape:
    """A long Candle Setup: a deep lower wick, a tiny body, no upper wick, quiet volume."""
    return t.bar(1.0, 1.0001, 1 - depth, 1.0001, volume)


def fill_bar(t: Tape) -> Tape:
    """Trades through the trigger (the setup's high + 0.05%) and closes above it."""
    return t.bar(1.0, 1.003, 0.9998, 1.002)


def template(**changes: Any) -> Any:
    """The Template cloned into an editable document, with ``changes`` applied by block type."""
    raw = get_template("tcp_azizpour").clone("scenario")
    raw["universe"] = [SYM]
    for b in raw["blocks"]:
        if b["type"] in changes:
            change = changes[b["type"]]
            if isinstance(change, bool):
                b["enabled"] = change
            else:
                b["params"] = {**b["params"], **change}
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return res.document


def run(t: Tape, doc: Any = None, **kw: Any) -> tuple[DocumentRun, Journal]:
    journal = Journal()
    out = backtest_document(doc or template(), {SYM: t.frame()}, {SYM: BTC}, journal=journal, **kw)
    return out, journal


def events(journal: Journal) -> list[dict[str, Any]]:
    return [e for r in journal.records("cycle") for e in r["orders"]]


def align(t: Tape) -> Tape:
    """Flat bars up to the next 4H boundary: the next bar opens a 4H candle."""
    while len(t) % 16:
        t.bar(1.0, 1.0001, 0.9999, 1.0)
    return t


def breakout_tape(top_touches: int) -> Tape:
    """A box under the trend's peak, then a gap through its top edge on a fresh 4H candle.

    The box has ``top_touches`` swing highs on its top edge and two on its bottom.
    """
    t = warmup()
    t.leg(160, -0.025)  # bottom 1, well under the peak so the peak is not a touch
    for _ in range(top_touches):
        t.leg(96, 0.01).leg(96, -0.01)  # a top touch, then the bottom again
    t.leg(96, 0.0095, turn=False)  # back up to just under the top edge, no new swing
    align(t)
    t.bar(1.012, 1.013, 1.011, 1.012).leg(15, 0.003).leg(96, 0.01)
    return t


def refusals(out: DocumentRun) -> list[list[str]]:
    return [c["reasons"] for c in out.candidates]


def stop_moves(journal: Journal) -> list[str]:
    return [
        ev["values"]["reason"]
        for r in journal.records("cycle")
        for ev in r["evaluations"]
        if ev["values"].get("event") == "stop_move"
    ]


# ---------------------------------------------------------------------- scenario 1
def test_a_clean_candle_setup_fills_ladders_out_and_trails():
    t = warmup()
    setup_bar(t)
    fill_bar(t)
    for _ in range(8):  # an uptrend with 4H pullbacks: swings for the breakeven and the trail
        t.leg(96, 0.016).leg(56, -0.005)
    t.leg(2 * DAY, -0.08)  # then it turns over: the Runner is trailed out
    out, journal = run(t)

    (cand,) = out.candidates
    assert cand["setup"] == "candle_setup" and cand["decision"] == "placed"
    names = {i["block"].split("#")[0] for i in cand["checklist"]}
    assert {"second_wave", "rsi_momentum", "volume_continuation"} <= names
    assert not names & {"touch_count", "breakout_body_close", "box_volume_dryup"}  # box-only checks
    assert cand["risk_tier"] == 0.0075  # volume dried up and the Second Wave: score 2
    assert [e["e"] for e in events(journal)] == ["place", "fill", *["close"] * 4]
    trades = out.result.trades
    assert [x.exit_reason for x in trades] == ["target_partial"] * 3 + ["trailing_stop"]
    assert [round(x.r_multiple, 2) for x in trades[:3]] == [2.0, 5.0, 10.0]
    assert trades[3].r_multiple > 10  # the Runner kept the trend
    units = [x.units for x in trades]
    total = sum(units)
    assert [round(u / total, 2) for u in units] == [0.35, 0.40, 0.15, 0.10]  # the Profit Chain
    # Positions are managed on 4H closes: every stop move is stamped on a 4H boundary.
    stamps = [
        pd.Timestamp(ev["time"])
        for r in journal.records("cycle")
        for ev in r["evaluations"]
        if ev["values"].get("event") == "stop_move"
    ]
    assert stamps and all(ts.hour % 4 == 0 and ts.minute == 0 for ts in stamps)
    moves = stop_moves(journal)
    assert moves[0] == "breakeven_after_pivot" and "runner_trail" in moves


# ---------------------------------------------------------------------- scenario 2
def test_a_setup_cancelled_by_an_invalidation_close_never_fills():
    t = warmup()
    setup_bar(t)
    t.bar(1.0, 1.0, 0.99, 0.992)  # closes under the setup's low before the trigger trades
    t.leg(DAY, 0.03)  # the trigger would have been hit afterwards
    out, journal = run(t)

    (cand,) = out.candidates
    assert cand["decision"] == "placed"
    assert [(e["e"], e.get("reason")) for e in events(journal)] == [
        ("place", None),
        ("cancel", "invalidated"),
    ]
    assert out.result.trades == []


# ---------------------------------------------------------------------- scenario 3
def test_a_breakout_on_its_first_touch_is_refused_and_needs_three_touches_to_arm():
    t = breakout_tape(1)
    # As shipped, one touch on the top edge is no box at all: nothing is even considered.
    shipped, _ = run(t)
    assert shipped.candidates == []
    # A cloner who allows one-touch boxes still meets the touch-count rule.
    loose, journal = run(t, template(box_breakout={"min_touches": 1}))
    assert loose.candidates
    label = f"touch_count#{[b.type for b in get_template('tcp_azizpour').document.blocks].index('touch_count')}"
    assert all(c["reasons"] == [f"confirmation:{label}"] for c in loose.candidates)
    assert "rsi_momentum" not in {
        i["block"].split("#")[0] for i in loose.candidates[0]["checklist"]
    }
    item = next(i for i in loose.candidates[0]["checklist"] if i["block"] == label)
    assert item["outcome"] == "fail" and "first touch" in item["reason"]
    assert events(journal) == [] and loose.result.trades == []
    # The same breakout with three touches passes the rule and is placed.
    ok, _ = run(breakout_tape(3))
    assert any(c["decision"] == "placed" for c in ok.candidates)
    assert not any("touch_count" in r for rs in refusals(ok) for r in rs)


# ---------------------------------------------------------------------- scenario 4
def chop_tape() -> Tape:
    t = warmup()
    for _ in range(30):  # the three SMAs knot together: up and down by 0.8% every half day
        t.leg(48, 0.008).leg(48, -0.008)
    for _ in range(4):  # Candle Setups inside the chop
        t.leg(48, 0.008)
        setup_bar(t)
        t.leg(48, -0.008)
    return t


def candle(out: DocumentRun) -> list[dict[str, Any]]:
    return [c for c in out.candidates if c["setup"] == "candle_setup"]


def test_a_choppy_regime_places_no_orders():
    t = chop_tape()
    out, journal = run(t)
    assert len(candle(out)) == 4
    assert all("context:choppy_regime#2" in c["reasons"] for c in candle(out))
    assert events(journal) == [] and out.result.trades == []


def test_the_choppy_filter_alone_is_what_stops_those_setups():
    t = chop_tape()
    # Only the Choppy filter stands between the setups and an order, then not even that.
    contexts = {"wave_cycles": False, "three_sma_alignment": False, "sma_baseline_filter": False}
    alone, journal = run(t, template(**contexts))
    assert len(candle(alone)) == 4
    assert all(c["reasons"] == ["context:choppy_regime#2"] for c in candle(alone))
    assert events(journal) == []
    _, journal = run(t, template(**contexts, choppy_regime=False))
    assert any(e["e"] == "place" for e in events(journal))


# ---------------------------------------------------------------------- scenario 5
def losing_tape(losses: int) -> Tape:
    """A Candle Setup a day, each filled and stopped out at once, then the trend resumes."""
    t = warmup()
    for _ in range(losses):
        setup_bar(t)
        fill_bar(t)
        t.bar(1.0, 1.0, 0.985, 0.988)
        t.leg(DAY, 0.012)
    return t


def test_a_losing_streak_cuts_risk_after_three_and_halts_after_five():
    out, _ = run(losing_tape(8))
    trades = out.result.trades
    assert [x.exit_reason for x in trades] == ["stop"] * 6
    risk = [x.risk_cash / out.result.initial_equity for x in trades]
    assert risk[:3] == pytest.approx([0.0075] * 3, rel=0.03)  # the tier of the setup
    assert risk[3:5] == pytest.approx([0.0025] * 2, rel=0.06)  # after three losses: 0.25%
    placed = [c for c in candle(out) if c["decision"] == "placed"]
    assert [bool(c["risk"]["cuts"]) for c in placed] == [False] * 3 + [True] * 3
    assert all(c["risk"]["cuts"] == ["streak"] for c in placed[3:])
    # Five losses in a row: no entry for 48 hours from the fifth loss, then one is allowed.
    fifth = pd.Timestamp(trades[4].exit_time)
    halted = [c for c in candle(out) if "streak_halt" in c["reasons"]]
    assert halted and all(c["decision"] == "refused" for c in halted)
    assert all(
        fifth <= pd.Timestamp(c["time"]) < fifth + pd.Timedelta(hours=48) for c in halted[:1]
    )
    assert pd.Timestamp(trades[5].entry_time) >= fifth + pd.Timedelta(hours=48)
    assert not any("daily_loss_limit" in r for rs in refusals(out) for r in rs)


def test_the_daily_loss_limit_halts_trading_for_the_day():
    t = warmup()
    for _ in range(4):  # stop-outs within one day, 0.75% each, the trend barely dented
        setup_bar(t)
        fill_bar(t)
        t.bar(1.0, 1.0, 0.99, 0.996)
        t.leg(40, 0.006)
    out, _ = run(t)
    assert len(out.result.trades) == 3  # -1.5% is passed: the fourth setup is refused
    last = candle(out)[-1]
    assert last["decision"] == "refused" and "daily_loss_limit" in last["reasons"]
