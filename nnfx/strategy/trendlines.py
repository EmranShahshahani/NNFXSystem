"""Trendlines (Strategy Builder ticket 19, ADR 10 §23).

Video 25. A trendline is a rule, not a drawing:

* **Anchor from the second swing.** The first swing of the window is the impulse (the sharp
  peak or panic spike) and is never an anchor; lines start at the second confirmed swing.
* **Third touch.** Two points are a hypothesis. A line is *active* once at least
  ``min_touches`` (3) distinct swings sit on it, and not before the third is confirmed.
* **200-bar window.** Only swings of the last ``window`` bars take part, and a line expires
  ``window`` bars after its anchor. A longer trend belongs to a higher timeframe.
* **Slope bounds in ATR per bar.** The source limits the angle to 20-60 degrees, which only
  means something on a chart with a fixed scale. ``degrees_to_atr_per_bar`` converts them
  for a reference chart (``window`` bars across, ``VISIBLE_ATR`` ATR of price up, ``ASPECT``
  wide to high), giving about 0.073 and 0.346 ATR per bar. Below the minimum a line is a
  box edge, above the maximum a blow-off. ATR per bar is the same on any price scale.

A support line rises through swing lows (a falling one is no uptrend line); a resistance line
falls through swing highs. A close more than ``tol_atr`` ATR beyond a line breaks it for good
(wicks that pierce and recover are sweeps). Everything is causal: a swing counts from
``pivot_bars`` bars after its own bar.

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``trendline_bounce``  Setup. A bar touches an active line and closes back on the
                      trend's side: a long at support, a short at resistance
``trendline_break``   Setup. A close beyond an active line: a short through
                      support, a long through resistance
====================  ==========================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pydantic import Field, model_validator

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    Role,
    SetupBlock,
    SetupOutput,
    StrategyData,
    register,
)
from nnfx.strategy.series import pivots

VISIBLE_ATR = 20.0  # price range a 200-bar window fills on the reference chart, in ATR
ASPECT = 2.0  # that chart's width over its height


def degrees_to_atr_per_bar(
    degrees: float, *, window: int = 200, visible_atr: float = VISIBLE_ATR, aspect: float = ASPECT
) -> float:
    """The slope, in ATR per bar, that looks like ``degrees`` on the reference chart.

    The chart shows ``window`` bars across a width of ``aspect`` and ``visible_atr`` ATR up a
    height of 1, so a slope of ``s`` ATR per bar rises ``s / visible_atr`` while running
    ``aspect / window``: ``tan(angle) = s * window / (visible_atr * aspect)``.
    """
    return math.tan(math.radians(degrees)) * visible_atr * aspect / window


MIN_SLOPE = round(degrees_to_atr_per_bar(20), 3)  # 0.073
MAX_SLOPE = round(degrees_to_atr_per_bar(60), 3)  # 0.346


@dataclass(frozen=True)
class TrendSide:
    """One kind of line (support or resistance) on every bar of a timeframe.

    The line values are NaN where no active line stands. ``bounce`` marks a bar that touched
    the line and closed back on the trend's side, ``broke`` the bar that closed through it
    (the line is gone from that bar on, and ``value`` there is NaN; ``break_level`` is where
    it stood).
    """

    value: np.ndarray
    touches: np.ndarray  # int: swings on the line
    slope: np.ndarray  # ATR per bar, signed in price terms
    anchor: np.ndarray  # int: the bar of the line's first point (-1: none)
    bounce: np.ndarray
    broke: np.ndarray
    break_level: np.ndarray
    break_touches: np.ndarray


@dataclass(frozen=True)
class TrendTrack:
    support: TrendSide
    resistance: TrendSide


@dataclass(frozen=True)
class _Line:
    anchor: int  # bar of the first point
    y0: float  # price of the first point (in the mirrored space)
    slope: float  # price per bar, positive
    touches: tuple[int, ...]  # bars of the swings on it
    slope_atr: float

    def at(self, bar: int) -> float:
        return self.y0 + self.slope * (bar - self.anchor)


@dataclass(frozen=True)
class TrendRules:
    """The parameters that shape a line, as they travel together."""

    pivot_bars: int
    window: int
    min_slope: float
    max_slope: float
    tol_atr: float
    min_touches: int


def _build(
    pts: list[tuple[int, float]], close: np.ndarray, rng: np.ndarray, i: int, r: TrendRules
) -> list[_Line]:
    """Every active line through the swings confirmed by bar ``i`` (mirrored: rising lows)."""
    recent = [p for p in pts if p[0] > i - r.window]
    eligible = recent[1:]  # the first swing is the impulse, never an anchor
    out: list[_Line] = []
    tolerance = r.tol_atr * np.where(np.isfinite(rng), rng, np.inf)
    for ai, (a_bar, a_y) in enumerate(eligible[:-1]):
        for b_bar, b_y in eligible[ai + 1 :]:
            slope = (b_y - a_y) / (b_bar - a_bar)
            if slope <= 0:
                continue
            on = [a_bar]
            for t_bar, t_y in eligible[ai + 1 :]:
                scale = rng[min(t_bar + r.pivot_bars, i)]
                if not np.isfinite(scale):
                    continue
                if abs(t_y - (a_y + slope * (t_bar - a_bar))) <= r.tol_atr * scale:
                    on.append(t_bar)
            scale = rng[min(on[-1] + r.pivot_bars, i)]
            if len(on) < r.min_touches or b_bar not in on or not np.isfinite(scale) or scale <= 0:
                continue
            slope_atr = slope / float(scale)
            if not r.min_slope <= slope_atr <= r.max_slope:
                continue
            span = np.arange(a_bar, i + 1)
            if np.any(
                close[a_bar : i + 1] < a_y + slope * (span - a_bar) - tolerance[a_bar : i + 1]
            ):
                continue  # already broken
            out.append(_Line(a_bar, a_y, slope, tuple(on), slope_atr))
    return out


def _track_side(
    pts: list[tuple[int, float]],
    low_y: np.ndarray,
    close_y: np.ndarray,
    rng: np.ndarray,
    r: TrendRules,
    *,
    sign: float,
) -> TrendSide:
    """One side, in the mirrored space where the line rises under the price (``sign`` maps back)."""
    n = len(close_y)
    value = np.full(n, np.nan)
    touches = np.zeros(n, dtype="int64")
    slope = np.full(n, np.nan)
    anchor = np.full(n, -1, dtype="int64")
    bounce = np.zeros(n, dtype=bool)
    broke = np.zeros(n, dtype=bool)
    break_level = np.full(n, np.nan)
    break_touches = np.zeros(n, dtype="int64")
    lines: list[_Line] = []
    ptr, seen = 0, 0
    confirmed: list[tuple[int, float]] = []
    for i in range(n):
        while ptr < len(pts) and pts[ptr][0] + r.pivot_bars <= i:
            confirmed.append(pts[ptr])
            ptr += 1
        if len(confirmed) != seen:
            seen = len(confirmed)
            lines = _build(confirmed, close_y, rng, i, r)
        tol = r.tol_atr * rng[i] if np.isfinite(rng[i]) else np.inf
        alive = [ln for ln in lines if i - ln.anchor <= r.window]
        broken = [ln for ln in alive if close_y[i] < ln.at(i) - tol]
        lines = [ln for ln in alive if ln not in broken]
        if broken:
            best = max(broken, key=lambda ln: (len(ln.touches), ln.touches[-1]))
            broke[i] = True
            break_level[i] = sign * best.at(i)
            break_touches[i] = len(best.touches)
        if lines:
            best = max(lines, key=lambda ln: (len(ln.touches), ln.touches[-1]))
            v = best.at(i)
            value[i] = sign * v
            touches[i] = len(best.touches)
            slope[i] = sign * best.slope_atr
            anchor[i] = best.anchor
            bounce[i] = bool(low_y[i] <= v + tol and close_y[i] >= v)
    return TrendSide(value, touches, slope, anchor, bounce, broke, break_level, break_touches)


def track_trendlines(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    rng: np.ndarray,
    *,
    pivot_bars: int,
    window: int,
    min_slope: float,
    max_slope: float,
    tol_atr: float,
    min_touches: int,
) -> TrendTrack:
    """The support and resistance lines of one timeframe, as of every bar."""
    swing_lows, swing_highs = pivots(low, high, pivot_bars, pivot_bars)
    kw = TrendRules(pivot_bars, window, min_slope, max_slope, tol_atr, min_touches)
    support = _track_side(
        [(int(k), float(low[k])) for k in swing_lows], low, close, rng, kw, sign=1.0
    )
    # Resistance mirrors the price: a falling line through highs is a rising line through -highs.
    resistance = _track_side(
        [(int(k), float(-high[k])) for k in swing_highs], -high, -close, rng, kw, sign=-1.0
    )
    return TrendTrack(support, resistance)


class TrendParams(BlockParams):
    timeframe: Role = Field("mwc", description="تایم‌فریمی که خط روند روی آن رسم می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف")
    window: int = Field(200, ge=10, description="پنجرهٔ برازش خط، تعداد کندل (جزوه: ۲۰۰)")
    min_slope: float = Field(
        MIN_SLOPE, gt=0, description="کمترین شیب (ATR در هر کندل؛ معادل ۲۰ درجه)"
    )
    max_slope: float = Field(
        MAX_SLOPE, gt=0, description="بیشترین شیب (ATR در هر کندل؛ معادل ۶۰ درجه)"
    )
    tol_atr: float = Field(0.3, gt=0, description="فاصلهٔ مجاز لمس از خط، و شکست با کلوز (ATR)")
    min_touches: int = Field(3, ge=3, description="کمترین لمس برای فعال‌شدن خط (جزوه: ۳)")

    @model_validator(mode="after")
    def _ordered(self) -> TrendParams:
        if self.min_slope >= self.max_slope:
            raise ValueError("کمترین شیب باید کوچک‌تر از بیشترین شیب باشد")
        return self


def trend_track(data: StrategyData, p: TrendParams) -> TrendTrack:
    """The block's trendlines on its timeframe (cached per parameter set)."""
    role = p.timeframe
    key = (
        *("trendlines", role, p.pivot_bars, p.window, p.min_slope, p.max_slope),
        *(p.tol_atr, p.min_touches),
    )

    def make() -> TrendTrack:
        f = data.frames[role]
        return track_trendlines(
            f.high, f.low, f.close, data.atr(role), pivot_bars=p.pivot_bars, window=p.window,
            min_slope=p.min_slope, max_slope=p.max_slope, tol_atr=p.tol_atr,
            min_touches=p.min_touches,
        )  # fmt: skip

    return data.memo(key, make)


