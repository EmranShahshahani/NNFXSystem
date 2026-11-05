"""Order Book Sources: live Nobitex, recorded snapshots, and fixtures (ticket 04).

All three answer ``snapshot(symbol, at)``: the latest book known at ``at``,
never a later one, or None when there is none (or it is older than
``max_age``). The historical providers also list ``snapshots(symbol, start,
end)``. Order-book data is live-only at the exchange, so backtests can use it
only where the recorder ran (spec: order-book rules are live-first).

Nobitex (https://apidocs.nobitex.ir, "market data"): ``GET /v3/orderbook/SYMBOL``
and ``/v3/orderbook/all`` return ``{"status": "ok", "lastUpdate": ms,
"lastTradePrice": "...", "asks": [["price", "size"], ...], "bids": [...]}``;
``/v2/depth/SYMBOL`` has the same shape with ``lastUpdate`` as a string. Poll at
most every 1-10 s (300 requests a minute; responses are cached for 1 s).
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import pandas as pd

from nnfx.data.dukascopy import default_http_get
from nnfx.data.feeds import HttpGet
from nnfx.data.udf import udf_symbol
from nnfx.orderbook.book import OrderBookError, OrderBookSnapshot

NOBITEX_API = "https://apiv2.nobitex.ir"
# A book older than this is not "the book at" a moment; the provider answers None.
DEFAULT_MAX_AGE = pd.Timedelta(minutes=2)


def utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


class OrderBookSource(Protocol):
    def snapshot(self, symbol: str, at: pd.Timestamp) -> OrderBookSnapshot | None: ...


def _utc(at: pd.Timestamp) -> pd.Timestamp:
    t = pd.Timestamp(at)
    if t.tzinfo is None:
        raise ValueError(f"order-book times are UTC and tz-aware; got naive {t}")
    return t


def _stale(s: OrderBookSnapshot, at: pd.Timestamp, max_age: pd.Timedelta | None) -> bool:
    """Too old to be the book "at" ``at``, judged by when the exchange last updated it."""
    if max_age is None:
        return False
    born = s.exchange_time if s.exchange_time is not None else s.time
    return at - born > max_age


def parse_nobitex(payload: Mapping[str, object], symbol: str) -> OrderBookSnapshot:
    """One Nobitex order-book (v3) or depth (v2) response -> a snapshot."""
    if payload.get("status", "ok") != "ok":
        raise OrderBookError(f"Nobitex order book for {symbol}: {payload.get('status')} {payload}")
    try:
        t = pd.Timestamp(int(str(payload["lastUpdate"])), unit="ms", tz="UTC")
        last = payload.get("lastTradePrice")
        return OrderBookSnapshot.of(
            symbol,
            t,
            payload["bids"],  # type: ignore[arg-type]
            payload["asks"],  # type: ignore[arg-type]
            None if last in (None, "") else float(str(last)),
            exchange_time=t,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OrderBookError(f"Nobitex order book for {symbol}: unexpected shape ({exc})") from exc


class NobitexOrderBook:
    """Live snapshots from Nobitex (``endpoint`` "orderbook" or "depth").

    ``snapshots_now`` reads many symbols in one ``/v3/orderbook/all`` call and
    returns those the exchange answered for; the recorder reports the rest.
    """

    PATHS = {"orderbook": "/v3/orderbook/", "depth": "/v2/depth/"}

    def __init__(
        self,
        *,
        http_get: HttpGet | None = None,
        base_url: str = NOBITEX_API,
        endpoint: str = "orderbook",
        clock: Callable[[], pd.Timestamp] = utc_now,
        max_age: pd.Timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        if endpoint not in self.PATHS:
            raise ValueError(f"endpoint must be one of {tuple(self.PATHS)}")
        self.http_get = http_get or default_http_get
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint
        self.clock = clock
        self.max_age = max_age

    def _get(self, path: str) -> dict[str, object]:
        data: dict[str, object] = json.loads(self.http_get(f"{self.base_url}{path}"))
        if data.get("status", "ok") != "ok":
            raise OrderBookError(f"Nobitex {path}: {data}")
        return data

    def snapshot(self, symbol: str, at: pd.Timestamp | None = None) -> OrderBookSnapshot | None:
        """The current book. A live source cannot look back: an old ``at`` gets None."""
        if at is not None and self.clock() - _utc(at) > self.max_age:
            return None
        path = self.PATHS[self.endpoint] + quote(udf_symbol(symbol))
        return parse_nobitex(self._get(path), symbol)

    def snapshots_now(self, symbols: Sequence[str]) -> dict[str, OrderBookSnapshot]:
        if len(symbols) == 1 or self.endpoint == "depth":
            out = {}
            for sym in symbols:
                s = self.snapshot(sym)
                if s is not None:
                    out[sym] = s
            return out
        data = self._get("/v3/orderbook/all")
        books = {sym: data.get(udf_symbol(sym)) for sym in symbols}
        return {sym: parse_nobitex(b, sym) for sym, b in books.items() if isinstance(b, dict)}


class _History:
    """Snapshots in time order per symbol, answered without lookahead.

    Subclasses provide ``_series(symbol)``: the symbol's snapshots sorted by the
    time they were seen.
    """

    def __init__(self, max_age: pd.Timedelta | None) -> None:
        self.max_age = max_age
        self._times: dict[str, list[pd.Timestamp]] = {}

    def _series(self, symbol: str) -> list[OrderBookSnapshot]:
        raise NotImplementedError

    def _index(self, symbol: str) -> tuple[list[OrderBookSnapshot], list[pd.Timestamp]]:
        snaps = self._series(symbol)
        if symbol not in self._times:
            self._times[symbol] = [s.time for s in snaps]
        return snaps, self._times[symbol]

    def snapshots(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[OrderBookSnapshot]:
        snaps, times = self._index(symbol)
        lo = bisect.bisect_left(times, _utc(start))
        hi = bisect.bisect_right(times, _utc(end))
        return snaps[lo:hi]

    def snapshot(self, symbol: str, at: pd.Timestamp) -> OrderBookSnapshot | None:
        """The latest book seen at or before ``at``; None if none, or if stale."""
        snaps, times = self._index(symbol)
        at = _utc(at)
        i = bisect.bisect_right(times, at) - 1
        if i < 0 or _stale(snaps[i], at, self.max_age):
            return None
        return snaps[i]

    def gaps(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp, max_gap: pd.Timedelta
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Stretches of [start, end] longer than ``max_gap`` with no snapshot."""
        start, end = _utc(start), _utc(end)
        times = [s.time for s in self.snapshots(symbol, start, end)]
        edges = [start, *times, end]
        return [(a, b) for a, b in pairwise(edges) if b - a > max_gap]


