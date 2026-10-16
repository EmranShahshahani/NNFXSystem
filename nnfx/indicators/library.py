"""The concrete indicator catalogue (doc 05). Each class is a thin, causal wrapper.

Published defaults are used as ``defaults``; ``grid`` holds a 3-5 point grid
spanning a sensible range around them (doc 05 §9). Every threshold is
dimensionless or ATR/percentage-relative, never a price-scale constant.
"""

from __future__ import annotations

import math

import numpy as np

from nnfx.data.bars import BarFrame
from nnfx.indicators import _math as m
from nnfx.indicators.base import Baseline, Confirmation, Exit, Volatility, Volume, register

# ============================================================== volatility


@register("volatility", "atr")
class ATR(Volatility):
    family = "true_range"
    defaults = {"period": 14, "method": "wilder"}
    grid = {"period": (10, 14, 20)}

    def value(self, bars: BarFrame) -> np.ndarray:
        tr = m.true_range(bars.high, bars.low, bars.close)
        n = self.p["period"]
        return m.sma(tr, n) if self.p["method"] == "sma" else m.rma(tr, n)


@register("volatility", "adr")
class ADR(Volatility):
    family = "range"
    defaults = {"period": 14}
    grid = {"period": (10, 14, 20)}

    def value(self, bars: BarFrame) -> np.ndarray:
        return m.sma(bars.high - bars.low, self.p["period"])


@register("volatility", "parkinson")
class Parkinson(Volatility):
    """Range-based estimator, expressed in price units (close x per-bar sigma)."""

    family = "range_estimator"
    defaults = {"period": 20}
    grid = {"period": (14, 20, 30)}

    def value(self, bars: BarFrame) -> np.ndarray:
        hl = np.log(bars.high / bars.low) ** 2
        sigma = np.sqrt(m.sma(hl, self.p["period"]) / (4 * math.log(2)))
        # Scale so it is comparable to ATR (E|range| ~ 1.6 sigma for a random walk).
        return bars.close * sigma * 1.6


# ================================================================ baseline


@register("baseline", "sma")
class SMA(Baseline):
    family = "moving_average"
    defaults = {"period": 20}
    grid = {"period": (10, 20, 50)}

    def line(self, bars: BarFrame) -> np.ndarray:
        return m.sma(bars.close, self.p["period"])


@register("baseline", "ema")
class EMA(Baseline):
    family = "moving_average"
    defaults = {"period": 20}
    grid = {"period": (10, 20, 50)}

    def line(self, bars: BarFrame) -> np.ndarray:
        return m.ema(bars.close, self.p["period"])


@register("baseline", "kama")
class KAMA(Baseline):
    family = "adaptive_ma"
    defaults = {"period": 10, "fast": 2, "slow": 30}
    grid = {"period": (8, 10, 14), "slow": (20, 30, 40)}

    def line(self, bars: BarFrame) -> np.ndarray:
        c = bars.close
        n = self.p["period"]
        er = m.efficiency_ratio(c, n)
        fast, slow = 2 / (self.p["fast"] + 1), 2 / (self.p["slow"] + 1)
        sc = (er * (fast - slow) + slow) ** 2
        out = np.full(len(c), np.nan)
        if len(c) > n:
            out[n] = c[n]
            for i in range(n + 1, len(c)):
                out[i] = out[i - 1] + sc[i] * (c[i] - out[i - 1])
        return out


