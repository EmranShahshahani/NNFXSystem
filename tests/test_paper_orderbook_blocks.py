"""Order-book Blocks read the recorded books in Paper Runs (Strategy Builder ticket 25, ADR 10 §28)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nnfx.alerts import AlertStore, BaleSender, Notifier
from nnfx.orderbook import LiveRecordedOrderBook, OrderBookSnapshot, RecordedOrderBook
from nnfx.orderbook.sources import append_snapshot
from nnfx.strategy.book import BookData
from nnfx.strategy.paper import PaperManager
from tests.test_strategy_engine import BTC, SYM, frame, run
from tests.test_strategy_orderbook import ROWS, T, book, book_doc, standing
from tests.test_strategy_paper import COMPARED, Bars, cycles, start, step_through

F = frame(ROWS)
INST = {SYM: BTC}
WALLS = dict(asks=((112.0, 80.0),), bids=((109.0, 60.0),))


def write(root: Path, snaps: list[OrderBookSnapshot]) -> None:
    for s in snaps:
        append_snapshot(root, s)


def manager(tmp_path: Path, root: Path | None, bars: Bars | None = None) -> PaperManager:
    n = Notifier(AlertStore(tmp_path / "alerts"), BaleSender("T", post=lambda u, b: None))
    live = None if root is None else BookData(LiveRecordedOrderBook(root, history=None))
    return PaperManager(tmp_path / "paper", INST, bars or Bars(F), n, book=live)


def play(m: PaperManager) -> str:
    rid = start(m, raw=book_doc())
    step_through(m, F)
    return rid


def test_a_paper_run_decides_as_the_order_book_backtest_over_the_same_recording(tmp_path: Path):
    rec = tmp_path / "rec"
    write(rec, standing(**WALLS))
    _, bt_journal = run(ROWS, book_doc(), book_data=BookData(RecordedOrderBook(rec)))
    bt = {r["time"]: {k: r[k] for k in COMPARED} for r in bt_journal.records("cycle")}
    m = manager(tmp_path, rec)
    rid = play(m)
    paper = cycles(m.run_dir("ali", rid) / "journal.jsonl")
    assert set(paper) == set(bt)
    for t in bt:
        assert json.dumps(paper[t], sort_keys=True) == json.dumps(bt[t], sort_keys=True), t
    (ev,) = [e for c in bt_journal.records("cycle") for e in c["evaluations"]]
    assert ev["intents"][0]["level"] == pytest.approx(112.0 * 1.0005)  # the walls did matter


def test_a_restart_on_every_bar_changes_nothing(tmp_path: Path):
    rec = tmp_path / "rec"
    write(rec, standing(**WALLS))
    whole = manager(tmp_path / "a", rec)
    want = cycles(whole.run_dir("ali", play(whole)) / "journal.jsonl")
    bars = Bars(F)
    rid = start(manager(tmp_path / "b", rec, bars), raw=book_doc())
    for now in list(F.index)[1:]:
        manager(tmp_path / "b", rec, bars).tick(now + pd.Timedelta(minutes=1))  # a fresh process
    got = cycles(manager(tmp_path / "b", rec, bars).run_dir("ali", rid) / "journal.jsonl")
    for t in got:
        assert json.dumps(got[t], sort_keys=True) == json.dumps(want[t], sort_keys=True), t


def test_books_recorded_while_the_run_goes_are_seen_by_later_cycles(tmp_path: Path):
    rec = tmp_path / "rec"
    m = manager(tmp_path, rec)
    rid = start(m, raw=book_doc())
    for now in list(F.index)[:10]:  # up to the bar before the setup: no book recorded yet
        m.tick(now + pd.Timedelta(minutes=1))
    write(rec, standing(**WALLS))  # the recorder catches up
    for now in list(F.index)[10:]:
        m.tick(now + pd.Timedelta(minutes=1))
    journal = [
        json.loads(ln) for ln in (m.run_dir("ali", rid) / "journal.jsonl").read_text().splitlines()
    ]
    (ev,) = [e for r in journal if r["type"] == "cycle" for e in r["evaluations"]]
    assert ev["values"]["book_missing"] == [] and ev["intents"][0]["level"] > 112.0


def test_without_recorded_books_the_run_trades_plainly_and_says_so(tmp_path: Path):
    m = manager(tmp_path, None)
    rid = play(m)
    j = [
        json.loads(ln) for ln in (m.run_dir("ali", rid) / "journal.jsonl").read_text().splitlines()
    ]
    (ev,) = [e for r in j if r["type"] == "cycle" for e in r["evaluations"]]
    assert len(ev["values"]["book_missing"]) == 3 and ev["intents"][0]["level"] == 111.3


def test_the_run_reports_the_stretches_without_a_book(tmp_path: Path):
    rec = tmp_path / "rec"
    write(rec, standing(**WALLS))  # only around the setup
    m = manager(tmp_path, rec)
    play(m)
    (info,) = m.runs("ali")
    assert info.book_gaps and all({"symbol", "start", "end"} <= set(g) for g in info.book_gaps)
    assert info.public()["book_gaps"] == info.book_gaps
    plain = manager(tmp_path / "x", rec)
    rid = start(plain)  # a document without order-book Blocks reports none
    step_through(plain, F)
    assert plain.runs("ali")[0].id == rid and plain.runs("ali")[0].book_gaps == []


def test_a_cycle_reads_only_what_was_recorded_since_the_last_one(tmp_path: Path):
    rec = tmp_path / "rec"
    reader = LiveRecordedOrderBook(rec, history=None)
    reader.snapshots(SYM, T, T)  # a symbol is read once something asks about it
    write(rec, [book(t) for t in range(-2000, 0)])
    reader.refresh()
    assert reader.parsed_lines == 2000
    write(rec, [book(t) for t in range(0, 3)])
    reader.refresh()
    assert reader.parsed_lines == 2003  # three new lines, not the whole file again
    reader.refresh()
    assert reader.parsed_lines == 2003


def test_a_half_written_line_waits_for_the_rest(tmp_path: Path):
    rec = tmp_path / "rec"
    reader = LiveRecordedOrderBook(rec, history=None)
    write(rec, [book(0)])
    (f,) = rec.rglob("*.jsonl")
    full = json.dumps(book(10).to_json(), separators=(",", ":"))
    with f.open("a") as fh:
        fh.write(full[:40])  # the recorder is mid-write
    reader.refresh()
    assert len(reader.snapshots(SYM, T - pd.Timedelta(hours=1), T + pd.Timedelta(hours=1))) == 1
    with f.open("a") as fh:
        fh.write(full[40:] + "\n")
    reader.refresh()
    assert len(reader.snapshots(SYM, T - pd.Timedelta(hours=1), T + pd.Timedelta(hours=1))) == 2


def test_days_older_than_the_history_are_not_read(tmp_path: Path):
    rec = tmp_path / "rec"
    old = OrderBookSnapshot.of(SYM, T - pd.Timedelta(days=30), [[99, 1]], [[101, 1]])
    write(rec, [old, book(0)])
    reader = LiveRecordedOrderBook(rec, history=pd.Timedelta(days=2), clock=lambda: T)
    reader.snapshots(SYM, T, T)
    assert reader.parsed_lines == 1


def test_old_states_are_forgotten_but_the_latest_before_the_cutoff_still_answers(tmp_path: Path):
    rec = tmp_path / "rec"
    write(rec, [book(t) for t in range(-100, 0, 10)])
    data = BookData(LiveRecordedOrderBook(rec, history=None))
    from nnfx.orderbook import WallParams

    params, age = WallParams(), pd.Timedelta(hours=1)
    assert data.at(SYM, T, params, age) is not None
    tl = data._timeline(SYM, params)
    assert len(tl.times) == 10
    data.refresh(forget_before=T - pd.Timedelta(seconds=35))
    assert len(tl.times) == 4  # the latest state before the cutoff is kept, then the 3 after
    assert data.at(SYM, T, params, age) is not None
    assert BookData().refresh() is None  # no source: nothing to do
