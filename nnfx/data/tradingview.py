"""Import TradingView "Export chart data" CSVs.

TradingView has no public market-data API; the supported way out is the chart
menu's *Export chart data...*, which writes ``time,open,high,low,close[,Volume]``
plus one column per indicator plot on the chart. ``time`` is the bar *open*,
either unix seconds or ISO-8601 with an offset, depending on the export option.

Export hourly bars (``1h``) and let ``resample_to_daily`` cut them at our
session close: TradingView's own daily bar is cut wherever the data vendor
cuts it, which is exactly the convention mismatch doc 03 §2 warns about.
Indicator plot columns are dropped; every indicator is recomputed here.
Volume on an FX chart is the vendor's tick volume, so ``volume_kind`` follows
the instrument, never the file.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from nnfx.data.bars import BarFrame, VolumeKind

_TIMEFRAMES = {"H1": pd.Timedelta(hours=1)}


def read_tradingview_csv(
    path: Path | str,
    symbol: str,
    *,
    timeframe: str = "H1",
    volume_kind: VolumeKind = "traded",
    venue: str | None = None,
) -> BarFrame:
    if timeframe not in _TIMEFRAMES:
        raise ValueError(
            "export 1h bars; a TradingView daily bar is cut at the vendor's close, not ours"
        )
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["time", "open", "high", "low", "close"]
    missing = [c for c in need if c not in cols]
    if missing:
        raise ValueError(f"{path}: not a TradingView export, missing columns {missing}")
    t = df[cols["time"]]
    opens = (
        pd.to_datetime(t.astype("int64"), unit="s", utc=True)
        if pd.api.types.is_numeric_dtype(t)
        else pd.to_datetime(t, utc=True)
    )
    out = pd.DataFrame({c: df[cols[c]].astype("float64").to_numpy() for c in need[1:]})
    if "volume" in cols:
        out["volume"] = df[cols["volume"]].fillna(0.0).astype("float64").to_numpy()
    else:
        out["volume"] = 0.0
        volume_kind = "none"
    out.index = pd.DatetimeIndex(opens + _TIMEFRAMES[timeframe])
    return BarFrame(out, symbol, timeframe=timeframe, volume_kind=volume_kind, price_venue=venue)