class FixtureOrderBook(_History):
    """In-memory snapshots for tests and demos."""

    def __init__(
        self, snapshots: Iterable[OrderBookSnapshot], *, max_age: pd.Timedelta | None = None
    ) -> None:
        super().__init__(max_age)
        self._by_symbol: dict[str, list[OrderBookSnapshot]] = {}
        for s in sorted(snapshots, key=lambda s: (s.symbol, s.time)):
            self._by_symbol.setdefault(s.symbol, []).append(s)

    def _series(self, symbol: str) -> list[OrderBookSnapshot]:
        return self._by_symbol.get(symbol, [])


def _symbol_dir(root: Path, symbol: str) -> Path:
    return root / symbol.replace("/", "_").replace(":", "_")


class RecordedOrderBook(_History):
    """Snapshots the recorder wrote under ``root/<SYMBOL>/<UTC date>.jsonl``.

    A line that does not parse (the recorder killed mid-write) is skipped and
    counted in ``skipped_lines``; the rest of the recording stays usable.
    """

    def __init__(self, root: Path | str, *, max_age: pd.Timedelta | None = DEFAULT_MAX_AGE):
        super().__init__(max_age)
        self.root = Path(root)
        self.skipped_lines = 0
        self._cache: dict[str, list[OrderBookSnapshot]] = {}

    def _series(self, symbol: str) -> list[OrderBookSnapshot]:
        if symbol not in self._cache:
            snaps = []
            for f in sorted(_symbol_dir(self.root, symbol).glob("*.jsonl")):
                for ln in f.read_text().splitlines():
                    try:
                        snaps.append(OrderBookSnapshot.from_json(json.loads(ln)))
                    except (ValueError, KeyError, TypeError):
                        self.skipped_lines += 1
            self._cache[symbol] = sorted(snaps, key=lambda s: s.time)
        return self._cache[symbol]


def append_snapshot(root: Path | str, snapshot: OrderBookSnapshot) -> Path:
    path = _symbol_dir(Path(root), snapshot.symbol) / f"{snapshot.time.date().isoformat()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(snapshot.to_json(), separators=(",", ":")) + "\n")
    return path
