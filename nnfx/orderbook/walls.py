"""Walls and spoofs from a sequence of order-book snapshots (ticket 04).

A **Wall** is a resting cluster that is large *for this book*: above the
``percentile`` of the level sizes within ``window_pct`` of the mid and at
least ``min_multiple`` times their median, seen in ``persist`` snapshots in a
row. Thresholds are relative because TCP's numbers come from Binance futures
depth and Nobitex books are far thinner (spec, Further Notes).

A confirmed wall ends in one of three ways:

- **consumed**: price reached it (traded at or through it);
- **spoof**: it vanished, or stepped back by more than ``step_back_pct``, while
  price was approaching it (the gap to the mid shrank since the last snapshot);
- **faded**: it was pulled while price moved away.

The tracker is causal: ``update`` sees one snapshot at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from nnfx.orderbook.book import OrderBookSnapshot

Side = Literal["bid", "ask"]


@dataclass(frozen=True)
class WallParams:
    percentile: float = 95.0
    min_multiple: float = 3.0
    persist: int = 3
    window_pct: float = 2.0  # levels this far from the mid are considered
    cluster_pct: float = 0.05  # levels closer than this merge into one cluster
    follow_pct: float = 2.0  # a wall seen again within this distance is the same wall
    step_back_pct: float = 0.5  # moving away from price by more than this is stepping back


@dataclass(frozen=True)
class Wall:
    side: Side
    price: float
    size: float
    seen: int
    first_seen: pd.Timestamp
    distance_pct: float  # from the mid, at the last snapshot


@dataclass(frozen=True)
class WallEvent:
    time: pd.Timestamp
    kind: Literal["confirmed", "consumed", "spoof", "faded"]
    wall: Wall
    reason: str = ""


@dataclass
class _Track:
    side: Side
    price: float
    size: float
    first_seen: pd.Timestamp
    seen: int = 1
    distance: float = 0.0
    confirmed: bool = False

    def wall(self) -> Wall:
        return Wall(self.side, self.price, self.size, self.seen, self.first_seen, self.distance)


def _distance_pct(side: Side, price: float, mid: float) -> float:
    return (price - mid) / mid * 100.0 if side == "ask" else (mid - price) / mid * 100.0


def _clusters(levels: np.ndarray, cluster_pct: float) -> list[tuple[float, float]]:
    """Merge neighbouring levels; a cluster sits at its largest level."""
    out: list[tuple[float, float]] = []
    cur: list[tuple[float, float]] = []
    for p, s in levels:
        if cur and abs(p - cur[-1][0]) > cluster_pct / 100.0 * p:
            out.append((max(cur, key=lambda x: x[1])[0], sum(x[1] for x in cur)))
            cur = []
        cur.append((float(p), float(s)))
    if cur:
        out.append((max(cur, key=lambda x: x[1])[0], sum(x[1] for x in cur)))
    return out


@dataclass
class WallTracker:
    params: WallParams = field(default_factory=WallParams)
    events: list[WallEvent] = field(default_factory=list)
    _tracks: list[_Track] = field(default_factory=list)

    def walls(self) -> list[Wall]:
        """Confirmed walls standing at the last snapshot."""
        return [t.wall() for t in self._tracks if t.confirmed]

    def candidates(self, s: OrderBookSnapshot) -> list[tuple[Side, float, float]]:
        """(side, price, size) of clusters large enough to be walls in this book."""
        prm, mid = self.params, s.mid
        sides: list[tuple[Side, list[tuple[float, float]]]] = []
        sizes: list[float] = []
        for side, levels in (("bid", s.bids), ("ask", s.asks)):
            near = levels[np.abs(levels[:, 0] - mid) <= prm.window_pct / 100.0 * mid]
            cl = _clusters(near, prm.cluster_pct)
            sides.append((side, cl))  # type: ignore[arg-type]
            sizes += [c[1] for c in cl]
        if not sizes:
            return []
        cut = max(
            float(np.percentile(sizes, prm.percentile)), prm.min_multiple * float(np.median(sizes))
        )
        return [(side, p, z) for side, cl in sides for p, z in cl if z > cut]

    def update(self, s: OrderBookSnapshot) -> list[WallEvent]:
        """Feed the next snapshot; returns the events it caused."""
        prm, mid = self.params, s.mid
        cands = self.candidates(s)
        used: set[int] = set()
        new: list[WallEvent] = []
        keep: list[_Track] = []
        for tr in self._tracks:
            near = [
                (abs(p - tr.price), k)
                for k, (side, p, _) in enumerate(cands)
                if side == tr.side
                and k not in used
                and abs(p - tr.price) <= prm.follow_pct / 100.0 * tr.price
            ]
            dist = _distance_pct(tr.side, tr.price, mid)
            approaching = dist < tr.distance - 1e-12
            if near:
                k = min(near)[1]
                used.add(k)
                _, p, z = cands[k]
                away = (p - tr.price) if tr.side == "ask" else (tr.price - p)
                if away > prm.step_back_pct / 100.0 * tr.price and approaching:
                    if tr.confirmed:
                        new.append(WallEvent(s.time, "spoof", tr.wall(), "stepped_back"))
                    continue
                tr.price, tr.size, tr.seen = p, z, tr.seen + 1
                tr.distance = _distance_pct(tr.side, p, mid)
                if not tr.confirmed and tr.seen >= prm.persist:
                    tr.confirmed = True
                    new.append(WallEvent(s.time, "confirmed", tr.wall()))
                keep.append(tr)
                continue
            if tr.confirmed:
                if self._reached(tr, s):
                    new.append(WallEvent(s.time, "consumed", tr.wall()))
                elif approaching:
                    new.append(WallEvent(s.time, "spoof", tr.wall(), "vanished"))
                else:
                    new.append(WallEvent(s.time, "faded", tr.wall()))
        for k, (side, p, z) in enumerate(cands):
            if k not in used:
                tr = _Track(side, p, z, s.time, distance=_distance_pct(side, p, mid))
                if prm.persist <= 1:
                    tr.confirmed = True
                    new.append(WallEvent(s.time, "confirmed", tr.wall()))
                keep.append(tr)
        self._tracks = keep
        self.events += new
        return new

    @staticmethod
    def _reached(tr: _Track, s: OrderBookSnapshot) -> bool:
        last = s.last_trade
        if tr.side == "ask":
            return (
                s.best_bid >= tr.price
                or s.best_ask > tr.price
                or (last is not None and last >= tr.price)
            )
        return (
            s.best_ask <= tr.price
            or s.best_bid < tr.price
            or (last is not None and last <= tr.price)
        )
