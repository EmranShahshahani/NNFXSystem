"""Record live order-book snapshots so order-book rules become backtestable (ticket 04)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import pandas as pd

from nnfx.orderbook.book import OrderBookSnapshot
from nnfx.orderbook.sources import append_snapshot


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
    clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
    on_error: Callable[[str], None] = lambda msg: None,
) -> int:
    """Poll ``symbols`` every ``interval_s`` and append each book; returns books stored.

    Each snapshot is stamped with the recorder's clock at the poll, the time a
    strategy would have seen it. A failed poll is reported and skipped, never
    fatal: a gap in the recording is better than a dead recorder.
    """
    stored, n = 0, 0
    while iterations is None or n < iterations:
        if n:
            sleep(interval_s)
        n += 1
        now = clock()
        try:
            books = source.snapshots_now(symbols)
        except Exception as exc:  # network, rate limit, bad payload: keep recording
            on_error(f"{now.isoformat()} order-book poll failed: {exc}")
            continue
        for sym in symbols:
            append_snapshot(root, books[sym].at(now))
            stored += 1
    return stored
