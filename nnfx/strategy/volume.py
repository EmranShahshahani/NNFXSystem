"""Volume rules as Confirmation Blocks (Strategy Builder ticket 17, ADR 10 §21).

Videos 29-33. Every threshold is *relative*: volume against the mean of the bars before
it, a body against the ATR, a range against the mean range before it. There is no absolute
volume constant, so the rules mean the same on any venue, symbol and price level. A venue
that reports no volume (``volume_kind == "none"``) gives ``na``, never a pass.

====================  ==========================================================
Block                 What it checks
====================  ==========================================================
``volume_matrix``     the four-state price/volume matrix agrees with the trade
                      (divergences block entries, video 29)
``effort_result``     no suspicious bar lately: big volume on a doji (absorption)
                      or a big body on light volume (vacuum) (video 33)
``volume_climax``     no climax in the trade's direction lately (video 30, 31)
``low_volume_dip``    volume sank to a multi-bar low just before the candidate:
                      lack of participation (video 30, 31)
``volume_node``       no heavy node of the 200-bar volume profile just ahead
                      (video 32)
====================  ==========================================================

Climaxes also drive the Profit Chain's ``climax_exit`` (see ``library.ProfitChain``).
A candidate stands on the latest closed bar of the Block's ``role``; every series is
causal (a bar is compared only with the bars before it, or the bars up to it).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import Field

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

NO_VOLUME = "the venue reports no volume"


def has_volume(data: StrategyData, role: str) -> bool:
    return data.frames[role].volume_kind != "none"


def _prior_mean(x: np.ndarray, lookback: int) -> np.ndarray:
    """Mean of the ``lookback`` bars before each bar (NaN until they exist)."""
    return pd.Series(x).shift(1).rolling(lookback, min_periods=lookback).mean().to_numpy()


def _ratio(x: np.ndarray, base: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(np.where(base > 0, x / base, np.nan))


def volume_ratio(data: StrategyData, role: str, lookback: int) -> np.ndarray:
    """Each ``role`` bar's volume over the mean of the ``lookback`` bars before it."""

    def make() -> np.ndarray:
        v = data.frames[role].volume
        return _ratio(v, _prior_mean(v, lookback))

    return data.memo(("vol_ratio", role, lookback), make)


def range_ratio(data: StrategyData, role: str, lookback: int) -> np.ndarray:
    """Each ``role`` bar's high-low range over the mean range of the bars before it."""

    def make() -> np.ndarray:
        f = data.frames[role]
        r = f.high - f.low
        return _ratio(r, _prior_mean(r, lookback))

    return data.memo(("range_ratio", role, lookback), make)


def fresh(flags: np.ndarray, m: int, bars: int) -> bool:
    """Whether ``flags`` is set on any of the ``bars`` bars ending at ``m``."""
    return bool(m >= 0 and flags[max(0, m - bars + 1) : m + 1].any())


# ----------------------------------------------------------------- climax
def climaxes(
    data: StrategyData, role: str, lookback: int, factor: float, range_factor: float
) -> tuple[np.ndarray, np.ndarray]:
    """Buying and selling climax bars: volume and range both far above their baseline.

    A buying climax closes up (a blow-off top), a selling climax closes down (capitulation);
    a bar that closes where it opened is neither.
    """

    def make() -> tuple[np.ndarray, np.ndarray]:
        f = data.frames[role]
        with np.errstate(invalid="ignore"):
            big = (volume_ratio(data, role, lookback) >= factor) & (
                range_ratio(data, role, lookback) >= range_factor
            )
            return big & (f.close > f.open), big & (f.close < f.open)

    return data.memo(("climax", role, lookback, factor, range_factor), make)


def climax_at(
    data: StrategyData,
    role: str,
    m: int,
    d: int,
    *,
    lookback: int,
    factor: float,
    range_factor: float,
    bars: int = 1,
) -> bool:
    """A climax in the direction ``d`` (buying for longs) within ``bars`` bars ending at ``m``."""
    if m < 0 or not has_volume(data, role):
        return False
    buying, selling = climaxes(data, role, lookback, factor, range_factor)
    return fresh(buying if d > 0 else selling, m, bars)


class VolumeParams(ConfirmationParams):
    role: Role = Field("lwc", description="تایم‌فریمی که حجم روی آن خوانده می‌شود")
    lookback: int = Field(20, ge=2, description="تعداد کندل‌های پیش از هر کندل برای خط پایهٔ حجم")


class VolumeBlock[P: VolumeParams](ConfirmationBlock[P]):
    """A Confirmation over one role's volume, read at the role bar the candidate stands on."""

    kind = BlockKind.CONFIRMATION

    def stand(self, candidate: SetupCandidate, data: StrategyData) -> int:
        return int(data.positions[self.p.role][candidate.bar])


