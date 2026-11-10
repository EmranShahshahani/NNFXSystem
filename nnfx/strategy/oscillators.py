"""The eight oscillator methods as Confirmation Blocks (Strategy Builder ticket 15, ADR 10 §19).

An oscillator measures velocity; it warns and filters, it never triggers (videos 44
and 53). Every Block here is a Confirmation (``oscillator = True``, which the
registry refuses to combine with a Setup or Execution kind) that reads the
oscillator of one timeframe role at the role bar the candidate stands on:

====================  =====  ==========================================================
Block                 Method What it checks
====================  =====  ==========================================================
``osc_momentum``      1      beyond the overbought/oversold zone, in the trade's favour
``osc_inflection``    2      on the trade's side of the 50 (0) line
``osc_signal_cross``  3      signal-line crossover in an extreme zone or with a midline cross
``osc_level_break``   4      the oscillator broke its own horizontal level
``rsi_bb_reentry``    5      RSI back over its Bollinger middle line after an impulse or dip
``osc_recalibrated``  6      momentum with the period set to the average swing cycle
``osc_mf``            7      momentum with the period scaled by the multiplier factor
``osc_divergence``    8      regular/hidden divergence with a pivot in an extreme zone
``rsi_cascade``       -      RSI entering the zone up the timeframe ladder
====================  =====  ==========================================================

Bounded oscillators (RSI) use fixed zones; unbounded ones (CCI, ROC) use zones set
by a fraction of their rolling 200-bar extremes, the bars *before* the one tested.
A pivot of a role is read only once confirmed (``pivot_bars`` bars later).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import Field, field_validator, model_validator

from nnfx.data.timeframes import duration
from nnfx.strategy.blocks import (
    BlockKind,
    CheckResult,
    ConfirmationBlock,
    ConfirmationParams,
    Role,
    SetupCandidate,
    StrategyData,
    register,
)
from nnfx.strategy.series import bollinger, cci, pivots, prior_extremes, roc, sma

Oscillator = Literal["rsi", "cci", "roc"]


# ----------------------------------------------------------------- series
@dataclass(frozen=True)
class Osc:
    """One oscillator on a role's bars, with its zones and midline."""

    value: np.ndarray
    hi: np.ndarray  # overbought zone edge per bar (NaN: not yet known)
    lo: np.ndarray
    mid: float  # the inflection point: 50 for a bounded oscillator, else 0


def oscillator(
    data: StrategyData,
    role: str,
    kind: Oscillator,
    period: int,
    *,
    overbought: float,
    oversold: float,
    window: int,
    fraction: float,
) -> Osc:
    def make() -> Osc:
        f = data.frames[role]
        if kind == "rsi":
            v = data.rsi(role, period)
            n = len(v)
            return Osc(v, np.full(n, overbought), np.full(n, oversold), 50.0)
        v = cci(f.high, f.low, f.close, period) if kind == "cci" else roc(f.close, period)
        top, bottom = prior_extremes(v, window)
        with np.errstate(invalid="ignore"):
            hi = np.where(top > 0, fraction * top, np.nan)
            lo = np.where(bottom < 0, fraction * bottom, np.nan)
        return Osc(v, hi, lo, 0.0)

    return data.memo(("osc", role, kind, period, overbought, oversold, window, fraction), make)


# ----------------------------------------------------------------- params
class ZoneParams(ConfirmationParams):
    """The overbought/oversold zone of a bounded oscillator (RSI)."""

    overbought: float = Field(70.0, gt=50, lt=100, description="مرز اشباع خرید (RSI)")
    oversold: float = Field(30.0, gt=0, lt=50, description="مرز اشباع فروش (RSI)")

    def zone_level(self, sign: int) -> float:
        """The edge a trade of ``sign`` wants the oscillator beyond."""
        return self.overbought if sign > 0 else self.oversold


