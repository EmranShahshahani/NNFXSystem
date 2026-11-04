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
- W1 groups D1 sessions by ISO week (Monday to Sunday session dates) and is
  labelled at the week's scheduled close: Monday 00:00 UTC for a continuous
  market, the Friday session close for an FX week.

Buckets that the base does not cover in full at either end are dropped; gaps
inside a bucket (an exchange outage) are aggregated over what is there and are
reported by the intraday gap gate instead (ADR 02 §3.1 amendment).

Intraday views are built for continuous (crypto) instruments, the Strategy
Builder's market. For session instruments the H1/H4 grid is plain UTC, so the
Friday-close and Sunday-open buckets are short, and the gap gate does not run.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from nnfx.config import SessionConfig
from nnfx.data.bars import AGGREGATION, BASE_TIMEFRAMES, TIMEFRAMES, BarFrame, ns
from nnfx.data.session import resample_to_daily, trim_partial_ends
from nnfx.instruments import InstrumentSpec

ORDER = tuple(TIMEFRAMES)


def duration(timeframe: str) -> pd.Timedelta:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise ValueError(f"unknown timeframe {timeframe!r}; expected one of {ORDER}") from None


def _with_bars(base: BarFrame, df: pd.DataFrame, timeframe: str) -> BarFrame:
    """A frame of ``df`` bars carrying ``base``'s symbol, volume kind and venues."""
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
    out = df.groupby(base.index.ceil(step)).agg({c: AGGREGATION[c] for c in df.columns})
    out.index = pd.DatetimeIndex(out.index, tz="UTC")
    return _with_bars(base, trim_partial_ends(out, base, step), timeframe)


def _weekly(
    base: BarFrame, d1: BarFrame, instrument: InstrumentSpec, session: SessionConfig
) -> BarFrame:
    """Group D1 sessions by ISO week; label each week by its scheduled close.

    The label is the close of the week's last session (Sunday for continuous
    markets, Friday for session markets), whether or not every session in the
    week has data, so a hole never moves a week's close earlier.
    """
    if instrument.has_sessions:
        tz, hour, last_day = session.close_tz, session.close_hour, 4
    else:
        tz, hour, last_day = session.continuous_close_tz, session.continuous_close_hour, 6
    sess = (d1.index.tz_convert(tz) - pd.Timedelta(seconds=1)).tz_localize(None).normalize()
    monday = sess - pd.to_timedelta(sess.weekday, unit="D")
    # A session dated d closes at d + hour (or at the next midnight when hour is 0).
    close_local = monday + pd.Timedelta(days=last_day) + pd.Timedelta(hours=hour or 24)
    label = (
        pd.DatetimeIndex(close_local)
        .tz_localize(tz, ambiguous=True, nonexistent="shift_forward")
        .tz_convert("UTC")
    )
    df = d1.df
    out = df.groupby(label).agg({c: AGGREGATION[c] for c in df.columns})
    out.index = pd.DatetimeIndex(out.index, tz="UTC")
    # A week still in progress is not a bar...
    if len(out) and base.index[-1] < out.index[-1]:
        out = out.iloc[:-1]
    # ...nor is a first week that starts after its Monday session.
    if len(out) and sess[0].weekday() > 0:
        out = out.iloc[1:]
    return _with_bars(d1, out, "W1")


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
    return d1 if timeframe == "D1" else _weekly(base, d1, instrument, session)


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