@register("baseline", "kijun")
class Kijun(Baseline):
    """Midpoint of the N-bar range. Not a moving average: flat in ranges, steps in trends."""

    family = "range_midpoint"
    defaults = {"period": 26}
    grid = {"period": (20, 26, 34)}

    def line(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        return np.asarray((m.rolling_max(bars.high, n) + m.rolling_min(bars.low, n)) / 2)


@register("baseline", "donchian_mid")
class DonchianMid(Baseline):
    family = "range_midpoint"
    defaults = {"period": 20}
    grid = {"period": (14, 20, 30)}

    def line(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        return np.asarray((m.rolling_max(bars.high, n) + m.rolling_min(bars.low, n)) / 2)


@register("baseline", "hma")
class HMA(Baseline):
    family = "moving_average"
    defaults = {"period": 20}
    grid = {"period": (14, 20, 30)}

    def line(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        raw = 2 * m.wma(bars.close, max(n // 2, 1)) - m.wma(bars.close, n)
        return m.wma(raw, max(int(math.sqrt(n)), 1))


@register("baseline", "alma")
class ALMA(Baseline):
    family = "moving_average"
    defaults = {"period": 9, "offset": 0.85, "sigma": 6.0}
    grid = {"period": (9, 14, 21)}

    def line(self, bars: BarFrame) -> np.ndarray:
        n, off, sig = self.p["period"], self.p["offset"], self.p["sigma"]
        mu = off * (n - 1)
        s = n / sig
        w = np.exp(-((np.arange(n) - mu) ** 2) / (2 * s * s))
        w /= w.sum()
        c = bars.close
        out = np.full(len(c), np.nan)
        for i in range(n - 1, len(c)):
            out[i] = float(np.dot(c[i - n + 1 : i + 1], w))
        return out


@register("baseline", "mcginley")
class McGinley(Baseline):
    family = "adaptive_ma"
    defaults = {"period": 14}
    grid = {"period": (10, 14, 20)}

    def line(self, bars: BarFrame) -> np.ndarray:
        c, n = bars.close, self.p["period"]
        out = np.full(len(c), np.nan)
        if len(c) >= n:
            out[n - 1] = float(np.mean(c[:n]))
            for i in range(n, len(c)):
                prev = out[i - 1]
                ratio = min(max(c[i] / prev, 0.5), 2.0)
                out[i] = prev + (c[i] - prev) / (n * ratio**4)
        return out


@register("baseline", "tema")
class TEMA(Baseline):
    family = "moving_average"
    defaults = {"period": 20}
    grid = {"period": (10, 20, 30)}

    def line(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        e1 = m.ema(bars.close, n)
        e2 = m.ema(e1, n)
        e3 = m.ema(e2, n)
        return np.asarray(3 * e1 - 3 * e2 + e3)


# ============================================================ confirmation


@register("confirmation", "macd")
class MACD(Confirmation):
    family = "ma_convergence"
    defaults = {"fast": 12, "slow": 26, "signal": 9}
    grid = {"fast": (8, 12, 16), "slow": (21, 26, 34)}

    def state(self, bars: BarFrame) -> np.ndarray:
        line = m.ema(bars.close, self.p["fast"]) - m.ema(bars.close, self.p["slow"])
        sig = m.ema(line, self.p["signal"])
        return m.sign_state(line - sig)


@register("confirmation", "aroon")
class Aroon(Confirmation):
    """Time since extreme: no price averaging at all."""

    family = "time_since_extreme"
    defaults = {"period": 25}
    grid = {"period": (14, 25, 35)}

    def state(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        h, lo = bars.high, bars.low
        diff = np.full(len(h), np.nan)
        for i in range(n, len(h)):
            wh, wl = h[i - n : i + 1], lo[i - n : i + 1]
            # Bars since the most recent extreme in the (n+1)-bar window.
            since_high = int(np.argmax(wh[::-1]))
            since_low = int(np.argmin(wl[::-1]))
            diff[i] = 100.0 * (since_low - since_high) / n
        return m.sign_state(diff)


@register("confirmation", "vortex")
class Vortex(Confirmation):
    family = "directional_movement"
    defaults = {"period": 14}
    grid = {"period": (10, 14, 21)}

    def state(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        h, lo, c = bars.high, bars.low, bars.close
        vmp = np.abs(h - m.shift(lo))
        vmm = np.abs(lo - m.shift(h))
        tr = m.rolling_sum(m.true_range(h, lo, c), n)
        return m.sign_state((m.rolling_sum(vmp, n) - m.rolling_sum(vmm, n)) / tr)


def _supertrend_state(bars: BarFrame, period: int, mult: float) -> np.ndarray:
    h, lo, c = bars.high, bars.low, bars.close
    atr = m.rma(m.true_range(h, lo, c), period)
    mid = (h + lo) / 2
    ub, lb = mid + mult * atr, mid - mult * atr
    st = np.zeros(len(c), dtype="int8")
    fub, flb = np.nan, np.nan
    d = 0
    for i in range(len(c)):
        if np.isnan(atr[i]):
            continue
        pc = c[i - 1] if i else c[i]
        fub = ub[i] if np.isnan(fub) or ub[i] < fub or pc > fub else fub
        flb = lb[i] if np.isnan(flb) or lb[i] > flb or pc < flb else flb
        if d == 0:
            d = 1 if c[i] >= mid[i] else -1
        elif d == 1 and c[i] < flb:
            d = -1
        elif d == -1 and c[i] > fub:
            d = 1
        st[i] = d
    return st


@register("confirmation", "supertrend")
class SuperTrend(Confirmation):
    """ATR band; non-repainting by construction."""

    family = "atr_band"
    defaults = {"period": 10, "multiplier": 3.0}
    grid = {"period": (7, 10, 14), "multiplier": (2.0, 3.0, 4.0)}

    def state(self, bars: BarFrame) -> np.ndarray:
        return _supertrend_state(bars, self.p["period"], self.p["multiplier"])


@register("confirmation", "cmo")
class CMO(Confirmation):
    family = "momentum"
    defaults = {"period": 9}
    grid = {"period": (7, 9, 14)}

    def state(self, bars: BarFrame) -> np.ndarray:
        d = np.diff(bars.close, prepend=np.nan)
        up = m.rolling_sum(np.where(d > 0, d, 0.0), self.p["period"])
        dn = m.rolling_sum(np.where(d < 0, -d, 0.0), self.p["period"])
        with np.errstate(invalid="ignore", divide="ignore"):
            cmo = np.where(up + dn > 0, (up - dn) / (up + dn), 0.0)
        cmo[np.isnan(up)] = np.nan
        return m.sign_state(cmo)


@register("confirmation", "laguerre_rsi")
class LaguerreRSI(Confirmation):
    family = "filtered_oscillator"
    defaults = {"gamma": 0.5}
    grid = {"gamma": (0.4, 0.5, 0.6, 0.7)}

    def state(self, bars: BarFrame) -> np.ndarray:
        g = self.p["gamma"]
        c = bars.close
        l0 = l1 = l2 = l3 = c[0] if len(c) else 0.0
        out = np.full(len(c), np.nan)
        for i in range(len(c)):
            p0, p1, p2 = l0, l1, l2
            l0 = (1 - g) * c[i] + g * p0
            l1 = -g * l0 + p0 + g * p1
            l2 = -g * l1 + p1 + g * p2
            l3 = -g * l2 + p2 + g * l3
            cu = max(l0 - l1, 0) + max(l1 - l2, 0) + max(l2 - l3, 0)
            cd = max(l1 - l0, 0) + max(l2 - l1, 0) + max(l3 - l2, 0)
            if i >= 4:
                out[i] = (cu / (cu + cd) if cu + cd > 0 else 0.5) - 0.5
        return m.sign_state(out)


@register("confirmation", "fisher")
class Fisher(Confirmation):
    family = "distribution_transform"
    defaults = {"period": 10}
    grid = {"period": (7, 10, 14)}

    def state(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        mid = (bars.high + bars.low) / 2
        hh, ll = m.rolling_max(mid, n), m.rolling_min(mid, n)
        val = 0.0
        fish = np.full(len(mid), np.nan)
        prev_f = 0.0
        for i in range(len(mid)):
            if np.isnan(hh[i]):
                continue
            rng = hh[i] - ll[i]
            x = 2 * ((mid[i] - ll[i]) / rng - 0.5) if rng > 0 else 0.0
            val = min(max(0.66 * x + 0.67 * val, -0.999), 0.999)
            f = 0.5 * math.log((1 + val) / (1 - val)) + 0.5 * prev_f
            fish[i] = f - prev_f
            prev_f = f
        return m.sign_state(fish)


def _ssl_state(bars: BarFrame, period: int) -> np.ndarray:
    sh, sl = m.sma(bars.high, period), m.sma(bars.low, period)
    c = bars.close
    st = np.zeros(len(c), dtype="int8")
    d = 0
    for i in range(len(c)):
        if np.isnan(sh[i]):
            continue
        if c[i] > sh[i]:
            d = 1
        elif c[i] < sl[i]:
            d = -1
        st[i] = d
    return st


@register("confirmation", "ssl")
class SSL(Confirmation):
    """HL-MA channel with discrete side flips (causal implementation)."""

    family = "hl_channel"
    defaults = {"period": 10}
    grid = {"period": (7, 10, 14, 20)}

    def state(self, bars: BarFrame) -> np.ndarray:
        return _ssl_state(bars, self.p["period"])


@register("confirmation", "adx_di")
class ADXDI(Confirmation):
    """DI+ vs DI- - a slower, state-oriented C2 candidate (doc 05 §5)."""

    family = "directional_movement"
    defaults = {"period": 14}
    grid = {"period": (10, 14, 21)}

    def state(self, bars: BarFrame) -> np.ndarray:
        pdi, mdi, _ = _dmi(bars, self.p["period"])
        return m.sign_state(pdi - mdi)


# ================================================================== volume


def _dmi(bars: BarFrame, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, lo, c = bars.high, bars.low, bars.close
    up = h - m.shift(h)
    dn = m.shift(lo) - lo
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = m.rma(m.true_range(h, lo, c), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * m.rma(pdm, n) / atr
        mdi = 100 * m.rma(mdm, n) / atr
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    adx = m.rma(np.nan_to_num(dx, nan=0.0), n)
    adx[np.isnan(atr)] = np.nan
    return pdi, mdi, adx


@register("volume", "adx")
class ADX(Volume):
    family = "trend_strength"
    defaults = {"period": 14, "threshold": 20.0}
    grid = {"period": (10, 14, 21), "threshold": (15.0, 20.0, 25.0)}

    def gate(self, bars: BarFrame) -> np.ndarray:
        _, _, adx = _dmi(bars, self.p["period"])
        return np.asarray(np.nan_to_num(adx, nan=0.0) > self.p["threshold"])


@register("volume", "normalized_volume")
class NormalizedVolume(Volume):
    family = "volume"
    defaults = {"period": 20, "threshold": 1.0}
    grid = {"period": (14, 20, 30), "threshold": (0.8, 1.0, 1.2)}

    def gate(self, bars: BarFrame) -> np.ndarray:
        avg = m.sma(bars.volume, self.p["period"])
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = np.where(avg > 0, bars.volume / avg, 0.0)
        return np.asarray(np.nan_to_num(ratio, nan=0.0) > self.p["threshold"])


@register("volume", "choppiness")
class Choppiness(Volume):
    """Inverted Choppiness Index: open the gate when the market is trending."""

    family = "trend_vs_range"
    defaults = {"period": 14, "threshold": 55.0}
    grid = {"period": (10, 14, 21), "threshold": (50.0, 55.0, 61.8)}

    def gate(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        tr = m.rolling_sum(m.true_range(bars.high, bars.low, bars.close), n)
        rng = m.rolling_max(bars.high, n) - m.rolling_min(bars.low, n)
        with np.errstate(invalid="ignore", divide="ignore"):
            chop = 100 * np.log10(tr / rng) / math.log10(n)
        return np.asarray(np.nan_to_num(chop, nan=100.0) < self.p["threshold"])


@register("volume", "bb_width")
class BollingerBandwidth(Volume):
    """Volatility expansion: percentage bandwidth above its own trailing mean."""

    family = "volatility_expansion"
    defaults = {"period": 20, "mult": 2.0, "lookback": 50}
    grid = {"period": (14, 20, 30), "lookback": (30, 50, 100)}

    def gate(self, bars: BarFrame) -> np.ndarray:
        n = self.p["period"]
        mid = m.sma(bars.close, n)
        sd = m._s(bars.close).rolling(n, min_periods=n).std(ddof=0).to_numpy()
        width = 2 * self.p["mult"] * sd / mid
        ref = m.sma(width, self.p["lookback"])
        return np.asarray(np.nan_to_num(width - ref, nan=-1.0) > 0)


@register("volume", "waddah_attar")
class WaddahAttar(Volume):
    """MACD-delta 'explosion' vs Bollinger width, with an ATR-relative dead zone.

    The published dead zone is an absolute price constant; it is re-expressed as a
    multiple of ATR so the indicator survives a three-order-of-magnitude price range
    (story 28).
    """

    family = "momentum_vs_volatility"
    defaults = {
        "fast": 20,
        "slow": 40,
        "bb_period": 20,
        "bb_mult": 2.0,
        "sensitivity": 150.0,
        "deadzone_atr": 0.1,
    }
    grid = {"sensitivity": (100.0, 150.0, 200.0), "deadzone_atr": (0.05, 0.1, 0.2)}

    def gate(self, bars: BarFrame) -> np.ndarray:
        c = bars.close
        macd = m.ema(c, self.p["fast"]) - m.ema(c, self.p["slow"])
        explosion = np.abs(macd - m.shift(macd)) * self.p["sensitivity"]
        n = self.p["bb_period"]
        sd = m._s(c).rolling(n, min_periods=n).std(ddof=0).to_numpy()
        band = 2 * self.p["bb_mult"] * sd
        atr = m.rma(m.true_range(bars.high, bars.low, c), 14)
        dead = self.p["deadzone_atr"] * atr
        ok = (explosion > band) & (explosion > dead)
        out: np.ndarray = np.nan_to_num(ok.astype("float64"), nan=0.0) > 0
        return out


# ==================================================================== exit


@register("exit", "psar")
class PSAR(Exit):
    family = "parabolic"
    defaults = {"step": 0.02, "max_step": 0.2}
    grid = {"step": (0.01, 0.02, 0.03)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        h, lo = bars.high, bars.low
        n = len(h)
        st = np.zeros(n, dtype="int8")
        if n < 3:
            return m.state_to_exit(st)
        d = 1 if h[1] >= h[0] else -1
        sar = lo[0] if d == 1 else h[0]
        ep = h[1] if d == 1 else lo[1]
        af = self.p["step"]
        for i in range(2, n):
            sar = sar + af * (ep - sar)
            if d == 1:
                sar = min(sar, lo[i - 1], lo[i - 2])
                if lo[i] < sar:
                    d, sar, ep, af = -1, ep, lo[i], self.p["step"]
                elif h[i] > ep:
                    ep, af = h[i], min(af + self.p["step"], self.p["max_step"])
            else:
                sar = max(sar, h[i - 1], h[i - 2])
                if h[i] > sar:
                    d, sar, ep, af = 1, ep, h[i], self.p["step"]
                elif lo[i] < ep:
                    ep, af = lo[i], min(af + self.p["step"], self.p["max_step"])
            st[i] = d
        return m.state_to_exit(st)


@register("exit", "chandelier")
class Chandelier(Exit):
    family = "atr_trailing"
    defaults = {"period": 22, "multiplier": 3.0}
    grid = {"period": (14, 22), "multiplier": (2.0, 3.0, 4.0)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        n, k = self.p["period"], self.p["multiplier"]
        h, lo, c = bars.high, bars.low, bars.close
        atr = m.rma(m.true_range(h, lo, c), n)
        long_stop = m.rolling_max(h, n) - k * atr
        short_stop = m.rolling_min(lo, n) + k * atr
        st = np.zeros(len(c), dtype="int8")
        d = 0
        for i in range(len(c)):
            if np.isnan(long_stop[i]):
                continue
            if d == 0:
                d = 1 if c[i] > (long_stop[i] + short_stop[i]) / 2 else -1
            elif d == 1 and c[i] < long_stop[i]:
                d = -1
            elif d == -1 and c[i] > short_stop[i]:
                d = 1
            st[i] = d
        return m.state_to_exit(st)


@register("exit", "supertrend_fast")
class SuperTrendExit(Exit):
    family = "atr_band"
    defaults = {"period": 7, "multiplier": 2.0}
    grid = {"period": (5, 7, 10), "multiplier": (1.5, 2.0, 2.5)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        return m.state_to_exit(_supertrend_state(bars, self.p["period"], self.p["multiplier"]))


@register("exit", "ssl_fast")
class SSLExit(Exit):
    family = "hl_channel"
    defaults = {"period": 5}
    grid = {"period": (3, 5, 7)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        return m.state_to_exit(_ssl_state(bars, self.p["period"]))


@register("exit", "macd_cross")
class MACDExit(Exit):
    family = "ma_convergence"
    defaults = {"fast": 12, "slow": 26, "signal": 9}
    grid = {"signal": (5, 9, 12)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        return m.state_to_exit(MACD(**self.params).state(bars))


@register("exit", "ema_cross")
class FastBaselineExit(Exit):
    """A faster copy of an MA baseline: exit when close crosses EMA(period)."""

    family = "moving_average"
    defaults = {"period": 8}
    grid = {"period": (5, 8, 13)}

    def exits(self, bars: BarFrame) -> np.ndarray:
        return m.state_to_exit(m.sign_state(bars.close - m.ema(bars.close, self.p["period"])))