class OscParams(ZoneParams):
    role: Role = Field("lwc", description="تایم‌فریمی که نوسان‌نما روی آن خوانده می‌شود")
    osc: Oscillator = Field("rsi", description="نوسان‌نما: RSI (کران‌دار)، CCI یا ROC (بی‌کران)")
    period: int = Field(14, ge=2, description="دورهٔ نوسان‌نما")
    extreme_window: int = Field(
        200, ge=10, description="نوسان‌نمای بی‌کران: پنجرهٔ قله و دره‌های غلتان برای ناحیه‌ها"
    )
    extreme_fraction: float = Field(
        0.8, gt=0, le=1, description="نوسان‌نمای بی‌کران: ناحیه از این کسر قلهٔ غلتان آغاز می‌شود"
    )


class OscillatorBlock[P: ConfirmationParams](ConfirmationBlock[P]):
    """A Confirmation that reads an oscillator: it filters, it never triggers."""

    kind = BlockKind.CONFIRMATION
    oscillator = True


class OscBlock[P: OscParams](OscillatorBlock[P]):
    """A Confirmation over one oscillator of one role (``self.p.role``)."""

    def osc(self, data: StrategyData) -> Osc:
        p = self.p
        return oscillator(
            data, p.role, p.osc, p.period, overbought=p.overbought, oversold=p.oversold,
            window=p.extreme_window, fraction=p.extreme_fraction,
        )  # fmt: skip

    @staticmethod
    def stand(data: StrategyData, role: str, bar: int) -> int:
        """The role bar a candidate on LWC ``bar`` stands on (-1: none closed yet)."""
        return int(data.positions[role][bar])


def _beyond(value: float, level: float, sign: int) -> bool | None:
    """Whether ``value`` is past ``level`` in the trade's favour (None: unknown)."""
    if not (np.isfinite(value) and np.isfinite(level)):
        return None
    return bool((value - level) * sign > 0)


def _word(sign: int) -> str:
    return "above" if sign > 0 else "below"


def _na(what: str) -> CheckResult:
    return CheckResult("na", what)


def _entered(x: np.ndarray, level: np.ndarray | float, m: int, sign: int, bars: int) -> bool:
    """Whether ``x`` was *not* beyond ``level`` (in the trade's favour) at some bar of the
    ``bars`` before ``m``: it has just entered. ``level`` is a number or one per bar."""
    lo = max(0, m - bars)
    before = x[lo:m]
    edge = level[lo:m] if isinstance(level, np.ndarray) else level
    return bool(np.any(np.isfinite(before) & np.isfinite(edge) & ((before - edge) * sign <= 0)))


# ------------------------------------------------- method 1: OB/OS momentum
class OscMomentumParams(OscParams):
    fresh_bars: int = Field(
        3, ge=0, description="باید در این تعداد کندل اخیر وارد ناحیه شده باشد (۰: فقط سطح)"
    )


@register
class OscMomentum(OscBlock[OscMomentumParams]):
    """Method 1 (video 46): overbought is momentum, not a sell signal.

    Passes for a long when the oscillator is above the overbought zone (for a
    short, below the oversold zone), and, with ``fresh_bars`` > 0, entered it
    within that many role bars. ``rsi_momentum`` is the RSI-only form on the
    LWC for the Candle Setup; this one picks the role, the oscillator and the
    zone rule (rolling extremes for CCI and ROC).
    """

    type = "osc_momentum"
    title_fa = "مومنتوم نوسان‌نما (اشباع)"
    sources = ("tcp-blueprint 05: video 46 (overbought/oversold as momentum)",)
    Params = OscMomentumParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        m = self.stand(data, p.role, candidate.bar)
        o = self.osc(data)
        level = (o.hi if sign > 0 else o.lo)[m] if m >= 0 else np.nan
        now = o.value[m] if m >= 0 else np.nan
        verdict = _beyond(float(now), float(level), sign)
        if verdict is None:
            return _na(f"{p.osc} {p.period} on {p.role} has no zone yet")
        word = f"{p.osc} {now:.1f} {_word(sign)} {level:.1f}"
        if not verdict:
            return CheckResult("fail", f"{word} is false")
        if p.fresh_bars and not _entered(
            o.value, o.hi if sign > 0 else o.lo, m, sign, p.fresh_bars
        ):
            return CheckResult("fail", f"{word}: already there for more than {p.fresh_bars} bars")
        return CheckResult("pass", word)


