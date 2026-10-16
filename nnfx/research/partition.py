"""Development / validation / holdout partitioning (doc 03 §3, §3b).

The evidence standard is structural rather than remembered: data for a
segment is only obtainable through ``Partition.segment``, and the holdout only
through ``HoldoutGuard.touch``, which refuses a second access forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from nnfx.data.bars import BarFrame

SegmentName = Literal["development", "validation", "holdout"]
Market = Literal["fx", "crypto"]


@dataclass(frozen=True)
class Segment:
    name: SegmentName
    start: pd.Timestamp
    end: pd.Timestamp  # inclusive

    def contains(self, ts: pd.Timestamp) -> bool:
        return bool(self.start <= ts <= self.end)


def _seg(name: SegmentName, y0: int, y1: int) -> Segment:
    return Segment(
        name, pd.Timestamp(f"{y0}-01-01", tz="UTC"), pd.Timestamp(f"{y1}-12-31 23:59:59", tz="UTC")
    )


PARTITIONS: dict[Market, tuple[Segment, Segment, Segment]] = {
    "fx": (
        _seg("development", 2004, 2015),
        _seg("validation", 2016, 2021),
        _seg("holdout", 2022, 2026),
    ),
    "crypto": (
        _seg("development", 2017, 2021),
        _seg("validation", 2022, 2024),
        _seg("holdout", 2025, 2026),
    ),
}


class HoldoutAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class Partition:
    market: Market
    development: Segment
    validation: Segment
    holdout: Segment

    @classmethod
    def for_market(cls, market: Market) -> Partition:
        d, v, h = PARTITIONS[market]
        return cls(market, d, v, h)

    def get(self, name: SegmentName) -> Segment:
        seg: Segment = getattr(self, name)
        return seg

    def segment(
        self, frame: BarFrame, name: SegmentName, *, _holdout_token: object = None
    ) -> BarFrame:
        """Slice ``frame`` to a segment. The holdout needs a token from ``HoldoutGuard``."""
        if name == "holdout" and _holdout_token is not _HOLDOUT_TOKEN:
            raise HoldoutAccessError(
                "the holdout is touch-once; obtain it via HoldoutGuard.touch() (doc 03 §3)"
            )
        seg = self.get(name)
        # Include warmup history before the segment start: indicators need it, and
        # trading is restricted to the segment by the harness's trade window.
        return frame.between(None, seg.end)


_HOLDOUT_TOKEN = object()
