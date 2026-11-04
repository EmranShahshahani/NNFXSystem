"""Higher-timeframe views built from one intraday base (Strategy Builder ticket 01).

Every view is resampled from a single base frame (15-minute or hourly bars), so
all timeframes agree on prices and on what was known when. Bars keep the close
time labelling contract of ``bars.py``: a bar is labelled by the instant it is
complete. Under that contract "the latest higher-timeframe bar visible from a
lower-timeframe bar" is simply the last higher bar whose close is at or before
the lower bar's close, so an unfinished 4H bar can never leak into a 15m
decision.

- H1 and H4 buckets sit on a fixed UTC grid (4H bars close at 00, 04, ... UTC).
- D1 uses the session-close convention of ``session.resample_to_daily``.
- W1 groups D1 sessions by ISO week (Monday to Sunday session dates), so a
  continuous market's week closes at Monday 00:00 UTC and an FX week at its
  Friday session close.

Buckets that the base does not cover in full at either end are dropped; gaps
inside a bucket (an exchange outage) are aggregated over what is there and are
reported by the intraday gap gate instead.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame, ns
from nnfx.data.session import _AGG, resample_to_daily
from nnfx.instruments import InstrumentSpec

DURATIONS: dict[str, pd.Timedelta] = {
    "M15": pd.Timedelta(minutes=15),
    "H1": pd.Timedelta(hours=1),
    "H4": pd.Timedelta(hours=4),
    "D1": pd.Timedelta(days=1),
    "W1": pd.Timedelta(days=7),
}
BASE_TIMEFRAMES = ("M15", "H1")
ORDER = tuple(DURATIONS)


def duration(timeframe: str) -> pd.Timedelta:
    try:
        return DURATIONS[timeframe]
    except KeyError:
        raise ValueError(f"unknown timeframe {timeframe!r}; expected one of {ORDER}") from None


def _like(base: BarFrame, df: pd.DataFrame, timeframe: str) -> BarFrame:
    return BarFrame(
        df,
        base.symbol,
        timeframe=timeframe,
        volume_kind=base.volume_kind,
        price_venue=base.price_venue,
        volume_venue=base.volume_venue,
    )


def _grid(base: BarFrame, timeframe: str) -> BarFrame:
    step = duration(timeframe)
    df = base.df
    key = base.index.ceil(step)
    out = df.groupby(key).agg({c: _AGG[c] for c in df.columns})
    out.index = pd.DatetimeIndex(out.index, tz="UTC")
    if len(out):
        bar = duration(base.timeframe)
        if base.index[-1] < out.index[-1]:
            out = out.iloc[:-1]
        if len(out) and base.index[0] - bar > out.index[0] - step:
            out = out.iloc[1:]
    return _like(base, out, timeframe)


def _weekly(d1: BarFrame, instrument: InstrumentSpec, session: SessionConfig) -> BarFrame:
    tz = session.close_tz if instrument.has_sessions else session.continuous_close_tz
    sess = (d1.index.tz_convert(tz) - pd.Timedelta(seconds=1)).tz_localize(None).normalize()
    week = sess - pd.to_timedelta(sess.weekday, unit="D")
    df = d1.df
    out = df.groupby(week).agg({c: _AGG[c] for c in df.columns})
    label = pd.Series(d1.index, index=week).groupby(level=0).max()
    out.index = pd.DatetimeIndex(label.loc[out.index].to_numpy(), tz="UTC")
    last_day = 4 if instrument.has_sessions else 6
    wd = pd.Series(sess.weekday, index=week)
    if len(out):
        if wd.groupby(level=0).max().iloc[-1] < last_day:
            out = out.iloc[:-1]
        if len(out) and wd.groupby(level=0).min().iloc[0] > 0:
            out = out.iloc[1:]
    return _like(d1, out, "W1")


def resample(
    base: BarFrame, timeframe: str, *, instrument: InstrumentSpec, session: SessionConfig
) -> BarFrame:
    """``base`` (M15 or H1) resampled to ``timeframe`` under the close-time contract."""
    if base.timeframe not in BASE_TIMEFRAMES:
        raise ValueError(f"base bars must be one of {BASE_TIMEFRAMES}, got {base.timeframe}")
    if duration(timeframe) < duration(base.timeframe):
        raise ValueError(f"cannot build {timeframe} from coarser {base.timeframe} bars")
    if timeframe == base.timeframe:
        return base
    if timeframe in ("H1", "H4"):
        return _grid(base, timeframe)
    d1 = resample_to_daily(base, instrument, session)
    return d1 if timeframe == "D1" else _weekly(d1, instrument, session)


class TimeframeViews:
    """One base frame and the higher-timeframe views resampled from it.

    ``as_of(tf, t)`` is the only way a consumer should read a higher timeframe
    from a lower-timeframe bar closing at ``t``: it holds the ``tf`` bars that
    had closed by ``t`` and nothing later.
    """

    def __init__(
        self,
        base: BarFrame,
        *,
        instrument: InstrumentSpec,
        session: SessionConfig,
        timeframes: Iterable[str] = ("H1", "H4", "D1", "W1"),
    ) -> None:
        self.base = base
        self.frames: dict[str, BarFrame] = {base.timeframe: base}
        for tf in timeframes:
            self.frames[tf] = resample(base, tf, instrument=instrument, session=session)
        self._close_ns = {tf: ns(f.index) for tf, f in self.frames.items()}

    @property
    def timeframes(self) -> tuple[str, ...]:
        return tuple(sorted(self.frames, key=ORDER.index))

    def frame(self, timeframe: str) -> BarFrame:
        try:
            return self.frames[timeframe]
        except KeyError:
            raise ValueError(f"no {timeframe} view; built: {self.timeframes}") from None

    def latest_closed(self, timeframe: str, at: pd.Timestamp) -> int:
        """Position of the last ``timeframe`` bar closed by ``at``; -1 if none yet."""
        self.frame(timeframe)
        t = np.int64(ns(pd.DatetimeIndex([pd.Timestamp(at)]))[0])
        return int(np.searchsorted(self._close_ns[timeframe], t, side="right")) - 1

    def as_of(self, timeframe: str, at: pd.Timestamp) -> BarFrame:
        """The ``timeframe`` bars that had closed by ``at``."""
        return self.frame(timeframe).head(self.latest_closed(timeframe, at) + 1)
