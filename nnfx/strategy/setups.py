"""The remaining Setup Blocks and the chase guard (Strategy Builder ticket 14, ADR 10 §18).

Engulfing, Giant Indecision Reversal, Absorption Wick, the "LA" layered setup, Dow
continuation, the binary scenario pair and momentum continuation, plus a Context
Block that refuses entries after an outsized bar. Every number is a parameter with
the blueprint's default (docs/sources/tcp-blueprint). The candle setups read the
LWC bars; the structural ones read the timeframe role their parameters name.

Each Setup emits per-bar candidates with a trigger, an invalidation and a proposed
stop; sizing, orders and the checklist are other Blocks' work.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

from nnfx.strategy.blocks import (
    BlockKind,
    BlockParams,
    ContextBlock,
    ContextOutput,
    Role,
    SetupBlock,
    SetupOutput,
    StrategyData,
    register,
)
from nnfx.strategy.candles import candle_setup
from nnfx.strategy.library import BoxParams
from nnfx.strategy.series import atr, rsi, sma


def _prior(x: np.ndarray, n: int, how: str) -> np.ndarray:
    """The ``how`` (max, min or mean) of the ``n`` values before each bar (NaN until ``n`` exist)."""
    out: np.ndarray = getattr(pd.Series(x).shift(1).rolling(n, min_periods=n), how)().to_numpy()
    return out


def _prior_max(x: np.ndarray, n: int) -> np.ndarray:
    return _prior(x, n, "max")


def _prior_min(x: np.ndarray, n: int) -> np.ndarray:
    return _prior(x, n, "min")


def _prior_mean(x: np.ndarray, n: int) -> np.ndarray:
    return _prior(x, n, "mean")


def _lag(x: np.ndarray, k: int, fill: float = np.nan) -> np.ndarray:
    """``x`` as it was ``k`` bars ago."""
    return np.r_[np.full(k, fill), x[:-k]] if 0 < k < len(x) else np.full(len(x), fill)


# --------------------------------------------------------------- engulfing
class EngulfingParams(BlockParams):
    lookback: int = Field(8, ge=2, description="طول موج قبلی که سنجیده می‌شود، تعداد کندل")
    min_prior_move_atr: float = Field(0.5, ge=0, description="کمترین حرکت موج قبلی (ATR)")
    weak_bars: int = Field(3, ge=1, description="تعداد کندل برای سنجش ضعف فشارها")
    weakness_ratio: float = Field(
        0.8, gt=0, description="بدنهٔ فشارهای اخیر دست‌بالا این ضریبِ فشارهای قبلی باشد"
    )
    volume_contraction: bool = Field(
        False, description="حجم فشارهای اخیر هم باید کمتر از قبلی باشد (بدون حجم نادیده)"
    )
    atr_period: int = Field(14, ge=2, description="دورهٔ ATR")


@register
class Engulfing(SetupBlock[EngulfingParams]):
    """The crypto engulfing candle, only after prior weakness (blueprint 04, video 38).

    Crypto has no gaps, so a bullish engulfing is a bullish candle whose *body* covers the
    previous bearish candle's whole range, wicks included (mirrored for bearish). It is
    never taken alone: the move before it must have been a leg the other way of at least
    ``min_prior_move_atr`` ATR whose pushes were fading (the recent bodies at most
    ``weakness_ratio`` x the earlier ones, optionally with shrinking volume). Trigger at the
    engulfing candle's high (low for shorts); invalidation and stop at its other end.
    """

    kind = BlockKind.SETUP
    type = "engulfing"
    title_fa = "کندل اینگلف (پس از ضعف)"
    sources = ("tcp-blueprint 04: video 38 (engulfing without gaps, weakness prerequisite)",)
    Params = EngulfingParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        o, h, lo, c = f.open, f.high, f.low, f.close
        body_hi, body_lo = np.maximum(o, c), np.minimum(o, c)
        rng = atr(h, lo, c, p.atr_period)
        body = body_hi - body_lo
        w = p.weak_bars
        recent = pd.Series(body).rolling(w, min_periods=w).mean().to_numpy()
        earlier = _lag(recent, w)  # the same measure w bars before
        with np.errstate(invalid="ignore"):
            weak = _lag(recent, 1) <= p.weakness_ratio * _lag(earlier, 1)
            if p.volume_contraction and f.volume_kind != "none":
                v = pd.Series(f.volume).rolling(w, min_periods=w).mean().to_numpy()
                weak &= _lag(v, 1) < _lag(_lag(v, w), 1)
            down_move = _lag(c, 1 + p.lookback) - _lag(c, 1)  # the leg into the engulfed bar
            floor = p.min_prior_move_atr * _lag(rng, 1)
            covers_up = (c > o) & (body_hi >= _lag(h, 1)) & (body_lo <= _lag(lo, 1))
            covers_dn = (c < o) & (body_hi >= _lag(h, 1)) & (body_lo <= _lag(lo, 1))
            long_ = covers_up & (_lag(c, 1) < _lag(o, 1)) & (down_move >= floor) & weak
            short = covers_dn & (_lag(c, 1) > _lag(o, 1)) & (-down_move >= floor) & weak
        return candle_setup(long_, short, h, lo, "engulfing")


# ------------------------------------------------- giant indecision reversal
class GiantIndecisionParams(BlockParams):
    lookback: int = Field(10, ge=2, description="کندل‌های قبلی برای مقایسهٔ دامنه و حجم (جزوه: ۱۰)")
    range_factor: float = Field(1.0, gt=0, description="دامنه دست‌کم این ضریبِ بزرگ‌ترین دامنهٔ قبلی")
    volume_factor: float = Field(1.0, gt=0, description="حجم دست‌کم این ضریبِ بزرگ‌ترین حجم قبلی")
    max_body_ratio: float = Field(0.5, gt=0, le=1, description="بدنه حداکثر این نسبت از دامنه")
    min_wick_share: float = Field(0.4, gt=0, le=1, description="سایهٔ ردکننده دست‌کم این سهم دامنه")
    trend_bars: int = Field(10, ge=1, description="طول روندی که برگشتش معامله می‌شود، تعداد کندل")
    require_htf_weakness: bool = Field(
        True, description="ضعف تایم‌فریم بالاتر باید پیش‌تر دیده شده باشد"
    )
    htf: Role = Field("mwc", description="تایم‌فریم بالاتر برای ضعف")
    htf_sma: int = Field(7, ge=2, description="میانگین کوتاه تایم‌فریم بالاتر برای ضعف")


@register
class GiantIndecisionReversal(SetupBlock[GiantIndecisionParams]):
    """A reversal marked by one giant indecision candle (blueprint 03, video 26).

    The bar's range (and, where the venue reports volume, its volume) exceeds every one of
    the previous ``lookback`` bars, it has a small body and a long wick on one side. After
    an up-move the long upper wick makes a short candidate (a long wick below after a
    down-move, a long). The trigger is *beyond the opposite side* of the candle (its low for
    a short), the invalidation and stop the extreme wick tip. When ``require_htf_weakness``
    is on, the higher timeframe must already show it: for a long its latest closed bar is
    above its ``htf_sma`` SMA (below it for a short): the old trend has lost its short
    average.
    """

    kind = BlockKind.SETUP
    type = "giant_indecision"
    title_fa = "برگشت با کندل بی‌تصمیمی غول‌پیکر"
    sources = ("tcp-blueprint 03: video 26 (giant indecision reversal)",)
    Params = GiantIndecisionParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        o, h, lo, c = f.open, f.high, f.low, f.close
        span = h - lo
        body_hi, body_lo = np.maximum(o, c), np.minimum(o, c)
        upper, lower = h - body_hi, body_lo - lo
        with np.errstate(invalid="ignore", divide="ignore"):
            big = span > p.range_factor * _prior_max(span, p.lookback)
            if f.volume_kind != "none":
                big &= f.volume > p.volume_factor * _prior_max(f.volume, p.lookback)
            small_body = (body_hi - body_lo) <= p.max_body_ratio * span
            up_trend = _lag(c, 1) > _lag(c, 1 + p.trend_bars)
            dn_trend = _lag(c, 1) < _lag(c, 1 + p.trend_bars)
            short = (
                big & small_body & up_trend & (upper >= p.min_wick_share * span) & (upper > lower)
            )
            long_ = (
                big & small_body & dn_trend & (lower >= p.min_wick_share * span) & (lower > upper)
            )
            if p.require_htf_weakness:
                fh = data.frames[p.htf]
                m = data.aligned(p.htf, sma(fh.close, p.htf_sma), np.nan)
                hc = data.aligned(p.htf, fh.close, np.nan)
                long_ &= hc > m
                short &= hc < m
        # Beyond the opposite side of the wick: a long (wick below) triggers above the
        # candle's high; the invalidation and stop are the wick tip.
        return candle_setup(long_, short, h, lo, "giant_indecision")


# --------------------------------------------------------- absorption wick
class AbsorptionWickParams(BlockParams):
    lookback: int = Field(20, ge=2, description="پنجرهٔ تعیین حمایت/مقاومت، تعداد کندل قبلی")
    min_wick_ratio: float = Field(1.0, gt=0, description="سایه دست‌کم این ضریبِ بدنه")
    min_pierce_atr: float = Field(0.0, ge=0, description="کمترین فرورفتن سایه از سطح (ATR)")
    atr_period: int = Field(14, ge=2, description="دورهٔ ATR")


@register
class AbsorptionWick(SetupBlock[AbsorptionWickParams]):
    """A wick through support that closes back inside: trapped sellers (blueprint 07, video 68).

    Support is the lowest low of the ``lookback`` bars before the candle (resistance the
    highest high). A candle whose low pierces it by at least ``min_pierce_atr`` ATR but
    whose close (and body) stays above it, with a lower wick at least ``min_wick_ratio`` x
    the body, is the absorption wick. Trigger: a stop-buy above its high; invalidation and
    stop at its low. Mirrored at resistance. ``level`` is the pierced level.
    """

    kind = BlockKind.SETUP
    type = "absorption_wick"
    title_fa = "سایهٔ جذب (دام فروشنده‌ها)"
    sources = ("tcp-blueprint 07: video 68 (absorption wick at support)",)
    Params = AbsorptionWickParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        o, h, lo, c = f.open, f.high, f.low, f.close
        body_hi, body_lo = np.maximum(o, c), np.minimum(o, c)
        body = body_hi - body_lo
        support, resistance = _prior_min(lo, p.lookback), _prior_max(h, p.lookback)
        pierce = p.min_pierce_atr * _lag(atr(h, lo, c, p.atr_period), 1)
        with np.errstate(invalid="ignore"):
            long_ = (
                (lo < support - pierce)
                & (body_lo > support)
                & ((body_lo - lo) >= p.min_wick_ratio * body)
            )
            short = (
                (h > resistance + pierce)
                & (body_hi < resistance)
                & ((h - body_hi) >= p.min_wick_ratio * body)
            )
        level = np.where(long_, support, np.where(short, resistance, np.nan))
        return candle_setup(long_, short, h, lo, "absorption_wick", {"level": level})


# ------------------------------------------------------------ the LA setup
class LayeredParams(BoxParams):
    side: Literal["long", "short"] = Field("long", description="سمت: خرید بالای باکس / فروش زیر آن")
    refresh_bars: int = Field(4, ge=1, description="هر چند کندل (تایم‌فریم باکس) ستاپ تازه شود")
    impulse_bars: int = Field(8, ge=1, description="طول ایمپالس پیش از باکس، تعداد کندل")
    impulse_atr: float = Field(2.0, ge=0, description="کمترین اندازهٔ ایمپالس (ATR)")
    min_lift_atr: float = Field(
        0.25, ge=0, description="کمترین بالاتر بودن کف داخلی از کف اول (ATR)"
    )
    atr_period: int = Field(14, ge=2, description="دورهٔ ATR")
    speed_ratio: float = Field(
        0.9, gt=0, description="میانگین طول موج‌های صعودی دست‌بالا این ضریبِ موج‌های نزولی"
    )


@register
class LayeredSetup(SetupBlock[LayeredParams]):
    """The "LA" layers setup (blueprint 07, video 69): impulse, box, a higher low inside it.

    A directional impulse (``impulse_atr`` ATR over ``impulse_bars`` bars) is followed by a
    box. Inside the box price stops reaching the bottom edge: the latest confirmed swing
    low is above the first one by ``min_lift_atr`` ATR, and the pushes up take fewer bars
    than the pullbacks down (mean up-leg length at most ``speed_ratio`` x the mean down-leg).
    A stop-buy waits above the ceiling; the stop is under the inner higher low and the
    invalidation is the box bottom. One instance per side; a short mirrors it (a lower
    high, the impulse down, a stop-sell under the floor).
    """

    kind = BlockKind.SETUP
    type = "layered_setup"
    title_fa = "ستاپ لایه‌ای LA"
    sources = ("tcp-blueprint 07: video 69 (layers of Arshia: impulse, box, higher low)",)
    Params = LayeredParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p, role = self.p, self.p.timeframe
        n = len(data.frames[role])
        t = p.track(data, 1)
        sign = 1 if p.side == "long" else -1
        fr = data.frames[role]
        # Mirror shorts so one body of logic reads "long": prices become -price.
        low = fr.low if sign > 0 else -fr.high
        close = fr.close * sign
        top = t.top if sign > 0 else -t.bottom
        bottom = t.bottom if sign > 0 else -t.top
        rng = data.atr(role, p.atr_period)
        lows_idx, highs_idx = data.pivots(role, p.pivot_bars, p.pivot_bars)
        piv_lo, piv_hi = (lows_idx, highs_idx) if sign > 0 else (highs_idx, lows_idx)
        pb = p.pivot_bars
        due = t.in_box & (t.age % p.refresh_bars == 0)
        trigger, stop, level = (np.full(n, np.nan) for _ in range(3))
        ok = np.zeros(n, bool)
        for i in map(int, np.flatnonzero(due)):
            s = int(t.start[i])
            a = rng[i]
            if s - 1 - p.impulse_bars < 0 or not np.isfinite(a):
                continue
            if close[s - 1] - close[s - 1 - p.impulse_bars] < p.impulse_atr * a:
                continue
            los = piv_lo[(piv_lo >= s) & (piv_lo + pb <= i)]  # confirmed swing lows in the box
            his = piv_hi[(piv_hi >= s) & (piv_hi + pb <= i)]
            if len(los) < 2 or low[los[-1]] < low[los[0]] + p.min_lift_atr * a:
                continue
            legs = sorted([(int(k), "L") for k in los] + [(int(k), "H") for k in his])
            ups, downs = [], []
            for (k0, a0), (k1, a1) in pairwise(legs):
                if a0 == "L" and a1 == "H":
                    ups.append(k1 - k0)
                elif a0 == "H" and a1 == "L":
                    downs.append(k1 - k0)
            if not ups or not downs or np.mean(ups) > p.speed_ratio * np.mean(downs):
                continue
            ok[i] = True
            trigger[i] = top[i]
            stop[i] = low[los[-1]]
            level[i] = top[i]
        d = (ok.astype("int8") * sign).astype("int8")
        trig = np.where(ok, sign * trigger, np.nan)
        stp = np.where(ok, sign * stop, np.nan)
        inval = np.where(ok, sign * bottom, np.nan)
        lvl = np.where(ok, sign * level, np.nan)
        return SetupOutput(
            data.on_close(role, d, 0).astype("int8"),
            data.on_close(role, trig, np.nan),
            data.on_close(role, inval, np.nan),
            data.on_close(role, stp, np.nan),
            {"layered_setup": data.on_close(role, d, 0) != 0},
            {"level": data.on_close(role, lvl, np.nan)},
        )


# ---------------------------------------------------------- dow continuation
class DowContinuationParams(BlockParams):
    timeframe: Role = Field("mwc", description="تایم‌فریمی که ساختار روی آن سنجیده می‌شود")
    pivot_bars: int = Field(2, ge=1, description="پیوت: تعداد کندل‌های دو طرف")
    window: int = Field(4, ge=1, description="تا چند کندل پس از شکست، ستاپ معتبر می‌ماند")


@register
class DowContinuation(SetupBlock[DowContinuationParams]):
    """Mid-trend continuation: a close breaks the last swing (blueprint 07, video 62).

    In a Dow uptrend, the first close above the last confirmed swing high makes a long
    candidate for ``window`` bars while the closes stay above it. Trigger: the break bar's
    high; invalidation: the broken swing high; stop: the last confirmed swing low before the
    break (the previous swing). Shorts mirror it in a downtrend. A pure structure trade:
    it asks nothing of levels or volume (the blueprint's "clear of higher-timeframe barriers" is left to
    the Level Confirmation Blocks, not built in).
    """

    kind = BlockKind.SETUP
    type = "dow_continuation"
    title_fa = "ادامهٔ روند داو (شکست آخرین سوینگ)"
    sources = ("tcp-blueprint 07: video 62 (Dow wave continuation, second wave)",)
    Params = DowContinuationParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p, role = self.p, self.p.timeframe
        fr = data.frames[role]
        n = len(fr)
        pb = p.pivot_bars
        state = data.dow(role, pb)
        sl, sh = data.pivots(role, pb, pb)

        def last_confirmed(idx: np.ndarray, at: np.ndarray) -> np.ndarray:
            k = np.searchsorted(idx + pb, at, side="right") - 1
            return np.where(
                k >= 0, idx[np.clip(k, 0, max(len(idx) - 1, 0))] if len(idx) else -1, -1
            )

        prev = np.arange(n) - 1
        hi_i, lo_i = last_confirmed(sh, prev), last_confirmed(sl, prev)
        level_hi = np.where(hi_i >= 0, fr.high[np.clip(hi_i, 0, n - 1)], np.nan)
        level_lo = np.where(lo_i >= 0, fr.low[np.clip(lo_i, 0, n - 1)], np.nan)
        c = fr.close
        st_prev = _lag(state.astype(float), 1, 0.0)
        with np.errstate(invalid="ignore"):
            up = (c > level_hi) & (_lag(c, 1) <= level_hi) & (st_prev > 0)
            dn = (c < level_lo) & (_lag(c, 1) >= level_lo) & (st_prev < 0)
        # The break bar and the window after it, while the closes stay beyond the level.
        d = np.zeros(n, "int8")
        trig, inval, stop = (np.full(n, np.nan) for _ in range(3))
        for i in map(int, np.flatnonzero(up | dn)):
            sgn = 1 if up[i] else -1
            lvl = level_hi[i] if sgn > 0 else level_lo[i]
            stp = level_lo[i] if sgn > 0 else level_hi[i]
            if not np.isfinite(stp):
                continue
            for j in range(i, min(i + p.window, n)):
                if (c[j] - lvl) * sgn <= 0:
                    break
                d[j] = sgn
                trig[j] = fr.high[j] if sgn > 0 else fr.low[j]
                inval[j], stop[j] = lvl, stp
        return SetupOutput(
            data.on_close(role, d, 0).astype("int8"),
            data.on_close(role, trig, np.nan),
            data.on_close(role, inval, np.nan),
            data.on_close(role, stop, np.nan),
            {"dow_continuation": data.on_close(role, d, 0) != 0},
            {"level": data.on_close(role, inval, np.nan)},
        )


# -------------------------------------------------------- binary scenario
class BinaryScenarioParams(BoxParams):
    side: Literal["long", "short"] = Field("long", description="سمت: خرید بالای باکس / فروش زیر آن")
    refresh_bars: int = Field(
        0, ge=0, description="هر چند کندل ستاپ تازه شود (۰: یک بار برای هر باکس)"
    )


@register
class BinaryScenario(SetupBlock[BinaryScenarioParams]):
    """Both scenarios of a box, armed at once (blueprint 09, video 87).

    Use one instance per side. When a box is confirmed, the long arms a stop-buy at the top
    edge and the short a stop-sell at the bottom edge (stop and invalidation on the far
    edge); whichever breaks first fills, and the Execution Block's ``oco`` cancels the other
    ("discard the alternate path without regret"). Give the pair the same expiry and allow
    two positions per symbol. The scenarios' volume and RSI readings (volume expansion,
    RSI beyond 70 / 30) are Confirmation Blocks attached with ``only_setups``: they judge
    the candidate when it is armed. Unlike ``box_extremes`` the pair is armed once per box
    unless ``refresh_bars`` asks for more.
    """

    kind = BlockKind.SETUP
    type = "binary_scenario"
    title_fa = "سناریوی دوگانه (استاپ خرید و فروش هم‌زمان)"
    sources = ("tcp-blueprint 09: video 87 (binary scenario engine)",)
    Params = BinaryScenarioParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p, role = self.p, self.p.timeframe
        t = p.track(data, 1)
        first = t.in_box & ~_lag(t.in_box.astype(float), 1, 0.0).astype(bool)
        due = first if p.refresh_bars == 0 else t.in_box & (t.age % p.refresh_bars == 0)
        long_ = p.side == "long"
        near, far = (t.top, t.bottom) if long_ else (t.bottom, t.top)
        d = data.on_close(role, due.astype("int8"), 0).astype("int8") * (1 if long_ else -1)
        trigger = data.on_close(role, np.where(due, near, np.nan), np.nan)
        stop = data.on_close(role, np.where(due, far, np.nan), np.nan)
        return SetupOutput(
            d.astype("int8"),
            trigger,
            stop.copy(),
            stop,
            {"binary_scenario": d != 0},
            {"level": trigger.copy()},
        )


# ------------------------------------------------ momentum continuation mode
class MomentumContinuationParams(BlockParams):
    roles: list[Role] = Field(
        default_factory=lambda: list[Role](["lwc", "mwc"]),
        description="تایم‌فریم‌هایی که هم‌زمان باید مومنتوم قوی داشته باشند (hwc, mwc, lwc)",
    )
    rsi_period: int = Field(14, ge=2, description="دورهٔ RSI")
    rsi_long: float = Field(70.0, gt=0, lt=100, description="RSI بالاتر از این: مومنتوم صعودی قوی")
    rsi_short: float = Field(
        30.0, gt=0, lt=100, description="RSI پایین‌تر از این: مومنتوم نزولی قوی"
    )
    micro: Literal["sma_pullback", "prior_high", "either"] = Field(
        "sma_pullback", description="نوع ریزستاپ: پولبک به SMA کوتاه، شکست سقف کندل قبل، یا هر دو"
    )
    sma_period: int = Field(7, ge=2, description="SMA کوتاه برای پولبک")


@register
class MomentumContinuation(SetupBlock[MomentumContinuationParams]):
    """In strong multi-timeframe momentum any valid micro-setup triggers (blueprint 07, video 66).

    Strong momentum is RSI beyond ``rsi_long`` (below ``rsi_short``) on *every* listed
    timeframe at once (their latest closed bars). Then, on the LWC bars, a micro-setup
    is enough: a minor pullback whose low touches the short SMA while the bar closes back
    above it (``sma_pullback``), or a bar that takes out the prior bar's extreme (``prior_high``), or either. Trigger at the bar's high (low for shorts);
    invalidation and stop at its other end. Deep pullbacks do not occur in these runs.
    """

    kind = BlockKind.SETUP
    type = "momentum_continuation"
    title_fa = "حالت ادامهٔ مومنتوم (هر ریزستاپ معتبر)"
    sources = ("tcp-blueprint 07: video 66 (never get left behind: continuation mode)",)
    Params = MomentumContinuationParams

    def compute(self, data: StrategyData) -> SetupOutput:
        p = self.p
        f = data.base
        h, lo, c = f.high, f.low, f.close
        strong_up = np.ones(len(c), bool)
        strong_dn = np.ones(len(c), bool)
        for r in dict.fromkeys(p.roles):
            r_rsi = data.aligned(r, rsi(data.frames[r].close, p.rsi_period), np.nan)
            with np.errstate(invalid="ignore"):
                strong_up &= r_rsi > p.rsi_long
                strong_dn &= r_rsi < p.rsi_short
        m = sma(c, p.sma_period)
        with np.errstate(invalid="ignore"):
            pull_up = (lo <= m) & (c > m)
            pull_dn = (h >= m) & (c < m)
        with np.errstate(invalid="ignore"):
            break_up, break_dn = h > _lag(h, 1), lo < _lag(lo, 1)
        use_pull, use_break = p.micro != "prior_high", p.micro != "sma_pullback"
        up = (pull_up & use_pull) | (break_up & use_break)
        dn = (pull_dn & use_pull) | (break_dn & use_break)
        return candle_setup(strong_up & up, strong_dn & dn, h, lo, "momentum_continuation")


# ------------------------------------------------------------- chase guard
class ChaseGuardParams(BlockParams):
    timeframe: Role = Field("lwc", description="تایم‌فریمی که کندل بزرگ روی آن سنجیده می‌شود")
    lookback: int = Field(20, ge=2, description="کندل‌های قبلی برای دامنهٔ عادی")
    multiple: float = Field(
        3.0, gt=1, description="کندل با دامنه بیش از این ضریبِ عادی، ایمپالس است"
    )
    cooldown_bars: int = Field(1, ge=1, description="پس از ایمپالس تا چند کندل ورود تازه رد شود")
    same_direction_only: bool = Field(
        True, description="فقط ورود هم‌جهت با ایمپالس رد شود (تعقیب)، نه برگشت"
    )


@register
class ChaseGuard(ContextBlock[ChaseGuardParams]):
    """No chasing after an outsized bar (blueprint 07, video 64).

    A bar whose range exceeds ``multiple`` x the mean range of the ``lookback`` bars
    before it is an outsized impulse: the stop behind it is too far for a sound R:R. From
    its close, and for ``cooldown_bars`` bars of ``timeframe``, no new candidate is
    accepted in its direction (both directions when ``same_direction_only`` is off).
    Resting orders placed before the bar are not touched: the blueprint says to trade only
    through triggers anchored at the boundary *before* the displacement.
    """

    kind = BlockKind.CONTEXT
    type = "chase_guard"
    title_fa = "ضد تعقیب (پس از کندل غول‌پیکر)"
    sources = ("tcp-blueprint 07: video 64 (the elimination of chasing)",)
    Params = ChaseGuardParams

    def compute(self, data: StrategyData) -> ContextOutput:
        p, role = self.p, self.p.timeframe
        fr = data.frames[role]
        span = fr.high - fr.low
        with np.errstate(invalid="ignore"):
            big = span > p.multiple * _prior_mean(span, p.lookback)
        up = big & (fr.close > fr.open)
        dn = big & (fr.close < fr.open)
        k = p.cooldown_bars

        def hold(x: np.ndarray) -> np.ndarray:
            return pd.Series(x.astype(float)).rolling(k, min_periods=1).max().to_numpy() > 0

        block_long, block_short = (
            (hold(up), hold(dn)) if p.same_direction_only else (hold(big),) * 2
        )
        return ContextOutput(
            data.aligned(role, ~block_long, True),
            data.aligned(role, ~block_short, True),
            {"outsized": data.aligned(role, big, False)},
        )
