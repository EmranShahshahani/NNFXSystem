"""The first Blocks: the Strategy Document tracer bullet (ticket 05).

Simple versions on purpose; the full TCP rules come in tickets 06-21. Every
number is a parameter with the blueprint's default (docs/sources/tcp-blueprint).
"""

from __future__ import annotations

import numpy as np
from pydantic import Field, model_validator

from nnfx.engine.types import ExitPlan, ExitStep
from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    CheckResult,
    ConfirmationBlock,
    ConfirmationParams,
    ContextBlock,
    ContextOutput,
    ExecutionBlock,
    ExitBlock,
    OrderSpec,
    Role,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StopBlock,
    StrategyData,
    register,
)
from nnfx.strategy.series import falling, rising, rsi, sma


# ---------------------------------------------------------------- context
class ThreeSmaParams(BlockParams):
    fast: int = Field(7, gt=0, description="SMA کوتاه (مومنتوم)")
    mid: int = Field(25, gt=0, description="SMA میانی (ساختار)")
    slow: int = Field(99, gt=0, description="SMA بلند (مبنای کلان)")
    timeframe: Role = Field("mwc", description="تایم‌فریمی که هم‌ترازی روی آن سنجیده می‌شود")
    price_beyond_fast: bool = Field(True, description="قیمت هم باید آن سوی SMA کوتاه بسته شود")
    same_slope: bool = Field(True, description="هر سه میانگین باید هم‌جهت شیب داشته باشند")
    slope_bars: int = Field(1, ge=1, description="شیب نسبت به چند کندل قبل سنجیده شود")

    @model_validator(mode="after")
    def _ordered(self) -> ThreeSmaParams:
        if not self.fast < self.mid < self.slow:
            raise ValueError("fast < mid < slow لازم است")
        return self


@register
class ThreeSmaAlignment(ContextBlock[ThreeSmaParams]):
    """Longs only when price > SMA fast > mid > slow, all sloping up; shorts mirrored.

    The blueprint's 3-SMA system (7 momentum, 25 structure, 99 macro baseline).
    """

    kind = BlockKind.CONTEXT
    type = "three_sma_alignment"
    title_fa = "هم‌ترازی سه میانگین (۷/۲۵/۹۹)"
    sources = ("tcp-blueprint: 3-SMA system note",)
    Params = ThreeSmaParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        c = data.frames[p.timeframe].close
        a, b, s = sma(c, p.fast), sma(c, p.mid), sma(c, p.slow)
        with np.errstate(invalid="ignore"):
            up = (a > b) & (b > s)
            dn = (a < b) & (b < s)
            if p.price_beyond_fast:
                up &= c > a
                dn &= c < a
        if p.same_slope:
            n = p.slope_bars
            up &= rising(a, n) & rising(b, n) & rising(s, n)
            dn &= falling(a, n) & falling(b, n) & falling(s, n)
        return ContextOutput(
            data.aligned(p.timeframe, up, False), data.aligned(p.timeframe, dn, False)
        )


# ------------------------------------------------------------------ setup
class CandleSetupParams(BlockParams):
    sma: int = Field(7, gt=0, description="SMA که باید پشت سایه باشد")
    wick_to_body: float = Field(
        1.5, gt=0, description="سایهٔ ردکننده دست‌کم چند برابر بدنه (۱٫۵ تا ۲)"
    )
    opposite_to_body: float = Field(1.0, gt=0, description="سایهٔ مخالف کمتر از این ضریبِ بدنه")


