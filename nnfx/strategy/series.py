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


def pivots(
    low: np.ndarray, high: np.ndarray, left: int, right: int
) -> tuple[np.ndarray, np.ndarray]:
    """Indices of swing lows and swing highs (fractals), oldest first.

    Bar ``k`` is a swing low when its low is strictly below the ``left`` lows
    before it and the ``right`` lows after it (swing highs mirrored). A pivot
    at ``k`` is only *confirmed* at the close of bar ``k + right``: read it
    there, never earlier.
    """
    n = len(low)

    def find(x: np.ndarray, sign: float) -> np.ndarray:
        v = sign * x  # find minima of v
        ok = np.zeros(n, dtype=bool)
        if n < left + right + 1:
            return np.flatnonzero(ok)
        ok[left : n - right] = True
        for j in range(1, left + 1):
            ok[left : n - right] &= v[left : n - right] < v[left - j : n - right - j]
        for j in range(1, right + 1):
            ok[left : n - right] &= v[left : n - right] < v[left + j : n - right + j]
        return np.flatnonzero(ok)

    # Comparisons with NaN are False: a NaN bar, or one next to it, is never a pivot.
    return find(low, 1.0), find(high, -1.0)


def bollinger(x: np.ndarray, n: int, k: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger bands of ``x``: (lower, middle, upper), population deviation; NaN until ``n``."""
    s = pd.Series(x)
    mid = s.rolling(n, min_periods=n).mean()
    dev = s.rolling(n, min_periods=n).std(ddof=0)
    return (mid - k * dev).to_numpy(), mid.to_numpy(), (mid + k * dev).to_numpy()


def cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int) -> np.ndarray:
    """Commodity channel index (unbounded, zero-centred); NaN until ``n`` bars exist."""
    tp = pd.Series((high + low + close) / 3.0)
    mean = tp.rolling(n, min_periods=n).mean()
    dev = tp.rolling(n, min_periods=n).apply(lambda w: np.abs(w - w.mean()).mean(), raw=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (tp - mean) / (0.015 * dev)
    return out.replace([np.inf, -np.inf], np.nan).to_numpy()


def roc(close: np.ndarray, n: int) -> np.ndarray:
    """Rate of change in percent over ``n`` bars (unbounded, zero-centred)."""
    prev = np.r_[np.full(n, np.nan), close[:-n]]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(100.0 * (close / prev - 1.0))


def prior_extremes(x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Rolling (max, min) of the ``window`` bars *before* each bar (the bar itself excluded).

    The zones of an unbounded oscillator: causal, and a new extreme can still break them.
    """
    s = pd.Series(x).shift(1)
    mn = max(2, window // 4)
    return (
        s.rolling(window, min_periods=mn).max().to_numpy(),
        s.rolling(window, min_periods=mn).min().to_numpy(),
    )


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """Exponential moving average (span ``n``); NaN until ``n`` values exist."""
    return pd.Series(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def macd(
    close: np.ndarray, fast: int, slow: int, signal: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD (line, signal, histogram): EMA(fast) - EMA(slow), its EMA, and their difference."""
    line = ema(close, fast) - ema(close, slow)
    sig = pd.Series(line).ewm(span=signal, adjust=False, min_periods=signal).mean().to_numpy()
    return line, sig, line - sig


def dmi(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wilder's directional movement: (+DI, -DI, ADX); NaN until the smoothing has ``n`` bars."""
    prev_c = np.r_[np.nan, close[:-1]]
    tr = np.nanmax(
        np.column_stack([high - low, np.abs(high - prev_c), np.abs(low - prev_c)]), axis=1
    )
    tr[0] = np.nan
    up = np.diff(high, prepend=np.nan)
    down = -np.diff(low, prepend=np.nan)
    with np.errstate(invalid="ignore"):
        plus = np.where((up > down) & (up > 0), up, 0.0)
        minus = np.where((down > up) & (down > 0), down, 0.0)
    plus[0] = minus[0] = np.nan

    def smooth(v: np.ndarray) -> pd.Series:
        return pd.Series(v).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()

    s_tr = smooth(tr)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * smooth(plus) / s_tr
        mdi = 100.0 * smooth(minus) / s_tr
        dx = 100.0 * (pdi - mdi).abs() / (pdi + mdi)
    adx = smooth(dx.to_numpy())
    return pdi.to_numpy(), mdi.to_numpy(), adx.to_numpy()