# ----------------------------------------------------------------- matrix
class VolumeMatrixParams(VolumeParams):
    bars: int = Field(5, ge=1, description="پنجرهٔ مقایسهٔ قیمت و حجم (کندل)")
    margin: float = Field(
        0.1, ge=0, description="حجم باید دست‌کم این کسر بیش یا کم‌تر از پنجرهٔ قبل باشد"
    )
    move_atr: float = Field(0.5, ge=0, description="حرکت قیمت در پنجره دست‌کم این‌قدر ATR باشد")


def matrix_state(
    data: StrategyData, role: str, bars: int, margin: float, move_atr: float
) -> tuple[np.ndarray, np.ndarray]:
    """Per bar the direction of price and of volume over the last ``bars`` bars (0: flat/unknown).

    Price: the close against the close ``bars`` bars ago, beyond ``move_atr`` ATR. Volume:
    the mean of the last ``bars`` bars against the mean of the ``bars`` before them.
    """

    def make() -> tuple[np.ndarray, np.ndarray]:
        f = data.frames[role]
        move = f.close - pd.Series(f.close).shift(bars).to_numpy()
        rng = data.atr(role)
        v = pd.Series(f.volume)
        now = v.rolling(bars, min_periods=bars).mean()
        before = now.shift(bars)
        with np.errstate(invalid="ignore"):
            price = np.where(np.abs(move) >= move_atr * rng, np.sign(move), 0.0)
            vol = np.where(
                now > before * (1 + margin), 1.0, np.where(now < before * (1 - margin), -1.0, 0.0)
            )
        return np.nan_to_num(price).astype("int8"), np.nan_to_num(vol).astype("int8")

    return data.memo(("vol_matrix", role, bars, margin, move_atr), make)


STATE_NAMES = {
    (1, 1): "bullish confirmation (price up, volume up)",
    (1, -1): "bearish divergence (price up, volume down)",
    (-1, 1): "bearish confirmation (price down, volume up)",
    (-1, -1): "bullish divergence (price down, volume down)",
}


@register
class VolumeMatrix(VolumeBlock[VolumeMatrixParams]):
    """The four-state volume matrix as a filter (video 29).

    Price up on rising volume and price down on falling volume (selling exhausted)
    favour longs; price up on falling volume (buyers drying up) and price down on rising
    volume favour shorts. A candidate against the matrix's side fails. Inside a box
    volume drying up is compression, not weakness, so a Box Breakout candidate is
    ``na``; so is a flat price or volume.
    """

    type = "volume_matrix"
    title_fa = "ماتریس حجم و قیمت"
    sources = ("tcp-blueprint 03: video 29 (four-state volume matrix)",)
    Params = VolumeMatrixParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        if not has_volume(data, p.role):
            return CheckResult("na", NO_VOLUME)
        if "box_breakout" in candidate.tags:
            return CheckResult("na", "inside a box, quiet volume is compression, not weakness")
        m = self.stand(candidate, data)
        if m < 0:
            return CheckResult("na", f"no closed {p.role} bar yet")
        price, vol = matrix_state(data, p.role, p.bars, p.margin, p.move_atr)
        pr, vo = int(price[m]), int(vol[m])
        if pr == 0 or vo == 0:
            return CheckResult("na", "price or volume is flat: no matrix state")
        side = pr * vo  # +1 favours longs, -1 shorts
        name = STATE_NAMES[(pr, vo)]
        return CheckResult("pass" if side == candidate.direction else "fail", name)


# ----------------------------------------------------------- effort/result
class EffortResultParams(VolumeParams):
    anomaly: Literal["both", "absorption", "vacuum"] = Field(
        "both", description="کدام ناهنجاری رد کند: جذب، خلأ نقدینگی، یا هر دو"
    )
    heavy: float = Field(2.0, gt=0, description="جذب: حجم دست‌کم این ضریبِ خط پایه")
    small_body_atr: float = Field(0.3, ge=0, description="جذب: بدنه حداکثر این‌قدر ATR (دوجی)")
    big_body_atr: float = Field(1.5, gt=0, description="خلأ: بدنه دست‌کم این‌قدر ATR")
    light: float = Field(0.8, gt=0, description="خلأ: حجم حداکثر این ضریبِ خط پایه")
    fresh_bars: int = Field(1, ge=1, description="ناهنجاری در این تعداد کندل اخیر دیده شود")


