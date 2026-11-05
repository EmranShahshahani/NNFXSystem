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
from nnfx.strategy.series import falling, rising, sma


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
