"""The rest of the doc 05 candidate pool (previously ``catalogue.PLANNED``).

Same rules as ``library``: causal, published defaults, small grids, every
threshold dimensionless or ATR/percentage-relative. Where a published indicator
is directional but sits in the (non-directional) volume slot, the wrapper gates
on the *strength* of its reading, and says so. Where a published formula has a
price-scale constant (TDFI's x1000) it is dropped when it cancels exactly.
"""

from __future__ import annotations

import math

import numpy as np

from nnfx.data.bars import BarFrame
from nnfx.indicators import _math as m
from nnfx.indicators.base import Baseline, Confirmation, Exit, Volatility, Volume, register

Arr = np.ndarray


def _atr(bars: BarFrame, n: int = 14) -> Arr:
    return m.rma(m.true_range(bars.high, bars.low, bars.close), n)


def _std(x: Arr, n: int) -> Arr:
    return m._s(x).rolling(n, min_periods=n).std(ddof=0).to_numpy()


def _ewm_alpha(x: Arr, alpha: float) -> Arr:
    return m._s(x).ewm(alpha=alpha, adjust=False).mean().to_numpy()


def _rsi(c: Arr, n: int) -> Arr:
    d = np.diff(c, prepend=np.nan)
    up = m.rma(np.where(d > 0, d, 0.0), n)
    dn = m.rma(np.where(d < 0, -d, 0.0), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        rsi = np.where(up + dn > 0, 100 * up / (up + dn), 50.0)
    rsi[np.isnan(up)] = np.nan
    return np.asarray(rsi)


def _stoch(x: Arr, hi: Arr, lo: Arr, n: int) -> Arr:
    hh, ll = m.rolling_max(hi, n), m.rolling_min(lo, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(hh - ll > 0, 100 * (x - ll) / (hh - ll), 50.0) + np.where(
            np.isnan(hh), np.nan, 0.0
        )


def _hold_state(up: Arr, down: Arr, valid: Arr) -> Arr:
    """+1 on ``up``, -1 on ``down``, otherwise hold; 0 until ``valid``."""
    st = np.zeros(len(up), dtype="int8")
    d = 0
    for i in range(len(up)):
        if not valid[i]:
            d = 0
        elif up[i]:
            d = 1
        elif down[i]:
            d = -1
        st[i] = d
    return st


# ============================================================== volatility


@register("volatility", "keltner_width")
class KeltnerWidth(Volatility):
    """Keltner's band half-width: an EMA of the daily high-low range (no gap term)."""

    family = "range"
    defaults = {"period": 20}
    grid = {"period": (10, 20, 30)}

    def value(self, bars: BarFrame) -> Arr:
        return m.ema(bars.high - bars.low, self.p["period"])


@register("volatility", "garman_klass")
class GarmanKlass(Volatility):
    """OHLC estimator, in price units on the same scale as ``parkinson``."""

    family = "range_estimator"
    defaults = {"period": 20}
    grid = {"period": (14, 20, 30)}

    def value(self, bars: BarFrame) -> Arr:
        hl = np.log(bars.high / bars.low) ** 2
        co = np.log(bars.close / bars.open) ** 2
        var = m.sma(0.5 * hl - (2 * math.log(2) - 1) * co, self.p["period"])
        return np.asarray(bars.close * np.sqrt(np.maximum(var, 0.0)) * 1.6)


@register("volatility", "yang_zhang")
class YangZhang(Volatility):
    """Gap-aware estimator: overnight + open-to-close + Rogers-Satchell."""

    family = "range_estimator"
    defaults = {"period": 20}
    grid = {"period": (14, 20, 30)}

    def value(self, bars: BarFrame) -> Arr:
        n = self.p["period"]
        o, h, lo, c = bars.open, bars.high, bars.low, bars.close
        on = np.log(o / m.shift(c))
        oc = np.log(c / o)
        rs = np.log(h / c) * np.log(h / o) + np.log(lo / c) * np.log(lo / o)
        k = 0.34 / (1.34 + (n + 1) / (n - 1))
        vo = m._s(on).rolling(n, min_periods=n).var(ddof=1).to_numpy()
        vc = m._s(oc).rolling(n, min_periods=n).var(ddof=1).to_numpy()
        var = vo + k * vc + (1 - k) * m.sma(rs, n)
        return np.asarray(c * np.sqrt(np.maximum(var, 0.0)) * 1.6)


# ================================================================ baseline


def _t3_combine(x: Arr, alpha: float, v: float) -> Arr:
    e = x
    es = []
    for _ in range(6):
        e = _ewm_alpha(e, alpha)
        es.append(e)
    c1 = -(v**3)
    c2 = 3 * v**2 + 3 * v**3
    c3 = -6 * v**2 - 3 * v - 3 * v**3
    c4 = 1 + 3 * v + v**3 + 3 * v**2
    return np.asarray(c1 * es[5] + c2 * es[4] + c3 * es[3] + c4 * es[2])


@register("baseline", "t3")
class T3(Baseline):
    """Tillson T3: six cascaded EMAs combined with volume factor ``vfactor``."""

    family = "moving_average"
    defaults = {"period": 5, "vfactor": 0.7}
    grid = {"period": (5, 8, 13), "vfactor": (0.5, 0.7, 0.9)}

    def line(self, bars: BarFrame) -> Arr:
        n = self.p["period"]
        out = _t3_combine(bars.close, 2 / (n + 1), self.p["vfactor"])
        out[: 6 * (n - 1)] = np.nan
        return out


@register("baseline", "vidya")
class VIDYA(Baseline):
    """Chande's variable index dynamic average: EMA speed scaled by |CMO|."""

    family = "adaptive_ma"
    defaults = {"period": 14, "cmo_period": 9}
    grid = {"period": (10, 14, 21), "cmo_period": (9, 14)}

    def line(self, bars: BarFrame) -> Arr:
        c = bars.close
        n, k = self.p["period"], self.p["cmo_period"]
        d = np.diff(c, prepend=np.nan)
        up = m.rolling_sum(np.where(d > 0, d, 0.0), k)
        dn = m.rolling_sum(np.where(d < 0, -d, 0.0), k)
        with np.errstate(invalid="ignore", divide="ignore"):
            cmo = np.where(up + dn > 0, np.abs(up - dn) / (up + dn), 0.0)
        a = 2 / (n + 1)
        out = np.full(len(c), np.nan)
        start = max(n, k)
        if len(c) > start:
            out[start] = c[start]
            for i in range(start + 1, len(c)):
                ak = a * cmo[i]
                out[i] = ak * c[i] + (1 - ak) * out[i - 1]
        return out


@register("baseline", "ssl_channel_baseline")
class SSLChannelBaseline(Baseline):
    """The SSL channel as a line: the SMA(low) under price in an up state, SMA(high) above in a down state."""

    family = "hl_channel"
    defaults = {"period": 10}
    grid = {"period": (7, 10, 14, 20)}

    def line(self, bars: BarFrame) -> Arr:
        from nnfx.indicators.library import _ssl_state

        n = self.p["period"]
        st = _ssl_state(bars, n)
        sh, sl = m.sma(bars.high, n), m.sma(bars.low, n)
        return np.asarray(np.where(st == 1, sl, np.where(st == -1, sh, np.nan)))


@register("baseline", "range_filter")
class RangeFilter(Baseline):
    """Range filter: the line moves only when close escapes a smoothed-range band."""

    family = "range_filter"
    defaults = {"period": 100, "multiplier": 3.0}
    grid = {"period": (50, 100, 150), "multiplier": (2.0, 3.0, 4.0)}

    def line(self, bars: BarFrame) -> Arr:
        c = bars.close
        n = self.p["period"]
        avrng = m.ema(np.abs(c - m.shift(c)), n)
        # Second pass starts as soon as the first is defined (as published), so warmup is n bars.
        rng = m._s(avrng).ewm(span=2 * n - 1, adjust=False).mean().to_numpy() * self.p["multiplier"]
        out = np.full(len(c), np.nan)
        f = np.nan
        for i in range(len(c)):
            if np.isnan(rng[i]):
                continue
            if np.isnan(f):
                f = c[i]
            elif c[i] > f:
                f = max(f, c[i] - rng[i])
            else:
                f = min(f, c[i] + rng[i])
            out[i] = f
        return out


@register("baseline", "ehlers_supersmoother")
class SuperSmoother(Baseline):
    """Ehlers' two-pole super smoother filter."""

    family = "dsp_filter"
    defaults = {"period": 10}
    grid = {"period": (8, 10, 14, 20)}

    def line(self, bars: BarFrame) -> Arr:
        n = self.p["period"]
        x = bars.close
        a1 = math.exp(-math.sqrt(2) * math.pi / n)
        b1 = 2 * a1 * math.cos(math.sqrt(2) * math.pi / n)
        c2, c3 = b1, -(a1**2)
        c1 = 1 - c2 - c3
        f = np.array(x, dtype="float64")
        for i in range(2, len(x)):
            f[i] = c1 * (x[i] + x[i - 1]) / 2 + c2 * f[i - 1] + c3 * f[i - 2]
        f[: min(n, len(f))] = np.nan
        return f


# ============================================================ confirmation


@register("confirmation", "schaff_trend_cycle")
class SchaffTrendCycle(Confirmation):
    """MACD put through two smoothed stochastics; stance = STC above/below 50."""

    family = "cycle_oscillator"
    defaults = {"fast": 23, "slow": 50, "cycle": 10, "factor": 0.5}
    grid = {"cycle": (8, 10, 12), "fast": (20, 23, 26)}

    def state(self, bars: BarFrame) -> Arr:
        c = bars.close
        n, fct = self.p["cycle"], self.p["factor"]
        macd = m.ema(c, self.p["fast"]) - m.ema(c, self.p["slow"])

        def smoothed_stoch(x: Arr) -> Arr:
            k = _stoch(x, x, x, n)
            out = np.full(len(x), np.nan)
            prev = np.nan
            for i in range(len(x)):
                if np.isnan(k[i]):
                    continue
                prev = k[i] if np.isnan(prev) else prev + fct * (k[i] - prev)
                out[i] = prev
            return out

        stc = smoothed_stoch(smoothed_stoch(macd))
        return m.sign_state(stc - 50)


@register("confirmation", "coral_trend")
class CoralTrend(Confirmation):
    """Coral trend (T3-style cascade, 'sm' smoothing); stance = slope of the line."""

    family = "moving_average"
    defaults = {"period": 21, "coefficient": 0.4}
    grid = {"period": (14, 21, 34), "coefficient": (0.2, 0.4, 0.6)}

    def state(self, bars: BarFrame) -> Arr:
        n = self.p["period"]
        di = (n - 1) / 2 + 1
        line = _t3_combine(bars.close, 2 / (di + 1), self.p["coefficient"])
        slope = line - m.shift(line)
        slope[:n] = np.nan
        return m.sign_state(slope)


@register("confirmation", "half_trend")
class HalfTrend(Confirmation):
    """HalfTrend: trend flips when the HL averages break the running extreme."""

    family = "hl_channel"
    defaults = {"amplitude": 2}
    grid = {"amplitude": (2, 3, 4, 5)}

    def state(self, bars: BarFrame) -> Arr:
        a = self.p["amplitude"]
        h, lo, c = bars.high, bars.low, bars.close
        hp, lp = m.rolling_max(h, a), m.rolling_min(lo, a)
        hma, lma = m.sma(h, a), m.sma(lo, a)
        st = np.zeros(len(c), dtype="int8")
        trend, nxt = 0, 0
        max_low, min_high = np.nan, np.nan
        for i in range(len(c)):
            if np.isnan(hma[i]):
                continue
            if np.isnan(max_low):
                max_low, min_high = lo[i - 1] if i else lo[i], h[i - 1] if i else h[i]
            if nxt == 1:
                max_low = max(lp[i], max_low)
                if hma[i] < max_low and c[i] < lo[i - 1]:
                    trend, nxt, min_high = 1, 0, hp[i]
            else:
                min_high = min(hp[i], min_high)
                if lma[i] > min_high and c[i] > h[i - 1]:
                    trend, nxt, max_low = 0, 1, lp[i]
            st[i] = 1 if trend == 0 else -1
        return st


def _qqe_state(c: Arr, rsi_period: int, smoothing: int, factor: float) -> Arr:
    rsi_ma = m.ema(_rsi(c, rsi_period), smoothing)
    atr_rsi = np.abs(rsi_ma - m.shift(rsi_ma))
    dar = m.ema(m.ema(atr_rsi, 2 * rsi_period - 1), 2 * rsi_period - 1) * factor
    st = np.zeros(len(c), dtype="int8")
    lb = sb = np.nan
    trend = 0
    for i in range(1, len(c)):
        r, d = rsi_ma[i], dar[i]
        if np.isnan(r) or np.isnan(d):
            continue
        rp = rsi_ma[i - 1]
        new_l, new_s = r - d, r + d
        plb, psb = lb, sb
        lb = max(plb, new_l) if not np.isnan(plb) and rp > plb and r > plb else new_l
        sb = min(psb, new_s) if not np.isnan(psb) and rp < psb and r < psb else new_s
        if trend == 0:
            trend = 1 if r >= 50 else -1
        elif not np.isnan(psb) and r > psb and rp <= psb:
            trend = 1
        elif not np.isnan(plb) and r < plb and rp >= plb:
            trend = -1
        st[i] = trend
    return st


@register("confirmation", "qqe")
class QQE(Confirmation):
    """Quantitative qualitative estimation: smoothed RSI vs its ATR-of-RSI trailing bands."""

    family = "filtered_oscillator"
    defaults = {"rsi_period": 14, "smoothing": 5, "factor": 4.236}
    grid = {"rsi_period": (10, 14, 21), "factor": (2.618, 4.236, 5.0)}

    def state(self, bars: BarFrame) -> Arr:
        return _qqe_state(bars.close, self.p["rsi_period"], self.p["smoothing"], self.p["factor"])


@register("confirmation", "wave_trend")
class WaveTrend(Confirmation):
    """LazyBear WaveTrend: channel index of HLC3, stance = wt1 vs its 4-bar mean."""

    family = "channel_oscillator"
    defaults = {"channel": 10, "average": 21}
    grid = {"channel": (9, 10, 12), "average": (18, 21, 24)}

    def state(self, bars: BarFrame) -> Arr:
        ap = (bars.high + bars.low + bars.close) / 3
        esa = m.ema(ap, self.p["channel"])
        d = m.ema(np.abs(ap - esa), self.p["channel"])
        with np.errstate(invalid="ignore", divide="ignore"):
            ci = np.where(d > 0, (ap - esa) / (0.015 * d), 0.0)
        ci[np.isnan(d)] = np.nan
        wt1 = m.ema(ci, self.p["average"])
        return m.sign_state(wt1 - m.sma(wt1, 4))


@register("confirmation", "tdfi")
class TDFI(Confirmation):
    """Trend direction & force index; holds stance inside the +/-``trigger`` band."""

    family = "trend_force"
    defaults = {"lookback": 13, "trigger": 0.05}
    grid = {"lookback": (10, 13, 20), "trigger": (0.0, 0.05, 0.1)}

    def state(self, bars: BarFrame) -> Arr:
        n = self.p["lookback"]
        mma = m.ema(bars.close, n)
        smma = m.ema(mma, n)
        impet = ((mma - m.shift(mma)) + (smma - m.shift(smma))) / 2
        tdf = np.abs(mma - smma) * impet**3
        top = m.rolling_max(np.abs(tdf), 3 * n)
        with np.errstate(invalid="ignore", divide="ignore"):
            tdfi = np.where(top > 0, tdf / top, 0.0)
        tdfi[np.isnan(top)] = np.nan
        t = self.p["trigger"]
        return m.sign_state(np.where(np.abs(tdfi) > t, tdfi, np.where(np.isnan(tdfi), np.nan, 0.0)))


@register("confirmation", "kase_permission")
class KasePermission(Confirmation):
    """Kase permission stochastic, daily approximation.

    Kase reads the stochastic on a timeframe ``tf_mult`` times higher; on daily
    bars that is a ``length * tf_mult``-bar window, double-smoothed. Stance = fast
    line vs slow line.
    """

    family = "stochastic"
    defaults = {"length": 9, "tf_mult": 4, "smooth": 3}
    grid = {"length": (7, 9, 12), "tf_mult": (3, 4, 5)}

    def state(self, bars: BarFrame) -> Arr:
        w = self.p["length"] * self.p["tf_mult"]
        k = _stoch(bars.close, bars.high, bars.low, w)
        fast = m.ema(k, self.p["smooth"])
        slow = m.ema(fast, self.p["smooth"])
        return m.sign_state(fast - slow)


@register("confirmation", "ergodic_tvi")
class ErgodicTVI(Confirmation):
    """Blau's ergodic trade volume index from up/down-close volume; stance vs its signal."""

    family = "volume_momentum"
    defaults = {"r": 12, "s": 12, "signal": 5}
    grid = {"r": (8, 12, 16), "signal": (3, 5, 8)}
    notes = "needs real volume; with none the state stays 0"

    def state(self, bars: BarFrame) -> Arr:
        c, v = bars.close, bars.volume
        d = c - m.shift(c)
        up = np.where(d > 0, v, 0.0)
        dn = np.where(d < 0, v, 0.0)

        def ds(x: Arr) -> Arr:
            return m.ema(m.ema(x, self.p["r"]), self.p["s"])

        num, den = ds(up - dn), ds(up + dn)
        with np.errstate(invalid="ignore", divide="ignore"):
            tvi = np.where(den > 0, 100 * num / den, np.nan)
        return m.sign_state(tvi - m.ema(tvi, self.p["signal"]))


@register("confirmation", "trend_trigger_factor")
class TrendTriggerFactor(Confirmation):
    """Pee's TTF: buy power vs sell power of two adjacent N-bar windows."""

    family = "range_momentum"
    defaults = {"period": 15}
    grid = {"period": (10, 15, 20)}

    def state(self, bars: BarFrame) -> Arr:
        n = self.p["period"]
        hh, ll = m.rolling_max(bars.high, n), m.rolling_min(bars.low, n)
        bp = hh - m.shift(ll, n)
        sp = m.shift(hh, n) - ll
        with np.errstate(invalid="ignore", divide="ignore"):
            ttf = np.where(bp + sp != 0, 200 * (bp - sp) / (bp + sp), 0.0)
        ttf[np.isnan(bp) | np.isnan(sp)] = np.nan
        return m.sign_state(ttf)


@register("confirmation", "smi")
class SMI(Confirmation):
    """Stochastic momentum index (Blau); stance = SMI vs its EMA signal."""

    family = "stochastic"
    defaults = {"length": 10, "smooth": 3, "signal": 10}
    grid = {"length": (8, 10, 14), "signal": (5, 10)}

    def state(self, bars: BarFrame) -> Arr:
        n, s = self.p["length"], self.p["smooth"]
        hh, ll = m.rolling_max(bars.high, n), m.rolling_min(bars.low, n)
        rel = bars.close - (hh + ll) / 2
        num = m.ema(m.ema(rel, s), s)
        den = m.ema(m.ema(hh - ll, s), s) / 2
        with np.errstate(invalid="ignore", divide="ignore"):
            smi = np.where(den > 0, 100 * num / den, 0.0)
        smi[np.isnan(den)] = np.nan
        return m.sign_state(smi - m.ema(smi, self.p["signal"]))


@register("confirmation", "ttm_trend")
class TTMTrend(Confirmation):
    """TTM trend: close vs the mean of the last N bars' midpoints."""

    family = "hl_channel"
    defaults = {"period": 6}
    grid = {"period": (4, 6, 8, 10)}

    def state(self, bars: BarFrame) -> Arr:
        return m.sign_state(bars.close - m.sma((bars.high + bars.low) / 2, self.p["period"]))


# ================================================================== volume


@register("volume", "vpci")
class VPCI(Volume):
    """Volume price confirmation indicator; non-directional: |VPCI| above its own average."""

    family = "volume_price"
    defaults = {"short": 5, "long": 20, "signal": 8}
    grid = {"short": (3, 5, 8), "long": (14, 20, 30)}

    def gate(self, bars: BarFrame) -> Arr:
        c, v = bars.close, bars.volume
        s, ln = self.p["short"], self.p["long"]
        with np.errstate(invalid="ignore", divide="ignore"):
            vw_l = m.rolling_sum(c * v, ln) / m.rolling_sum(v, ln)
            vw_s = m.rolling_sum(c * v, s) / m.rolling_sum(v, s)
            vpc = vw_l - m.sma(c, ln)
            vpr = vw_s / m.sma(c, s)
            vm = m.sma(v, s) / m.sma(v, ln)
        mag = np.abs(vpc * vpr * vm)
        return np.asarray(np.nan_to_num(mag - m.ema(mag, self.p["signal"]), nan=-1.0) > 0)


@register("volume", "damiani_volatmeter")
class DamianiVolatmeter(Volume):
    """Trade when short/long ATR ratio clears ``threshold`` less the short/long stdev ratio."""

    family = "volatility_regime"
    defaults = {"vis_atr": 13, "vis_std": 20, "sed_atr": 40, "sed_std": 100, "threshold": 1.4}
    grid = {"vis_atr": (7, 13, 20), "threshold": (1.1, 1.4, 1.7)}

    def gate(self, bars: BarFrame) -> Arr:
        c = bars.close
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = _atr(bars, self.p["vis_atr"]) / _atr(bars, self.p["sed_atr"])
            anti = _std(c, self.p["vis_std"]) / _std(c, self.p["sed_std"])
        vol = np.full(len(c), np.nan)
        for i in range(len(c)):
            if np.isnan(ratio[i]):
                continue
            lag = (vol[i - 1] - vol[i - 3]) if i >= 3 and not np.isnan(vol[i - 3]) else 0.0
            vol[i] = ratio[i] + 0.5 * lag
        return np.asarray(np.nan_to_num(vol - (self.p["threshold"] - anti), nan=-1.0) > 0)


@register("volume", "volume_zone_oscillator")
class VolumeZoneOscillator(Volume):
    """VZO; non-directional: |VZO| beyond ``threshold`` per cent."""

    family = "volume"
    defaults = {"period": 14, "threshold": 15.0}
    grid = {"period": (10, 14, 21), "threshold": (5.0, 15.0, 25.0)}

    def gate(self, bars: BarFrame) -> Arr:
        c, v = bars.close, bars.volume
        sv = np.sign(c - m.shift(c)) * v
        with np.errstate(invalid="ignore", divide="ignore"):
            vzo = 100 * m.ema(np.nan_to_num(sv), self.p["period"]) / m.ema(v, self.p["period"])
        vzo[:1] = np.nan
        return np.asarray(np.nan_to_num(np.abs(vzo), nan=0.0) > self.p["threshold"])


@register("volume", "chaikin_money_flow")
class ChaikinMoneyFlow(Volume):
    """CMF; non-directional: |CMF| beyond ``threshold``."""

    family = "volume_price"
    defaults = {"period": 20, "threshold": 0.05}
    grid = {"period": (14, 20, 30), "threshold": (0.0, 0.05, 0.1)}

    def gate(self, bars: BarFrame) -> Arr:
        h, lo, c, v = bars.high, bars.low, bars.close, bars.volume
        with np.errstate(invalid="ignore", divide="ignore"):
            mfm = np.where(h > lo, ((c - lo) - (h - c)) / (h - lo), 0.0)
            cmf = m.rolling_sum(mfm * v, self.p["period"]) / m.rolling_sum(v, self.p["period"])
        return np.asarray(np.nan_to_num(np.abs(cmf), nan=0.0) > self.p["threshold"])


@register("volume", "mfi")
class MFI(Volume):
    """Money flow index; non-directional: |MFI - 50| beyond ``threshold``."""

    family = "volume_price"
    defaults = {"period": 14, "threshold": 10.0}
    grid = {"period": (10, 14, 21), "threshold": (5.0, 10.0, 20.0)}

    def gate(self, bars: BarFrame) -> Arr:
        tp = (bars.high + bars.low + bars.close) / 3
        flow = tp * bars.volume
        d = tp - m.shift(tp)
        n = self.p["period"]
        pos = m.rolling_sum(np.where(d > 0, flow, 0.0), n)
        neg = m.rolling_sum(np.where(d < 0, flow, 0.0), n)
        with np.errstate(invalid="ignore", divide="ignore"):
            mfi = np.where(pos + neg > 0, 100 * pos / (pos + neg), 50.0)
        mfi[np.isnan(pos)] = np.nan
        return np.asarray(np.nan_to_num(np.abs(mfi - 50), nan=0.0) > self.p["threshold"])


@register("volume", "klinger")
class Klinger(Volume):
    """Klinger volume oscillator; non-directional: |KVO| above |signal| (force expanding)."""

    family = "volume_force"
    defaults = {"fast": 34, "slow": 55, "signal": 13}
    grid = {"fast": (25, 34, 45), "signal": (9, 13, 21)}

    def gate(self, bars: BarFrame) -> Arr:
        h, lo, v = bars.high, bars.low, bars.volume
        tp = (h + lo + bars.close) / 3
        dm = h - lo
        vf = np.zeros(len(tp))
        cm = 0.0
        prev_trend = 0
        for i in range(1, len(tp)):
            trend = 1 if tp[i] > tp[i - 1] else -1
            cm = cm + dm[i] if trend == prev_trend else dm[i - 1] + dm[i]
            prev_trend = trend
            vf[i] = v[i] * abs(2 * (dm[i] / cm - 1)) * trend * 100 if cm > 0 else 0.0
        kvo = m.ema(vf, self.p["fast"]) - m.ema(vf, self.p["slow"])
        sig = m.ema(kvo, self.p["signal"])
        return np.asarray(np.nan_to_num(np.abs(kvo) - np.abs(sig), nan=-1.0) > 0)


@register("volume", "obv_slope")
class OBVSlope(Volume):
    """Regression slope of OBV over N bars, per average bar volume; gate on its magnitude."""

    family = "volume"
    defaults = {"period": 20, "threshold": 0.2}
    grid = {"period": (14, 20, 30), "threshold": (0.1, 0.2, 0.3)}

    def gate(self, bars: BarFrame) -> Arr:
        c, v = bars.close, bars.volume
        obv = np.cumsum(np.sign(np.nan_to_num(c - m.shift(c))) * v)
        n = self.p["period"]
        x = np.arange(n, dtype="float64") - (n - 1) / 2
        slope = (
            m._s(obv)
            .rolling(n, min_periods=n)
            .apply(lambda w: float(np.dot(w, x) / np.dot(x, x)), raw=True)
            .to_numpy()
        )
        with np.errstate(invalid="ignore", divide="ignore"):
            norm = slope / m.sma(v, n)
        return np.asarray(np.nan_to_num(np.abs(norm), nan=0.0) > self.p["threshold"])


@register("volume", "vhf")
class VHF(Volume):
    """Vertical horizontal filter: trend gate when net range dominates the path length."""

    family = "trend_vs_range"
    defaults = {"period": 28, "threshold": 0.35}
    grid = {"period": (14, 28, 42), "threshold": (0.3, 0.35, 0.4)}

    def gate(self, bars: BarFrame) -> Arr:
        c = bars.close
        n = self.p["period"]
        num = m.rolling_max(c, n) - m.rolling_min(c, n)
        den = m.rolling_sum(np.abs(c - m.shift(c)), n)
        with np.errstate(invalid="ignore", divide="ignore"):
            vhf = np.where(den > 0, num / den, 0.0)
        vhf[np.isnan(den)] = np.nan
        return np.asarray(np.nan_to_num(vhf, nan=0.0) > self.p["threshold"])


# ==================================================================== exit


@register("exit", "rex")
class Rex(Exit):
    """Rex oscillator (true value of the bar) vs its signal line."""

    family = "bar_body"
    defaults = {"period": 14, "signal": 14}
    grid = {"period": (10, 14, 20), "signal": (7, 14)}

    def exits(self, bars: BarFrame) -> Arr:
        tvb = 3 * bars.close - (bars.low + bars.open + bars.high)
        rex = m.sma(tvb, self.p["period"])
        return m.state_to_exit(m.sign_state(rex - m.sma(rex, self.p["signal"])))


@register("exit", "qqe_exit")
class QQEExit(Exit):
    family = "filtered_oscillator"
    defaults = {"rsi_period": 14, "smoothing": 5, "factor": 2.618}
    grid = {"rsi_period": (8, 14), "factor": (2.0, 2.618, 4.236)}

    def exits(self, bars: BarFrame) -> Arr:
        return m.state_to_exit(
            _qqe_state(bars.close, self.p["rsi_period"], self.p["smoothing"], self.p["factor"])
        )


@register("exit", "braid_filter")
class BraidFilter(Exit):
    """Robert Hill's braid filter: EMA(close,3) vs EMA(open,7), only when the braid spread clears an ATR filter."""

    family = "ma_braid"
    defaults = {"p1": 3, "p2": 7, "p3": 14, "filter_atr": 0.4}
    grid = {"p2": (5, 7, 10), "filter_atr": (0.2, 0.4, 0.6)}

    def exits(self, bars: BarFrame) -> Arr:
        m1 = m.ema(bars.close, self.p["p1"])
        m2 = m.ema(bars.open, self.p["p2"])
        m3 = m.ema(bars.close, self.p["p3"])
        spread = np.fmax(np.fmax(m1, m2), m3) - np.fmin(np.fmin(m1, m2), m3)
        wide = spread > self.p["filter_atr"] * _atr(bars)
        valid = ~(np.isnan(m3) | np.isnan(_atr(bars)))
        return m.state_to_exit(_hold_state(wide & (m1 > m2), wide & (m2 > m1), valid))


@register("exit", "aroon_exit")
class AroonExit(Exit):
    family = "time_since_extreme"
    defaults = {"period": 10}
    grid = {"period": (7, 10, 14)}

    def exits(self, bars: BarFrame) -> Arr:
        from nnfx.indicators.library import Aroon

        return m.state_to_exit(Aroon(period=self.p["period"]).state(bars))


@register("exit", "waddah_dead_zone")
class WaddahDeadZone(Exit):
    """Exit when a Waddah Attar trend bar collapses into the (ATR-relative) dead zone or reverses."""

    family = "momentum_vs_volatility"
    defaults = {"fast": 20, "slow": 40, "sensitivity": 150.0, "deadzone_atr": 0.1}
    grid = {"sensitivity": (100.0, 150.0, 200.0), "deadzone_atr": (0.05, 0.1, 0.2)}

    def exits(self, bars: BarFrame) -> Arr:
        c = bars.close
        macd = m.ema(c, self.p["fast"]) - m.ema(c, self.p["slow"])
        t1 = (macd - m.shift(macd)) * self.p["sensitivity"]
        dead = self.p["deadzone_atr"] * _atr(bars)
        valid = ~(np.isnan(t1) | np.isnan(dead))
        power = np.where(valid & (t1 > dead), 1, np.where(valid & (-t1 > dead), -1, 0))
        out = np.zeros(len(c), dtype="int8")
        prev = np.concatenate([[0], power[:-1]])
        out[(prev == 1) & (power != 1) & valid] = 1
        out[(prev == -1) & (power != -1) & valid] = -1
        return out
