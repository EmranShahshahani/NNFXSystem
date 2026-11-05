"""Market structure: Dow trend states and the wave-cycle bias (Strategy Builder ticket 09).

Everything here is causal: a swing at bar ``k`` is used only from bar
``k + pivot_bars`` (its confirmation), and a state at bar ``j`` uses only bars
up to ``j``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nnfx.strategy.series import pivots

UP, RANGE, DOWN = 1, 0, -1


def dow_states(low: np.ndarray, high: np.ndarray, close: np.ndarray, pivot_bars: int) -> np.ndarray:
    """The Dow trend state (1 up, 0 range, -1 down) at each bar's close.

    - **Range to up:** a close above the latest confirmed swing high while the
      latest confirmed swing low is above the one before (a higher low).
      Down is mirrored. Video 3.
    - **Up ends only on a failed peak** (video 28): the latest confirmed swing
      high is equal to or below the one before it, and a close breaks the
      neckline, the lowest low between those two peaks. The state goes back
      to range; a lower high plus a break of a swing low then makes it down.
      A deep pullback that breaks a higher low without a failed peak does not
      end the trend. Down is mirrored. After a strict lower high the state
      turns down on a later close below the latest swing low (usually the
      very next one); after an equal high it stays in range.

    A NaN bar is never a swing; neckline extremes skip NaN.
    """
    if pivot_bars < 1:
        raise ValueError("pivot_bars must be at least 1")
    n = len(close)
    lows, highs = pivots(low, high, pivot_bars, pivot_bars)
    out = np.zeros(n, dtype="int8")
    hs: list[int] = []
    ls: list[int] = []
    hp = lp = 0
    s = RANGE
    for j in range(n):
        while hp < len(highs) and highs[hp] + pivot_bars <= j:
            hs.append(int(highs[hp]))
            hp += 1
        while lp < len(lows) and lows[lp] + pivot_bars <= j:
            ls.append(int(lows[lp]))
            lp += 1
        c = close[j]
        if s == UP:
            if len(hs) >= 2 and high[hs[-1]] <= high[hs[-2]]:
                neck = np.nanmin(low[hs[-2] + 1 : hs[-1]])  # never empty: swings are 2+ apart
                if c < neck:
                    s = RANGE
        elif s == DOWN:
            if len(ls) >= 2 and low[ls[-1]] >= low[ls[-2]]:
                neck = np.nanmax(high[ls[-2] + 1 : ls[-1]])
                if c > neck:
                    s = RANGE
        elif hs and len(ls) >= 2 and c > high[hs[-1]] and low[ls[-1]] > low[ls[-2]]:
            s = UP
        elif ls and len(hs) >= 2 and c < low[ls[-1]] and high[hs[-1]] < high[hs[-2]]:
            s = DOWN
        out[j] = s
    return out


@dataclass(frozen=True)
class WaveBias:
    """Per LWC bar: what the wave cycles allow, and which trades are secondary waves."""

    long_ok: np.ndarray
    short_ok: np.ndarray
    counter_long: np.ndarray  # a long here is against the primary (HWC) trend
    counter_short: np.ndarray
    primary: np.ndarray  # the HWC's last trend direction (0 before any)
    hwc_effective: np.ndarray  # the HWC bias after the bottom-up reversal rule
    box: np.ndarray  # two-way box mode is active


def wave_bias(
    hwc: np.ndarray,
    mwc: np.ndarray,
    lwc: np.ndarray,
    *,
    follow_mwc_when_flat: bool = True,
    two_way_box: bool = False,
) -> WaveBias:
    """Combine the three roles' Dow states (aligned to LWC bars) into allowed directions.

    - **The HWC sets the direction** (video 63). In an HWC uptrend only longs
      are allowed, so an LWC downtrend is never shorted: it is a discounted
      long entry. Mirrored for a downtrend.
    - **Bottom-up reversal.** The HWC is treated as flat only when the MWC
      turns away from its trend (range or opposite) while the LWC already has
      (the same bar counts), or once the HWC's own trend has ended. An MWC
      that turns first does not count, even if the LWC follows. One LWC
      breakdown never flips it. "Flat" is this effective bias: the HWC's own
      Dow state may still read up.
    - **A flat HWC** follows the MWC's trend (``follow_mwc_when_flat``). A
      trade against the HWC's last trend is a secondary wave, tagged
      counter-trend.
    - **Two-way box** (video 64). When the HWC is flat and the MWC ranges,
      ``two_way_box`` allows both directions, each tagged counter-trend so the
      Profit Chain takes 2R-3R.
    """
    n = len(lwc)
    long_ok, short_ok = np.zeros(n, bool), np.zeros(n, bool)
    cl, cs = np.zeros(n, bool), np.zeros(n, bool)
    prim_out, eff_out, box = np.zeros(n, "int8"), np.zeros(n, "int8"), np.zeros(n, bool)
    prim = 0
    lwc_away = False  # the LWC had turned away from the primary trend by the last bar
    mwc_with = True  # the MWC was with the primary trend at the last bar
    sequence = False  # the MWC turned away while the LWC already had
    for i in range(n):
        h, m, lo = int(hwc[i]), int(mwc[i]), int(lwc[i])
        if h != 0 and h != prim:
            prim, lwc_away, mwc_with, sequence = h, False, True, False
        if prim != 0:
            if m == prim:
                sequence = False  # the MWC is back with the trend
            elif mwc_with and (lwc_away or lo != prim):
                sequence = True  # the MWC turns now, after (or with) the LWC
            lwc_away, mwc_with = lo != prim, m == prim
        eff = prim if h != 0 and not sequence else 0
        if eff != 0:
            long_ok[i], short_ok[i] = eff > 0, eff < 0
        elif m != 0 and follow_mwc_when_flat:
            long_ok[i], short_ok[i] = m > 0, m < 0
            cl[i], cs[i] = prim < 0, prim > 0
        elif m == 0 and two_way_box:
            long_ok[i] = short_ok[i] = cl[i] = cs[i] = box[i] = True
        prim_out[i], eff_out[i] = prim, eff
    return WaveBias(long_ok, short_ok, cl, cs, prim_out, eff_out, box)
