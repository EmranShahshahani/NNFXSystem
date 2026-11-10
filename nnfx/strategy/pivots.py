"""Floor-trader pivots on 4H and weekly periods (Strategy Builder ticket 18, ADR 10 §22).

Video 57. Pivots come from the *previous closed* 4H bar or week only (lower-timeframe
pivots are noise and are not offered). With H, L, C of that period::

    P  = (H + L + C) / 3          range = H - L
    R1 = 2P - L    S1 = 2P - H
    R2 = P + range S2 = P - range
    R3 = P + 2 range  S3 = P - 2 range
    R4 = P + 3 range  S4 = P - 3 range

(the "traditional" tier set; the blueprint names R1-R4 and S1-S4 without formulas).

``pivot_levels`` puts them on the LWC bars: at an LWC bar, the levels of the latest period
that had closed by then, so a period still in progress never leaks into its own pivots.

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``pivot_breach``      Confirmation. The close is beyond R1 (longs) or S1 (shorts):
                      directional displacement away from the baseline range. The
                      central P is never an entry signal on its own
====================  ==========================================================

``ProfitChain.pivot_exit`` uses R3/S3 and R4/S4 as targets (see ``library``).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import Field

from nnfx.data.bars import BarFrame, ns
from nnfx.data.timeframes import resample
from nnfx.strategy.blocks import (
    BlockKind,
    CheckResult,
    ConfirmationBlock,
    ConfirmationParams,
    SetupCandidate,
    StrategyData,
    register,
)

Period = Literal["H4", "W1"]
LEVELS = ("p", "r1", "r2", "r3", "r4", "s1", "s2", "s3", "s4")


def floor_pivots(frame: BarFrame) -> dict[str, np.ndarray]:
    """Every pivot level of each bar of ``frame``, meant for the bar *after* it."""
    h, lo, c = frame.high, frame.low, frame.close
    p = (h + lo + c) / 3.0
    rng = h - lo
    return {
        "p": p,
        "r1": 2 * p - lo,
        "r2": p + rng,
        "r3": p + 2 * rng,
        "r4": p + 3 * rng,
        "s1": 2 * p - h,
        "s2": p - rng,
        "s3": p - 2 * rng,
        "s4": p - 3 * rng,
    }


def period_frame(data: StrategyData, period: Period) -> BarFrame:
    """``period`` bars of this data (a role's own frame when one has that timeframe)."""

    def make() -> BarFrame:
        for role, tf in data.roles.items():
            if tf == period:
                return data.frames[role]
        return resample(data.base, period, instrument=data.instrument, session=data.session)

    return data.memo(("period_frame", period), make)


def pivot_levels(data: StrategyData, period: Period) -> dict[str, np.ndarray]:
    """Each level on the LWC bars: the levels of the latest ``period`` bar closed by then.

    NaN before the first period closes. Every period in the frame is closed (partial ends
    are dropped when the frame is built), so no unfinished period contributes.
    """

    def make() -> dict[str, np.ndarray]:
        f = period_frame(data, period)
        pos = np.searchsorted(ns(f.index), ns(data.base.index), side="right") - 1
        ok = pos >= 0
        out: dict[str, np.ndarray] = {}
        for name, values in floor_pivots(f).items():
            x = np.full(len(pos), np.nan)
            x[ok] = values[pos[ok]]
            out[name] = x
        return out

    return data.memo(("pivot_levels", period), make)


class PivotBreachParams(ConfirmationParams):
    period: Period = Field("W1", description="دورهٔ پیوت: H4 (چهارساعته) یا W1 (هفتگی)")


@register
class PivotBreach(ConfirmationBlock[PivotBreachParams]):
    """Beyond R1 for longs, beyond S1 for shorts (video 57).

    The candidate bar's close must lie past the first resistance (support) of the last
    closed ``period``: price has left the baseline range in the trade's direction. The
    central pivot alone is never a signal. ``na`` until a period has closed.
    """

    kind = BlockKind.CONFIRMATION
    type = "pivot_breach"
    title_fa = "عبور از پیوت R1/S1"
    sources = ("tcp-blueprint 06: video 57 (directional asymmetry of floor pivots)",)
    Params = PivotBreachParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        levels = pivot_levels(data, self.p.period)
        name = "r1" if candidate.direction > 0 else "s1"
        level = levels[name][candidate.bar]
        if not np.isfinite(level):
            return CheckResult("na", f"no closed {self.p.period} period yet")
        close = float(data.base.close[candidate.bar])
        if (close - level) * candidate.direction > 0:
            return CheckResult("pass", f"close beyond {name.upper()}")
        return CheckResult("fail", f"close has not passed {name.upper()}")
