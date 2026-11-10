"""Trend health: signs that a trend is running out (Strategy Builder ticket 17, ADR 10 §21).

Videos 22, 23, 27 and 67. A trend in direction ``d`` shows *weakness* when its legs, bars
or channel stop looking like a healthy impulse. Six metrics, each judged per bar of one
role from that bar's close and the bars before it:

=================  ==========================================================================
Metric             Weak when (an uptrend; a downtrend mirrors it)
=================  ==========================================================================
``amplitude``      the last ``amp_legs`` impulse legs shrink, each smaller than the one before
                   and the last under ``amp_shrink`` x the first (10% -> 6% -> 2%)
``duration``       the pullback took as long as the impulse before it (``dur_correction``), or
                   the last impulse took ``dur_slowdown`` x as many bars as the one before
``body``           price advances while the real-body share of the range averages under
                   ``body_floor`` and below the share before
``close_placement``  price advances while the closes sit lower in their candles, bar after bar
``color``          price advances while opposite-coloured candles are ``color_max_opposite`` or
                   more of the last ``color_window`` bars
``channel``        a close pierces the over-side of the regression channel fitted before it
=================  ==========================================================================

The channel is the least-squares line of the last ``channel_window`` closes with parallel
bands ``channel_width`` standard deviations away (a drawn trendline channel is ticket 19).

Swings are read only once confirmed (``pivot_bars`` later) and consecutive swings of the same
kind collapse to the more extreme, so legs alternate. Everything is causal.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal, get_args

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import Field, field_validator, model_validator

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    ContextBlock,
    ContextOutput,
    Role,
    StrategyData,
    register,
)
from nnfx.strategy.series import pivots

Metric = Literal["amplitude", "duration", "body", "close_placement", "color", "channel"]
METRICS: tuple[Metric, ...] = get_args(Metric)


class HealthParams(BlockParams):
    """The thresholds of the six metrics (shared by ``trend_health`` and the Profit Chain)."""

    metrics: list[Metric] = Field(
        default_factory=lambda: list(METRICS), description="معیارهای سلامت روند که شمرده می‌شوند"
    )
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف")
    amp_legs: int = Field(3, ge=2, description="دامنه: تعداد پای‌های ضربه‌ای که باید کوچک شوند")
    amp_shrink: float = Field(
        0.7, gt=0, lt=1, description="دامنه: آخرین پا حداکثر این کسر از اولین"
    )
    dur_correction: float = Field(1.0, gt=0, description="زمان: اصلاح دست‌کم این ضریبِ زمان ضربه")
    dur_slowdown: float = Field(2.0, gt=1, description="زمان: ضربهٔ آخر دست‌کم این ضریبِ ضربهٔ قبل")
    body_bars: int = Field(3, ge=1, description="بدنه به دامنه: پنجرهٔ میانگین (کندل)")
    body_floor: float = Field(0.3, gt=0, lt=1, description="بدنه به دامنه: میانگین زیر این مقدار")
    close_bars: int = Field(3, ge=2, description="جای کلوز: تعداد کندل‌های پیاپی با کلوز پایین‌تر")
    close_limit: float = Field(
        0.5, gt=0, le=1, description="جای کلوز: آخرین کلوز زیر این بخش از کندل"
    )
    color_window: int = Field(20, ge=4, description="نسبت رنگ: پنجرهٔ کندل‌ها")
    color_max_opposite: float = Field(
        0.5, gt=0, le=1, description="نسبت رنگ: سهم کندل‌های رنگ مخالف دست‌کم این مقدار"
    )
    channel_window: int = Field(50, ge=10, description="کانال: تعداد کندل‌های برازش رگرسیون")
    channel_width: float = Field(2.0, gt=0, description="کانال: فاصلهٔ باندها (انحراف معیار)")
    hold_bars: int = Field(
        3,
        ge=1,
        description="هشدار معیارهای تک‌کندلی (بدنه، جای کلوز، رنگ، کانال) این‌قدر کندل می‌ماند",
    )

    @field_validator("metrics")
    @classmethod
    def _some_metrics(cls, v: list[Metric]) -> list[Metric]:
        if not v or len(set(v)) != len(v):
            raise ValueError("دست‌کم یک معیار، و بدون تکرار")
        return v

    def key(self) -> tuple[float | int, ...]:
        """The numbers the series depend on (the cache key; ``metrics`` only selects)."""
        return (
            self.pivot_bars, self.amp_legs, self.amp_shrink, self.dur_correction,
            self.dur_slowdown, self.body_bars, self.body_floor, self.close_bars,
            self.close_limit, self.color_window, self.color_max_opposite,
            self.channel_window, self.channel_width, self.hold_bars,
        )  # fmt: skip


# ------------------------------------------------------------------ swings
@dataclass(frozen=True)
class _Swing:
    bar: int
    kind: int  # 1 swing high, -1 swing low
    price: float


def _leg_weakness(zz: list[_Swing], kind: int, p: HealthParams) -> tuple[bool, bool]:
    """(amplitude weak, duration weak) of the legs ending in swings of ``kind`` (1: up legs)."""
    legs: list[tuple[int, int, float]] = []  # newest first: (start bar, end bar, amplitude)
    need = max(p.amp_legs, 2)
    for j in range(len(zz) - 1, 0, -1):
        if zz[j].kind == kind:
            legs.append((zz[j - 1].bar, zz[j].bar, (zz[j].price - zz[j - 1].price) * kind))
            if len(legs) == need:
                break
    amp = False
    if len(legs) >= p.amp_legs:
        a = [leg[2] for leg in reversed(legs[: p.amp_legs])]  # oldest first
        amp = all(y < x for x, y in pairwise(a)) and a[-1] <= p.amp_shrink * a[0]
    dur = False
    if legs:
        start, end, _ = legs[0]
        if zz[-1].kind == -kind and zz[-2].bar == end:  # the pullback after it is complete
            dur = (zz[-1].bar - end) >= p.dur_correction * (end - start)
        if len(legs) >= 2:
            dur = dur or (end - start) >= p.dur_slowdown * (legs[1][1] - legs[1][0])
    return amp, dur


def swing_weakness(
    high: np.ndarray, low: np.ndarray, p: HealthParams
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per bar: amplitude and duration weakness of up legs, then of down legs."""
    n, w = len(high), p.pivot_bars
    lows, highs = pivots(low, high, w, w)
    events = sorted([(int(k), 1) for k in highs] + [(int(k), -1) for k in lows])
    out = np.zeros((4, n), dtype=bool)
    zz: list[_Swing] = []
    state = (False, False, False, False)
    ptr = 0
    for m in range(n):
        changed = False
        while ptr < len(events) and events[ptr][0] + w <= m:
            k, kind = events[ptr]
            ptr += 1
            price = float(high[k] if kind > 0 else low[k])
            if zz and zz[-1].kind == kind:
                if (price - zz[-1].price) * kind > 0:
                    zz[-1] = _Swing(k, kind, price)  # a more extreme swing of the same kind
            else:
                zz.append(_Swing(k, kind, price))
            changed = True
        if changed and len(zz) >= 2:
            state = (*_leg_weakness(zz, 1, p), *_leg_weakness(zz, -1, p))
        out[:, m] = state
    return out[0], out[2], out[1], out[3]


