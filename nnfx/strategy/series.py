"""Causal series helpers shared by Blocks and the engine."""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: np.ndarray, n: int) -> np.ndarray:
    """Simple moving average; NaN until ``n`` bars exist."""
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """Wilder's average true range; NaN until ``n`` bars exist."""
    prev = np.r_[np.nan, close[:-1]]
    tr = np.nanmax(np.column_stack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=1)
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def rising(x: np.ndarray, bars: int) -> np.ndarray:
    """``x`` higher than ``bars`` bars ago (False where either is NaN)."""
    prev = np.r_[np.full(bars, np.nan), x[:-bars]] if bars else x
    with np.errstate(invalid="ignore"):
        return np.asarray(x > prev)


def falling(x: np.ndarray, bars: int) -> np.ndarray:
    prev = np.r_[np.full(bars, np.nan), x[:-bars]] if bars else x
    with np.errstate(invalid="ignore"):
        return np.asarray(x < prev)


def rsi(close: np.ndarray, n: int) -> np.ndarray:
    """Wilder's RSI; NaN until ``n + 1`` closes exist."""
    d = np.diff(close, prepend=np.nan)
    up = pd.Series(np.where(d > 0, d, 0.0))
    down = pd.Series(np.where(d < 0, -d, 0.0))
    up[0] = down[0] = np.nan
    au = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    ad = down.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + au / ad)
    out[(ad == 0) & (au > 0)] = 100.0
    out[(ad == 0) & (au == 0)] = 50.0
    return out.to_numpy()
