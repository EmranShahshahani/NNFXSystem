"""The first Blocks: the Strategy Document tracer bullet (ticket 05).

Simple versions on purpose; the full TCP rules come in tickets 06-21. Every
number is a parameter with the blueprint's default (docs/sources/tcp-blueprint).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
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


def sma(x: np.ndarray, n: int) -> np.ndarray:
    """Simple moving average; NaN until ``n`` bars exist (causal)."""
    return pd.Series(x).rolling(n, min_periods=n).mean().to_numpy()


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder's average true range; NaN until ``n`` bars exist (causal)."""
    prev = np.r_[np.nan, close[:-1]]
    tr = np.nanmax(np.column_stack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=1)
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


# ---------------------------------------------------------------- context
class ThreeSmaParams(BlockParams):
    fast: int = Field(7, gt=0, description="SMA کوتاه (مومنتوم)")
    mid: int = Field(25, gt=0, description="SMA میانی (ساختار)")
    slow: int = Field(99, gt=0, description="SMA بلند (مبنای کلان)")
    timeframe: Role = Field("mwc", description="تایم‌فریمی که هم‌ترازی روی آن سنجیده می‌شود")
    close_beyond_mid: bool = Field(True, description="بسته‌شدن قیمت هم باید آن سوی SMA میانی باشد")

    @model_validator(mode="after")
    def _ordered(self) -> ThreeSmaParams:
        if not self.fast < self.mid < self.slow:
            raise ValueError("fast < mid < slow لازم است")
        return self


@register
class ThreeSmaAlignment(ContextBlock):
    """Longs only when SMA fast > mid > slow on the chosen timeframe; shorts mirrored."""

    kind = BlockKind.CONTEXT
    type = "three_sma_alignment"
    title_fa = "هم‌ترازی سه میانگین (۷/۲۵/۹۹)"
    sources = ("tcp-blueprint: 3-SMA system note",)
    Params = ThreeSmaParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p: ThreeSmaParams = self.p  # type: ignore[assignment]
        f = data.frames[p.timeframe]
        c = f.close
        a, b, s = sma(c, p.fast), sma(c, p.mid), sma(c, p.slow)
        with np.errstate(invalid="ignore"):
            up = (a > b) & (b > s)
            dn = (a < b) & (b < s)
            if p.close_beyond_mid:
                up &= c > b
                dn &= c < b
        return ContextOutput(
            data.aligned(p.timeframe, up, False), data.aligned(p.timeframe, dn, False)
        )


# ------------------------------------------------------------------ setup
class CandleSetupParams(BlockParams):
    sma: int = Field(7, gt=0, description="SMA که باید پشت سایه باشد")
    min_wick: float = Field(0.5, gt=0, lt=1, description="کمترین سایهٔ ردکننده، سهمی از طول کندل")
    max_opposite_wick: float = Field(
        0.25, ge=0, lt=1, description="بیشترین سایهٔ مخالف، سهمی از طول کندل"
    )


@register
class CandleSetup(SetupBlock):
    """TCP's 15m entry candle (basic form): a long rejection wick with the SMA inside it.

    Long: lower wick >= ``min_wick`` of the range, upper wick <= ``max_opposite_wick``
    of the range, and the SMA between the low and the body (behind the wick,
    never through the body). Trigger above the high, invalidation and proposed
    stop at the low. Shorts mirrored. The full Candle Setup is ticket 10.
    """

    kind = BlockKind.SETUP
    type = "candle_setup"
    title_fa = "کندل ستاپ (پایه)"
    sources = ("tcp-blueprint: Candle Setup",)
    Params = CandleSetupParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p: CandleSetupParams = self.p  # type: ignore[assignment]
        f = data.base
        o, h, lo, c = f.open, f.high, f.low, f.close
        m = sma(c, p.sma)
        rng = h - lo
        body_lo, body_hi = np.minimum(o, c), np.maximum(o, c)
        with np.errstate(invalid="ignore", divide="ignore"):
            lower, upper = (body_lo - lo) / rng, (h - body_hi) / rng
            long_ = (
                (rng > 0)
                & (lower >= p.min_wick)
                & (upper <= p.max_opposite_wick)
                & (lo <= m)
                & (m <= body_lo)
            )
            short = (
                (rng > 0)
                & (upper >= p.min_wick)
                & (lower <= p.max_opposite_wick)
                & (body_hi <= m)
                & (m <= h)
            )
        d = np.where(long_, 1, np.where(short, -1, 0)).astype("int8")
        nan = np.full(len(f), np.nan)
        trigger = np.where(d > 0, h, np.where(d < 0, lo, nan))
        inval = np.where(d > 0, lo, np.where(d < 0, h, nan))
        return SetupOutput(d, trigger, inval, inval.copy())


# -------------------------------------------------------------- execution
class StopMarketParams(BlockParams):
    buffer_pct: float = Field(0.05, ge=0, description="فاصلهٔ تریگر از سطح، درصد قیمت")
    expiry_bars: int = Field(4, ge=1, description="عمر سفارش منتظر، تعداد کندل")
    cancel_on_invalidation: bool = Field(True, description="لغو با بسته‌شدن کندل آن سوی سطح ابطال")


@register
class StopMarket(ExecutionBlock):
    """A stop-market order just beyond the setup's trigger (the TCP Trigger)."""

    kind = BlockKind.EXECUTION
    type = "stop_market"
    title_fa = "سفارش استاپ (تریگر)"
    sources = ("tcp-blueprint: Trigger / stop-market entries",)
    Params = StopMarketParams

    def orders(self, candidate: SetupCandidate, data: StrategyData) -> list[OrderSpec]:
        p: StopMarketParams = self.p  # type: ignore[assignment]
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
class StructuralStop(StopBlock):
    """The stop just beyond the setup's structural level (its proposed stop)."""

    kind = BlockKind.STOP
    type = "structural_stop"
    title_fa = "حد ضرر ساختاری"
    sources = ("tcp-blueprint: structural stops",)
    Params = StructuralStopParams

    def initial_stop(self, candidate: SetupCandidate, data: StrategyData) -> float:
        p: StructuralStopParams = self.p  # type: ignore[assignment]
        return candidate.stop - candidate.direction * candidate.stop * p.buffer_pct / 100.0


# ------------------------------------------------------------------- exit
class FixedRParams(BlockParams):
    r: float = Field(2.0, gt=0, description="خروج کامل در این ضریب R")


@register
class FixedR(ExitBlock):
    """Close the whole position at ``r`` R."""

    kind = BlockKind.EXIT
    type = "fixed_r"
    title_fa = "خروج کامل در R ثابت"
    sources = ("tcp-blueprint: no exit below 2R",)
    Params = FixedRParams

    def plan(self, candidate: SetupCandidate) -> ExitPlan:
        p: FixedRParams = self.p  # type: ignore[assignment]
        return ExitPlan(steps=(ExitStep(r=p.r, fraction=1.0),))
