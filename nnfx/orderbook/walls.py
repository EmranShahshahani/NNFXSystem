"""Walls and spoofs from a sequence of order-book snapshots (ticket 04).

A **Wall** is a resting cluster that is large *for this book*: bigger than the
``percentile`` of all the book's level sizes and at least ``min_multiple``
times their median, within ``window_pct`` of the mid, seen in ``persist``
snapshots in a row. Thresholds are relative because TCP's numbers come from
Binance futures depth and Nobitex books are far thinner (spec, Further Notes).
A cluster is neighbouring levels closer than ``cluster_pct``; it reports its
largest level (``price``) and its edges (``low``, ``high``).

A confirmed wall ends in one of three ways:

- **consumed**: price reached it (traded at or through it), even in one jump;
- **spoof**: it vanished, or stepped back by more than ``step_back_pct``, while
  price was approaching (the gap to the mid shrank since the last snapshot);
- **faded**: it was pulled while price moved away.

A price level that spoofed stays under suspicion for ``spoof_memory``
snapshots: a wall confirmed there again is flagged ``suspect`` and left out of
``walls()`` unless asked for. One-sided and crossed books are skipped. The
tracker is causal: ``update`` sees one snapshot at a time.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from nnfx.orderbook.book import OrderBookSnapshot

Side = Literal["bid", "ask"]
# Away from price: up for asks, down for bids.
AWAY: dict[Side, int] = {"ask": 1, "bid": -1}


def pct_of(price: float, pct: float) -> float:
    return price * pct / 100.0


@dataclass(frozen=True)
class WallParams:
    percentile: float = 95.0
    min_multiple: float = 3.0
    persist: int = 3
    window_pct: float = 5.0  # clusters this far from the mid are considered
    cluster_pct: float = 0.05  # levels closer than this merge into one cluster
    same_pct: float = 0.15  # a cluster this close to a tracked wall is that wall
    follow_pct: float = 2.0  # how far a wall may step back and still be the same wall
    step_back_pct: float = 0.5  # stepping back further than this while price nears is a spoof
    spoof_memory: int = 30  # snapshots a spoofed level stays suspect
    max_events: int = 10_000  # events kept in ``events`` (the service runs for months)


@dataclass(frozen=True)
class Cluster:
    side: Side
    price: float  # its largest level
    low: float
    high: float
    size: float

    def gap_pct(self, mid: float) -> float:
        """Distance from the mid to the cluster's near edge, in % of the mid."""
        near = self.low if self.side == "ask" else self.high
        return AWAY[self.side] * (near - mid) / mid * 100.0


@dataclass(frozen=True)
class Wall:
    side: Side
    price: float
    low: float
    high: float
    size: float
    seen: int
    first_seen: pd.Timestamp
    gap_pct: float  # from the mid to the near edge, at the last snapshot
    suspect: bool = False  # confirmed at a level that spoofed recently


@dataclass(frozen=True)
class WallEvent:
    time: pd.Timestamp
    kind: Literal["confirmed", "consumed", "spoof", "faded"]
    wall: Wall
    reason: str = ""


@dataclass
class _Track:
    cluster: Cluster
    first_seen: pd.Timestamp
    gap: float
    seen: int = 1
    confirmed: bool = False
    suspect: bool = False

    def wall(self) -> Wall:
        c = self.cluster
        return Wall(
            c.side,
            c.price,
            c.low,
            c.high,
            c.size,
            self.seen,
            self.first_seen,
            self.gap,
            self.suspect,
        )

    def reached_by(self, s: OrderBookSnapshot) -> bool:
        """Price traded at or through the wall."""
        c, last = self.cluster, s.last_trade
        if c.side == "ask":
            return (
                s.best_bid >= c.price
                or s.best_ask > c.price
                or (last is not None and last >= c.price)
            )
        return (
            s.best_ask <= c.price or s.best_bid < c.price or (last is not None and last <= c.price)
        )


def _clusters(side: Side, levels: np.ndarray, cluster_pct: float) -> list[Cluster]:
    """Merge neighbouring levels into clusters."""
    groups: list[list[tuple[float, float]]] = []
    for p, z in levels:
        if groups and abs(p - groups[-1][-1][0]) <= pct_of(p, cluster_pct):
            groups[-1].append((float(p), float(z)))
        else:
            groups.append([(float(p), float(z))])
    out = []
    for g in groups:
        prices = [p for p, _ in g]
        out.append(
            Cluster(
                side, max(g, key=lambda x: x[1])[0], min(prices), max(prices), sum(z for _, z in g)
            )
        )
    return out


