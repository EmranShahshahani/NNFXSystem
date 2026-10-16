"""The strict bar contract.

A ``BarFrame`` is validated at construction and immutable afterwards, so every
downstream module may assume its input is clean instead of re-checking it.

Index convention: each bar is labelled by its **close time** in UTC - the
instant the bar is complete and a decision on it may be taken. This makes the
"no partial final bar" rule a simple comparison against ``as_of``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

VolumeKind = Literal["traded", "tick", "none"]
OHLCV = ("open", "high", "low", "close", "volume")
# Optional columns that travel with the bars when a feed supplies them.
OPTIONAL = ("mark_high", "mark_low", "mark_close", "funding", "spliced")


def ns(index: pd.Index) -> np.ndarray:
    """UTC nanoseconds since the epoch for a tz-aware DatetimeIndex."""
    di = pd.DatetimeIndex(index).tz_convert("UTC").tz_localize(None).as_unit("ns")
    return np.asarray(di.to_numpy(dtype="datetime64[ns]")).view("int64")


class BarFrameError(ValueError):
    """Raised when a frame violates the bar contract at construction."""

    def __init__(self, check: str, symbol: str, timestamps: Sequence[pd.Timestamp], detail: str):
        self.check = check
        self.symbol = symbol
        self.timestamps = list(timestamps)
        shown = ", ".join(str(t) for t in self.timestamps[:10])
        more = f" (+{len(self.timestamps) - 10} more)" if len(self.timestamps) > 10 else ""
        super().__init__(f"[{check}] {symbol}: {detail} at {shown}{more}")


class BarFrame:
    """UTC-indexed OHLCV bars for one symbol, validated at construction."""

    __slots__ = (
        "_df",
        "price_venue",
        "symbol",
        "timeframe",
        "volume_kind",
        "volume_venue",
    )

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        *,
        timeframe: str = "D1",
        volume_kind: VolumeKind = "traded",
        price_venue: str | None = None,
        volume_venue: str | None = None,
        as_of: pd.Timestamp | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.volume_kind: VolumeKind = volume_kind
        self.price_venue = price_venue
        self.volume_venue = volume_venue if volume_venue is not None else price_venue
        self._df = self._validate(df, as_of)

    # ------------------------------------------------------------------ checks
    def _validate(self, df: pd.DataFrame, as_of: pd.Timestamp | None) -> pd.DataFrame:
        sym = self.symbol
        missing = [c for c in OHLCV if c not in df.columns]
        if missing:
            raise BarFrameError("schema", sym, [], f"missing columns {missing}")
        unknown = [c for c in df.columns if c not in OHLCV and c not in OPTIONAL]
        if unknown:
            raise BarFrameError("schema", sym, [], f"unknown columns {unknown}")
        if not isinstance(df.index, pd.DatetimeIndex):
            raise BarFrameError("index", sym, [], "index must be a DatetimeIndex")
        idx = df.index
        if idx.tz is None or str(idx.tz) != "UTC":
            raise BarFrameError("index", sym, [], f"index must be UTC, got tz={idx.tz}")
        dup = idx[idx.duplicated(keep="first")]
        if len(dup):
            raise BarFrameError("duplicate_timestamps", sym, list(dup), "duplicate timestamps")
        if len(idx) > 1:
            diffs = np.diff(ns(idx))
            bad = np.nonzero(diffs <= 0)[0]
            if len(bad):
                raise BarFrameError(
                    "out_of_order", sym, [idx[int(i) + 1] for i in bad], "out-of-order timestamps"
                )
        if as_of is not None and len(idx) and idx[-1] > as_of:
            raise BarFrameError(
                "partial_final_bar",
                sym,
                [idx[-1]],
                f"final bar closes after as_of={as_of}; it is not complete",
            )
        if self.volume_kind == "traded" and self.price_venue != self.volume_venue:
            raise BarFrameError(
                "venue_mismatch",
                sym,
                [],
                f"price from {self.price_venue!r} but volume from {self.volume_venue!r}",
            )
        out = df.loc[:, [c for c in (*OHLCV, *OPTIONAL) if c in df.columns]].copy()
        for c in out.columns:
            out[c] = out[c].astype(bool) if c == "spliced" else out[c].astype("float64")
        nans = out[list(OHLCV)].isna().any(axis=1)
        if nans.any():
            raise BarFrameError("nan_values", sym, list(out.index[nans]), "NaN in OHLCV")
        out.index.name = "close_time"
        return out

    # --------------------------------------------------------------- accessors
    @property
    def df(self) -> pd.DataFrame:
        """A copy; the frame itself is immutable."""
        return self._df.copy()

    @property
    def index(self) -> pd.DatetimeIndex:
        idx = self._df.index
        assert isinstance(idx, pd.DatetimeIndex)
        return idx

    def column(self, name: str) -> np.ndarray:
        arr = self._df[name].to_numpy(copy=True)
        arr.setflags(write=False)
        return arr

    @property
    def open(self) -> np.ndarray:
        return self.column("open")

    @property
    def high(self) -> np.ndarray:
        return self.column("high")

    @property
    def low(self) -> np.ndarray:
        return self.column("low")

    @property
    def close(self) -> np.ndarray:
        return self.column("close")

    @property
    def volume(self) -> np.ndarray:
        return self.column("volume")

    def has(self, name: str) -> bool:
        return name in self._df.columns

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        span = f"{self.index[0]}..{self.index[-1]}" if len(self) else "empty"
        return f"BarFrame({self.symbol}, {self.timeframe}, {len(self)} bars, {span})"

    # ---------------------------------------------------------------- slicing
    def _like(self, df: pd.DataFrame) -> BarFrame:
        return BarFrame(
            df,
            self.symbol,
            timeframe=self.timeframe,
            volume_kind=self.volume_kind,
            price_venue=self.price_venue,
            volume_venue=self.volume_venue,
        )

    def head(self, n: int) -> BarFrame:
        """The first ``n`` bars - i.e. history truncated at bar ``n - 1``."""
        return self._like(self._df.iloc[:n])

    def between(self, start: pd.Timestamp | None, end: pd.Timestamp | None) -> BarFrame:
        df = self._df
        if start is not None:
            df = df[df.index >= start]
        if end is not None:
            df = df[df.index <= end]
        return self._like(df)

    def scaled(self, factor: float) -> BarFrame:
        """Prices multiplied by ``factor`` - used by the parameterisation gate."""
        df = self._df.copy()
        for c in ("open", "high", "low", "close", "mark_high", "mark_low", "mark_close"):
            if c in df.columns:
                df[c] = df[c] * factor
        return self._like(df)

    # ------------------------------------------------------------- integrity
    def canonical_bytes(self) -> bytes:
        """Stable CSV bytes for checksumming (manifests) and golden files."""
        return self._df.to_csv(lineterminator="\n", float_format="%.10g").encode()

    def checksum(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def splice_points(self) -> list[pd.Timestamp]:
        """Bars where the source switches between spliced (spot) and native history."""
        if "spliced" not in self._df.columns or len(self) < 2:
            return []
        s = self._df["spliced"].to_numpy()
        return [self.index[i] for i in range(1, len(s)) if s[i] != s[i - 1]]
