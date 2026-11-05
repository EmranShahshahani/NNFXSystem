"""The first Blocks: the Strategy Document tracer bullet (ticket 05).

Simple versions on purpose; the full TCP rules come in tickets 06-21. Every
number is a parameter with the blueprint's default (docs/sources/tcp-blueprint).
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from nnfx.engine.types import ExitPlan, ExitStep, PositionView
from nnfx.strategy.blocks import (
    MIN_FULL_CLOSE_R,
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
    StopMove,
    StrategyData,
    register,
)
from nnfx.strategy.series import falling, rising, rsi, sma
from nnfx.strategy.structure import wave_bias


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


class DowTrendParams(BlockParams):
    timeframe: Role = Field("mwc", description="تایم‌فریمی که روند داو روی آن سنجیده می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف")
    in_range: Literal["none", "both"] = Field(
        "none", description="در حالت رنج: هیچ معامله‌ای، یا هر دو جهت"
    )


@register
class DowTrend(ContextBlock[DowTrendParams]):
    """Longs in a Dow uptrend (HH/HL), shorts in a downtrend, on one timeframe role.

    A trend starts on a break of the last swing with a higher low (lower high)
    and ends only on a failed peak plus a neckline break (videos 3, 28; see
    ``structure.dow_states``). Swings are confirmed ``pivot_bars`` bars later.
    """

    kind = BlockKind.CONTEXT
    type = "dow_trend"
    title_fa = "روند داو (سقف و کف)"
    sources = (
        "tcp-blueprint 01: video 3 (Dow theory HH/HL, LH/LL)",
        "tcp-blueprint 03: video 28 (failed peak and neckline)",
    )
    Params = DowTrendParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        st = data.dow(p.timeframe, p.pivot_bars)
        rng = st == 0 if p.in_range == "both" else np.zeros(len(st), bool)
        return ContextOutput(
            data.aligned(p.timeframe, (st > 0) | rng, False),
            data.aligned(p.timeframe, (st < 0) | rng, False),
            {"state": data.aligned(p.timeframe, st, 0)},
        )


class WaveCyclesParams(BlockParams):
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف (هر سه نقش)")
    follow_mwc_when_flat: bool = Field(
        True, description="وقتی HWC خنثی است، جهت روند MWC مجاز باشد (موج فرعی)"
    )
    two_way_box: bool = Field(
        False, description="باکس دوطرفه: وقتی HWC و MWC هر دو رنج‌اند، هر دو جهت با تارگت ۲R تا ۳R"
    )


@register
class WaveCycles(ContextBlock[WaveCyclesParams]):
    """The HWC/MWC/LWC wave cycles (videos 63, 64; see ``structure.wave_bias``).

    The HWC's Dow trend sets the direction; an LWC counter-move inside it is
    never shorted. The HWC is treated as flat only after the LWC and then the
    MWC turn away. Trades against the HWC's last trend (secondary waves, the
    two-way box) are tagged ``counter_trend``, which the Profit Chain's
    ``counter_trend: tagged`` mode closes at 2R-3R.
    """

    kind = BlockKind.CONTEXT
    type = "wave_cycles"
    title_fa = "سیکل‌های موج (HWC/MWC/LWC)"
    sources = (
        "tcp-blueprint 07: video 63 (cycle taxonomy, bottom-up reversal)",
        "tcp-blueprint 07: video 64 (two-way trading box)",
        "tcp-blueprint 03: video 26 (primary vs secondary waves)",
    )
    Params = WaveCyclesParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        st = {r: data.aligned(r, data.dow(r, p.pivot_bars), 0) for r in ("hwc", "mwc", "lwc")}
        b = wave_bias(
            st["hwc"],
            st["mwc"],
            st["lwc"],
            follow_mwc_when_flat=p.follow_mwc_when_flat,
            two_way_box=p.two_way_box,
        )
        flags = {f"{r}_state": s for r, s in st.items()}
        flags.update(primary=b.primary, hwc_effective=b.hwc_effective, box=b.box)
        return ContextOutput(
            b.long_ok, b.short_ok, flags, {"counter_trend": (b.counter_long, b.counter_short)}
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
    r: float = Field(2.0, ge=MIN_FULL_CLOSE_R, description="خروج کامل در این ضریب R (هرگز زیر ۲R)")


@register
class FixedR(ExitBlock[FixedRParams]):
    """Close the whole position at ``r`` R (never below 2R)."""

    kind = BlockKind.EXIT
    type = "fixed_r"
    title_fa = "خروج کامل در R ثابت"
    sources = ("tcp-blueprint: no exit below 2R",)
    Params = FixedRParams

    def plan(self, candidate: SetupCandidate, data: StrategyData, stop: float) -> ExitPlan:
        return ExitPlan(steps=(ExitStep(r=self.p.r, fraction=1.0),))


class ProfitChainParams(BlockParams):
    r1: float = Field(2.0, ge=MIN_FULL_CLOSE_R, description="پلهٔ اول: R (هرگز زیر ۲R)")
    f1: float = Field(0.35, gt=0, le=1, description="پلهٔ اول: سهم از حجم اولیه")
    r2: float = Field(5.0, gt=0, description="پلهٔ دوم: R")
    f2: float = Field(0.40, ge=0, le=1, description="پلهٔ دوم: سهم از حجم اولیه (۰: بدون این پله)")
    r3: float = Field(10.0, gt=0, description="پلهٔ سوم: R")
    f3: float = Field(
        0.15, ge=0, le=1, description="پلهٔ سوم: سهم از حجم اولیه (۰٫۱۵ پیش‌فرض یا ۰٫۲۰)"
    )
    runner: float = Field(
        0.10, ge=0, le=1, description="رانر: سهمی که با حد ضرر متحرک می‌ماند (۰: بدون رانر)"
    )
    breakeven: Literal["pivot", "always", "off"] = Field(
        "pivot",
        description="ریسک‌فری پس از پلهٔ اول: فقط با پیوت ساختاری تازه، همیشه، یا هرگز",
    )
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف روی تایم‌فریم مدیریت")
    trail_after_step: int = Field(
        3, ge=1, le=3, description="تریل حد ضرر پس از پر شدن این تعداد پله (۳: فقط رانر)"
    )
    trail_buffer_pct: float = Field(
        0.05, ge=0, description="فاصلهٔ حد ضرر رانر پشت سوئینگ، درصد قیمت"
    )
    counter_trend: Literal["off", "always", "tagged"] = Field(
        "off",
        description="حالت خلاف روند: خاموش، همیشه، یا فقط ستاپ‌های برچسب counter_trend",
    )
    counter_trend_exit: Literal["2r", "boundary"] = Field(
        "2r", description="خروج کامل خلاف روند: در ۲R یا در اولین مرز ساختاری"
    )
    counter_trend_max_r: float = Field(
        3.0, ge=MIN_FULL_CLOSE_R, description="سقف R خروج خلاف روند (مرز ساختاری دورتر از این)"
    )
    recycle_to_spot: bool = Field(
        False, description="ثبت انتقال سود خالص به دفتر اسپات پس از بسته‌شدن با سود زیاد"
    )
    recycle_min_r: float = Field(
        5.0, ge=MIN_FULL_CLOSE_R, description="انتقال به اسپات از این R به بالا (۵R تا ۱۰R)"
    )

    @model_validator(mode="after")
    def _ladder(self) -> ProfitChainParams:
        total = self.f1 + self.f2 + self.f3 + self.runner
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"جمع سهم پله‌ها و رانر باید ۱ شود، اکنون {total:.4g} است")
        rs = [r for r, f in ((self.r1, self.f1), (self.r2, self.f2), (self.r3, self.f3)) if f > 0]
        if any(b <= a for a, b in pairwise(rs)):
            raise ValueError("R پله‌ها باید صعودی باشد (r1 < r2 < r3)")
        return self


@register
class ProfitChain(ExitBlock[ProfitChainParams]):
    """The Profit Chain (Zanjire-ye Sood): a ladder out in R plus a trailing Runner.

    Blueprint 01 (B) and video 19: 35% at 2R, 40% at 5R, 15% at 10R (the
    blueprint also gives 20%), the last 10% trailed behind management swings;
    never a whole close below 2R. Management runs on the document's management
    timeframe (``timeframes.management``, the MWC unless set) and acts on its
    closes:

    - **Conditional breakeven.** At the first management close after the first
      step has filled where a swing low (shorts: high) has been confirmed on a
      management bar after the one the entry happened in, the stop goes to the
      entry fill. ``"always"`` moves it to the fill on the bar after the first
      step fills.
    - **Runner trail.** Once ``trail_after_step`` steps have filled (default:
      all, so only the Runner trails), the stop trails just behind the latest
      confirmed swing.
    - **Counter-trend mode.** No Runner: everything closes at 2R, or at the
      first structural boundary (the nearest confirmed swing beyond the
      trigger), never below 2R and at most ``counter_trend_max_r``
      (secondary-wave targets are 1:2 or 1:3, video 23).

    The futures-to-spot recycling record (video 61-70) is read by the run:
    ``recycle_to_spot`` / ``recycle_min_r``.
    """

    kind = BlockKind.EXIT
    type = "profit_chain"
    title_fa = "زنجیرهٔ سود"
    sources = (
        "tcp-blueprint 01 (B): Systematic Trade Management & Profit Harvesting",
        "tcp-blueprint 02: video 19 (Profit Chain, counter-trend deviation)",
        "tcp-blueprint 03: secondary waves use 1:2 or 1:3 targets",
        "tcp-blueprint 07: Capital Recycling Engine (futures to spot)",
    )
    Params = ProfitChainParams

    ROLE = "management"

    def counter_trend(self, candidate: SetupCandidate) -> bool:
        mode = self.p.counter_trend
        return mode == "always" or (mode == "tagged" and "counter_trend" in candidate.tags)

    def plan(self, candidate: SetupCandidate, data: StrategyData, stop: float) -> ExitPlan:
        p = self.p
        if self.counter_trend(candidate):
            r = MIN_FULL_CLOSE_R
            if p.counter_trend_exit == "boundary":
                b = self._boundary(candidate, data)
                if b is not None:
                    risk = abs(candidate.trigger - stop)
                    r = (b - candidate.trigger) * candidate.direction / risk
                r = round(min(max(r, MIN_FULL_CLOSE_R), p.counter_trend_max_r), 6)
            return ExitPlan(steps=(ExitStep(r=r, fraction=1.0),))
        steps = [
            ExitStep(r=r, fraction=f)
            for r, f in ((p.r1, p.f1), (p.r2, p.f2), (p.r3, p.f3))
            if f > 0
        ]
        return ExitPlan(steps=tuple(steps), runner=p.runner)

    def _swings(self, data: StrategyData, bar: int, direction: int) -> np.ndarray:
        """Management swing indices confirmed by LWC ``bar``'s close: lows for longs,
        highs for shorts."""
        n = self.p.pivot_bars
        m = int(data.positions[self.ROLE][bar])
        lows, highs = data.pivots(self.ROLE, n, n)
        idx = lows if direction > 0 else highs
        return idx[idx + n <= m]

    def _boundary(self, candidate: SetupCandidate, data: StrategyData) -> float | None:
        """The nearest confirmed management swing beyond the trigger, as of the candidate:
        for a long the lowest swing high above it, for a short the highest swing low below."""
        d = candidate.direction
        idx = self._swings(data, candidate.bar, -d)
        f = data.frames[self.ROLE]
        levels = f.high[idx] if d > 0 else f.low[idx]
        beyond = levels[(levels - candidate.trigger) * d > 0]
        if not len(beyond):
            return None
        return float(beyond.min() if d > 0 else beyond.max())

    def manage(self, position: PositionView, data: StrategyData, bar: int) -> StopMove | None:
        p, d = self.p, position.direction
        moves: list[StopMove] = []
        first_done = position.steps_filled >= 1 and position.at_risk
        if p.breakeven == "always" and first_done:
            moves.append(StopMove(position.entry_price, "breakeven"))  # at the fill, at once
        pos = data.positions[self.ROLE]
        m = int(pos[bar])
        if m < 0 or (bar > 0 and int(pos[bar - 1]) == m):
            return moves[0] if moves else None  # the rest acts on management closes only
        swings = self._swings(data, bar, d)
        if p.breakeven == "pivot" and first_done:
            # A swing on a management bar after the one the entry happened in.
            entered = data.bar_containing(self.ROLE, position.entry_time)
            if np.any(swings > entered):
                moves.append(StopMove(position.entry_price, "breakeven_after_pivot"))
        steps = position.exit_steps
        has_runner = sum(s.fraction for s in steps) < 1.0 - 1e-9
        trail_from = min(p.trail_after_step, len(steps))
        if steps and has_runner and position.steps_filled >= trail_from and len(swings):
            f = data.frames[self.ROLE]
            level = float(f.low[swings[-1]] if d > 0 else f.high[swings[-1]])
            moves.append(StopMove(level - d * level * p.trail_buffer_pct / 100.0, "runner_trail"))
        return max(moves, key=lambda mv: mv.stop * d, default=None)
