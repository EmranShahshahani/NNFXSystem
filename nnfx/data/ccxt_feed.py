"""Crypto bars through ccxt (doc 03 §2b).

Price and volume always come from the same exchange: the frame records the
exchange as both ``price_venue`` and ``volume_venue``, and ``BarFrame`` refuses
traded volume from a different venue. Volume is genuine traded size and is never
flagged as tick volume. The exchange object is injected for offline testing.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from nnfx.data.bars import BarFrame


class OhlcvExchange(Protocol):
    id: str

    def fetch_ohlcv(
        self, symbol: str, timeframe: str = ..., since: int | None = ..., limit: int | None = ...
    ) -> list[list[float]]: ...


def make_exchange(exchange_id: str, **kwargs: Any) -> OhlcvExchange:
    import ccxt

    ex: OhlcvExchange = getattr(ccxt, exchange_id)({"enableRateLimit": True, **kwargs})
    return ex


class CcxtFeed:
    def __init__(self, exchange: OhlcvExchange, page: int = 1000) -> None:
        self.exchange = exchange
        self.page = page

    @property
    def name(self) -> str:
        return f"ccxt-{self.exchange.id}"

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame:
        since = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)
        rows: list[list[float]] = []
        while since <= end_ms:
            batch = self.exchange.fetch_ohlcv(symbol, "1h", since, self.page)
            if not batch:
                break
            rows += [r for r in batch if r[0] <= end_ms]
            nxt = int(batch[-1][0]) + 3_600_000
            if nxt <= since:
                break
            since = nxt
        df = pd.DataFrame(
            rows, columns=["ts", "open", "high", "low", "close", "volume"]
        ).drop_duplicates("ts")
        # ccxt timestamps are bar *open*; our contract labels by close.
        idx = pd.to_datetime(df.pop("ts"), unit="ms", utc=True) + pd.Timedelta(hours=1)
        df.index = pd.DatetimeIndex(idx)
        return BarFrame(
            df, symbol, timeframe="H1", volume_kind="traded", price_venue=self.exchange.id
        )
