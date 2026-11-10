"""Sessions in UTC (Strategy Builder ticket 18, ADR 10 §22).

Video 58. Asia 00:00-08:00, London 07:00-16:00 and New York 12:00-21:00, all in UTC. UTC has
no daylight saving, so a window is the same instant range all year (the venues' local
clocks move, the blueprint's table does not); nothing here reads a local time zone.

A bar is labelled by its close (``bars.py``), which is also the instant the next bar opens:
"may I place an order now" is judged by the label's hour, "which session did this bar trade
in" by the bar's open (label minus its duration).

====================  ==========================================================
Block                 What it does
====================  ==========================================================
``session_filter``    Context. Entries only in the chosen sessions and never in the
                      21:00-00:00 UTC gap between the US close and the Asia open
``session_regime``    Context. The session-correlation regimes: London and New York
                      trending the same way set a continuation bias until the next
                      London close; a London that failed to trend moves the day's
                      momentum to the US open window
====================  ==========================================================
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from nnfx.data.bars import TIMEFRAMES, ns
from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    ContextBlock,
    ContextOutput,
    StrategyData,
    register,
)

Session = Literal["asia", "london", "new_york"]
SESSION_HOURS: dict[str, tuple[float, float]] = {
    "asia": (0.0, 8.0),
    "london": (7.0, 16.0),
    "new_york": (12.0, 21.0),
}
HOUR = pd.Timedelta(hours=1)
DAY_NS = 24 * HOUR.value


def label_hours(data: StrategyData) -> np.ndarray:
    """The UTC hour of day (0 <= h < 24, fractional) of each LWC bar's label, its close."""
    idx = data.base.index
    return np.asarray(idx.hour + idx.minute / 60.0, dtype=float)


def in_hours(hours: np.ndarray, start: float, end: float) -> np.ndarray:
    """Whether each hour is in [start, end); ``start`` > ``end`` wraps past midnight."""
    if start <= end:
        return (hours >= start) & (hours < end)
    return (hours >= start) | (hours < end)


# ----------------------------------------------------------------- filter
class SessionFilterParams(BlockParams):
    sessions: list[Session] = Field(
        default_factory=lambda: list[Session](["asia", "london", "new_york"]),
        description="سشن‌هایی که ورود در آن‌ها مجاز است (asia, london, new_york؛ ساعت UTC)",
    )
    blackout: bool = Field(True, description="در بازهٔ خلأ نقدینگی ورود جدید نشود")
    blackout_from: float = Field(21.0, ge=0, lt=24, description="شروع بازهٔ ممنوع (ساعت UTC)")
    blackout_to: float = Field(
        0.0,
        ge=0,
        lt=24,
        description="پایان بازهٔ ممنوع (ساعت UTC؛ کوچک‌تر از شروع: از نیمه‌شب می‌گذرد)",
    )


@register
class SessionFilter(ContextBlock[SessionFilterParams]):
    """Trade the liquid sessions only; no new entries 21:00-00:00 UTC (video 58).

    An order placed at a bar's close is live from that instant, so a bar labelled inside
    the blackout (from 21:00 up to but not including 00:00) places nothing, and one inside
    none of the chosen sessions places nothing. The defaults chart all three sessions
    (together 00:00-21:00) and the blackout, which is the blueprint's rule exactly. In UTC,
    so the clocks changing in London or New York move nothing.
    """

    kind = BlockKind.CONTEXT
    type = "session_filter"
    title_fa = "فیلتر سشن‌های معاملاتی (UTC)"
    sources = (
        "tcp-blueprint 06: video 58 (session parameter architecture, execution restriction)",
    )
    Params = SessionFilterParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        hours = label_hours(data)
        in_session = np.zeros(len(hours), bool)
        for s in dict.fromkeys(p.sessions):
            in_session |= in_hours(hours, *SESSION_HOURS[s])
        gap = np.zeros_like(in_session)
        if p.blackout:
            gap = in_hours(hours, p.blackout_from, p.blackout_to)
        ok = in_session & ~gap
        flags = {f"in_{s}": in_hours(hours, *w) for s, w in SESSION_HOURS.items()}
        return ContextOutput(ok, ok.copy(), {**flags, "blackout": gap})


# ----------------------------------------------------------------- regime
class SessionRegimeParams(BlockParams):
    trend_efficiency: float = Field(
        0.5,
        gt=0,
        le=1,
        description="سشن روند دارد اگر |جابه‌جایی خالص| دست‌کم این کسر از دامنهٔ سشن باشد",
    )
    follow_continuation: bool = Field(
        True, description="پس از هم‌جهتی لندن و نیویورک، ورود خلاف آن جهت ممنوع شود"
    )
    bias_until: float = Field(
        16.0, gt=0, le=24, description="سوگیری ادامه تا این ساعت UTC روز بعد برقرار است"
    )
    us_open_from: float = Field(13.5, gt=0, lt=24, description="شروع پنجرهٔ بازگشایی آمریکا (UTC)")
    us_open_to: float = Field(14.5, gt=0, le=24, description="پایان پنجرهٔ بازگشایی آمریکا (UTC)")
    us_open_only: bool = Field(
        False, description="در روز شکست لندن، پس از پنجرهٔ بازگشایی آمریکا ورود جدید نشود"
    )


