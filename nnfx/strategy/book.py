"""Order-book context for the order-book Blocks (Strategy Builder ticket 21, ADR 10 §25).

``BookData`` wraps one history of snapshots (the recorder's, or a fixture) and answers
"what walls stood at this moment": the snapshots are fed once, in time order, to a
``WallTracker`` per (symbol, wall parameters), and each snapshot's state is kept. A Block
asks for the state at a candidate's time and gets the latest snapshot at or before it, never
a later one, or None when there is none, it is too old, or the book was one-sided. Spoofed
walls (vanished, stepped back or re-confirmed at a spoofed level) are never in the state.

Without recorded snapshots the book is simply absent: every question answers None, and the
Blocks that need it fall back to their plain behaviour while the run is flagged incomplete.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Protocol

import pandas as pd

from nnfx.orderbook import OrderBookSnapshot, Wall, WallParams, WallTracker

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
FAR = pd.Timestamp("2200-01-01", tz="UTC")


class BookHistory(Protocol):
    """The slice of a historical Order Book Source this module reads."""

    def snapshots(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[OrderBookSnapshot]: ...


@dataclass(frozen=True)
class BookState:
    """What stood in one market's book at one snapshot."""

    time: pd.Timestamp  # when the snapshot was seen
    born: pd.Timestamp  # when the exchange last updated it (staleness is judged on this)
    mid: float
    walls: tuple[Wall, ...]  # confirmed and not suspect: spoofs are not in here

    def walls_on(self, side: str) -> list[Wall]:
        return [w for w in self.walls if w.side == side]


def utc(t: pd.Timestamp | str) -> pd.Timestamp:
    """``t`` as a UTC timestamp (a naive one is taken to be UTC already)."""
    ts = pd.Timestamp(t)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


@dataclass(frozen=True)
class _Timeline:
    times: list[pd.Timestamp]
    states: list[BookState | None]  # None: a one-sided or crossed book


@dataclass(frozen=True)
class BookData:
    """Order-book snapshots, or nothing (``source`` None) for a run without a recording."""

    source: BookHistory | None = None
    _timelines: dict[tuple[str, WallParams], _Timeline] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def present(self) -> bool:
        return self.source is not None

    def _timeline(self, symbol: str, params: WallParams) -> _Timeline:
        key = (symbol, params)
        if key not in self._timelines:
            assert self.source is not None
            tracker = WallTracker(params)
            times: list[pd.Timestamp] = []
            states: list[BookState | None] = []
            for s in self.source.snapshots(symbol, EPOCH, FAR):
                tracker.update(s)
                times.append(s.time)
                states.append(
                    BookState(
                        s.time,
                        s.exchange_time if s.exchange_time is not None else s.time,
                        s.mid,
                        tuple(tracker.walls()),
                    )
                    if s.two_sided
                    else None
                )
            self._timelines[key] = _Timeline(times, states)
        return self._timelines[key]

    def at(
        self, symbol: str, time: pd.Timestamp | str, params: WallParams, max_age: pd.Timedelta
    ) -> BookState | None:
        """The book as of ``time``: the latest snapshot seen by then, if fresh and two-sided."""
        if self.source is None:
            return None
        at = utc(time)
        tl = self._timeline(symbol, params)
        i = bisect.bisect_right(tl.times, at) - 1
        if i < 0:
            return None
        state = tl.states[i]
        return None if state is None or at - state.born > max_age else state

    def gaps(
        self, symbol: str, start: pd.Timestamp | str, end: pd.Timestamp | str, max_gap: pd.Timedelta
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Stretches of [start, end] longer than ``max_gap`` with no snapshot at all."""
        lo, hi = utc(start), utc(end)
        if self.source is None:
            return [(lo, hi)]
        # A snapshot just before ``start`` still covers its first stretch.
        seen = self.source.snapshots(symbol, lo - max_gap, hi)
        edges = [lo, *(max(lo, s.time) for s in seen), hi]
        return [(a, b) for a, b in pairwise(edges) if b - a > max_gap]
