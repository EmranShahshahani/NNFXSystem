"""Causal numeric building blocks. Every function: value at t uses only x[<= t]."""

from __future__ import annotations

import numpy as np
import pandas as pd

Arr = np.ndarray


def _s(x: Arr) -> pd.Series:
    return pd.Series(np.asarray(x, dtype="float64"))


def sma(x: Arr, n: int) -> Arr:
    return _s(x).rolling(n, min_periods=n).mean().to_numpy()


def ema(x: Arr, n: int) -> Arr:
    return _s(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy()


def rma(x: Arr, n: int) -> Arr:
    """Wilder smoothing."""
    return _s(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def wma(x: Arr, n: int) -> Arr:
    w = np.arange(1, n + 1, dtype="float64")
    return (
        _s(x)
        .rolling(n, min_periods=n)
        .apply(lambda v: float(np.dot(v, w) / w.sum()), raw=True)
        .to_numpy()
    )


def rolling_max(x: Arr, n: int) -> Arr:
    return _s(x).rolling(n, min_periods=n).max().to_numpy()


def rolling_min(x: Arr, n: int) -> Arr:
    return _s(x).rolling(n, min_periods=n).min().to_numpy()


def rolling_sum(x: Arr, n: int) -> Arr:
    return _s(x).rolling(n, min_periods=n).sum().to_numpy()


def shift(x: Arr, k: int = 1) -> Arr:
    return _s(x).shift(k).to_numpy()


def true_range(h: Arr, lo: Arr, c: Arr) -> Arr:
    pc = shift(c)
    tr = np.fmax(h - lo, np.fmax(np.abs(h - pc), np.abs(lo - pc)))
    tr[0] = h[0] - lo[0]
    return np.asarray(tr)


def sign_state(x: Arr) -> Arr:
    """+1/-1 by sign, 0 where undefined (warmup). Exact zero holds the prior state."""
    out = np.zeros(len(x), dtype="int8")
    prev = 0
    for i, v in enumerate(x):
        if np.isnan(v):
            prev = 0
        elif v > 0:
            prev = 1
        elif v < 0:
            prev = -1
        out[i] = prev
    return out


def state_to_signal(state: Arr) -> Arr:
    """A signal fires on the bar the state flips. Leaving warmup is not a signal."""
    st = np.asarray(state, dtype="int8")
    sig = np.zeros(len(st), dtype="int8")
    if len(st) > 1:
        flip = (st[1:] != st[:-1]) & (st[:-1] != 0) & (st[1:] != 0)
        sig[1:][flip] = st[1:][flip]
    return sig


def state_to_exit(state: Arr) -> Arr:
    """Exit contract: +1 = exit long (state flipped down), -1 = exit short (flipped up)."""
    return (-state_to_signal(state)).astype("int8")


def efficiency_ratio(c: Arr, n: int) -> Arr:
    change = np.abs(c - shift(c, n))
    vol = rolling_sum(np.abs(c - shift(c, 1)), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(vol > 0, change / vol, 0.0)
