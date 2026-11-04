"""Session-close resampling (doc 01 §3).

This module and ``timeframes`` (which builds H1/H4/W1 views on top of it) are
the only places a bar is ever re-timed (ADR 02 §3.1).

Intraday bars (H1 or M15, labelled by close time, UTC) are assigned to the D1 session whose
close is the first configured session close at or after the bar's close. For
instruments with ``has_sessions=True`` any session falling on a Saturday or
Sunday (the Sunday partial bar) is merged into the following Monday.
Instruments with ``has_sessions=False`` close at the continuous convention
(00:00 UTC by default) with no weekend handling.
"""

from __future__ import annotations

import pandas as pd

from nnfx.config import SessionConfig
from nnfx.data.bars import AGGREGATION, BASE_TIMEFRAMES, TIMEFRAMES, BarFrame
from nnfx.instruments import InstrumentSpec

_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "mark_high": "max",
    "mark_low": "min",
    "mark_close": "last",
    "funding": "sum",
    "spliced": "max",
}
_INTRADAY = {"H1": pd.Timedelta(hours=1), "M15": pd.Timedelta(minutes=15)}


def session_close_times(close_utc: pd.DatetimeIndex, tz: str, hour: int) -> pd.DatetimeIndex:
    """For each instant, the first session close at or after it (as UTC)."""
    local = close_utc.tz_convert(tz)
    day = local.tz_localize(None).normalize()
    candidate = (day + pd.Timedelta(hours=hour)).tz_localize(
        tz, ambiguous=True, nonexistent="shift_forward"
    )
    later = local > candidate
    nxt = (day + pd.Timedelta(days=1) + pd.Timedelta(hours=hour)).tz_localize(
        tz, ambiguous=True, nonexistent="shift_forward"
    )
    out = candidate.where(~later, nxt)
    return pd.DatetimeIndex(out).tz_convert("UTC")


def trim_partial_ends(out: pd.DataFrame, base: BarFrame, bucket: pd.Timedelta) -> pd.DataFrame:
    """Drop the first and last buckets unless ``base`` covers them in full.

    ``out`` is indexed by bucket close; a bucket of length ``bucket`` is whole at
    the end when the last base bar reaches its close, and at the start when the
    first base bar opens by the bucket's open.
    """
    if len(out) and base.index[-1] < out.index[-1]:
        out = out.iloc[:-1]
    bar_len = TIMEFRAMES[base.timeframe]
    if len(out) and base.index[0] - bar_len > out.index[0] - bucket:
        out = out.iloc[1:]
    return out


def resample_to_daily(
    base: BarFrame, instrument: InstrumentSpec, session: SessionConfig
) -> BarFrame:
    if base.timeframe not in BASE_TIMEFRAMES:
        raise ValueError(f"resample_to_daily expects H1 or M15 input, got {base.timeframe}")
    if instrument.has_sessions:
        tz, hour = session.close_tz, session.close_hour
    else:
        tz, hour = session.continuous_close_tz, session.continuous_close_hour
    df = base.df
    key = session_close_times(base.index, tz, hour)
    if instrument.has_sessions:
        # Session date = local date just before the close instant.
        sess_date = (key.tz_convert(tz) - pd.Timedelta(seconds=1)).weekday
        weekend = pd.Index(sess_date).isin([5, 6])
        if weekend.any():
            # Roll weekend sessions forward to the next weekday session close.
            local = key.tz_convert(tz).tz_localize(None)
            shift_days = pd.Series(sess_date).map({5: 2, 6: 1}).fillna(0).to_numpy()
            rolled = (local + pd.to_timedelta(shift_days, unit="D")).tz_localize(
                tz, ambiguous=True, nonexistent="shift_forward"
            )
            key = pd.DatetimeIndex(rolled).tz_convert("UTC")
    agg = {c: AGGREGATION[c] for c in df.columns}
    daily = df.groupby(key).agg(agg)
    daily.index = pd.DatetimeIndex(daily.index, tz="UTC")
    # Drop partial first and last sessions.
    daily = trim_partial_ends(daily, base, pd.Timedelta(days=1))
    return BarFrame(
        daily,
        base.symbol,
        timeframe="D1",
        volume_kind=base.volume_kind,
        price_venue=base.price_venue,
        volume_venue=base.volume_venue,
    )
