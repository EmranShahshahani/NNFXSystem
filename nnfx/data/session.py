"""Session-close resampling: the one place a bar is ever re-timed (doc 01 §3).

H1 bars (labelled by close time, UTC) are assigned to the D1 session whose
close is the first configured session close at or after the H1 close. For
instruments with ``has_sessions=True`` any session falling on a Saturday or
Sunday (the Sunday partial bar) is merged into the following Monday.
Instruments with ``has_sessions=False`` close at the continuous convention
(00:00 UTC by default) with no weekend handling.
"""

from __future__ import annotations

import pandas as pd

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
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


def resample_to_daily(h1: BarFrame, instrument: InstrumentSpec, session: SessionConfig) -> BarFrame:
    if h1.timeframe != "H1":
        raise ValueError(f"resample_to_daily expects H1 input, got {h1.timeframe}")
    if instrument.has_sessions:
        tz, hour = session.close_tz, session.close_hour
    else:
        tz, hour = session.continuous_close_tz, session.continuous_close_hour
    df = h1.df
    key = session_close_times(h1.index, tz, hour)
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
    agg = {c: _AGG[c] for c in df.columns}
    daily = df.groupby(key).agg(agg)
    daily.index = pd.DatetimeIndex(daily.index, tz="UTC")
    # Drop a partial final session: the last H1 bar must reach the session close.
    if len(daily) and h1.index[-1] < daily.index[-1]:
        daily = daily.iloc[:-1]
    # ...and a partial first session: data must start by the previous close.
    if len(daily) and h1.index[0] - pd.Timedelta(hours=1) > daily.index[0] - pd.Timedelta(days=1):
        daily = daily.iloc[1:]
    return BarFrame(
        daily,
        h1.symbol,
        timeframe="D1",
        volume_kind=h1.volume_kind,
        price_venue=h1.price_venue,
        volume_venue=h1.volume_venue,
    )
