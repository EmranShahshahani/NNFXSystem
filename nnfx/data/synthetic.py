"""Deterministic synthetic bars for tests, fixtures and demos. Never research data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame, VolumeKind


def regime_walk(
    n: int,
    *,
    seed: int = 0,
    start_price: float = 1.2,
    vol: float = 0.007,
    regime_len: int = 60,
    drift: float = 0.0025,
    start: str = "2010-01-04",
    freq: str = "B",
    hour: int = 22,
    symbol: str = "SYN",
    volume_kind: VolumeKind = "traded",
    venue: str | None = None,
    mark: bool = False,
) -> BarFrame:
    """A random walk with alternating trending regimes, so NNFX rules actually fire."""
    rng = np.random.default_rng(seed)
    regimes = np.repeat(rng.choice([-1.0, 0.0, 1.0], size=n // regime_len + 1), regime_len)[:n]
    rets = rng.normal(0, vol, n) + regimes * drift
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.r_[start_price, close[:-1]] * np.exp(rng.normal(0, vol * 0.1, n))
    wick = np.abs(rng.normal(0, vol * 0.6, (2, n)))
    high = np.maximum(open_, close) * np.exp(wick[0])
    low = np.minimum(open_, close) * np.exp(-wick[1])
    days = pd.date_range(start, periods=n, freq=freq)
    idx = pd.DatetimeIndex([d.replace(hour=hour) for d in days]).tz_localize("UTC")
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(500, 1500, n).round(),
        },
        index=idx,
    )
    if mark:
        # Mark price wicks less than last price.
        df["mark_high"] = np.maximum(open_, close) * np.exp(wick[0] * 0.5)
        df["mark_low"] = np.minimum(open_, close) * np.exp(-wick[1] * 0.5)
        df["mark_close"] = close
    return BarFrame(df, symbol, volume_kind=volume_kind, price_venue=venue)


def hourly_walk(
    n_hours: int,
    *,
    seed: int = 0,
    start: str = "2024-01-01",
    symbol: str = "SYN",
    start_price: float = 1.1,
) -> BarFrame:
    rng = np.random.default_rng(seed)
    close = start_price * np.exp(np.cumsum(rng.normal(0, 0.0015, n_hours)))
    open_ = np.r_[start_price, close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.0008, n_hours))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.0008, n_hours))
    idx = pd.date_range(
        pd.Timestamp(start) + pd.Timedelta(hours=1), periods=n_hours, freq="h", tz="UTC"
    )
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(10, 100, n_hours).round(),
        },
        index=idx,
    )
    return BarFrame(df, symbol, timeframe="H1", volume_kind="tick")
