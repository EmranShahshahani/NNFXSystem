"""Bollinger rules (Strategy Builder ticket 18, ADR 10 §22).

Video 14. Three Blocks and one Profit Chain exit, all causal (a band at a bar uses the
closes up to it):

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``bb_htf_touch``      Setup. With the higher timeframe's Dow trend up, a touch of
                      the lower band that closes back above it, or a close back
                      over the middle line, triggers a long (mirrored for shorts:
                      a Short never fires against an up-trend)
``bb_squeeze``        Setup. Bandwidth sank to a cyclical low, then a candle closes
                      outside the band: the expansion, traded in the break's way
``bb_runway``         Confirmation. The "Momentum Runway" of the double band: the
                      close is between the 1 SD and the 2 SD band on the trade's
                      side
====================  ==========================================================

``ProfitChain.runway_exit`` closes what remains once candles that were riding the runway
fall back inside the 1 SD band (see ``runway_lost``).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    CheckResult,
    ConfirmationBlock,
    ConfirmationParams,
    Role,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StrategyData,
    register,
)
from nnfx.strategy.candles import candle_setup
from nnfx.strategy.series import bollinger


def _lag(x: np.ndarray, k: int) -> np.ndarray:
    """``x`` as it was ``k`` bars ago (NaN before the start)."""
    return pd.Series(x).shift(k).to_numpy()


# ------------------------------------------------------------------ touch
class BbTouchParams(BlockParams):
    htf_role: Role = Field("hwc", description="تایم‌فریمی که جهت روند را می‌دهد (hwc, mwc, lwc)")
    pivot_bars: int = Field(2, ge=1, description="پیوت روند داو: تعداد کندل‌های دو طرف")
    period: int = Field(20, ge=2, description="دورهٔ میانگین بولینگر")
    k: float = Field(2.0, gt=0, description="ضریب انحراف معیار باندها")
    mode: Literal["touch", "cross", "either"] = Field(
        "either",
        description="touch: برخورد و برگشت از باند، cross: عبور از خط میانی، either: هر دو",
    )


@register
class BbHtfTouch(SetupBlock[BbTouchParams]):
    """Bollinger touches and mid-line crosses, directed by the higher timeframe (video 14).

    Higher-timeframe Dow trend up: *touch* is a low at or under the lower band with the
    close back above it (a rejection); *cross* is a close over the middle line after a
    close at or under it. Only longs. Trend down mirrors it with shorts at the upper band
    and below the middle line. A flat higher-timeframe state gives no candidate. Trigger
    at the bar's high (shorts: low); invalidation and stop at the other end.
    """

    kind = BlockKind.SETUP
    type = "bb_htf_touch"
    title_fa = "برخورد بولینگر هم‌جهت با روند تایم‌فریم بالاتر"
    sources = ("tcp-blueprint 02: video 14 (directional envelope)",)
    Params = BbTouchParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        lower, mid, upper = bollinger(f.close, p.period, p.k)
        trend = data.aligned(p.htf_role, data.dow(p.htf_role, p.pivot_bars), 0)
        prev = _lag(f.close, 1)
        with np.errstate(invalid="ignore"):
            touch_up = (f.low <= lower) & (f.close > lower)
            touch_dn = (f.high >= upper) & (f.close < upper)
            cross_up = (f.close > mid) & (prev <= _lag(mid, 1))
            cross_dn = (f.close < mid) & (prev >= _lag(mid, 1))
        use_touch, use_cross = p.mode != "cross", p.mode != "touch"
        up = (touch_up & use_touch) | (cross_up & use_cross)
        dn = (touch_dn & use_touch) | (cross_dn & use_cross)
        return candle_setup(up & (trend > 0), dn & (trend < 0), f.high, f.low, "bb_touch")


# ---------------------------------------------------------------- squeeze
class BbSqueezeParams(BlockParams):
    period: int = Field(20, ge=2, description="دورهٔ میانگین بولینگر")
    k: float = Field(2.0, gt=0, description="ضریب انحراف معیار باندها")
    window: int = Field(100, ge=5, description="تاریخچهٔ سنجش «کف دورهٔ» پهنای باند (کندل)")
    squeeze_pct: float = Field(
        0.2, gt=0, lt=1, description="پهنای باند در این کسر پایین پنجره = فشردگی"
    )
    squeeze_bars: int = Field(5, ge=1, description="فشردگی در این تعداد کندل پیش از شکست دیده شود")


def bandwidth(close: np.ndarray, period: int, k: float) -> np.ndarray:
    """(upper - lower) / middle: the band's width as a fraction of price (scale-free)."""
    lower, mid, upper = bollinger(close, period, k)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(np.where(mid > 0, (upper - lower) / mid, np.nan))


