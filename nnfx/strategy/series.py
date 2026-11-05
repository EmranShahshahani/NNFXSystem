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
