"""Market context for the Market Filter Blocks (Strategy Builder ticket 20, ADR 10 §24).

Dominance series (BTC.D, USDT.D, TOTAL2/3) are not exchange pairs: they come from a
TradingView export (``read_market_series``) or a provider, and ride along with the
bars as ``MarketData``. Pair ratios (ALT/BTC, ALT/ETH, ETH/BTC) are read as a series
when the cross pair was given and otherwise derived from the two exchange pairs.

Everything is read at a Block's timeframe role, causally: an LWC bar sees the latest
role bar closed by then, and a series that has nothing recent enough (it starts later,
or has a hole) is *unavailable* there. A Market Filter reports that as not-applicable
and the run is flagged incomplete (``DocumentRun.incomplete``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from nnfx.data.bars import BASE_TIMEFRAMES, TIMEFRAMES, BarFrame, ns
from nnfx.data.timeframes import TimeframeViews
from nnfx.data.tradingview import read_tradingview_csv
from nnfx.strategy.structure import waves

if TYPE_CHECKING:
    from nnfx.strategy.blocks import StrategyData


@dataclass(frozen=True)
class MarketData:
    """Named market series: dominance indices and the exchange pairs ratios derive from.

    Each is a ``BarFrame`` on a base timeframe (M15 or H1, as a TradingView export gives it);
    a Block reads it at its own role's timeframe.
    """

    series: Mapping[str, BarFrame] = field(default_factory=dict)

    def get(self, name: str) -> BarFrame | None:
        return self.series.get(name)


def read_market_series(path: Path | str, name: str, timeframe: str = "H1") -> BarFrame:
    """A dominance index or pair from a TradingView "Export chart data" CSV."""
    return read_tradingview_csv(path, name, timeframe=timeframe, volume_kind="none")


def base_asset(symbol: str) -> str:
    """``"SOL/USDT"`` -> ``"SOL"``; a name without a slash (``"BTC.D"``) is its own."""
    return symbol.partition("/")[0]


def role_frame(data: StrategyData, name: str, role: str) -> BarFrame | None:
    """``name``'s bars at ``role``'s timeframe, or None when it is not among the data."""

    def make() -> BarFrame | None:
        if name == data.symbol:
            return data.frames[role]
        f = data.market.get(name)
        tf = data.roles[role]
        if f is None or TIMEFRAMES[f.timeframe] > TIMEFRAMES[tf]:
            return None
        if f.timeframe == tf:
            return f
        if f.timeframe not in BASE_TIMEFRAMES:
            return None
        views = TimeframeViews(f, instrument=data.instrument, session=data.session, timeframes=[tf])
        return views.frame(tf)

    return data.memo(("role_frame", name, role), make)


def ratio_frame(top: BarFrame, bottom: BarFrame, name: str) -> BarFrame | None:
    """``top / bottom`` closes on the bars both have (None under two shared bars).

    Open, high, low and close are all the ratio of the closes, so the Dow structure of the
    ratio is read off its closes alone.
    """
    common = top.index.intersection(bottom.index)
    if len(common) < 2:
        return None
    r = top.df.loc[common, "close"].to_numpy() / bottom.df.loc[common, "close"].to_numpy()
    df = pd.DataFrame(
        {"open": r, "high": r, "low": r, "close": r, "volume": 0.0}, index=common
    )  # fmt: skip
    return BarFrame(df, name, timeframe=top.timeframe, volume_kind="none")


def trend_on_base(
    data: StrategyData, frame: BarFrame | None, role: str, pivot_bars: int, max_stale_bars: int
) -> tuple[np.ndarray, np.ndarray]:
    """The Dow state of ``frame``'s closes at each LWC bar, and whether it is known there.

    Known means a bar of ``frame`` closed by then, no more than ``max_stale_bars`` bars of
    ``role`` ago. State is 1 up, 0 range or unknown, -1 down.
    """
    n = len(data)
    if frame is None or len(frame) == 0:
        return np.zeros(n, "int8"), np.zeros(n, bool)
    c = frame.close
    state = waves(c, c, c, pivot_bars)[0]
    at, seen = ns(data.base.index), ns(frame.index)
    pos = np.searchsorted(seen, at, side="right") - 1
    ok = pos >= 0
    ok[ok] = (at[ok] - seen[pos[ok]] <= max_stale_bars * TIMEFRAMES[data.roles[role]].value) & (
        np.isfinite(c[pos[ok]])
    )
    out = np.zeros(n, "int8")
    out[ok] = state[pos[ok]]
    return out, ok


def series_state(
    data: StrategyData, name: str, role: str, pivot_bars: int, max_stale_bars: int
) -> tuple[np.ndarray, np.ndarray]:
    """``trend_on_base`` of the series ``name`` (the traded symbol itself counts)."""
    key = ("series_state", name, role, pivot_bars, max_stale_bars)
    return data.memo(
        key,
        lambda: trend_on_base(data, role_frame(data, name, role), role, pivot_bars, max_stale_bars),
    )


def pair_state(
    data: StrategyData, top: str, bottom: str, role: str, pivot_bars: int, max_stale_bars: int
) -> tuple[np.ndarray, np.ndarray]:
    """The trend of the ratio ``top / bottom`` (two exchange pairs, e.g. SOL/USDT over BTC/USDT).

    The cross pair itself (``SOL/BTC``) is used when it is among the series; otherwise the
    ratio is derived from the two pairs' closes.
    """
    key = ("pair_state", top, bottom, role, pivot_bars, max_stale_bars)

    def make() -> tuple[np.ndarray, np.ndarray]:
        if base_asset(top) == base_asset(bottom):  # an asset against itself is no ratio
            return trend_on_base(data, None, role, pivot_bars, max_stale_bars)
        cross = f"{base_asset(top)}/{base_asset(bottom)}"
        direct = data.market.get(cross)
        frame = role_frame(data, cross, role) if direct is not None else None
        if frame is None:
            a, b = role_frame(data, top, role), role_frame(data, bottom, role)
            frame = ratio_frame(a, b, cross) if a is not None and b is not None else None
        return trend_on_base(data, frame, role, pivot_bars, max_stale_bars)

    return data.memo(key, make)