def effort_flags(data: StrategyData, p: EffortResultParams) -> tuple[np.ndarray, np.ndarray]:
    """Absorption bars (heavy volume, tiny body) and vacuum bars (big body, light volume)."""

    def make() -> tuple[np.ndarray, np.ndarray]:
        f = data.frames[p.role]
        body = np.abs(f.close - f.open)
        rng = data.atr(p.role)
        ratio = volume_ratio(data, p.role, p.lookback)
        with np.errstate(invalid="ignore"):
            return (
                (ratio >= p.heavy) & (body <= p.small_body_atr * rng),
                (ratio <= p.light) & (body >= p.big_body_atr * rng),
            )

    key = ("effort", p.role, p.lookback, p.heavy, p.small_body_atr, p.big_body_atr, p.light)
    return data.memo(key, make)


@register
class EffortResult(VolumeBlock[EffortResultParams]):
    """Effort against result (video 33): a bar whose volume and body disagree is suspect.

    *Absorption*: abnormal volume with a compressed body, aggressive orders met by
    passive walls (hidden distribution in an uptrend). *Vacuum*: an outsized body on
    below-average volume, price sliding through an empty book with a sharp retest to
    follow. Either within ``fresh_bars`` bars fails the candidate; ``na`` without
    volume or history.
    """

    type = "effort_result"
    title_fa = "تلاش در برابر نتیجه"
    sources = ("tcp-blueprint 04: video 33 (effort vs result, absorption and vacuum)",)
    Params = EffortResultParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        if not has_volume(data, p.role):
            return CheckResult("na", NO_VOLUME)
        m = self.stand(candidate, data)
        if m < p.lookback:
            return CheckResult("na", f"needs {p.lookback} bars of volume history")
        absorption, vacuum = effort_flags(data, p)
        if p.anomaly in ("both", "absorption") and fresh(absorption, m, p.fresh_bars):
            return CheckResult("fail", "absorption: heavy volume with a compressed body")
        if p.anomaly in ("both", "vacuum") and fresh(vacuum, m, p.fresh_bars):
            return CheckResult("fail", "liquidity vacuum: a big body on light volume")
        return CheckResult("pass", "volume and body agree")


# ------------------------------------------------------------------ climax
class VolumeClimaxParams(VolumeParams):
    factor: float = Field(3.0, gt=1, description="حجم دست‌کم این ضریبِ خط پایه (۳ تا ۵)")
    range_factor: float = Field(1.8, gt=1, description="دامنه دست‌کم این ضریبِ میانگین دامنه")
    fresh_bars: int = Field(3, ge=1, description="اوج‌گیری در این تعداد کندل اخیر دیده شود")


@register
class VolumeClimax(VolumeBlock[VolumeClimaxParams]):
    """No buying into a climax (video 30, 31).

    A climax is volume at least ``factor`` x its baseline (3-5x) on an outsized range
    bar. A buying climax within ``fresh_bars`` bars fails a long, a selling climax a
    short: it marks the cycle's top (bottom), so the move is spent. ``na`` without
    volume or history. The Profit Chain's ``climax_exit`` takes profit on the same bar.
    """

    type = "volume_climax"
    title_fa = "اوج‌گیری حجم (کلایمکس)"
    sources = ("tcp-blueprint 03/04: videos 30, 31 (buying and selling climax)",)
    Params = VolumeClimaxParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        if not has_volume(data, p.role):
            return CheckResult("na", NO_VOLUME)
        m = self.stand(candidate, data)
        if m < p.lookback:
            return CheckResult("na", f"needs {p.lookback} bars of volume history")
        if climax_at(
            data, p.role, m, candidate.direction, lookback=p.lookback, factor=p.factor,
            range_factor=p.range_factor, bars=p.fresh_bars,
        ):  # fmt: skip
            word = "buying" if candidate.direction > 0 else "selling"
            return CheckResult("fail", f"a {word} climax within {p.fresh_bars} bars")
        return CheckResult("pass", "no climax in the trade's direction")


# --------------------------------------------------------------- low volume
class LowVolumeDipParams(VolumeParams):
    low: float = Field(0.6, gt=0, lt=1, description="حجم حداکثر این ضریبِ خط پایه شود")
    bars: int = Field(5, ge=1, description="افت حجم در این تعداد کندل پیش از کندل ستاپ باشد")


def low_volume_dips(data: StrategyData, role: str, lookback: int, low: float) -> np.ndarray:
    """Bars whose volume is a ``lookback``-bar low and at most ``low`` x the baseline."""

    def make() -> np.ndarray:
        v = data.frames[role].volume
        floor = pd.Series(v).rolling(lookback, min_periods=lookback).min().to_numpy()
        with np.errstate(invalid="ignore"):
            return np.asarray((volume_ratio(data, role, lookback) <= low) & (v <= floor))

    return data.memo(("low_vol_dip", role, lookback, low), make)


