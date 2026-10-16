"""Bars from any TradingView-UDF ``/history`` endpoint, with a Nobitex preset.

The UDF protocol (the one TradingView's charting library speaks to a broker's
own datafeed) is ``GET {base}/history?symbol=&resolution=&from=&to=`` answering
``{"s": "ok", "t": [...], "o": [...], "h": [...], "l": [...], "c": [...], "v": [...]}``
with ``t`` the bar *open* in unix seconds, ``{"s": "no_data"}`` for an empty
window, or ``{"s": "error", "errmsg": ...}``. Many exchanges' web charts sit on
one, so any of them plugs in through ``UdfFeed(base_url=...)``.

Nobitex (https://apidocs.nobitex.ir, "OHLC" under market data) serves it at
``https://apiv2.nobitex.ir/market/udf/history`` with symbols such as ``BTCIRT``
and ``BTCUSDT``; IRT prices are in rials. Its daily candles are cut at Tehran
midnight, so we always fetch hourly bars and let the data layer apply our own
session close (doc 03 §2b). Price and traded volume come from the same venue.

HTTP and the sleep between requests are injected, so the feed is testable offline.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.parse import urlencode

import pandas as pd

from nnfx.data.bars import BarFrame
from nnfx.data.dukascopy import default_http_get
from nnfx.data.feeds import HttpGet

NOBITEX_URL = "https://apiv2.nobitex.ir/market/udf"
HOUR = 3600


class UdfError(RuntimeError):
    pass


def udf_symbol(symbol: str) -> str:
    """``BTC/USDT`` (our naming) -> ``BTCUSDT`` (exchange naming)."""
    return symbol.split(":")[0].replace("/", "").upper()


def parse_history(payload: dict[str, object]) -> pd.DataFrame:
    """One UDF history response -> an OHLCV frame indexed by bar open (UTC)."""
    status = payload.get("s")
    if status == "no_data":
        return pd.DataFrame(
            {c: pd.Series(dtype="float64") for c in ("open", "high", "low", "close", "volume")},
            index=pd.DatetimeIndex([], tz="UTC"),
        )
    if status != "ok":
        raise UdfError(f"UDF history error: {payload.get('errmsg', payload)!r}")
    cols = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    t = payload["t"]
    assert isinstance(t, list)
    data = {}
    for k, name in cols.items():
        v = payload.get(k, [0.0] * len(t) if k == "v" else None)
        if not isinstance(v, list) or len(v) != len(t):
            raise UdfError(f"UDF history: field {k!r} missing or not aligned with t")
        data[name] = [float(x) for x in v]
    df = pd.DataFrame(data, index=pd.to_datetime(pd.Series(t, dtype="int64"), unit="s", utc=True))
    return df


class UdfFeed:
    """Hourly bars from a UDF datafeed, paged by time window."""

    def __init__(
        self,
        base_url: str,
        *,
        name: str = "udf",
        http_get: HttpGet | None = None,
        bars_per_request: int = 500,
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.http_get = http_get or default_http_get
        self.bars_per_request = bars_per_request
        self.min_interval_s = min_interval_s
        self.sleep = sleep
        self.clock = clock

    def url(self, symbol: str, start_s: int, end_s: int) -> str:
        q = urlencode(
            {"symbol": udf_symbol(symbol), "resolution": "60", "from": start_s, "to": end_s}
        )
        return f"{self.base_url}/history?{q}"

    def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame:
        now = self.clock()
        end = min(pd.Timestamp(end), now)
        lo = int(pd.Timestamp(start).timestamp())
        hi = int(end.timestamp())
        step = self.bars_per_request * HOUR
        parts = []
        first = True
        for a in range(lo, hi + 1, step):
            if not first and self.min_interval_s > 0:
                self.sleep(self.min_interval_s)
            first = False
            raw = self.http_get(self.url(symbol, a, min(a + step - 1, hi)))
            parts.append(parse_history(json.loads(raw)))
        df = pd.concat(parts) if parts else parse_history({"s": "no_data"})
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # UDF stamps bar open; our contract labels by close. Drop the forming bar.
        df.index = pd.DatetimeIndex(df.index + pd.Timedelta(hours=1))
        df = df[df.index <= now]
        return BarFrame(df, symbol, timeframe="H1", volume_kind="traded", price_venue=self.name)


def nobitex(**kwargs: object) -> UdfFeed:
    return UdfFeed(NOBITEX_URL, name="nobitex", **kwargs)  # type: ignore[arg-type]
