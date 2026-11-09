"""Horizontal levels, touch counts and boxes (Strategy Builder ticket 11).

Everything is causal: a swing at bar ``k`` is used only from ``k + pivot_bars``
(its confirmation), and every value at bar ``j`` uses only bars up to ``j``.
Prices are in the units of the bars given, and distances are in ATR, so the
results are scale-free.

Levels are single prices calibrated to candle bodies (a swing high is its
body's top, a swing low its body's bottom), never wide zones (blueprint 01,
video 5), and recent touches weigh more than old ones.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nnfx.strategy.series import pivots


def swings(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray, pivot_bars: int
) -> list[tuple[int, float, int]]:
    """Confirmed swings as (bar, body price, kind), in order of confirmation.

    kind 1 is a swing high (priced at its body top), -1 a swing low (body bottom).
    A swing is confirmed ``pivot_bars`` bars after its own bar.
    """
    lows, highs = pivots(low, high, pivot_bars, pivot_bars)
    top, bottom = np.maximum(open_, close), np.minimum(open_, close)
    out = [(int(k), float(top[k]), 1) for k in highs] + [
        (int(k), float(bottom[k]), -1) for k in lows
    ]
    out.sort(key=lambda s: (s[0], s[2]))
    return out


# ------------------------------------------------------------------ levels
@dataclass(frozen=True)
class LevelView:
    """One horizontal level as of a bar."""

    price: float  # the median of its touches' body prices
    touches: tuple[int, ...]  # the bars of the swings that touched it, oldest first
    weight: float  # touches weighted by recency: 1 for a touch now, 0.5 a half-life ago
    flipped: bool  # touched both as resistance and as support (a polarity flip)


class LevelBook:
    """All the horizontal levels of one timeframe, read as of any bar.

    Swings join the nearest level within ``tolerance_atr`` ATR, or start a new
    one. A level belongs to the bars it was built from: query it with those
    bars' timeframe, never a lower one (a 15m close beyond a 4H level is not a
    4H breakout; blueprint 03, video 21).
    """

    def __init__(
        self,
        open_: np.ndarray,
        high: np.ndarray,
        low: np.ndarray,
        close: np.ndarray,
        rng: np.ndarray,
        *,
        pivot_bars: int,
        tolerance_atr: float,
        half_life: float,
        max_age: int,
    ) -> None:
        self.half_life, self.max_age = half_life, max_age
        # Per level: its touches as (confirmed bar, swing bar, body price, kind) and its
        # current price (the median of the touches), kept up to date as swings join.
        self._levels: list[list[tuple[int, int, float, int]]] = []
        prices: dict[int, float] = {}
        active: list[list[tuple[int, int, float, int]]] = []
        n = len(close)
        for bar, price, kind in swings(open_, high, low, close, pivot_bars):
            confirm = bar + pivot_bars
            if confirm >= n:
                continue
            # Before the ATR exists, the confirming bar's own range stands in for it.
            scale = (
                float(rng[confirm])
                if np.isfinite(rng[confirm])
                else float(high[confirm] - low[confirm])
            )
            if scale <= 0:
                continue
            tol = tolerance_atr * scale
            active = [lv for lv in active if confirm - lv[-1][0] <= max_age]
            best, gap = None, np.inf
            for lv in active:
                d = abs(prices[id(lv)] - price)
                if d <= tol and d < gap:
                    best, gap = lv, d
            if best is None:
                best = []
                self._levels.append(best)
                active.append(best)
            best.append((confirm, bar, price, kind))
            prices[id(best)] = float(np.median([t[2] for t in best]))

    def at(self, i: int, *, min_weight: float = 0.0) -> list[LevelView]:
        """The levels known at the close of bar ``i`` and touched within ``max_age`` bars."""
        out = []
        for lv in self._levels:
            if lv[0][0] > i:
                break  # levels start in confirmation order
            seen = [t for t in lv if t[0] <= i]
            if i - seen[-1][0] > self.max_age:
                continue
            w = float(sum(0.5 ** ((i - t[1]) / self.half_life) for t in seen))
            if w < min_weight:
                continue
            kinds = {t[3] for t in seen}
            out.append(
                LevelView(
                    float(np.median([t[2] for t in seen])),
                    tuple(t[1] for t in seen),
                    w,
                    len(kinds) == 2,
                )
            )
        return out


# ------------------------------------------------------------------- boxes
@dataclass(frozen=True)
class BoxTrack:
    """Per-bar box state. Prices are NaN and counts 0 where there is none."""

    direction: np.ndarray  # int8: a breakout candidate stands here (1 up, -1 down), else 0
    trigger: np.ndarray  # the breakout bar's extreme in its direction
    edge: np.ndarray  # the broken edge (the level)
    opposite: np.ndarray  # the far edge (the structural stop)
    anchor: np.ndarray  # the bar of the first close beyond the edge (-1: none)
    start: np.ndarray  # the first touch of the box (-1: none)
    touches: np.ndarray  # touches of the broken edge
    in_box: np.ndarray  # bool: a box stands and price is inside it
    top: np.ndarray
    bottom: np.ndarray
    age: np.ndarray  # bars since the box's first touch, while in_box


def _recent(swings_: list[tuple[int, float]], since: int) -> list[tuple[int, float]]:
    """The swings at or after bar ``since`` (the list is in bar order)."""
    k = len(swings_)
    while k > 0 and swings_[k - 1][0] >= since:
        k -= 1
    return swings_[k:]


def _cluster(pts: list[tuple[int, float]], tol: float, need: int) -> tuple[float, list[int]] | None:
    """The densest group of (bar, price) within ``tol`` of one price, if it has ``need``."""
    best: tuple[int, int, float, list[int]] | None = None
    for _, seed in pts:
        group = [(b, p) for b, p in pts if abs(p - seed) <= tol]
        if len(group) < need:
            continue
        key = (len(group), max(b for b, _ in group))
        if best is None or key > (best[0], best[1]):
            best = (key[0], key[1], float(np.median([p for _, p in group])), [b for b, _ in group])
    return None if best is None else (best[2], best[3])


@dataclass
class _Box:
    top: float
    bottom: float
    start: int
    top_touches: int
    bottom_touches: int


def track_boxes(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    rng: np.ndarray,
    *,
    pivot_bars: int,
    lookback: int,
    tolerance_atr: float,
    min_top: int,
    min_bottom: int,
    min_height_atr: float,
    max_height_atr: float,
    min_bars: int,
    window: int,
) -> BoxTrack:
    """Detect consolidation boxes and their breakouts, bar by bar.

    A box is two horizontal edges: a top touched by at least ``min_top`` swing
    highs and a bottom touched by at least ``min_bottom`` swing lows within the
    last ``lookback`` bars (touches within ``tolerance_atr`` ATR of one price),
    between ``min_height_atr`` and ``max_height_atr`` ATR apart, at least
    ``min_bars`` old, with no close beyond an edge since its first touch. It is
    detected again whenever a swing is confirmed.

    A breakout is the first close beyond an edge by more than the tolerance.
    A candidate then stands on that bar and on each later bar, up to ``window``
    bars, for as long as every close since stays beyond the edge. A close back
    inside ends it.
    """
    n = len(close)
    nan = np.full(n, np.nan)
    d = np.zeros(n, "int8")
    trigger, edge, opposite = nan.copy(), nan.copy(), nan.copy()
    anchor, start = np.full(n, -1, "int64"), np.full(n, -1, "int64")
    touches = np.zeros(n, "int64")
    in_box, top, bottom = np.zeros(n, bool), nan.copy(), nan.copy()
    age = np.zeros(n, "int64")

    sw = swings(open_, high, low, close, pivot_bars)
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    nxt = 0
    box: _Box | None = None
    brk: tuple[int, int, float, float, int, int] | None = None  # dir, anchor, edge, far, start, k

    for j in range(n):
        fresh = False
        while nxt < len(sw) and sw[nxt][0] + pivot_bars <= j:
            bar, price, kind = sw[nxt]
            (highs if kind > 0 else lows).append((bar, price))
            nxt += 1
            fresh = True
        a = float(rng[j])
        tol = tolerance_atr * a if np.isfinite(a) else 0.0
        c = float(close[j])

        if brk is None and box is not None:
            # The standing box is tested first: a breakout on the very bar a swing is
            # confirmed must not be lost to the box being detected again.
            if c > box.top + tol:
                brk = (1, j, box.top, box.bottom, box.start, box.top_touches)
                box = None
            elif c < box.bottom - tol:
                brk = (-1, j, box.bottom, box.top, box.start, box.bottom_touches)
                box = None
        if brk is None and (fresh or box is None) and np.isfinite(a) and a > 0:
            box = _detect(
                highs, lows, close, j, a, tol, lookback, min_top, min_bottom,
                min_height_atr, max_height_atr, min_bars,
            )  # fmt: skip
        if brk is not None:
            sign, first, level, far, st, k = brk
            if (c - level) * sign > 0 and j - first < window:
                d[j] = sign
                trigger[j] = float(high[j] if sign > 0 else low[j])
                edge[j], opposite[j] = level, far
                anchor[j], start[j], touches[j] = first, st, k
            else:
                brk, box = None, None
        if box is not None:
            in_box[j], top[j], bottom[j] = True, box.top, box.bottom
            start[j] = box.start
            age[j] = j - box.start
    return BoxTrack(d, trigger, edge, opposite, anchor, start, touches, in_box, top, bottom, age)


def _detect(
    highs: list[tuple[int, float]],
    lows: list[tuple[int, float]],
    close: np.ndarray,
    j: int,
    a: float,
    tol: float,
    lookback: int,
    min_top: int,
    min_bottom: int,
    min_height_atr: float,
    max_height_atr: float,
    min_bars: int,
) -> _Box | None:
    h, lo = _recent(highs, j - lookback), _recent(lows, j - lookback)
    if len(h) < min_top or len(lo) < min_bottom:
        return None  # too few swings to hold the touches: skip the clustering
    top, bottom = _cluster(h, tol, min_top), _cluster(lo, tol, min_bottom)
    if top is None or bottom is None or top[0] - bottom[0] < min_height_atr * a:
        return None
    if top[0] - bottom[0] > max_height_atr * a:
        return None
    first = min(*top[1], *bottom[1])
    if j - first < min_bars:
        return None
    seg = close[first : j + 1]
    if np.any(seg > top[0] + tol) or np.any(seg < bottom[0] - tol):
        return None  # price already left it
    return _Box(top[0], bottom[0], first, len(top[1]), len(bottom[1]))


__all__ = ["BoxTrack", "LevelBook", "LevelView", "swings", "track_boxes"]
