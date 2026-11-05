"""Record live order-book snapshots so order-book rules become backtestable (ticket 04)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import pandas as pd

from nnfx.orderbook.book import OrderBookSnapshot
from nnfx.orderbook.sources import append_snapshot, utc_now


class LiveOrderBook(Protocol):
    def snapshots_now(self, symbols: Sequence[str]) -> dict[str, OrderBookSnapshot]: ...


def record(
    source: LiveOrderBook,
    symbols: Sequence[str],
    root: Path | str,
    *,
    interval_s: float = 10.0,
    iterations: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], pd.Timestamp] = utc_now,
    on_error: Callable[[str], None] = lambda msg: None,
) -> int:
    """Poll ``symbols`` every ``interval_s`` and append each book; returns books stored.

    Polls keep a fixed rhythm (poll time is taken out of the wait). Each book is
    stamped with the recorder's clock at the poll, the time a strategy would
    have seen it, and keeps the exchange's own update time. A failed poll, a
    symbol the exchange did not answer for, or a failed write is reported and
    skipped, never fatal: a gap in the recording is better than a dead recorder.
    """
    stored, n = 0, 0
    start: pd.Timestamp | None = None
    while iterations is None or n < iterations:
        if start is not None:
            due = start + pd.Timedelta(seconds=n * interval_s)
            sleep(max(0.0, (due - clock()).total_seconds()))
        n += 1
        now = clock()
        start = now if start is None else start
        try:
            books = source.snapshots_now(symbols)
        except Exception as exc:  # network, rate limit, bad payload: keep recording
            on_error(f"{now.isoformat()} order-book poll failed: {exc}")
            continue
        for sym in symbols:
            if sym not in books:
                on_error(f"{now.isoformat()} no order book for {sym} in the response")
                continue
            try:
                append_snapshot(root, books[sym].seen_at(now))
                stored += 1
            except OSError as exc:
                on_error(f"{now.isoformat()} could not store the {sym} book: {exc}")
    return stored
