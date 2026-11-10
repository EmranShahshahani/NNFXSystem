"""MACD, ROC and ADX/DMI rules (Strategy Builder ticket 16, ADR 10 §20).

Videos 54-56. Series helpers shared by the Blocks here, by the ADX order-type switch
(``adx_order_type``, in ``library``) and by the Profit Chain's exhaustion exits.

====================  ===========  ======================================================
Block                 Kind         What it does
====================  ===========  ======================================================
``macd_cross``        Confirmation signal-line cross in the trade's favour, ignoring crosses
                                   hugging the zero line (chop, video 54)
``roc_ceiling``       Context      no longs while the ROC of a higher timeframe sits at its
                                   rolling 200-bar ceiling (shorts: floor) (video 55)
``roc_box_breakout``  Confirmation ROC broke out of its own recent range in the trade's
                                   direction (video 55)
``adx_order_type``    Execution    stop-market order when DI are separated and ADX rises,
                                   a market entry on a confirmed candle close when they
                                   are tangled (video 56)
====================  ===========  ======================================================

and the Profit Chain options ``macd_decel_exit``, ``roc_ceiling_exit`` and
``adx_exhaustion`` (see ``library.ProfitChain``). MACD and ROC are unbounded: their
zero band and ceiling come from the rolling extremes of the bars *before* the one
tested (``series.prior_extremes``), so a new extreme can still break them.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    CheckResult,
    ConfirmationBlock,
    ConfirmationParams,
    ContextBlock,
    ContextOutput,
    Role,
    SetupCandidate,
    StrategyData,
    register,
)
from nnfx.strategy.series import dmi, macd, prior_extremes, roc


# ----------------------------------------------------------------- series
def macd_of(
    data: StrategyData, role: str, fast: int, slow: int, signal: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(line, signal, histogram) of ``role``'s closes, cached."""
    return data.memo(
        ("macd", role, fast, slow, signal),
        lambda: macd(data.frames[role].close, fast, slow, signal),
    )


def roc_of(data: StrategyData, role: str, period: int) -> np.ndarray:
    """Rate of change (percent) of ``role``'s closes, cached."""
    return data.memo(("roc", role, period), lambda: roc(data.frames[role].close, period))


