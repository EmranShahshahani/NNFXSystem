"""A stale order book is announced once per outage in a Paper Run (ticket 26, ADR 10 §28)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from nnfx.orderbook import OrderBookSnapshot
from nnfx.orderbook.sources import append_snapshot
from tests.test_paper_orderbook_blocks import SYM, F, book_doc, manager
from tests.test_strategy_paper import Bars, start

BARS = list(F.index)


def snap_before(bar: int) -> OrderBookSnapshot:
    """A two-sided book seen 20 s before bar ``bar`` closed (fresh for the 120 s default)."""
    return OrderBookSnapshot.of(
        SYM, BARS[bar] - pd.Timedelta(seconds=20), [[99, 1]], [[101, 1]], 100.0
    )


def tick(m, bar: int) -> None:
    m.tick(BARS[bar] + pd.Timedelta(minutes=1))


def kinds(m) -> list[tuple[str, str]]:
    m.notifier.flush()
    return [(a["kind"], a["time"][11:16]) for a in m.notifier.store.feed("ali")]


def outage(m, rec: Path) -> None:
    """Books for bars 0-5, none for 6-11, books again from 12."""
    for b in range(6):
        append_snapshot(rec, snap_before(b))
    for b in range(6):
        tick(m, b)
    for b in range(6, 12):
        tick(m, b)
    for b in range(12, len(BARS)):
        append_snapshot(rec, snap_before(b))
        tick(m, b)


def test_one_alert_when_the_books_stop_and_one_when_they_are_back(tmp_path: Path):
    rec = tmp_path / "rec"
    m = manager(tmp_path, rec)
    start(m, raw=book_doc())
    outage(m, rec)
    stale = [k for k in kinds(m) if k[0].startswith("book_")]
    assert stale == [
        ("book_stale", BARS[6].strftime("%H:%M")),
        ("book_back", BARS[12].strftime("%H:%M")),
    ]
    (info,) = m.runs("ali")
    assert info.status == "running" and info.book_stale == []  # the run went on, recovered


def test_the_run_keeps_deciding_through_the_outage(tmp_path: Path):
    rec = tmp_path / "rec"
    m = manager(tmp_path, rec)
    rid = start(m, raw=book_doc())
    outage(m, rec)
    j = [
        json.loads(ln) for ln in (m.run_dir("ali", rid) / "journal.jsonl").read_text().splitlines()
    ]
    assert len([r for r in j if r["type"] == "cycle"]) == len(BARS)


def test_a_restart_in_the_middle_of_an_outage_does_not_alert_again(tmp_path: Path):
    rec = tmp_path / "rec"
    bars = Bars(F)
    start(manager(tmp_path, rec, bars), raw=book_doc())
    append_snapshot(rec, snap_before(0))
    for b in range(len(BARS)):
        manager(tmp_path, rec, bars).tick(
            BARS[b] + pd.Timedelta(minutes=1)
        )  # a new process each bar
    m = manager(tmp_path, rec, bars)
    assert [k for k in kinds(m) if k[0] == "book_stale"] == [
        ("book_stale", BARS[1].strftime("%H:%M"))
    ]


def test_a_run_whose_document_has_no_order_book_blocks_never_raises_it(tmp_path: Path):
    rec = tmp_path / "rec"
    m = manager(tmp_path, rec)
    start(m)  # the plain document
    for b in range(len(BARS)):
        tick(m, b)
    assert [k for k in kinds(m) if k[0].startswith("book_")] == []


def test_without_a_recordings_directory_there_is_nothing_to_go_stale(tmp_path: Path):
    m = manager(tmp_path, None)
    start(m, raw=book_doc())
    for b in range(len(BARS)):
        tick(m, b)
    assert [k for k in kinds(m) if k[0].startswith("book_")] == []


def test_the_alert_goes_to_bale_too_and_a_bale_outage_changes_no_decision(tmp_path: Path):
    from nnfx.alerts import AlertSettings

    rec = tmp_path / "rec"
    m = manager(tmp_path, rec)
    sent: list[dict] = []
    m.notifier.bale.post = lambda url, body: sent.append(body)  # type: ignore[union-attr]
    m.notifier.store.set_settings("ali", AlertSettings(True, True, "7", True))
    rid = start(m, raw=book_doc())
    outage(m, rec)
    m.notifier.flush()
    assert sum("دفتر سفارش" in b["text"] for b in sent) == 2  # stale once, back once

    def down(url: str, body: dict) -> None:
        raise OSError("bale unreachable")

    rec2 = tmp_path / "rec2"
    m2 = manager(tmp_path / "two", rec2)
    m2.notifier.bale.post = down  # type: ignore[union-attr]
    m2.notifier.bale.sleep = lambda s: None  # type: ignore[union-attr]
    m2.notifier.store.set_settings("ali", AlertSettings(True, True, "7", True))
    rid2 = start(m2, raw=book_doc())
    outage(m2, rec2)
    m2.notifier.flush()
    n = lambda mm, r: len(  # noqa: E731
        [
            ln
            for ln in (mm.run_dir("ali", r) / "journal.jsonl").read_text().splitlines()
            if '"cycle"' in ln
        ]
    )
    assert n(m, rid) == n(m2, rid2) == len(BARS)