# ---------------------------------------------------------- per-bar metrics
def _ahead(close: np.ndarray, bars: int) -> tuple[np.ndarray, np.ndarray]:
    """(advancing, declining): the close against the close ``bars`` bars ago."""
    prev = pd.Series(close).shift(bars).to_numpy()
    with np.errstate(invalid="ignore"):
        return np.asarray(close > prev), np.asarray(close < prev)


def _share(num: np.ndarray, rng: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(np.where(rng > 0, num / rng, np.nan))


def body_weakness(
    o: np.ndarray, h: np.ndarray, lo: np.ndarray, c: np.ndarray, p: HealthParams
) -> tuple[np.ndarray, np.ndarray]:
    share = pd.Series(_share(np.abs(c - o), h - lo))
    recent = share.rolling(p.body_bars, min_periods=p.body_bars).mean()
    before = recent.shift(p.body_bars)
    with np.errstate(invalid="ignore"):
        decayed = ((recent < p.body_floor) & (recent < before)).to_numpy()
    up, down = _ahead(c, p.body_bars)
    return up & decayed, down & decayed


def close_weakness(
    h: np.ndarray, lo: np.ndarray, c: np.ndarray, p: HealthParams
) -> tuple[np.ndarray, np.ndarray]:
    def worsening(place: np.ndarray) -> np.ndarray:
        s = pd.Series(place)
        ok = np.ones(len(place), dtype=bool)
        for k in range(p.close_bars - 1):
            with np.errstate(invalid="ignore"):
                ok &= (s.shift(k) < s.shift(k + 1)).to_numpy()
        with np.errstate(invalid="ignore"):
            return ok & (place < p.close_limit)

    up, down = _ahead(c, p.close_bars)
    return (
        up & worsening(_share(c - lo, h - lo)),  # an up bar closes high in its range
        down & worsening(_share(h - c, h - lo)),
    )


def color_weakness(o: np.ndarray, c: np.ndarray, p: HealthParams) -> tuple[np.ndarray, np.ndarray]:
    w = p.color_window
    red = pd.Series((c < o).astype(float)).rolling(w, min_periods=w).mean().to_numpy()
    green = pd.Series((c > o).astype(float)).rolling(w, min_periods=w).mean().to_numpy()
    up, down = _ahead(c, w)
    with np.errstate(invalid="ignore"):
        return up & (red >= p.color_max_opposite), down & (green >= p.color_max_opposite)


def channel_weakness(c: np.ndarray, p: HealthParams) -> tuple[np.ndarray, np.ndarray]:
    """A close beyond the regression channel fitted on the bars *before* it, projected forward."""
    w, n = p.channel_window, len(c)
    up, down = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    if n < w + 1:
        return up, down
    x = np.arange(w) - (w - 1) / 2.0
    wins = sliding_window_view(c, w)  # row r = bars r .. r + w - 1
    ym = wins.mean(axis=1)
    slope = wins @ x / float(x @ x)
    line = ym[:, None] + slope[:, None] * x[None, :]
    sd = np.sqrt(((wins - line) ** 2).mean(axis=1))
    centre = ym + slope * x[-1] + slope  # the line one bar past the window's last bar
    with np.errstate(invalid="ignore"):
        over = c[w:] > centre[:-1] + p.channel_width * sd[:-1]
        under = c[w:] < centre[:-1] - p.channel_width * sd[:-1]
        up[w:] = over & (slope[:-1] > 0)
        down[w:] = under & (slope[:-1] < 0)
    return up, down


def _hold(flags: np.ndarray, bars: int) -> np.ndarray:
    """A single-bar flag stays up for ``bars`` bars, so signals of different bars can coincide."""
    held: np.ndarray = (
        pd.Series(flags).rolling(bars, min_periods=1).max().fillna(0).astype(bool).to_numpy()
    )
    return held


@dataclass(frozen=True)
class Weakness:
    """Per role bar and metric: the up- and down-trend shows this weakness."""

    up: dict[str, np.ndarray]
    down: dict[str, np.ndarray]

    def signals(self, m: int, d: int, metrics: list[Metric]) -> list[str]:
        """The metrics (of ``metrics``) flagging the trend in direction ``d`` at role bar ``m``."""
        side = self.up if d > 0 else self.down
        return [k for k in metrics if m >= 0 and side[k][m]]


def weakness(data: StrategyData, role: str, p: HealthParams) -> Weakness:
    """All six metrics on ``role``'s bars, cached per thresholds."""

    def make() -> Weakness:
        f = data.frames[role]
        amp_u, amp_d, dur_u, dur_d = swing_weakness(f.high, f.low, p)
        body = body_weakness(f.open, f.high, f.low, f.close, p)
        place = close_weakness(f.high, f.low, f.close, p)
        colour = color_weakness(f.open, f.close, p)
        chan = channel_weakness(f.close, p)
        h = p.hold_bars
        return Weakness(
            {"amplitude": amp_u, "duration": dur_u, "body": _hold(body[0], h),
             "close_placement": _hold(place[0], h), "color": _hold(colour[0], h),
             "channel": _hold(chan[0], h)},
            {"amplitude": amp_d, "duration": dur_d, "body": _hold(body[1], h),
             "close_placement": _hold(place[1], h), "color": _hold(colour[1], h),
             "channel": _hold(chan[1], h)},
        )  # fmt: skip

    return data.memo(("health", role, p.key()), make)


# ------------------------------------------------------------------- block
class TrendHealthParams(HealthParams):
    role: Role = Field("mwc", description="تایم‌فریمی که سلامت روندش سنجیده می‌شود")
    min_signals: int = Field(
        2, ge=1, description="ورود هم‌جهت با روند وقتی بسته می‌شود که دست‌کم این‌قدر معیار هشدار دهند"
    )

    @model_validator(mode="after")
    def _reachable(self) -> TrendHealthParams:
        if self.min_signals > len(self.metrics):
            raise ValueError("min_signals از تعداد معیارهای انتخاب‌شده بیشتر است")
        return self


@register
class TrendHealth(ContextBlock[TrendHealthParams]):
    """Halts continuation entries in a trend that shows ``min_signals`` or more weaknesses.

    Per bar of ``role``: the uptrend is unhealthy when enough of the selected metrics
    flag it, and longs are disabled; the downtrend mirrors it for shorts. A trade the
    other way is untouched (a failing trend is where a reversal starts). The flags
    ``health_up`` / ``health_down`` count the signals per bar for the record. The Profit
    Chain's ``health_exit`` tightens the stop of an open trade on the same metrics.
    """

    kind = BlockKind.CONTEXT
    type = "trend_health"
    title_fa = "سلامت روند"
    sources = (
        "tcp-blueprint 03: videos 22, 23 (swing amplitude, body-to-range, channel excursion)",
        "tcp-blueprint 03: video 27 (candle colour ratio); 07: video 67",
    )
    Params = TrendHealthParams

    @staticmethod
    def _count(side: dict[str, np.ndarray], metrics: list[Metric]) -> np.ndarray:
        """How many of ``metrics`` flag each bar."""
        total: np.ndarray = np.sum([side[k] for k in metrics], axis=0, dtype="int16")
        return total

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        w = weakness(data, p.role, p)
        up = data.aligned(p.role, self._count(w.up, p.metrics), 0)
        down = data.aligned(p.role, self._count(w.down, p.metrics), 0)
        return ContextOutput(
            long_ok=up < p.min_signals,
            short_ok=down < p.min_signals,
            flags={"health_up": up, "health_down": down},
        )