@register
class CandleSetup(SetupBlock[CandleSetupParams]):
    """TCP's 15m entry candle (basic form), blueprint 01.

    Long: a lower (rejection) wick at least ``wick_to_body`` x the real body,
    an upper wick smaller than ``opposite_to_body`` x the body, and the SMA
    between the low and the body (behind the wick, never through the body).
    Trigger at the high; invalidation and proposed stop at the low. Shorts
    mirrored. The full Candle Setup (context, location, size) is ticket 10.
    """

    kind = BlockKind.SETUP
    type = "candle_setup"
    title_fa = "کندل ستاپ (پایه)"
    sources = ("tcp-blueprint 01: Candle Setup",)
    Params = CandleSetupParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        o, h, lo, c = f.open, f.high, f.low, f.close
        m = sma(c, p.sma)
        body = np.abs(c - o)
        body_lo, body_hi = np.minimum(o, c), np.maximum(o, c)
        lower, upper = body_lo - lo, h - body_hi
        with np.errstate(invalid="ignore"):
            long_ = (lower >= p.wick_to_body * body) & (upper < p.opposite_to_body * body)
            long_ &= (lower > 0) & (lo <= m) & (m <= body_lo)
            short = (upper >= p.wick_to_body * body) & (lower < p.opposite_to_body * body)
            short &= (upper > 0) & (body_hi <= m) & (m <= h)
        d = np.where(long_, 1, np.where(short, -1, 0)).astype("int8")
        nan = np.full(len(f), np.nan)
        trigger = np.where(d > 0, h, np.where(d < 0, lo, nan))
        inval = np.where(d > 0, lo, np.where(d < 0, h, nan))
        return SetupOutput(d, trigger, inval, inval.copy(), {"rejection_wick": d != 0})


# ----------------------------------------------------------- confirmation
class RsiMomentumParams(ConfirmationParams):
    period: int = Field(14, ge=2, description="دورهٔ RSI")
    long_above: float = Field(70.0, gt=0, lt=100, description="برای خرید، RSI بالاتر از این")
    short_below: float = Field(30.0, gt=0, lt=100, description="برای فروش، RSI پایین‌تر از این")
    fresh_bars: int = Field(
        3, ge=0, description="RSI باید در این تعداد کندل اخیر وارد ناحیه شده باشد (۰: فقط سطح)"
    )


@register
class RsiMomentum(ConfirmationBlock[RsiMomentumParams]):
    """RSI momentum on the setup candle (blueprint 04: RSI 14 must *cross into* overbought
    for longs, oversold for shorts).

    Passes when RSI is beyond the threshold now and was not, at some point, within
    the last ``fresh_bars`` bars (it *entered* the zone); ``fresh_bars = 0`` checks
    the level only. Not applicable until ``period + 1`` closes exist. The basic
    form; the oscillator methods (Bollinger on RSI, divergences, ...) are ticket 15.
    """

    kind = BlockKind.CONFIRMATION
    type = "rsi_momentum"
    title_fa = "مومنتوم RSI"
    sources = ("tcp-blueprint 04: RSI 14 crossing into overbought/oversold",)
    Params = RsiMomentumParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        close = data.base.close[: candidate.bar + 1]
        if len(close) < p.period + 1:
            return CheckResult(
                "na", f"RSI {p.period} needs {p.period + 1} closes, {len(close)} so far"
            )
        series = rsi(close, p.period)
        sign = 1.0 if candidate.direction > 0 else -1.0
        level = p.long_above if sign > 0 else p.short_below
        word = "above" if sign > 0 else "below"
        now = float(series[-1])
        if not (now - level) * sign > 0:
            return CheckResult("fail", f"RSI {now:.1f} not {word} {level:g}")
        if p.fresh_bars == 0:
            return CheckResult("pass", f"RSI {now:.1f} {word} {level:g}")
        before = series[-1 - p.fresh_bars : -1]
        outside = before[np.isfinite(before) & ((before - level) * sign <= 0)]
        if len(outside):
            return CheckResult(
                "pass", f"RSI {now:.1f} entered {word} {level:g} within {p.fresh_bars} bars"
            )
        return CheckResult(
            "fail", f"RSI {now:.1f} already {word} {level:g} for more than {p.fresh_bars} bars"
        )


class VolumeExpansionParams(ConfirmationParams):
    lookback: int = Field(20, ge=1, description="تعداد کندل‌های میانگین حجم")
    factor: float = Field(1.0, gt=0, description="حجم کندل ستاپ دست‌کم این ضریبِ میانگین")


