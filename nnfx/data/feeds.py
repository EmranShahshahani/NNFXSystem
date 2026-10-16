"""BarFeed protocol and the CSV feed."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pandas as pd

from nnfx.data.bars import BarFrame, VolumeKind

HttpGet = Callable[[str], bytes]


class BarFeed(Protocol):
    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame: ...


def read_bars_csv(
    path: Path | str,
    symbol: str,
    *,
    timeframe: str = "D1",
    volume_kind: VolumeKind = "traded",
    venue: str | None = None,
) -> BarFrame:
    """Read a CSV with a ``time`` column (bar close, ISO8601 or naive-UTC) and OHLCV."""
    df = pd.read_csv(path)
    tcol = next((c for c in ("close_time", "time", "date", "timestamp") if c in df.columns), None)
    if tcol is None:
        raise ValueError(f"{path}: needs a close_time/time/date/timestamp column")
    idx = pd.to_datetime(df.pop(tcol), utc=True)
    df.index = pd.DatetimeIndex(idx)
    df.columns = [c.lower() for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
        volume_kind = "none"
    return BarFrame(df, symbol, timeframe=timeframe, volume_kind=volume_kind, price_venue=venue)


class CsvFeed:
    """Bars from ``<root>/<symbol>.csv`` (``/`` and ``:`` in symbols become ``_``)."""

    def __init__(
        self,
        root: Path | str,
        *,
        timeframe: str = "D1",
        volume_kind: VolumeKind = "traded",
        venue: str | None = None,
    ) -> None:
        self.root = Path(root)
        self.timeframe = timeframe
        self.volume_kind: VolumeKind = volume_kind
        self.venue = venue

    def path(self, symbol: str) -> Path:
        return self.root / (symbol.replace("/", "_").replace(":", "_") + ".csv")

    def bars(
        self, symbol: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None
    ) -> BarFrame:
        frame = read_bars_csv(
            self.path(symbol),
            symbol,
            timeframe=self.timeframe,
            volume_kind=self.volume_kind,
            venue=self.venue,
        )
        return frame.between(start, end)


def write_bars_csv(frame: BarFrame, path: Path | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(frame.canonical_bytes())