# ------------------------------------------------- method 2: inflection point
class OscInflectionParams(OscParams):
    offset: float = Field(
        0.0, description="جابه‌جایی نقطهٔ عطف (مثلاً ۶- وقتی نوسان‌نما از ۴۴ برمی‌گردد)"
    )
    cross_bars: int = Field(
        0, ge=0, description="باید در این تعداد کندل اخیر نقطهٔ عطف را شکسته باشد (۰: فقط سمت)"
    )


@register
class OscInflection(OscBlock[OscInflectionParams]):
    """Method 2 (video 47): the 50 (0) line sets the bias; it never enters on its own.

    A long passes when the oscillator is above the inflection point (shorts
    below), optionally having crossed it within ``cross_bars`` role bars.
    ``offset`` moves the line to a structural level the oscillator keeps
    reacting to (the 44 instead of 50 example).
    """

    type = "osc_inflection"
    title_fa = "نقطهٔ عطف نوسان‌نما"
    sources = ("tcp-blueprint 05: video 47 (inflection point, 50 or 0)",)
    Params = OscInflectionParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        m = self.stand(data, p.role, candidate.bar)
        o = self.osc(data)
        line = o.mid + p.offset
        if m < 0 or not np.isfinite(o.value[m]):
            return _na(f"{p.osc} {p.period} on {p.role} has no value yet")
        side = (o.value[m] - line) * sign > 0
        word = f"{p.osc} {o.value[m]:.1f} {_word(sign)} the line {line:g}"
        if not side:
            return CheckResult("fail", f"{word} is false")
        if p.cross_bars and not _entered(o.value, line, m, sign, p.cross_bars):
            return CheckResult("fail", f"{word}: crossed more than {p.cross_bars} bars ago")
        return CheckResult("pass", word)


# ------------------------------------------------- method 3: signal-line cross
class OscSignalCrossParams(OscParams):
    signal_period: int = Field(
        0, ge=0, description="دورهٔ خط سیگنال ساختگی (SMA)؛ ۰: نصف دورهٔ نوسان‌نما"
    )
    cross_bars: int = Field(3, ge=1, description="تقاطع باید در این تعداد کندل اخیر رخ داده باشد")
    zone: Literal["extreme", "inflection", "either"] = Field(
        "either",
        description="تقاطع معتبر: در ناحیهٔ اشباع، همراه با شکست نقطهٔ عطف، یا هر دو حالت",
    )
    zone_margin: float = Field(
        0.1,
        ge=0,
        le=1,
        description="ناحیهٔ اشباع را به این کسر از فاصلهٔ دو مرز به سمت میانه گسترش بده",
    )


