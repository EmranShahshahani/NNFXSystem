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


class OrderBookSource(Protocol):
    def snapshot(self, symbol: str, at: pd.Timestamp | None = None) -> OrderBookSnapshot | None: ...


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
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise OrderBookError(f"Nobitex order book for {symbol}: unexpected shape ({exc})") from exc


class NobitexOrderBook:
    """Live snapshots from Nobitex; ``snapshots_now`` reads many symbols in one call."""

    name = "nobitex"

    def __init__(
        self,
        *,
        http_get: HttpGet | None = None,
        base_url: str = NOBITEX_API,
        clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
        max_age: pd.Timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        self.http_get = http_get or default_http_get
        self.base_url = base_url.rstrip("/")
        self.clock = clock
        self.max_age = max_age

    def _get(self, path: str) -> dict[str, object]:
        data: dict[str, object] = json.loads(self.http_get(f"{self.base_url}{path}"))
        return data

    def snapshot(self, symbol: str, at: pd.Timestamp | None = None) -> OrderBookSnapshot | None:
        """The current book. A live source cannot look back: an old ``at`` gets None."""
        if at is not None and self.clock() - pd.Timestamp(at) > self.max_age:
            return None
        return parse_nobitex(self._get(f"/v3/orderbook/{quote(udf_symbol(symbol))}"), symbol)

    def snapshots_now(self, symbols: Sequence[str]) -> dict[str, OrderBookSnapshot]:
        if len(symbols) == 1:
            s = self.snapshot(symbols[0])
            assert s is not None
            return {symbols[0]: s}
        data = self._get("/v3/orderbook/all")
        if data.get("status", "ok") != "ok":
            raise OrderBookError(f"Nobitex order book (all): {data}")
        out = {}
        for sym in symbols:
            book = data.get(udf_symbol(sym))
            if not isinstance(book, dict):
                raise OrderBookError(f"Nobitex order book (all): no market {udf_symbol(sym)}")
            out[sym] = parse_nobitex(book, sym)
        return out


class _History:
    """Snapshots in time order per symbol, answered without lookahead."""

    def __init__(self, max_age: pd.Timedelta | None) -> None:
        self.max_age = max_age
        self._by_symbol: dict[str, list[OrderBookSnapshot]] = {}

    def _load(self, symbol: str) -> list[OrderBookSnapshot]:
        return self._by_symbol.get(symbol, [])

    def snapshots(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[OrderBookSnapshot]:
        return [s for s in self._load(symbol) if start <= s.time <= end]

    def snapshot(self, symbol: str, at: pd.Timestamp | None = None) -> OrderBookSnapshot | None:
        snaps = self._load(symbol)
        if not snaps:
            return None
        if at is None:
            return snaps[-1]
        i = bisect.bisect_right([s.time for s in snaps], pd.Timestamp(at)) - 1
        if i < 0:
            return None
        s = snaps[i]
        if self.max_age is not None and pd.Timestamp(at) - s.time > self.max_age:
            return None
        return s


class FixtureOrderBook(_History):
    """In-memory snapshots for tests and demos."""

    def __init__(
        self, snapshots: Iterable[OrderBookSnapshot], *, max_age: pd.Timedelta | None = None
    ) -> None:
        super().__init__(max_age)
        for s in sorted(snapshots, key=lambda s: (s.symbol, s.time)):
            self._by_symbol.setdefault(s.symbol, []).append(s)


def _symbol_dir(root: Path, symbol: str) -> Path:
    return root / symbol.replace("/", "_").replace(":", "_")


class RecordedOrderBook(_History):
    """Snapshots the recorder wrote under ``root/<SYMBOL>/<date>.jsonl``."""

    def __init__(self, root: Path | str, *, max_age: pd.Timedelta | None = DEFAULT_MAX_AGE):
        super().__init__(max_age)
        self.root = Path(root)

    def _load(self, symbol: str) -> list[OrderBookSnapshot]:
        if symbol not in self._by_symbol:
            snaps = []
            for f in sorted(_symbol_dir(self.root, symbol).glob("*.jsonl")):
                snaps += [
                    OrderBookSnapshot.from_json(json.loads(ln))
                    for ln in f.read_text().splitlines()
                    if ln
                ]
            self._by_symbol[symbol] = sorted(snaps, key=lambda s: s.time)
        return self._by_symbol[symbol]


def append_snapshot(root: Path | str, snapshot: OrderBookSnapshot) -> Path:
    path = _symbol_dir(Path(root), snapshot.symbol) / f"{snapshot.time.date().isoformat()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(snapshot.to_json(), separators=(",", ":")) + "\n")
    return path