@register
class VolumeExpansion(ConfirmationBlock[VolumeExpansionParams]):
    """The setup candle's volume against the average of the ``lookback`` bars before it.

    Passes when it is strictly above ``factor`` x that average (expansion for a
    new leg). Not applicable when the venue reports no volume or there is too
    little history. The basic form: the continuation case (quieter than the
    impulse), the volume matrix and climaxes are ticket 17.
    """

    kind = BlockKind.CONFIRMATION
    type = "volume_expansion"
    title_fa = "افزایش حجم"
    sources = ("tcp-blueprint: volume confirms a new leg",)
    Params = VolumeExpansionParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        f = data.base
        if f.volume_kind == "none":
            return CheckResult("na", "the venue reports no volume")
        i = candidate.bar
        if i < p.lookback:
            return CheckResult(
                "na", f"needs {p.lookback} bars of volume before the setup, {i} so far"
            )
        v = f.volume
        avg = float(np.mean(v[i - p.lookback : i]))
        ratio = float(v[i]) / avg if avg > 0 else float("inf")
        ok = ratio > p.factor  # expansion: strictly above the average
        return CheckResult(
            "pass" if ok else "fail",
            f"volume {ratio:.2f}x its {p.lookback}-bar average (needs more than {p.factor:g}x)",
        )


# -------------------------------------------------------------- execution
class StopMarketParams(BlockParams):
    buffer_pct: float = Field(0.05, ge=0, description="فاصلهٔ تریگر از سطح، درصد قیمت")
    expiry_bars: int = Field(4, ge=1, description="عمر سفارش منتظر، تعداد کندل")
    cancel_on_invalidation: bool = Field(True, description="لغو با بسته‌شدن کندل آن سوی سطح ابطال")


@register
class StopMarket(ExecutionBlock[StopMarketParams]):
    """A stop-market order just beyond the setup's trigger (the TCP Trigger)."""

    kind = BlockKind.EXECUTION
    type = "stop_market"
    title_fa = "سفارش استاپ (تریگر)"
    sources = ("tcp-blueprint: Trigger / stop-market entries",)
    Params = StopMarketParams

    def orders(self, candidate: SetupCandidate, data: StrategyData) -> list[OrderSpec]:
        p = self.p
        return [
            OrderSpec(
                level=candidate.trigger,
                buffer=candidate.trigger * p.buffer_pct / 100.0,
                invalidation=candidate.invalidation if p.cancel_on_invalidation else None,
                expires_after_bars=p.expiry_bars,
            )
        ]


# ------------------------------------------------------------------- stop
class StructuralStopParams(BlockParams):
    buffer_pct: float = Field(0.05, ge=0, description="فاصلهٔ حد ضرر پشت سطح ساختاری، درصد قیمت")


@register
class StructuralStop(StopBlock[StructuralStopParams]):
    """The stop just beyond the setup's structural level (its proposed stop)."""

    kind = BlockKind.STOP
    type = "structural_stop"
    title_fa = "حد ضرر ساختاری"
    sources = ("tcp-blueprint: structural stops",)
    Params = StructuralStopParams

    def initial_stop(self, candidate: SetupCandidate, data: StrategyData) -> float:
        return candidate.stop - candidate.direction * candidate.stop * self.p.buffer_pct / 100.0


# ------------------------------------------------------------------- exit
class FixedRParams(BlockParams):
    r: float = Field(2.0, gt=0, description="خروج کامل در این ضریب R")


@register
class FixedR(ExitBlock[FixedRParams]):
    """Close the whole position at ``r`` R."""

    kind = BlockKind.EXIT
    type = "fixed_r"
    title_fa = "خروج کامل در R ثابت"
    sources = ("tcp-blueprint: no exit below 2R",)
    Params = FixedRParams

    def plan(self, candidate: SetupCandidate, data: StrategyData) -> ExitPlan:
        return ExitPlan(steps=(ExitStep(r=self.p.r, fraction=1.0),))
