"""Fibonacci retracements, extensions and the 0.382 reclaim (Strategy Builder ticket 19, ADR 10 §23).

Videos 76-81. Fibonacci is a measuring tool, never a trigger on its own:

* **Anchored on structure.** A leg runs from a confirmed swing (the pivot that started the
  impulse: the lowest swing low since the previous swing high for an up-leg, mirrored for a
  down-leg) to the confirmed swing that ended it. Never an intra-range wick, never an impulse
  that is still extending: the end of the leg counts only once its swing is confirmed, that
  is ``pivot_bars`` bars after it (the objective reaction).
* **Log scale.** Ratios are measured on ``ln(price)``, so a 38.2% pullback is the same
  proportion at any price and on any price scale.
* **One leg at a time.** A leg lives until a close goes beyond its start (more than 100%
  retraced). A higher high (lower low) confirmed in its direction moves its end and forgets
  its retracement low; retracement lows inside the leg become the ``C`` point.
* **Extensions** project the leg from ``C``, the validated retracement: 1.0 is the equal move,
  then 1.272, 1.618 and 2.0.
* **Confluence.** A Fibonacci level counts only with other factors on the same price (within
  ``tol_atr`` ATR): a horizontal level, the SMA 25 and the SMA 99 (the order-book wall joins
  with ticket 21). A lone Fibonacci line makes no candidate.

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``fib_reclaim``       Setup. A wick through the 0.382 retracement that closes back on
                      the trend's side: the sweep-and-reclaim long (short mirrored)
``fib_confluence``    Confirmation. The setup sits on a retracement level backed by
                      other factors
====================  ==========================================================

``ProfitChain.fib_target`` closes the remainder at an extension (see ``library``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pydantic import Field

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
from nnfx.strategy.series import pivots

RETRACEMENTS = (0.382, 0.5, 0.618, 0.786)
EXTENSIONS = (1.0, 1.272, 1.618, 2.0)


def retracement(a: float, b: float, ratio: float) -> float:
    """The price ``ratio`` of the way back from ``b`` toward ``a``, on a log scale."""
    return math.exp(math.log(b) - ratio * (math.log(b) - math.log(a)))


def extension(a: float, b: float, c: float, ratio: float) -> float:
    """``ratio`` times the leg ``a``-``b``, projected from the retracement ``c`` (log scale)."""
    return math.exp(math.log(c) + ratio * (math.log(b) - math.log(a)))


@dataclass(frozen=True)
class FibTrack:
    """The leg in force on every bar of a timeframe (NaN / 0 where there is none)."""

    direction: np.ndarray  # int8: 1 an up-leg (retraces down), -1 a down-leg
    a: np.ndarray  # the leg's start
    b: np.ndarray  # the leg's end
    c: np.ndarray  # the retracement extreme since b (NaN until one is confirmed)


def track_fib(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    rng: np.ndarray,
    *,
    pivot_bars: int,
    min_impulse_atr: float,
) -> FibTrack:
    """Fibonacci legs on confirmed swings only (see the module docstring)."""
    n = len(close)
    swing_lows, swing_highs = pivots(low, high, pivot_bars, pivot_bars)
    events: dict[int, list[tuple[int, float, int]]] = {}
    for k in swing_lows:
        events.setdefault(int(k) + pivot_bars, []).append((int(k), float(low[k]), -1))
    for k in swing_highs:
        events.setdefault(int(k) + pivot_bars, []).append((int(k), float(high[k]), 1))
    direction = np.zeros(n, dtype="int8")
    a_out, b_out, c_out = (np.full(n, np.nan) for _ in range(3))
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    leg: list[float] | None = None  # [direction, a, b, c, bar of b]
    for i in range(n):
        if leg is not None and (close[i] - leg[1]) * leg[0] < 0:
            leg = None  # more than 100% retraced
        for bar, price, kind in sorted(events.get(i, ()), key=lambda e: e[0]):
            (highs if kind > 0 else lows).append((bar, price))
            if leg is None:
                leg = _start(highs, lows, kind, bar, price, rng[i], min_impulse_atr, close[i])
                continue
            d = leg[0]
            if kind == d and (price - leg[2]) * d > 0:
                leg[2], leg[3], leg[4] = price, math.nan, bar  # the impulse went on
            elif kind == -d and bar > leg[4] and (price - leg[1]) * d > 0:
                leg[3] = price if math.isnan(leg[3]) else (min if d > 0 else max)(leg[3], price)
        if leg is not None:
            direction[i], a_out[i], b_out[i], c_out[i] = int(leg[0]), leg[1], leg[2], leg[3]
    return FibTrack(direction, a_out, b_out, c_out)


def _start(
    highs: list[tuple[int, float]],
    lows: list[tuple[int, float]],
    kind: int,
    bar: int,
    price: float,
    scale: float,
    min_impulse_atr: float,
    close: float,
) -> list[float] | None:
    """A leg ending at the swing just confirmed, or None."""
    if not np.isfinite(scale) or scale <= 0:
        return None
    mine, other = (highs, lows) if kind > 0 else (lows, highs)
    previous = max((k for k, _ in mine if k < bar), default=-1)  # the last same-kind swing
    start = [y for k, y in other if previous < k < bar]
    if not start:
        return None
    a = min(start) if kind > 0 else max(start)
    if a <= 0 or price <= 0 or (price - a) * kind < min_impulse_atr * scale:
        return None
    if (close - a) * kind <= 0:
        return None  # already beyond its start
    return [float(kind), a, price, math.nan, float(bar)]


class FibParams(BlockParams):
    timeframe: Role = Field("mwc", description="تایم‌فریمی که موج و فیبوناچی روی آن رسم می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف")
    min_impulse_atr: float = Field(3.0, gt=0, description="کمترین طول موج ایمپالس (ATR)")
    tol_atr: float = Field(0.3, gt=0, description="فاصلهٔ مجاز عوامل هم‌پوشان از سطح فیبو (ATR)")
    min_confluence: int = Field(
        2, ge=0, description="دست‌کم این‌قدر عامل دیگر روی سطح فیبو (۰: بدون شرط؛ جزوه: ۲)"
    )
    level_pivot_bars: int = Field(2, ge=1, description="سطح افقی: پیوت")
    level_tolerance_atr: float = Field(0.5, gt=0, description="سطح افقی: فاصلهٔ لمس‌ها (ATR)")
    level_half_life: float = Field(100.0, gt=0, description="سطح افقی: نیمه‌عمر وزن تازگی")
    level_min_weight: float = Field(0.3, ge=0, description="سطح افقی: کمترین وزن تازگی")
    sma_fast: int = Field(25, ge=2, description="میانگین پویای اول (جزوه: ۲۵)")
    sma_slow: int = Field(99, ge=2, description="میانگین پویای دوم (جزوه: ۹۹)")


def fib_track(data: StrategyData, role: str, pivot_bars: int, min_impulse_atr: float) -> FibTrack:
    """The Fibonacci legs of ``role`` (cached)."""

    def make() -> FibTrack:
        f = data.frames[role]
        return track_fib(
            f.high, f.low, f.close, data.atr(role), pivot_bars=pivot_bars,
            min_impulse_atr=min_impulse_atr,
        )  # fmt: skip

    return data.memo(("fib", role, pivot_bars, min_impulse_atr), make)


def confluence(data: StrategyData, p: FibParams, i: int, price: float) -> list[str]:
    """The other factors standing on ``price`` at ``timeframe`` bar ``i``."""
    role = p.timeframe
    scale = data.atr(role)[i]
    if not np.isfinite(scale):
        return []
    tol = p.tol_atr * float(scale)
    found: list[str] = []
    book = data.levels(
        role, pivot_bars=p.level_pivot_bars, tolerance_atr=p.level_tolerance_atr,
        half_life=p.level_half_life, max_age=1000,
    )  # fmt: skip
    if any(abs(lv.price - price) <= tol for lv in book.at(i, min_weight=p.level_min_weight)):
        found.append("level")
    for n in (p.sma_fast, p.sma_slow):
        line = data.sma(role, n)[i]
        if np.isfinite(line) and abs(float(line) - price) <= tol:
            found.append(f"sma{n}")
    return found


class FibReclaimParams(FibParams):
    ratio: float = Field(0.382, gt=0, lt=1, description="سطح بازگشت فیبو که شکار و بازپس‌گیری می‌شود")


@register
class FibReclaim(SetupBlock[FibReclaimParams]):
    """The 0.382 sweep and reclaim (video 81): never a limit order at the level.

    In an up-leg, a bar whose low wicks under the ``ratio`` retracement and whose close is
    back on or above it has swept the liquidity below the level and reclaimed it: a long,
    straight away rather than at the leg's high. A down-leg mirrors it. The level is on a log
    scale. With ``min_confluence`` (default 2) the level must also stand on that many other
    factors (a horizontal level, SMA 25, SMA 99), so a lone Fibonacci line makes none. Trigger:
    the bar's high (low); invalidation and stop: its far side, the sweep's extreme.
    """

    kind = BlockKind.SETUP
    type = "fib_reclaim"
    title_fa = "بازپس‌گیری سطح ۰٫۳۸۲ فیبوناچی (فیک‌اوت)"
    sources = ("tcp-blueprint 09: video 81 (the 0.382 structural fakeout trigger)",)
    Params = FibReclaimParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p, role = self.p, self.p.timeframe
        f, t = data.frames[role], fib_track(data, role, self.p.pivot_bars, self.p.min_impulse_atr)
        n = len(f)
        d = np.zeros(n, dtype="int8")
        level = np.full(n, np.nan)
        for i in np.flatnonzero(t.direction):
            leg = int(t.direction[i])
            price = retracement(float(t.a[i]), float(t.b[i]), p.ratio)
            swept = f.low[i] < price <= f.close[i] if leg > 0 else f.close[i] <= price < f.high[i]
            if swept and len(confluence(data, p, int(i), price)) >= p.min_confluence:
                d[i], level[i] = leg, price
        trigger = np.where(d > 0, f.high, f.low)
        far = np.where(d > 0, f.low, f.high)
        on = d != 0
        d_lwc = data.on_close(role, d, 0).astype("int8")
        nan = np.nan

        def place(x: np.ndarray) -> np.ndarray:
            return data.on_close(role, np.where(on, x, nan), nan)

        return SetupOutput(
            d_lwc, place(trigger), place(far), place(far), {"fib_reclaim": d_lwc != 0},
            {"level": place(level)},
        )  # fmt: skip


class FibConfluenceParams(ConfirmationParams, FibParams):
    ratios: list[float] = Field(
        default_factory=lambda: [0.382, 0.5, 0.618],
        description="سطح‌های بازگشت که حساب می‌شوند (۰٫۳۸۲ و ۰٫۵ و ۰٫۶۱۸؛ ۰٫۷۸۶ عمیق‌ترین)",
    )


@register
class FibConfluence(ConfirmationBlock[FibConfluenceParams]):
    """The setup stands on a Fibonacci level backed by other factors (video 80).

    The leg in force must run with the trade (an up-leg for longs). Some retracement level of
    ``ratios`` must fall in the setup's range (invalidation to trigger, widened by
    ``tol_atr`` ATR) and have at least ``min_confluence`` other factors on it: a horizontal
    level, the SMA 25, the SMA 99. A Fibonacci line alone is ignored. ``na`` until a leg exists.
    """

    kind = BlockKind.CONFIRMATION
    type = "fib_confluence"
    title_fa = "هم‌پوشانی فیبوناچی با سطح/میانگین"
    sources = ("tcp-blueprint 08: video 80 (structural confluence scoring)",)
    Params = FibConfluenceParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, role = self.p, self.p.timeframe
        i = int(data.positions[role][candidate.bar])
        if i < 0:
            return CheckResult("na", f"{role} history is too short")
        t = fib_track(data, role, p.pivot_bars, p.min_impulse_atr)
        leg = int(t.direction[i])
        if leg == 0:
            return CheckResult("na", f"no confirmed {role} leg to measure")
        if leg != candidate.direction:
            return CheckResult("fail", "the Fibonacci leg runs against the trade")
        scale = data.atr(role)[i]
        if not np.isfinite(scale):
            return CheckResult("na", f"{role} ATR is not ready")
        tol = p.tol_atr * float(scale)
        lo, hi = sorted((candidate.invalidation, candidate.trigger))
        best: tuple[float, list[str]] | None = None
        for r in p.ratios:
            price = retracement(float(t.a[i]), float(t.b[i]), r)
            if lo - tol <= price <= hi + tol:
                found = confluence(data, p, i, price)
                if best is None or len(found) > len(best[1]):
                    best = (r, found)
        if best is None:
            return CheckResult("fail", "no Fibonacci retracement level in the setup's range")
        ratio, found = best
        if len(found) >= p.min_confluence:
            return CheckResult(
                "pass", f"fib {ratio:g} with {', '.join(found) or 'no other factor'}"
            )
        return CheckResult(
            "fail", f"fib {ratio:g} stands alone: {len(found)} of {p.min_confluence} other factors"
        )
