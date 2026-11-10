"""The daily altcoin screener (Strategy Builder ticket 20, ADR 10 §24).

Video 83's LiveCoinWatch sieve, run on exchange ticker data instead of a website: value
every coin in BTC, keep those with a 24-hour volume of at least 1,000 BTC and positive
24-hour and 7-day performance *against BTC*, and rank them into a watchlist of at most
five. It is the morning routine's input, not a signal: a coin on the list still needs its
ALT/BTC trend (``relative_strength``) and a setup.

``screen`` is pure, over ``AssetStats``. ``stats_from_exchange`` gathers those from a
ccxt-style exchange (injected, so tests run offline).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_WATCHLIST = 5
MIN_VOLUME_BTC = 1000.0
BTC_SYMBOL = "BTC/USDT"
STABLECOINS = frozenset({"USDT", "USDC", "FDUSD", "TUSD", "DAI", "USDE", "BUSD", "USDP"})
WEEK_BARS = 7  # daily bars back to the close a week ago


@dataclass(frozen=True)
class AssetStats:
    """One USDT pair's figures."""

    symbol: str  # e.g. "SOL/USDT"
    last: float  # price in USDT
    quote_volume_24h: float  # traded value over 24 hours, in USDT
    change_24h: float  # fraction: 0.03 is +3%
    change_7d: float


@dataclass(frozen=True)
class WatchEntry:
    symbol: str
    volume_btc: float
    vs_btc_24h: float  # performance valued in BTC over 24 hours, a fraction
    vs_btc_7d: float


@dataclass(frozen=True)
class Watchlist:
    entries: tuple[WatchEntry, ...]
    considered: int  # USDT altcoin pairs looked at
    rejected: dict[str, str] = field(default_factory=dict)  # symbol -> why it did not qualify

    @property
    def symbols(self) -> list[str]:
        return [e.symbol for e in self.entries]


def vs_btc(change: float, btc_change: float) -> float:
    """The performance of an asset valued in BTC: (1 + asset) / (1 + btc) - 1."""
    return (1.0 + change) / (1.0 + btc_change) - 1.0


def screen(
    assets: Sequence[AssetStats],
    btc: AssetStats,
    *,
    min_volume_btc: float = MIN_VOLUME_BTC,
    max_assets: int = MAX_WATCHLIST,
) -> Watchlist:
    """The watchlist: liquid assets beating BTC over 24 hours and 7 days, strongest first.

    ``btc`` is the BTC/USDT line: its price converts volumes to BTC and its changes are the
    benchmark. Stablecoins, BTC itself and pairs quoted in anything but USDT are skipped.
    Ranked by the 7-day figure, then the 24-hour one, then the symbol, so the list is
    reproducible.
    """
    if not 1 <= max_assets <= MAX_WATCHLIST:
        raise ValueError(f"the watchlist holds 1 to {MAX_WATCHLIST} assets, not {max_assets}")
    if btc.last <= 0 or btc.change_24h <= -1 or btc.change_7d <= -1:
        raise ValueError("BTC's own price and changes are needed to value the other coins in BTC")
    rejected: dict[str, str] = {}
    passed: list[WatchEntry] = []
    considered = 0
    for a in assets:
        base, _, quote = a.symbol.partition("/")
        if quote != "USDT" or base in STABLECOINS or base == "BTC":
            continue
        considered += 1
        entry = WatchEntry(
            a.symbol,
            a.quote_volume_24h / btc.last,
            vs_btc(a.change_24h, btc.change_24h),
            vs_btc(a.change_7d, btc.change_7d),
        )
        if entry.volume_btc < min_volume_btc:
            rejected[a.symbol] = (
                f"24h volume {entry.volume_btc:,.0f} BTC is under {min_volume_btc:,.0f}"
            )
        elif entry.vs_btc_24h <= 0:
            rejected[a.symbol] = "not ahead of BTC over 24 hours"
        elif entry.vs_btc_7d <= 0:
            rejected[a.symbol] = "not ahead of BTC over 7 days"
        else:
            passed.append(entry)
    passed.sort(key=lambda e: (-e.vs_btc_7d, -e.vs_btc_24h, e.symbol))
    return Watchlist(tuple(passed[:max_assets]), considered, rejected)


class TickerExchange(Protocol):
    """The slice of a ccxt exchange the screener reads."""

    id: str

    def fetch_tickers(self) -> dict[str, dict[str, Any]]: ...

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = ..., since: int | None = ..., limit: int | None = ...
    ) -> list[list[float]]: ...


def stats_from_exchange(
    exchange: TickerExchange, *, min_volume_btc: float = MIN_VOLUME_BTC
) -> tuple[list[AssetStats], AssetStats]:
    """USDT pairs' stats from one ticker call and a daily-bar call for each pair worth it.

    The 24-hour figures come from the tickers (``percentage`` in percent, ``quoteVolume`` in
    USDT). The 7-day change needs daily closes, fetched only for pairs that already pass the
    volume and 24-hour tests, so a few dozen calls rather than hundreds. Returns the other pairs
    and BTC's line; raises when BTC/USDT is not among the tickers.
    """
    tickers = exchange.fetch_tickers()
    if BTC_SYMBOL not in tickers:
        raise ValueError(f"{exchange.id}: no {BTC_SYMBOL} ticker, so nothing can be valued in BTC")
    parsed = {
        s: a for s, t in tickers.items() if s.endswith("/USDT") and (a := _ticker(s, t)) is not None
    }
    if BTC_SYMBOL not in parsed:
        raise ValueError(f"{exchange.id}: the {BTC_SYMBOL} ticker has no price, volume or change")
    btc = _with_week(exchange, parsed[BTC_SYMBOL])
    if btc is None:
        raise ValueError(f"{exchange.id}: not enough daily {BTC_SYMBOL} bars for a 7-day change")
    out = []
    for sym, a in sorted(parsed.items()):
        if sym == BTC_SYMBOL:
            continue
        # Cheap tests first: only a liquid pair ahead of BTC today is worth a bar request.
        if (
            a.quote_volume_24h / btc.last < min_volume_btc
            or vs_btc(a.change_24h, btc.change_24h) <= 0
        ):
            out.append(a)  # kept with a zero week: ``screen`` rejects it for the first reason
            continue
        full = _with_week(exchange, a)
        if full is not None:
            out.append(full)
    return out, btc


def _ticker(symbol: str, t: dict[str, Any]) -> AssetStats | None:
    last, vol, pct = t.get("last"), t.get("quoteVolume"), t.get("percentage")
    if last is None or vol is None or pct is None or last <= 0:
        return None
    return AssetStats(symbol, float(last), float(vol), float(pct) / 100.0, 0.0)


def _with_week(exchange: TickerExchange, a: AssetStats) -> AssetStats | None:
    """``a`` with its 7-day change: the last price against the close seven days earlier."""
    bars = exchange.fetch_ohlcv(a.symbol, "1d", None, WEEK_BARS + 2)
    if len(bars) < WEEK_BARS + 1:
        return None
    ref = float(bars[-(WEEK_BARS + 1)][4])
    if ref <= 0:
        return None
    return AssetStats(a.symbol, a.last, a.quote_volume_24h, a.change_24h, a.last / ref - 1.0)