@register
class BbSqueeze(SetupBlock[BbSqueezeParams]):
    """Squeeze and expansion (video 14): compression, then a decisive close outside the band.

    A bar is *squeezed* when the bandwidth sits strictly under the ``squeeze_pct`` quantile of the
    ``window`` bandwidths before it (a cyclical low). A candle closing above the upper band
    (below the lower) with a squeezed bar among the ``squeeze_bars`` bars before it is an
    institutional expansion: a long (short) in the break's direction, trigger at the bar's
    high (low), invalidation and stop at the other end.
    """

    kind = BlockKind.SETUP
    type = "bb_squeeze"
    title_fa = "فشردگی و انبساط بولینگر"
    sources = ("tcp-blueprint 02: video 14 (squeeze and expansion engine)",)
    Params = BbSqueezeParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        lower, _, upper = bollinger(f.close, p.period, p.k)
        bw = bandwidth(f.close, p.period, p.k)
        floor = (
            pd.Series(bw).shift(1).rolling(p.window, min_periods=p.window).quantile(p.squeeze_pct)
        )
        with np.errstate(invalid="ignore"):
            squeezed = (bw < floor.to_numpy()).astype(float)
        recent = (
            pd.Series(squeezed).shift(1).rolling(p.squeeze_bars, min_periods=1).max().to_numpy() > 0
        )
        with np.errstate(invalid="ignore"):
            up, dn = f.close > upper, f.close < lower
        return candle_setup(up & recent, dn & recent, f.high, f.low, "bb_squeeze")


# ----------------------------------------------------------------- runway
class RunwayParams(BlockParams):
    period: int = Field(20, ge=2, description="دورهٔ میانگین بولینگر")
    inner: float = Field(1.0, gt=0, description="باند داخلی: ضریب انحراف معیار")
    outer: float = Field(2.0, gt=0, description="باند بیرونی: ضریب انحراف معیار")

    @model_validator(mode="after")
    def _ordered(self) -> RunwayParams:
        if self.inner >= self.outer:
            raise ValueError("باند داخلی باید کوچک‌تر از باند بیرونی باشد")
        return self


def runway_state(
    data: StrategyData, role: str, period: int, inner: float, outer: float
) -> np.ndarray:
    """Per ``role`` bar: +1 when the close is in the upward runway (above the 1 SD band, at
    or under the 2 SD band), -1 in the downward one, 0 anywhere else."""

    def make() -> np.ndarray:
        c = data.frames[role].close
        in_dn, _, in_up = bollinger(c, period, inner)
        out_dn, _, out_up = bollinger(c, period, outer)
        with np.errstate(invalid="ignore"):
            up = (c > in_up) & (c <= out_up)
            dn = (c < in_dn) & (c >= out_dn)
        return np.where(up, 1, np.where(dn, -1, 0)).astype("int8")

    return data.memo(("runway", role, period, inner, outer), make)


def runway_lost(
    data: StrategyData, role: str, m: int, d: int, *, period: int, inner: float, outer: float,
    bars: int,
) -> bool:  # fmt: skip
    """Whether the trade's candles were riding the runway within the last ``bars`` bars of
    ``role`` and the bar ``m`` closed back inside the 1 SD band (not out past the 2 SD band)."""
    state = runway_state(data, role, period, inner, outer)
    if m < 1 or state[m] == d:
        return False
    c = data.frames[role].close
    lower, _, upper = bollinger(c, period, inner)
    band = upper[m] if d > 0 else lower[m]
    if not np.isfinite(band) or (c[m] - band) * d > 0:
        return False  # beyond the 1 SD band but off the runway: past the 2 SD band, not lost
    return bool(np.any(state[max(0, m - bars) : m] == d))


class BbRunwayParams(RunwayParams, ConfirmationParams):
    role: Role = Field("lwc", description="تایم‌فریمی که باندها روی آن خوانده می‌شود")
    bars: int = Field(1, ge=1, description="این تعداد کندلِ بستهٔ آخر هر کدام در باند باشند")


@register
class BbRunway(ConfirmationBlock[BbRunwayParams]):
    """The double band's Momentum Runway (video 14): the close sits between 1 and 2 SD.

    Two bands over the same SMA, 1.0 and 2.0 deviations. A trade in momentum has candles
    closing in the channel between them on its side; the last ``bars`` closes must all be
    there. Inside the 1 SD band there is no momentum; past the 2 SD band the move is
    stretched. Either fails; ``na`` until the bands exist.
    """

    kind = BlockKind.CONFIRMATION
    type = "bb_runway"
    title_fa = "باند دوگانهٔ بولینگر (مسیر مومنتوم)"
    sources = ("tcp-blueprint 02: video 14 (double Bollinger band protocol)",)
    Params = BbRunwayParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        m = int(data.positions[p.role][candidate.bar])
        if m < p.period + p.bars - 2:
            return CheckResult("na", f"needs {p.period} {p.role} bars for the bands")
        state = runway_state(data, p.role, p.period, p.inner, p.outer)
        if bool(np.all(state[m - p.bars + 1 : m + 1] == candidate.direction)):
            return CheckResult("pass", f"closing in the {p.inner:g}-{p.outer:g} SD runway")
        return CheckResult("fail", f"not in the {p.inner:g}-{p.outer:g} SD runway")