@dataclass
class WallTracker:
    params: WallParams = field(default_factory=WallParams)
    events: deque[WallEvent] = field(default_factory=deque)
    _tracks: list[_Track] = field(default_factory=list)
    _spoofed: dict[tuple[Side, float], int] = field(default_factory=dict)  # level -> snapshots left

    def walls(self, *, include_suspect: bool = False) -> list[Wall]:
        """Confirmed walls standing at the last snapshot."""
        return [
            t.wall() for t in self._tracks if t.confirmed and (include_suspect or not t.suspect)
        ]

    def candidates(self, s: OrderBookSnapshot) -> list[Cluster]:
        """Clusters near the mid that are large compared with the whole book."""
        prm, mid = self.params, s.mid
        sizes = np.concatenate([s.bids[:, 1], s.asks[:, 1]])
        if not len(sizes):
            return []
        cut = max(
            float(np.percentile(sizes, prm.percentile)), prm.min_multiple * float(np.median(sizes))
        )
        out = []
        for side, levels in (("bid", s.bids), ("ask", s.asks)):
            near = levels[np.abs(levels[:, 0] - mid) <= pct_of(mid, prm.window_pct)]
            out += [c for c in _clusters(side, near, prm.cluster_pct) if c.size > cut]  # type: ignore[arg-type]
        return out

    def _was_spoofed(self, c: Cluster) -> bool:
        return any(
            side == c.side and abs(p - c.price) <= pct_of(p, self.params.same_pct)
            for side, p in self._spoofed
        )

    def update(self, s: OrderBookSnapshot) -> list[WallEvent]:
        """Feed the next snapshot; returns the events it caused."""
        if not s.two_sided:
            return []
        prm, mid = self.params, s.mid
        self._spoofed = {k: v - 1 for k, v in self._spoofed.items() if v > 1}
        cands = self.candidates(s)
        free = set(range(len(cands)))
        matched: dict[int, int] = {}  # track -> candidate
        # 1. Same wall: a candidate at (nearly) the same price. Closest pairs first.
        pairs = sorted(
            (abs(c.price - tr.cluster.price), ti, ci)
            for ti, tr in enumerate(self._tracks)
            for ci, c in enumerate(cands)
            if c.side == tr.cluster.side
            and abs(c.price - tr.cluster.price) <= pct_of(tr.cluster.price, prm.same_pct)
        )
        for _, ti, ci in pairs:
            if ti not in matched and ci in free:
                matched[ti] = ci
                free.discard(ci)
        new: list[WallEvent] = []
        keep: list[_Track] = []
        for ti, tr in enumerate(self._tracks):
            c0 = tr.cluster
            approaching = c0.gap_pct(mid) < tr.gap - 1e-12
            if tr.confirmed and tr.reached_by(s):
                new.append(WallEvent(s.time, "consumed", tr.wall()))
                continue
            if ti in matched:
                self._advance(tr, cands[matched[ti]], s, new)
                keep.append(tr)
                continue
            # 2. Moved: an unclaimed candidate further from price, within follow_pct.
            away = [
                ci
                for ci in free
                if cands[ci].side == c0.side
                and 0
                < AWAY[c0.side] * (cands[ci].price - c0.price)
                <= pct_of(c0.price, prm.follow_pct)
            ]
            if away:
                ci = min(away, key=lambda k: abs(cands[k].price - c0.price))
                stepped = AWAY[c0.side] * (cands[ci].price - c0.price) > pct_of(
                    c0.price, prm.step_back_pct
                )
                if stepped and approaching:
                    if tr.confirmed:
                        self._spoof(tr, s, "stepped_back", new)
                    continue
                free.discard(ci)
                self._advance(tr, cands[ci], s, new)
                keep.append(tr)
                continue
            if tr.confirmed:
                if approaching:
                    self._spoof(tr, s, "vanished", new)
                else:
                    new.append(WallEvent(s.time, "faded", tr.wall()))
        for ci in sorted(free):
            tr = _Track(cands[ci], s.time, cands[ci].gap_pct(mid))
            tr.seen = 0
            self._advance(tr, cands[ci], s, new)
            keep.append(tr)
        self._tracks = keep
        self.events.extend(new)
        while len(self.events) > prm.max_events:
            self.events.popleft()
        return new

    def _advance(self, tr: _Track, c: Cluster, s: OrderBookSnapshot, new: list[WallEvent]) -> None:
        tr.cluster, tr.seen, tr.gap = c, tr.seen + 1, c.gap_pct(s.mid)
        if not tr.confirmed and tr.seen >= self.params.persist:
            tr.confirmed, tr.suspect = True, self._was_spoofed(c)
            new.append(WallEvent(s.time, "confirmed", tr.wall()))

    def _spoof(self, tr: _Track, s: OrderBookSnapshot, reason: str, new: list[WallEvent]) -> None:
        new.append(WallEvent(s.time, "spoof", tr.wall(), reason))
        self._spoofed[(tr.cluster.side, tr.cluster.price)] = self.params.spoof_memory