def dmi_of(data: StrategyData, role: str, period: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(+DI, -DI, ADX) of ``role``'s bars, cached."""

    def make() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        f = data.frames[role]
        return dmi(f.high, f.low, f.close, period)

    return data.memo(("dmi", role, period), make)


def roc_band(
    data: StrategyData, role: str, period: int, window: int, fraction: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(ROC, ceiling, floor) per ``role`` bar: ``fraction`` of the rolling extremes of the
    ``window`` bars before it. NaN where that side has no extreme yet (no positive ceiling)."""

    def make() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        v = roc_of(data, role, period)
        top, bottom = prior_extremes(v, window)
        with np.errstate(invalid="ignore"):
            return (
                v,
                np.where(top > 0, fraction * top, np.nan),
                np.where(bottom < 0, fraction * bottom, np.nan),
            )

    return data.memo(("roc_band", role, period, window, fraction), make)


# ------------------------------------------------------ exit-side signals
def roc_at_extreme(
    data: StrategyData, role: str, period: int, window: int, fraction: float, m: int, d: int
) -> bool:
    """ROC at ``role`` bar ``m`` is at its ceiling (shorts: floor) in the trade's direction."""
    v, ceiling, floor = roc_band(data, role, period, window, fraction)
    if m < 0:
        return False
    edge = ceiling[m] if d > 0 else floor[m]
    return bool(np.isfinite(v[m]) and np.isfinite(edge) and (v[m] - edge) * d >= 0)


def macd_decelerating(
    data: StrategyData,
    role: str,
    fast: int,
    slow: int,
    signal: int,
    m: int,
    d: int,
    *,
    bars: int,
    extreme_bars: int,
) -> bool:
    """The histogram has shrunk (in the trade's direction) for ``bars`` bars in a row while
    price is at a new extreme: moving-average separation is decelerating (video 54).

    The histogram must still be on the trade's side (a contraction, not a reversal), and the
    close within the last ``bars`` + 1 bars must have set the highest (shorts: lowest) close of
    the ``extreme_bars`` before it.
    """
    h = macd_of(data, role, fast, slow, signal)[2] * d
    if m < bars:
        return False
    run = h[m - bars : m + 1]
    if not (np.all(np.isfinite(run)) and run[-1] > 0 and np.all(np.diff(run) < 0)):
        return False
    c = data.frames[role].close * d
    for j in range(m - bars, m + 1):
        lo = max(0, j - extreme_bars)
        prior = c[lo:j]
        if np.isfinite(prior).any() and c[j] > np.nanmax(prior):
            return True
    return False


def adx_exhausted(
    data: StrategyData, role: str, period: int, level: float, peak_bars: int, m: int
) -> bool:
    """ADX reached ``level`` within the last ``peak_bars`` bars and has curled down (video 56)."""
    adx = dmi_of(data, role, period)[2]
    if m < 1 or not (np.isfinite(adx[m]) and np.isfinite(adx[m - 1])):
        return False
    recent = adx[max(0, m - peak_bars) : m]
    return bool(np.isfinite(recent).any() and np.nanmax(recent) >= level and adx[m] < adx[m - 1])


DiState = Literal["separated", "tangled", "between", "unknown"]


def di_state(
    data: StrategyData,
    role: str,
    period: int,
    m: int,
    *,
    separation: float,
    tangled: float,
    slope_bars: int,
) -> DiState:
    """``"separated"`` (|+DI - -DI| >= ``separation`` and ADX rising), ``"tangled"``
    (|+DI - -DI| < ``tangled``), ``"between"``, or ``"unknown"`` while the series warms up."""  # fmt: skip
    pdi, mdi, adx = dmi_of(data, role, period)
    if m < slope_bars or not np.all(np.isfinite([pdi[m], mdi[m], adx[m], adx[m - slope_bars]])):
        return "unknown"
    gap = abs(float(pdi[m] - mdi[m]))
    if gap < tangled:
        return "tangled"
    if gap >= separation and adx[m] > adx[m - slope_bars]:
        return "separated"
    return "between"


# ------------------------------------------------------------ macd cross
class MacdCrossParams(ConfirmationParams):
    role: Role = Field("lwc", description="تایم‌فریمی که MACD روی آن خوانده می‌شود")
    fast: int = Field(12, ge=2, description="EMA سریع")
    slow: int = Field(26, ge=3, description="EMA کند")
    signal: int = Field(9, ge=2, description="دورهٔ خط سیگنال")
    cross_bars: int = Field(3, ge=1, description="تقاطع باید در این تعداد کندل اخیر رخ داده باشد")
    zero_band: float = Field(
        0.1, ge=0, le=1,
        description="تقاطعی که |MACD| آن کمتر از این کسر قلهٔ ۲۰۰کندلی قبلی است، نزدیک صفر و نویز است",
    )  # fmt: skip
    extreme_window: int = Field(200, ge=10, description="پنجرهٔ قلهٔ غلتان |MACD| برای باند صفر")

    @model_validator(mode="after")
    def _periods(self) -> MacdCrossParams:
        if self.fast >= self.slow:
            raise ValueError("EMA سریع باید کوتاه‌تر از EMA کند باشد")
        return self


@register
class MacdCross(ConfirmationBlock[MacdCrossParams]):
    """The MACD line crossed its signal line in the trade's favour, away from zero (video 54).

    Crossovers hugging the zero line mark tightening averages in a sideways chop, not a
    fresh trend, and are ignored: the newest cross in the last ``cross_bars`` role bars that
    is not inside the zero band decides. ``zero_band`` is a fraction of the rolling
    ``extreme_window``-bar maximum of ``|MACD|`` before the cross.
    """

    kind = BlockKind.CONFIRMATION
    type = "macd_cross"
    title_fa = "تقاطع MACD (به‌جز نزدیک صفر)"
    sources = ("tcp-blueprint 06: video 54 (midline chop filter)",)
    oscillator = True
    Params = MacdCrossParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, d = self.p, candidate.direction
        m = int(data.positions[p.role][candidate.bar])
        line, sig, _ = macd_of(data, p.role, p.fast, p.slow, p.signal)
        scale = prior_extremes(np.abs(line), p.extreme_window)[0]
        if m < 1 or not np.isfinite(sig[m]):
            return CheckResult("na", "MACD هنوز محاسبه نشده")
        diff = (line - sig) * d
        chop = False
        for j in range(m, max(0, m - p.cross_bars), -1):
            if not (np.isfinite(diff[j]) and np.isfinite(diff[j - 1])):
                continue
            if diff[j] > 0 >= diff[j - 1]:  # a cross in the trade's favour on bar j
                if not np.isfinite(scale[j]):
                    return CheckResult("na", "تاریخچهٔ MACD برای باند صفر کافی نیست")
                if abs(line[j]) < p.zero_band * scale[j]:
                    chop = True
                    continue
                return CheckResult("pass", f"تقاطع MACD در {m - j} کندل پیش، دور از صفر")
        if chop:
            return CheckResult("fail", "تقاطع MACD نزدیک خط صفر است (نویز)")
        return CheckResult("fail", f"تقاطع MACD در {p.cross_bars} کندل اخیر نیست")


# ----------------------------------------------------------- roc ceiling
class RocParams(BlockParams):
    role: Role = Field("mwc", description="تایم‌فریمی که ROC روی آن خوانده می‌شود (۴ساعته)")
    period: int = Field(14, ge=2, description="دورهٔ ROC")
    extreme_window: int = Field(200, ge=10, description="پنجرهٔ قله و دره‌های غلتان ROC")
    extreme_fraction: float = Field(
        0.95, gt=0, le=1, description="سقف: این کسر از بالاترین ROC پنجرهٔ قبل (کف: پایین‌ترین)"
    )


class RocCeilingParams(RocParams):
    mirror: bool = Field(True, description="کف ROC شورت‌ها را هم ببندد (قرینهٔ سقف)")


@register
class RocCeiling(ContextBlock[RocCeilingParams]):
    """No longs while the ROC of ``role`` is at its rolling ceiling (video 55).

    Momentum velocity is depleted at the ceiling and a sharp pullback is likely, so
    every long trigger is disabled until ROC falls back below it (``mirror``: shorts
    at the floor). The ceiling is ``extreme_fraction`` of the highest ROC of the
    ``extreme_window`` role bars before the tested one. Where no ceiling exists yet
    the Block does not forbid anything. The exit-side counterpart is the Profit
    Chain's ``roc_ceiling_exit``.
    """

    kind = BlockKind.CONTEXT
    type = "roc_ceiling"
    title_fa = "سقف ROC (ممنوعیت لانگ)"
    sources = ("tcp-blueprint 06: video 55 (exhaustion ceiling)",)
    oscillator = True
    Params = RocCeilingParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        v, ceiling, floor = roc_band(data, p.role, p.period, p.extreme_window, p.extreme_fraction)
        with np.errstate(invalid="ignore"):
            at_top = np.isfinite(ceiling) & (v >= ceiling)
            at_bottom = np.isfinite(floor) & (v <= floor) & p.mirror
        return ContextOutput(
            data.aligned(p.role, ~at_top, True),
            data.aligned(p.role, ~at_bottom, True),
            {"roc_at_ceiling": data.aligned(p.role, at_top, False)},
        )


# ------------------------------------------------------- roc box breakout
class RocBoxParams(ConfirmationParams):
    role: Role = Field("lwc", description="تایم‌فریمی که ROC روی آن خوانده می‌شود")
    period: int = Field(14, ge=2, description="دورهٔ ROC")
    box_bars: int = Field(20, ge=3, description="پنجرهٔ محدودهٔ خنثی (باکس) ROC، تعداد کندل قبل")
    fresh_bars: int = Field(3, ge=1, description="شکست باید در این تعداد کندل اخیر رخ داده باشد")


@register
class RocBoxBreakout(ConfirmationBlock[RocBoxParams]):
    """ROC broke out of its own recent range in the trade's direction (video 55).

    The box is the high-low range of ROC over the ``box_bars`` role bars before
    the tested bar; ROC above its top (shorts: below its bottom) within the last
    ``fresh_bars`` bars means volatility has expanded and validates the
    trend-following setup.
    """

    kind = BlockKind.CONFIRMATION
    type = "roc_box_breakout"
    title_fa = "شکست باکس ROC"
    sources = ("tcp-blueprint 06: video 55 (range box on ROC)",)
    oscillator = True
    Params = RocBoxParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, d = self.p, candidate.direction
        m = int(data.positions[p.role][candidate.bar])
        v = roc_of(data, p.role, p.period)
        top, bottom = prior_extremes(v, p.box_bars)
        if m < 0 or not np.isfinite(v[m]):
            return CheckResult("na", "ROC هنوز محاسبه نشده")
        edge = top if d > 0 else bottom
        lo = max(0, m - p.fresh_bars + 1)
        seg, lim = v[lo : m + 1], edge[lo : m + 1]
        ok = np.isfinite(seg) & np.isfinite(lim)
        if not ok.any():
            return CheckResult("na", "تاریخچهٔ ROC برای باکس کافی نیست")
        if np.any(ok & ((seg - lim) * d > 0)):
            return CheckResult("pass", "ROC از باکس خود در جهت معامله بیرون زده است")
        return CheckResult("fail", "ROC هنوز درون باکس خود است")