@register
class OscSignalCross(OscBlock[OscSignalCrossParams]):
    """Method 3 (video 48): twin-line crossovers, only where they mean something.

    The signal line is a synthetic SMA of half the period (a 7 over the 14 RSI).
    A bullish cross (oscillator over its signal) passes for a long when it
    happened within ``cross_bars`` role bars and either in the oversold zone
    (widened toward the midline by ``zone_margin`` of the span between the zones), or with a breach of the
    inflection line on the cross bar or the one after. Crosses in the mid-zone,
    where whipsaws live, are ignored. Shorts mirror it.
    """

    type = "osc_signal_cross"
    title_fa = "تقاطع خط سیگنال نوسان‌نما"
    sources = ("tcp-blueprint 05: video 48 (signal-line crossovers, mid-zone chop filter)",)
    Params = OscSignalCrossParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        m = self.stand(data, p.role, candidate.bar)
        o = self.osc(data)
        if m < 0:
            return _na("no closed role bar yet")
        n_sig = p.signal_period or max(2, p.period // 2)
        sig = data.memo(
            (
                "osc_signal",
                p.role,
                p.osc,
                p.period,
                p.overbought,
                p.oversold,
                p.extreme_window,
                p.extreme_fraction,
                n_sig,
            ),
            lambda: sma(o.value, n_sig),
        )
        diff = (o.value - sig) * sign  # > 0: on the trade's side of the signal line
        mid_zone: int | None = None
        for j in range(m, max(m - p.cross_bars, 0), -1):
            if not (diff[j] > 0 and diff[j - 1] <= 0):
                continue  # not a cross on this bar (NaN compares False)
            span = o.hi[j] - o.lo[j]
            zone_edge = (
                o.lo[j] + p.zone_margin * span if sign > 0 else o.hi[j] - p.zone_margin * span
            )
            extreme = bool((o.value[j] - zone_edge) * sign <= 0) if np.isfinite(span) else False
            near = o.value[max(j - 1, 0) : min(j + 2, m + 1)]
            inflection = bool(
                np.any(near <= o.mid) and np.any(near > o.mid)
                if sign > 0
                else np.any(near >= o.mid) and np.any(near < o.mid)
            )
            ok = {"extreme": extreme, "inflection": inflection, "either": extreme or inflection}
            if ok[p.zone]:
                where = "in the extreme zone" if extreme else "through the midline"
                return CheckResult("pass", f"signal-line cross {m - j} bars ago {where}")
            mid_zone = m - j  # a cross in the mid-zone is ignored; an older one may still count
        if not np.isfinite(diff[m]):
            return _na(f"{p.osc} signal line not ready on {p.role}")
        if mid_zone is not None:
            return CheckResult("fail", f"signal-line cross {mid_zone} bars ago was in the mid-zone")
        return CheckResult("fail", f"no signal-line cross in the last {p.cross_bars} bars")


# ------------------------------------------------- method 4: levels on the oscillator
class OscLevelBreakParams(OscParams):
    pivot_bars: int = Field(2, ge=1, description="پیوت نوسان‌نما: تعداد کندل‌های دو طرف")
    fresh_bars: int = Field(3, ge=1, description="شکست باید در این تعداد کندل اخیر رخ داده باشد")


@register
class OscLevelBreak(OscBlock[OscLevelBreakParams]):
    """Method 4 (videos 49, 54): the oscillator breaks its own horizontal level first.

    The level is the latest confirmed oscillator swing high (a long) or swing
    low (a short). The check passes when the oscillator closed beyond it within
    ``fresh_bars`` role bars, not before: the early momentum alert that
    precedes price breaking its resistance. A level belongs to the timeframe it
    was read on: nothing here crosses roles. Trendlines on the oscillator are a
    later, optional addition; this reads horizontal levels only.
    """

    type = "osc_level_break"
    title_fa = "شکست سطح افقی روی نوسان‌نما"
    sources = ("tcp-blueprint 05: videos 49, 54 (horizontal levels on the oscillator)",)
    Params = OscLevelBreakParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign, n = self.p, candidate.direction, self.p.pivot_bars
        m = self.stand(data, p.role, candidate.bar)
        v = self.osc(data).value
        if m < 0 or not np.isfinite(v[m]):
            return _na(f"{p.osc} {p.period} on {p.role} has no value yet")
        lows, highs = pivots(v, v, n, n)
        idx = highs if sign > 0 else lows
        idx = idx[idx + n <= m]
        if not len(idx):
            return _na("no confirmed oscillator level yet")
        # The level as known now (the latest confirmed swing); the bars before are judged
        # against it, so a break counts only if the oscillator was under it recently.
        level = float(v[idx[-1]])
        if (v[m] - level) * sign <= 0:
            return CheckResult(
                "fail", f"{p.osc} {v[m]:.1f} not {_word(sign)} its level {level:.1f}"
            )
        if _entered(v, level, m, sign, p.fresh_bars):
            return CheckResult(
                "pass", f"{p.osc} broke its level {level:.1f} within {p.fresh_bars} bars"
            )
        return CheckResult(
            "fail", f"{p.osc} broke its level {level:.1f} more than {p.fresh_bars} bars ago"
        )


# ------------------------------------------------- method 5: Bollinger on RSI
class RsiBollingerParams(ConfirmationParams):
    role: Role = Field("lwc", description="تایم‌فریمی که RSI روی آن خوانده می‌شود")
    rsi_period: int = Field(14, ge=2, description="دورهٔ RSI")
    bb_period: int = Field(20, ge=2, description="دورهٔ بولینگر روی RSI")
    bb_k: float = Field(2.0, gt=0, description="ضریب انحراف معیار بولینگر")
    mode: Literal["impulse", "dip"] = Field(
        "impulse",
        description="impulse: پس از خروج RSI از باند بالا (ویدیو ۵۰)؛ dip: پس از فرو رفتن در باند پایین (ویدیو ۱۵)",
    )
    lookback: int = Field(
        30, ge=2, description="موج اول/فرو رفتن باید در این تعداد کندل پیش از تقاطع باشد"
    )
    cross_bars: int = Field(3, ge=1, description="بازگشت از خط میانی در این تعداد کندل اخیر")


@register
class RsiBollingerReentry(OscillatorBlock[RsiBollingerParams]):
    """Method 5 (videos 15, 50): re-entry in a trend when RSI curls back over its middle line.

    A long passes when RSI, within ``cross_bars`` role bars, crossed up through
    the middle line of its own Bollinger band, after having been (``impulse``)
    above the upper band or (``dip``) at or below the lower band within the
    ``lookback`` bars before that cross. The trend is the context's to decide;
    the price continuation candle is the Setup. Shorts mirror it.
    """

    type = "rsi_bb_reentry"
    title_fa = "ورود دوباره: RSI روی خط میانی بولینگر"
    sources = (
        "tcp-blueprint 02: video 15; tcp-blueprint 05: video 50 (secondary impulse re-entry)",
    )
    Params = RsiBollingerParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        m = int(data.positions[p.role][candidate.bar])
        r = data.rsi(p.role, p.rsi_period)
        lower, mid, upper = bollinger(r, p.bb_period, p.bb_k)
        if m < 0 or not np.isfinite(mid[m]):
            return _na(f"RSI {p.rsi_period} bands on {p.role} not ready")
        up = r - mid if sign > 0 else mid - r  # > 0: on the trade's side of the middle line
        prev = np.r_[np.nan, up[:-1]]
        for j in range(m, max(m - p.cross_bars, 0), -1):
            if not (up[j] > 0 and prev[j] <= 0):
                continue
            lo = max(0, j - p.lookback)
            # impulse: the first wave pushed RSI out of the band on the trade's side;
            # dip: the pullback sank RSI into the band on the other side.
            band_side = (p.mode == "impulse") == (sign > 0)
            if band_side:
                touched = r[lo:j] > upper[lo:j] if p.mode == "impulse" else r[lo:j] >= upper[lo:j]
            else:
                touched = r[lo:j] < lower[lo:j] if p.mode == "impulse" else r[lo:j] <= lower[lo:j]
            if np.any(touched & np.isfinite(r[lo:j])):
                return CheckResult(
                    "pass", f"RSI curled over its band middle {m - j} bars ago after the {p.mode}"
                )
            return CheckResult(
                "fail", f"RSI crossed its band middle but there was no {p.mode} before"
            )
        return CheckResult(
            "fail", f"RSI did not cross its band middle in the last {p.cross_bars} bars"
        )


# ------------------------------------------------- method 6: cycle recalibration
class RecalibratedParams(ZoneParams):
    role: Role = Field("lwc", description="تایم‌فریمی که RSI و چرخه‌ها روی آن خوانده می‌شود")
    base_period: int = Field(14, ge=2, description="دورهٔ RSI وقتی چرخهٔ کافی نیست")
    pivot_bars: int = Field(3, ge=1, description="پیوت قیمت: تعداد کندل‌های دو طرف")
    swings: int = Field(4, ge=2, description="میانگین فاصلهٔ این تعداد چرخهٔ اخیر")
    min_period: int = Field(5, ge=2, description="کمینهٔ دورهٔ بازتنظیم‌شده")
    max_period: int = Field(60, ge=3, description="بیشینهٔ دورهٔ بازتنظیم‌شده")
    structure_pivot_bars: int = Field(
        3, ge=1, description="پیوت دائو برای تشخیص تغییر رژیم (چرخه‌های رژیم پیشین کنار می‌روند)"
    )
    fresh_bars: int = Field(
        3, ge=0, description="باید در این تعداد کندل اخیر وارد ناحیه شده باشد (۰: فقط سطح)"
    )

    @model_validator(mode="after")
    def _periods(self) -> RecalibratedParams:
        if self.min_period > self.max_period:
            raise ValueError("کمینهٔ دوره نباید از بیشینهٔ آن بیشتر باشد")
        return self


def cycle_period(
    data: StrategyData, p: RecalibratedParams, m: int, direction: int
) -> tuple[int, int]:
    """(period, cycles used) at role bar ``m``: the mean distance between the last
    ``swings`` confirmed same-side price swings of the current Dow regime."""
    n = p.pivot_bars
    lows, highs = data.pivots(p.role, n, n)
    idx = lows if direction > 0 else highs
    idx = idx[idx + n <= m]
    dow = data.dow(p.role, p.structure_pivot_bars)
    changes = np.flatnonzero(dow[1 : m + 1] != dow[:m]) + 1
    if len(changes):
        idx = idx[idx >= changes[-1]]  # the regime shift governor: only this regime's swings
    idx = idx[-(p.swings + 1) :]
    if len(idx) < 3:
        return p.base_period, 0
    mean = float(np.mean(np.diff(idx)))
    return int(min(max(round(mean), p.min_period), p.max_period)), len(idx) - 1


@register
class OscRecalibrated(OscillatorBlock[RecalibratedParams]):
    """Method 6 (video 51): replace the arbitrary 14 with the market's own cycle length.

    The period is the mean distance, in bars, between the last ``swings``
    confirmed swing lows (longs; highs for shorts) of the current Dow regime,
    clamped to ``min_period..max_period``. A Dow state change starts a new
    regime and the earlier swings are forgotten; with fewer than two cycles in
    the regime the base period stands. The check is then momentum on that RSI.
    """

    type = "osc_recalibrated"
    title_fa = "مومنتوم RSI با دورهٔ بازتنظیم‌شده"
    sources = ("tcp-blueprint 06: video 51 (cycle length recalibration)",)
    Params = RecalibratedParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        m = int(data.positions[p.role][candidate.bar])
        if m < 0:
            return _na("no closed role bar yet")
        period, cycles = cycle_period(data, p, m, sign)
        r = data.rsi(p.role, period)
        level = p.zone_level(sign)
        verdict = _beyond(float(r[m]), level, sign)
        if verdict is None:
            return _na(f"RSI {period} on {p.role} not ready")
        word = f"RSI({period}, {cycles} cycles) {r[m]:.1f} {_word(sign)} {level:g}"
        if not verdict:
            return CheckResult("fail", f"{word} is false")
        if p.fresh_bars and not _entered(r, level, m, sign, p.fresh_bars):
            return CheckResult("fail", f"{word}: already there for more than {p.fresh_bars} bars")
        return CheckResult("pass", word)


# ------------------------------------------------- method 7: multiplier factor
class MultiplierParams(ZoneParams):
    source: Literal["mwc", "hwc"] = Field(
        "mwc", description="تایم‌فریم بالاتری که روی LWC بازسازی می‌شود"
    )
    base_period: int = Field(14, ge=2, description="دورهٔ RSI روی همان تایم‌فریم بالاتر")
    fresh_bars: int = Field(
        0, ge=0, description="باید در این تعداد کندل LWC اخیر وارد ناحیه شده باشد (۰: فقط سطح)"
    )


def multiplier_factor(data: StrategyData, source: str) -> int:
    """MF = the higher timeframe's minutes over the LWC's (4H on 15m: 16)."""
    ratio = duration(data.roles[source]) / duration(data.roles["lwc"])
    return max(1, round(ratio))


@register
class OscMultiplier(OscillatorBlock[MultiplierParams]):
    """Method 7 (video 52): a higher-timeframe RSI drawn on the execution chart.

    The LWC's RSI period is ``base_period x MF`` (14 x 16 = 224 for the 4H RSI on
    15m), which tracks the higher-timeframe line without a second timeframe's
    redraw problem. It needs that many LWC bars first (not applicable before).
    """

    type = "osc_mf"
    title_fa = "RSI تایم‌فریم بالاتر با ضریب MF"
    sources = ("tcp-blueprint 06: video 52 (multi-timeframe multiplier factor)",)
    Params = MultiplierParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        mf = multiplier_factor(data, p.source)
        period = p.base_period * mf
        r = data.rsi("lwc", period)
        i = candidate.bar
        level = p.zone_level(sign)
        verdict = _beyond(float(r[i]), level, sign)
        if verdict is None:
            return _na(f"RSI {period} (MF {mf}) needs {period + 1} LWC bars, {i + 1} so far")
        word = f"RSI({p.base_period}x{mf}={period}) {r[i]:.1f} {_word(sign)} {level:g}"
        if not verdict:
            return CheckResult("fail", f"{word} is false")
        if p.fresh_bars and not _entered(r, level, i, sign, p.fresh_bars):
            return CheckResult("fail", f"{word}: already there for more than {p.fresh_bars} bars")
        return CheckResult("pass", word)


# ------------------------------------------------- method 8: divergences
class DivergenceParams(OscParams):
    form: Literal["regular", "hidden", "either"] = Field(
        "either", description="واگرایی معمولی (برگشت)، پنهان (ادامه) یا هر دو"
    )
    pivot_bars: int = Field(3, ge=1, description="پیوت قیمت: تعداد کندل‌های دو طرف")
    fresh_bars: int = Field(
        5, ge=0, description="آخرین پیوت باید در این تعداد کندل اخیر تأیید شده باشد"
    )


@register
class OscDivergence(OscBlock[DivergenceParams]):
    """Method 8 (video 53): regular and hidden divergence, only with a pivot in an extreme zone.

    Takes the last two confirmed price swing lows (longs; highs for shorts).
    *Regular bullish*: price makes a lower low, the oscillator a higher low.
    *Hidden bullish*: price a higher low, the oscillator a lower low. Neutral
    territory is discarded: at least one of the two oscillator pivots must lie
    in the oversold zone (shorts: overbought). The newer pivot must have been
    confirmed within ``fresh_bars`` role bars. Divergence is an alert and a
    filter, never an entry.
    """

    type = "osc_divergence"
    title_fa = "واگرایی نوسان‌نما (با پیوت در ناحیهٔ اشباع)"
    sources = ("tcp-blueprint 06: video 53 (regular and hidden divergence, extreme-zone rule)",)
    Params = DivergenceParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign, n = self.p, candidate.direction, self.p.pivot_bars
        m = self.stand(data, p.role, candidate.bar)
        o = self.osc(data)
        if m < 0:
            return _na("no closed role bar yet")
        lows, highs = data.pivots(p.role, n, n)
        idx = lows if sign > 0 else highs
        idx = idx[idx + n <= m]
        if len(idx) < 2:
            return _na("fewer than two confirmed swings")
        a, b = int(idx[-2]), int(idx[-1])
        if b + n < m - p.fresh_bars:
            return CheckResult(
                "fail", f"the latest swing was confirmed more than {p.fresh_bars} bars ago"
            )
        f = data.frames[p.role]
        price = f.low if sign > 0 else f.high
        pa, pb, oa, ob = price[a], price[b], o.value[a], o.value[b]
        if not (np.isfinite(oa) and np.isfinite(ob)):
            return _na(f"{p.osc} has no value at the swings")
        zone = o.lo if sign > 0 else o.hi
        in_zone = [
            (v - z) * sign < 0 if np.isfinite(z) else False
            for v, z in ((oa, zone[a]), (ob, zone[b]))
        ]
        if not any(in_zone):
            return CheckResult("fail", "neither oscillator pivot is in the extreme zone")
        # For a long the swings are lows: a higher oscillator low with a lower price low is regular.
        price_more = (pb - pa) * sign < 0  # price made the more extreme swing
        osc_more = (ob - oa) * sign < 0
        regular = price_more and not osc_more and ob != oa
        hidden = (not price_more) and osc_more and pb != pa
        wanted = {"regular": regular, "hidden": hidden, "either": regular or hidden}[p.form]
        if wanted:
            name = "regular" if regular else "hidden"
            return CheckResult(
                "pass", f"{name} divergence between swings {m - a} and {m - b} bars back"
            )
        return CheckResult("fail", "no divergence between the last two swings")


# ------------------------------------------------- the multi-timeframe cascade
class CascadeParams(ZoneParams):
    roles: list[Role] = Field(
        default_factory=lambda: list[Role](["lwc", "mwc", "hwc"]),
        description="تایم‌فریم‌ها از پایین به بالا؛ ورود از اولین نقشی که تازه وارد ناحیه شده",
    )
    rsi_period: int = Field(14, ge=2, description="دورهٔ RSI")
    fresh_bars: int = Field(3, ge=1, description="تازه: ورود به ناحیه در این تعداد کندل همان نقش")
    sequential: bool = Field(
        False,
        description="فقط وقتی تازه‌واردشدن معتبر است که نقش‌های پایین‌تر هنوز در ناحیه باشند",
    )

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[Role]) -> list[Role]:
        if not v or len(set(v)) != len(v):
            raise ValueError("نقش‌ها باید ناتهی و بدون تکرار باشند (از پایین‌ترین به بالاترین)")
        return v


