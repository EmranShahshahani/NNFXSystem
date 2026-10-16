"""Dukascopy H1 history (doc 03 §2), 2003 to present.

Dukascopy serves one LZMA-compressed ``.bi5`` file of hourly candles per day:
``/datafeed/{SYMBOL}/{YYYY}/{MM-1:02}/{DD:02}/BID_candles_hour_1.bi5``. Each
24-byte big-endian record is ``(seconds_from_midnight:int32, open, close, low,
high: int32 in points, volume: float32)``. Fetched files are cached locally so a
re-run never re-downloads. HTTP is injected, so the feed is testable offline.
"""

from __future__ import annotations

import lzma
import struct
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame
from nnfx.data.feeds import HttpGet

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">iiiiif")
START = pd.Timestamp("2003-05-05", tz="UTC")


def default_http_get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as resp:
        data: bytes = resp.read()
        return data


def point_size(symbol: str) -> float:
    return 1e-3 if symbol.endswith("JPY") else 1e-5


def day_url(symbol: str, day: pd.Timestamp, side: str = "BID") -> str:
    return f"{BASE_URL}/{symbol}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_hour_1.bi5"


def decode_bi5(raw: bytes, day: pd.Timestamp, point: float) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    data = lzma.decompress(raw)
    rows = [
        RECORD.unpack_from(data, off)
        for off in range(0, len(data) - len(data) % RECORD.size, RECORD.size)
    ]
    arr = np.array(rows, dtype="float64")
    opens_at = day.normalize() + pd.to_timedelta(arr[:, 0], unit="s")
    df = pd.DataFrame(
        {
            "open": arr[:, 1] * point,
            "high": arr[:, 4] * point,
            "low": arr[:, 3] * point,
            "close": arr[:, 2] * point,
            "volume": arr[:, 5],
        },
        index=pd.DatetimeIndex(opens_at + pd.Timedelta(hours=1), tz="UTC"),
    )
    # Dukascopy pads non-trading hours with flat zero-volume candles; drop them.
    return df[df["volume"] > 0]


def encode_bi5(df_open_indexed: pd.DataFrame, point: float) -> bytes:
    """Inverse of ``decode_bi5`` for one day; used to build offline fixtures."""
    out = bytearray()
    for ts, r in df_open_indexed.iterrows():
        t = pd.Timestamp(ts)  # type: ignore[arg-type]
        secs = int((t - t.normalize()).total_seconds())
        out += RECORD.pack(
            secs,
            round(r["open"] / point),
            round(r["close"] / point),
            round(r["low"] / point),
            round(r["high"] / point),
            float(r["volume"]),
        )
    return lzma.compress(bytes(out), format=lzma.FORMAT_ALONE)


class DukascopyFeed:
    name = "dukascopy"

    def __init__(
        self, cache_dir: Path | str = "data/cache/dukascopy", http_get: HttpGet | None = None
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.http_get = http_get or default_http_get
        self.downloads = 0

    def _day(self, symbol: str, day: pd.Timestamp) -> bytes:
        path = self.cache_dir / symbol / f"{day:%Y-%m-%d}.bi5"
        if path.exists():
            return path.read_bytes()
        raw = self.http_get(day_url(symbol, day))
        self.downloads += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return raw

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame:
        start = max(pd.Timestamp(start), START)
        point = point_size(symbol)
        parts = []
        for day in pd.date_range(start.normalize(), pd.Timestamp(end).normalize(), freq="D"):
            if day.weekday() == 5:  # Saturday: market closed
                continue
            df = decode_bi5(self._day(symbol, day), day, point)
            if len(df):
                parts.append(df)
        df = (
            pd.concat(parts)
            if parts
            else pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        )
        if len(df):
            df = df[(df.index > start) & (df.index <= pd.Timestamp(end))]
        else:
            df.index = pd.DatetimeIndex([], tz="UTC")
        return BarFrame(df, symbol, timeframe="H1", volume_kind="tick", price_venue=self.name)


class StooqFeed:
    """Second free source for the FX cross-check: Stooq daily CSV.

    Stooq's daily close is not cut at our session close, so the cross-check
    compares on tolerance and reports divergences rather than demanding equality.
    """

    name = "stooq"

    def __init__(self, http_get: HttpGet | None = None) -> None:
        self.http_get = http_get or default_http_get

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame:
        import io

        raw = self.http_get(f"https://stooq.com/q/d/l/?s={symbol.lower()}&i=d")
        df = pd.read_csv(io.BytesIO(raw))
        df.columns = [c.lower() for c in df.columns]
        idx = pd.to_datetime(df.pop("date")).dt.tz_localize("UTC") + pd.Timedelta(hours=22)
        df.index = pd.DatetimeIndex(idx)
        if "volume" not in df.columns:
            df["volume"] = 0.0
        frame = BarFrame(
            df[["open", "high", "low", "close", "volume"]],
            symbol,
            volume_kind="none",
            price_venue=self.name,
        )
        return frame.between(pd.Timestamp(start), pd.Timestamp(end))