@register
class LowVolumeDip(VolumeBlock[LowVolumeDipParams]):
    """Participation dried up before the candidate (video 30, 31).

    Price crawling into a level on volume at a multi-bar low means nobody is committed
    to the continuation. Passes when one of the ``bars`` bars before the candidate bar
    had volume at a ``lookback``-bar low and under ``low`` x the baseline. The dip alone
    is no entry: the candidate is the displacement that follows it, so pair this with
    reversal setups (``only_setups``) and ``level_location``.
    """

    type = "low_volume_dip"
    title_fa = "افت حجم پیش از برگشت"
    sources = ("tcp-blueprint 03/04: videos 30, 31 (low-volume reversal)",)
    Params = LowVolumeDipParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p = self.p
        if not has_volume(data, p.role):
            return CheckResult("na", NO_VOLUME)
        m = self.stand(candidate, data)
        if m < p.lookback + 1:
            return CheckResult("na", f"needs {p.lookback} bars of volume history")
        dips = low_volume_dips(data, p.role, p.lookback, p.low)
        if fresh(dips, m - 1, p.bars):
            return CheckResult("pass", f"volume sank to a {p.lookback}-bar low just before")
        return CheckResult("fail", f"no volume dip in the {p.bars} bars before")


# ----------------------------------------------------------------- profile
class VolumeNodeParams(VolumeParams):
    role: Role = Field("mwc", description="تایم‌فریمی که پروفایل حجمی روی آن ساخته می‌شود")
    window: int = Field(200, ge=20, description="تعداد کندل‌های پروفایل حجمی")
    bins: int = Field(40, ge=5, description="تعداد سطل‌های قیمتی پروفایل")
    node_factor: float = Field(2.0, gt=1, description="گرهٔ سنگین: حجم سطل دست‌کم این ضریبِ میانگین")
    clear_atr: float = Field(
        1.0, gt=0, description="مسیر پیش‌رو این‌قدر ATR از قیمت ورود باید خالی باشد"
    )


def volume_profile(
    high: np.ndarray, low: np.ndarray, volume: np.ndarray, bins: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """The horizontal volume profile: (bin edges, volume per bin); None for a flat range.

    A bar's volume is spread equally over the bins its high-low range touches.
    """
    lo, hi = float(np.min(low)), float(np.max(high))
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    out = np.zeros(bins)
    first = np.clip(np.searchsorted(edges, low, side="right") - 1, 0, bins - 1)
    last = np.clip(np.searchsorted(edges, high, side="right") - 1, 0, bins - 1)
    for a, b, v in zip(first, last, volume, strict=True):
        out[a : b + 1] += v / (b - a + 1)
    return edges, out


@register
class VolumeNode(VolumeBlock[VolumeNodeParams]):
    """A heavy node of the volume profile just ahead is a barrier (video 32).

    The profile covers the ``window`` closed bars up to the candidate's role bar. A node
    is a bin holding at least ``node_factor`` x the mean bin volume; the candidate fails
    when one lies within ``clear_atr`` ATR beyond its trigger, in the trade's direction
    (large resting orders there absorb the move). ``na`` without volume or ``window``
    bars of history.
    """

    type = "volume_node"
    title_fa = "گرهٔ پروفایل حجمی پیش‌رو"
    sources = ("tcp-blueprint 04: video 32 (200-bar volume profile, high-volume nodes)",)
    Params = VolumeNodeParams

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        p, d = self.p, candidate.direction
        if not has_volume(data, p.role):
            return CheckResult("na", NO_VOLUME)
        m = self.stand(candidate, data)
        reach = data.atr(p.role)[m] if m >= 0 else np.nan
        if m < p.window - 1 or not np.isfinite(reach):
            return CheckResult("na", f"needs {p.window} bars of volume history")
        f = data.frames[p.role]
        sl = slice(m - p.window + 1, m + 1)
        prof = volume_profile(f.high[sl], f.low[sl], f.volume[sl], p.bins)
        if prof is None:
            return CheckResult("na", "the profile window has no price range")
        edges, vol = prof
        centres = (edges[:-1] + edges[1:]) / 2.0
        ahead = (centres - candidate.trigger) * d
        near = (ahead > 0) & (ahead <= p.clear_atr * reach)
        heavy = vol >= p.node_factor * vol.mean()
        if np.any(near & heavy):
            price = float(centres[near & heavy][0 if d > 0 else -1])
            return CheckResult("fail", f"a heavy volume node at {price:.6g} lies ahead")
        return CheckResult("pass", f"no heavy node within {p.clear_atr:g} ATR ahead")