@register
class RsiCascade(OscillatorBlock[CascadeParams]):
    """The RSI trend-alignment cascade (videos 46, 54): missed entries move up a timeframe.

    High-momentum extensions pass RSI 70 on the 15m, then the 1H, 4H and the
    daily. The check passes when RSI on any listed role has just entered the
    zone (within ``fresh_bars`` of that role's bars), and, with ``sequential``,
    every lower listed role is still in it (off by default: a missed 15m entry may
    already have pulled back while the 4H closes above 70). The hold side of the cascade is
    ``ProfitChain.hold_while_rsi_role``.
    """

    type = "rsi_cascade"
    title_fa = "آبشار RSI چندتایم‌فریمی"
    sources = ("tcp-blueprint 02: video 27; tcp-blueprint 05: videos 46, 54 (RSI cascade)",)
    Params = CascadeParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, sign = self.p, candidate.direction
        level = p.zone_level(sign)
        lower_in = True
        for role in p.roles:
            m = int(data.positions[role][candidate.bar])
            r = data.rsi(role, p.rsi_period)
            verdict = _beyond(float(r[m]), level, sign) if m >= 0 else None
            if verdict is None:
                return _na(f"RSI {p.rsi_period} on {role} not ready")
            if verdict:
                fresh = _entered(r, level, m, sign, p.fresh_bars)
                if fresh and (lower_in or not p.sequential):
                    return CheckResult("pass", f"RSI on {role} entered {_word(sign)} {level:g}")
            else:
                lower_in = False
                if p.sequential:
                    break  # a role that is not in the zone ends the chain
        return CheckResult(
            "fail", f"no role in the cascade has just entered {_word(sign)} {level:g}"
        )
