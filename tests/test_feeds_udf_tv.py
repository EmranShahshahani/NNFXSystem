"""Nobitex/UDF feed and TradingView CSV import, offline (ticket 03 extension)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.session import resample_to_daily
from nnfx.data.tradingview import read_tradingview_csv
from nnfx.data.udf import UdfError, UdfFeed, nobitex, parse_history, udf_symbol
from nnfx.instruments import crypto_spec

# The example response in Nobitex's own docs (market data -> OHLC).
DOC_EXAMPLE = {
    "s": "ok",
    "t": [1562095800, 1562182200],
    "o": [146272500, 150551000],
    "h": [155869600, 161869500],
    "l": [140062400, 150551000],
    "c": [151440200, 157000000],
    "v": [18.221362316, 9.8592626506],
}


def test_parse_documented_example():
    df = parse_history(DOC_EXAMPLE)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index[0] == pd.Timestamp(1562095800, unit="s", tz="UTC")
    assert df["close"].iloc[1] == 157000000.0


def test_no_data_and_error():
    assert parse_history({"s": "no_data"}).empty
    with pytest.raises(UdfError, match="Invalid resolution"):
        parse_history({"s": "error", "errmsg": "Invalid resolution!"})
    with pytest.raises(UdfError, match="not aligned"):
        parse_history({"s": "ok", "t": [1, 2], "o": [1], "h": [1, 2], "l": [1, 2], "c": [1, 2]})


def test_symbol_mapping():
    assert udf_symbol("BTC/IRT") == "BTCIRT"
    assert udf_symbol("BTC/USDT:USDT") == "BTCUSDT"


class FakeUdf:
    """Serves hourly bars from a frame, honouring from/to like a UDF server."""

    def __init__(self, n_hours: int, start: int = 1_700_000_000 - 1_700_000_000 % 3600):
        self.t = start + 3600 * np.arange(n_hours)
        rng = np.random.default_rng(1)
        self.c = 100 + np.cumsum(rng.normal(0, 0.5, n_hours))
        self.calls: list[dict[str, list[str]]] = []

    def __call__(self, url: str) -> bytes:
        q = parse_qs(urlparse(url).query)
        self.calls.append(q)
        assert q["resolution"] == ["60"]
        a, b = int(q["from"][0]), int(q["to"][0])
        m = (self.t >= a) & (self.t <= b)
        if not m.any():
            return json.dumps({"s": "no_data"}).encode()
        c = self.c[m]
        return json.dumps(
            {
                "s": "ok",
                "t": self.t[m].tolist(),
                "o": c.tolist(),
                "h": (c + 1).tolist(),
                "l": (c - 1).tolist(),
                "c": c.tolist(),
                "v": [1.0] * int(m.sum()),
            }
        ).encode()


def test_udf_pages_dedupes_labels_by_close_and_drops_forming_bar():
    fake = FakeUdf(24 * 30)
    t0 = pd.Timestamp(int(fake.t[0]), unit="s", tz="UTC")
    now = t0 + pd.Timedelta(hours=24 * 30 - 1, minutes=30)  # last bar still forming
    sleeps: list[float] = []
    feed = UdfFeed(
        "https://x.test/udf",
        name="x",
        http_get=fake,
        bars_per_request=100,
        sleep=sleeps.append,
        clock=lambda: now,
    )
    f = feed.bars("BTC/USDT", t0, t0 + pd.Timedelta(days=60))
    assert len(fake.calls) > 1 and len(sleeps) == len(fake.calls) - 1
    assert f.index[0] == t0 + pd.Timedelta(hours=1)  # labelled by close
    assert f.index[-1] <= now
    assert len(f) == 24 * 30 - 1
    assert f.price_venue == f.volume_venue == "x" and f.volume_kind == "traded"
    assert f.index.is_monotonic_increasing and not f.index.duplicated().any()


def test_nobitex_preset_url():
    feed = nobitex()
    u = feed.url("BTC/IRT", 10, 20)
    assert u.startswith("https://apiv2.nobitex.ir/market/udf/history?")
    assert "symbol=BTCIRT" in u and "resolution=60" in u


def test_udf_hourly_resamples_to_utc_midnight_daily():
    fake = FakeUdf(24 * 10, start=1_700_006_400)  # 2023-11-15 00:00 UTC
    t0 = pd.Timestamp(1_700_006_400, unit="s", tz="UTC")
    feed = UdfFeed(
        "u", http_get=fake, sleep=lambda s: None, clock=lambda: t0 + pd.Timedelta(days=30)
    )
    h1 = feed.bars("BTC/USDT", t0, t0 + pd.Timedelta(days=10))
    d1 = resample_to_daily(h1, crypto_spec("BTC/USDT", "crypto_spot"), SessionConfig())
    assert all(ts.hour == 0 for ts in d1.index)


def test_tradingview_export_unix_and_iso(tmp_path: Path):
    t = 1_700_006_400 + 3600 * np.arange(5)
    df = pd.DataFrame(
        {
            "time": t,
            "open": [1.0, 2, 3, 4, 5],
            "high": [2.0, 3, 4, 5, 6],
            "low": [0.5, 1, 2, 3, 4],
            "close": [1.5, 2.5, 3.5, 4.5, 5.5],
            "Volume": [10, 11, 12, 13, 14],
            "Plot": [0.1] * 5,  # indicator column on the chart, must be dropped
        }
    )
    p = tmp_path / "tv.csv"
    df.to_csv(p, index=False)
    f = read_tradingview_csv(p, "EURUSD", volume_kind="tick", venue="tradingview-OANDA")
    assert f.index[0] == pd.Timestamp(int(t[0]) + 3600, unit="s", tz="UTC")
    assert list(f.df.columns) == ["open", "high", "low", "close", "volume"]
    assert f.volume_kind == "tick"

    iso = df.assign(
        time=pd.to_datetime(t, unit="s", utc=True).tz_convert("Asia/Tehran").astype(str)
    )
    p2 = tmp_path / "tv_iso.csv"
    iso.drop(columns=["Volume"]).to_csv(p2, index=False)
    g = read_tradingview_csv(p2, "EURUSD")
    assert (g.index == f.index).all() and g.volume_kind == "none"


def test_tradingview_rejects_daily_exports(tmp_path: Path):
    with pytest.raises(ValueError, match="1h"):
        read_tradingview_csv(tmp_path / "x.csv", "EURUSD", timeframe="D1")