def _setup_output(
    data: StrategyData,
    role: str,
    d: np.ndarray,
    trigger: np.ndarray,
    invalidation: np.ndarray,
    stop: np.ndarray,
    level: np.ndarray,
    touches: np.ndarray,
    tag: str,
) -> SetupOutput:
    """Role-bar arrays placed on the LWC bars where each role bar closes."""
    nan = np.nan
    on = d != 0
    d_lwc = data.on_close(role, d.astype("int8"), 0).astype("int8")
    meta = {
        "level": data.on_close(role, np.where(on, level, nan), nan),
        "touches": data.on_close(role, np.where(on, touches, nan).astype(float), nan),
    }
    return SetupOutput(
        d_lwc,
        data.on_close(role, np.where(on, trigger, nan), nan),
        data.on_close(role, np.where(on, invalidation, nan), nan),
        data.on_close(role, np.where(on, stop, nan), nan),
        {tag: d_lwc != 0},
        meta,
    )


@register
class TrendlineBounce(SetupBlock[TrendParams]):
    """A touch of an active trendline that holds (video 25).

    On a rising support line (three or more touches, slope within the bounds) a bar whose low
    reaches the line (within ``tol_atr`` ATR) and closes on or above it is a long; on a
    falling resistance line a bar whose high reaches it and closes on or below it is a
    short. Both on one bar make no candidate. Trigger: the bar's high (low); invalidation and
    stop: its far side. Read when a ``timeframe`` bar closes.
    """

    kind = BlockKind.SETUP
    type = "trendline_bounce"
    title_fa = "برگشت از خط روند"
    sources = ("tcp-blueprint 03: video 25 (trendline construction geometry)",)
    Params = TrendParams

    def compute(self, data: StrategyData) -> SetupOutput:
        role = self.p.timeframe
        f, t = data.frames[role], trend_track(data, self.p)
        up, dn = t.support.bounce, t.resistance.bounce
        d = np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0)).astype("int8")
        trigger = np.where(d > 0, f.high, f.low)
        far = np.where(d > 0, f.low, f.high)
        level = np.where(d > 0, t.support.value, t.resistance.value)
        touches = np.where(d > 0, t.support.touches, t.resistance.touches)
        return _setup_output(data, role, d, trigger, far, far.copy(), level, touches, "trendline")


@register
class TrendlineBreak(SetupBlock[TrendParams]):
    """A close through an active trendline (video 25).

    A bar closing more than ``tol_atr`` ATR under a support line is a short; one closing over
    a resistance line is a long. A wick that pierces and recovers breaks nothing. Trigger: the
    bar's low (high); invalidation and stop: the line where it broke. A line that broke is gone,
    so each line gives one break.
    """

    kind = BlockKind.SETUP
    type = "trendline_break"
    title_fa = "شکست خط روند"
    sources = ("tcp-blueprint 03: video 25 (trendline invalidation)",)
    Params = TrendParams

    def compute(self, data: StrategyData) -> SetupOutput:
        role = self.p.timeframe
        f, t = data.frames[role], trend_track(data, self.p)
        up, dn = t.resistance.broke, t.support.broke
        d = np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0)).astype("int8")
        trigger = np.where(d > 0, f.high, f.low)
        level = np.where(d > 0, t.resistance.break_level, t.support.break_level)
        touches = np.where(d > 0, t.resistance.break_touches, t.support.break_touches)
        return _setup_output(
            data, role, d, trigger, level, level.copy(), level, touches, "trendline_break"
        )