def session_trends(
    data: StrategyData, start: float, end: float, efficiency: float
) -> tuple[np.ndarray, np.ndarray]:
    """Each UTC day's trend in the window [start, end), and the instant it is known.

    Returns (known_at in ns, direction) sorted by time: direction is +1 / -1 when the net
    move from the first bar's open to the last bar's close is at least ``efficiency`` of the
    window's high-low range, 0 when it is not (a range), and the day is left out when the
    bars of its window are not all there.
    """

    def make() -> tuple[np.ndarray, np.ndarray]:
        f = data.base
        step = TIMEFRAMES[f.timeframe]
        opened = f.index - step
        hour = np.asarray(opened.hour + opened.minute / 60.0, dtype=float)
        # Only bars that close by ``end`` count, so a window that is not a whole number of bars
        # (13:30 on hourly bars) is judged up to the last bar that fits, never a bar beyond it.
        step_h = step / HOUR
        inside = (hour >= start) & (hour + step_h <= end + 1e-9)
        want = int((end - start) / step_h + 1e-9)
        day = ns(opened.floor("D"))[inside]
        o, h, lo, c = f.open[inside], f.high[inside], f.low[inside], f.close[inside]
        known: list[int] = []
        trend: list[int] = []
        for t in np.unique(day):
            sel = day == t
            if sel.sum() != want:
                continue
            rng = h[sel].max() - lo[sel].min()
            net = c[sel][-1] - o[sel][0]
            known.append(int(t) + round(start * HOUR.value) + want * step.value)
            trend.append(int(np.sign(net)) if rng > 0 and abs(net) >= efficiency * rng else 0)
        return np.array(known, dtype="int64"), np.array(trend, dtype="int8")

    return data.memo(("session_trends", start, end, efficiency), make)


def latest(known: np.ndarray, values: np.ndarray, at: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each instant in ``at``: the newest value known by then and when it became known
    (0 and -1 where there is none)."""
    k = np.searchsorted(known, at, side="right") - 1
    ok = k >= 0
    value = np.where(ok, values[np.maximum(k, 0)] if len(values) else 0, 0).astype("int8")
    when = np.where(ok, known[np.maximum(k, 0)] if len(known) else -1, -1)
    return value, when


@register
class SessionRegime(ContextBlock[SessionRegimeParams]):
    """The session regimes (video 58), judged only on sessions that have finished.

    A session *trends* when its net move covers at least ``trend_efficiency`` of its
    high-low range (scale-free), otherwise it ranges.

    *Continuation*: London (07-16) and New York (12-21) of one UTC day trend the same way.
    From New York's close until ``bias_until`` the next day, that direction is the bias
    (Asia in between is expected to range); with ``follow_continuation`` entries against it
    are refused, and entries with it are tagged ``continuation``.

    *US-open shift*: London judged over 07:00 until the US-open window opens
    (``us_open_from``) did not trend. Momentum then moves to that window: tagged
    ``us_open_shift`` inside it, and with ``us_open_only`` no later entry that day.
    """

    kind = BlockKind.CONTEXT
    type = "session_regime"
    title_fa = "رژیم‌های سشن (ادامه و بازگشایی آمریکا)"
    sources = ("tcp-blueprint 06: video 58 (session correlation engine, regimes 1 and 2)",)
    Params = SessionRegimeParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p = self.p
        n = len(data)
        at = ns(data.base.index)
        hours = label_hours(data)
        (l_start, l_end), (n_start, n_end) = SESSION_HOURS["london"], SESSION_HOURS["new_york"]
        london_known, london = session_trends(data, l_start, l_end, p.trend_efficiency)
        ny_known, ny = session_trends(data, n_start, n_end, p.trend_efficiency)
        # One value per UTC day, known at New York's close: both trended the same way.
        london_by_day = dict(zip(london_known - round(l_end * HOUR.value), london, strict=True))
        agree = [
            (t, ln) for t, d in zip(ny_known, ny, strict=True)
            if d != 0 and (ln := int(london_by_day.get(t - round(n_end * HOUR.value), 0))) == d
        ]  # fmt: skip
        cont_known = np.array([t for t, _ in agree], dtype="int64")
        cont_dir = np.array([d for _, d in agree], dtype="int8")
        # The latest agreeing day, and only until bias_until on the following day.
        bias, when = latest(cont_known, cont_dir, at)
        until = (when // DAY_NS + 1) * DAY_NS + round(p.bias_until * HOUR.value)
        bias = np.where((when >= 0) & (at < until), bias, 0).astype("int8")
        # London judged over [07:00, us_open_from): did it fail to trend that day?
        us_known, us_dir = session_trends(data, l_start, p.us_open_from, p.trend_efficiency)
        by_day = pd.Series(us_dir, index=us_known - int(p.us_open_from * HOUR.value))
        today = at // DAY_NS * DAY_NS
        no_trend = by_day.reindex(today).eq(0).to_numpy()
        failed = no_trend & (hours >= p.us_open_from)
        window = failed & in_hours(hours, p.us_open_from, p.us_open_to)
        long_ok = np.ones(n, bool)
        short_ok = np.ones(n, bool)
        if p.follow_continuation:
            long_ok &= bias >= 0
            short_ok &= bias <= 0
        if p.us_open_only:
            late = failed & (hours >= p.us_open_to)
            long_ok &= ~late
            short_ok &= ~late
        tags = {
            "continuation": (bias > 0, bias < 0),
            "us_open_shift": (window, window.copy()),
        }
        flags = {"bias": bias, "london_failed": failed, "us_open_window": window}
        return ContextOutput(long_ok, short_ok, flags, tags)
