"""The shared output of candle-style Setups (Strategy Builder tickets 14 and 18)."""

from __future__ import annotations

import numpy as np

from nnfx.strategy.blocks import SetupOutput


def candle_setup(
    long_: np.ndarray,
    short: np.ndarray,
    f_hi: np.ndarray,
    f_lo: np.ndarray,
    tag: str,
    meta: dict[str, np.ndarray] | None = None,
) -> SetupOutput:
    """Candle-style output: a long triggers above the bar's high, a short below its low.

    The invalidation and the proposed stop are the far side of the same bar.
    """
    both = long_ & short  # a bar cannot be both; it makes no candidate
    long_, short = long_ & ~both, short & ~both
    d = np.where(long_, 1, np.where(short, -1, 0)).astype("int8")
    nan = np.full(len(d), np.nan)
    trigger = np.where(d > 0, f_hi, np.where(d < 0, f_lo, nan))
    inval = np.where(d > 0, f_lo, np.where(d < 0, f_hi, nan))
    return SetupOutput(d, trigger, inval, inval.copy(), {tag: d != 0}, meta or {})
