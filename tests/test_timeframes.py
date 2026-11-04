"""Intraday base bars and multi-timeframe views (Strategy Builder ticket 01)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
from nnfx.data.timeframes import TimeframeViews, resample
from nnfx.instruments import crypto_spec

BTC = crypto_spec("BTC/USDT")


def m15(n: int, start: str = "2024-01-01", *, seed: int = 0, first_close: str | None = None):
    """``n`` 15-minute bars whose first bar opens at ``start`` (UTC); close = 100 + i."""
    t0 = pd.Timestamp(first_close or pd.Timestamp(start) + pd.Timedelta(minutes=15), tz="UTC")
    idx = pd.date_range(t0, periods=n, freq="15min")
    c = 100.0 + np.arange(n)
    df = pd.DataFrame(
        {"open": c - 0.5, "high": c + 1, "low": c - 1, "close": c, "volume": np.ones(n)},
        index=idx,
    )
    return BarFrame(df, "BTC/USDT", timeframe="M15", volume_kind="traded", price_venue="x")


def test_four_hour_bar_aggregates_its_sixteen_quarter_hours():
    base = m15(16 * 3)  # 2024-01-01 00:00 .. 12:00
    h4 = resample(base, "H4", instrument=BTC, session=SessionConfig())
    assert h4.timeframe == "H4"
    assert list(h4.index) == [
        pd.Timestamp("2024-01-01 04:00", tz="UTC"),
        pd.Timestamp("2024-01-01 08:00", tz="UTC"),
        pd.Timestamp("2024-01-01 12:00", tz="UTC"),
    ]
    # First 4H bar: closes 100..115.
    assert h4.open[0] == 99.5 and h4.close[0] == 115.0
    assert h4.high[0] == 116.0 and h4.low[0] == 99.0 and h4.volume[0] == 16.0
    assert h4.price_venue == "x" and h4.volume_kind == "traded"


def test_partial_first_and_last_buckets_are_dropped():
    # Starts at 00:30 (first 4H bucket incomplete) and stops at 09:00 (third incomplete).
    base = m15(34, first_close="2024-01-01 00:45")
    h4 = resample(base, "H4", instrument=BTC, session=SessionConfig())
    assert list(h4.index) == [pd.Timestamp("2024-01-01 08:00", tz="UTC")]


def test_daily_and_weekly_from_quarter_hours_close_at_utc_midnight_and_monday():
    base = m15(96 * 21)  # Mon 2024-01-01 .. Sun 2024-01-21, three whole weeks
    d1 = resample(base, "D1", instrument=BTC, session=SessionConfig())
    assert len(d1) == 21 and set(d1.index.hour) == {0}
    assert d1.close[0] == 100.0 + 95  # last quarter hour of 1 January
    w1 = resample(base, "W1", instrument=BTC, session=SessionConfig())
    assert list(w1.index) == [
        pd.Timestamp(d, tz="UTC") for d in ("2024-01-08", "2024-01-15", "2024-01-22")
    ]
    assert w1.open[0] == d1.open[0] and w1.close[0] == d1.close[6]
    assert w1.high[1] == d1.high[7:14].max()


def test_a_week_still_in_progress_is_not_a_bar():
    base = m15(96 * 10)  # Monday 1st .. Wednesday 10th
    w1 = resample(base, "W1", instrument=BTC, session=SessionConfig())
    assert list(w1.index) == [pd.Timestamp("2024-01-08", tz="UTC")]


def test_unclosed_four_hour_bar_is_never_visible_from_a_quarter_hour_inside_it():
    views = TimeframeViews(m15(96 * 3), instrument=BTC, session=SessionConfig())
    h4 = views.frame("H4")
    for t in views.base.index:
        seen = views.as_of("H4", t)
        if len(seen):
            assert seen.index[-1] <= t
        # Every 4H bar closing after t is hidden, including the one t sits inside.
        assert len(seen) == int((h4.index <= t).sum())
    inside = pd.Timestamp("2024-01-02 06:15", tz="UTC")
    assert views.as_of("H4", inside).index[-1] == pd.Timestamp("2024-01-02 04:00", tz="UTC")
    on_close = pd.Timestamp("2024-01-02 08:00", tz="UTC")
    assert views.as_of("H4", on_close).index[-1] == on_close
    assert views.latest_closed("D1", pd.Timestamp("2024-01-01 23:45", tz="UTC")) == -1


def test_views_agree_with_hourly_base_and_reject_bad_requests():
    base = m15(96 * 7)
    views = TimeframeViews(base, instrument=BTC, session=SessionConfig())
    assert views.timeframes == ("M15", "H1", "H4", "D1", "W1")
    via_h1 = resample(views.frame("H1"), "D1", instrument=BTC, session=SessionConfig())
    assert via_h1.df.equals(views.frame("D1").df)
    with pytest.raises(ValueError, match="coarser"):
        resample(views.frame("H1"), "M15", instrument=BTC, session=SessionConfig())
    with pytest.raises(ValueError, match="base bars"):
        resample(views.frame("H4"), "D1", instrument=BTC, session=SessionConfig())
    with pytest.raises(ValueError, match="no M5 view"):
        views.frame("M5")


# ------------------------------------------------------------------ feeds
def test_udf_feed_fetches_quarter_hours_labelled_by_close():
    from urllib.parse import parse_qs, urlparse

    from nnfx.data.udf import nobitex

    t0 = 1_704_067_200  # 2024-01-01 00:00 UTC
    opens = t0 + 900 * np.arange(96 * 2)
    calls: list[dict[str, list[str]]] = []

    def get(url: str) -> bytes:
        import json

        q = parse_qs(urlparse(url).query)
        calls.append(q)
        m = (opens >= int(q["from"][0])) & (opens <= int(q["to"][0]))
        c = (100.0 + np.arange(len(opens)))[m].tolist()
        body = {"s": "ok", "t": opens[m].tolist(), "o": c, "h": c, "l": c, "c": c, "v": c}
        return json.dumps(body).encode()

    now = pd.Timestamp(int(opens[-1]) + 600, unit="s", tz="UTC")  # last bar still forming
    feed = nobitex(timeframe="M15", http_get=get, sleep=lambda s: None, clock=lambda: now)
    f = feed.bars("BTC/IRT", pd.Timestamp(t0, unit="s", tz="UTC"), now)
    assert {q["resolution"][0] for q in calls} == {"15"} and len(calls) == 1
    assert f.timeframe == "M15" and len(f) == 96 * 2 - 1
    assert f.index[0] == pd.Timestamp("2024-01-01 00:15", tz="UTC")


def test_ccxt_feed_fetches_quarter_hours():
    from nnfx.data.ccxt_feed import CcxtFeed

    t0 = 1_704_067_200_000
    rows = [[t0 + 900_000 * i, 1.0, 2.0, 0.5, 1.5, 3.0] for i in range(250)]

    class Ex:
        id = "binance"
        frames: list[str] = []

        def fetch_ohlcv(self, symbol, timeframe="1h", since=None, limit=None):
            self.frames.append(timeframe)
            return [r for r in rows if since is None or r[0] >= since][: limit or 1000]

    ex = Ex()
    f = CcxtFeed(ex, page=100, timeframe="M15").bars(
        "BTC/USDT", pd.Timestamp(t0, unit="ms", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    )
    assert set(ex.frames) == {"15m"} and len(f) == 250 and f.timeframe == "M15"
    assert f.index[0] == pd.Timestamp("2024-01-01 00:15", tz="UTC")


def test_tradingview_quarter_hour_export(tmp_path):
    from nnfx.data.tradingview import read_tradingview_csv

    t = 1_704_067_200 + 900 * np.arange(4)
    pd.DataFrame({"time": t, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}).to_csv(
        tmp_path / "tv.csv", index=False
    )
    f = read_tradingview_csv(tmp_path / "tv.csv", "BTC/USDT", timeframe="M15")
    assert f.timeframe == "M15" and f.index[0] == pd.Timestamp("2024-01-01 00:15", tz="UTC")


# ------------------------------------------------------------------ gates
def test_gates_run_on_quarter_hour_input():
    from nnfx.data.gates import IntegrityError, ensure_clean, run_gates

    clean = run_gates(m15(96 * 3), BTC)
    assert clean.ok and not clean.flags
    assert "intraday_gaps" in {r.gate for r in clean.results}

    df = m15(96 * 3).df
    gappy = BarFrame(df.drop(df.index[40:44]), "BTC/USDT", timeframe="M15", price_venue="x")
    gap = next(r for r in run_gates(gappy, BTC).results if r.gate == "intraday_gaps")
    assert not gap.passed and gap.severity == "flag"
    assert gap.timestamps[0] == df.index[40] and len(gap.timestamps) == 4

    df.iloc[10, df.columns.get_loc("high")] = 0.1
    bad = BarFrame(df, "BTC/USDT", timeframe="M15", price_venue="x")
    with pytest.raises(IntegrityError, match="high_low"):
        ensure_clean(bad, BTC)


# -------------------------------------------------------------------- cli
def test_cli_fetches_quarter_hours_and_backtest_loading_resamples_them(tmp_path, monkeypatch):
    import json

    import nnfx.data.udf as udf
    from nnfx.cli import _load, main
    from nnfx.config import load_system_config

    src = m15(96 * 4)
    opens = (src.index - pd.Timedelta(minutes=15)).asi8 // 10**9

    def get(url: str) -> bytes:
        c = src.close.tolist()
        body = {"s": "ok", "t": opens.tolist(), "o": c, "h": c, "l": c, "c": c, "v": c}
        return json.dumps(body).encode()

    monkeypatch.setattr(udf, "default_http_get", get)
    monkeypatch.setattr(udf.time, "sleep", lambda s: None)
    rc = main(
        [
            "fetch", "--feed", "nobitex", "--timeframe", "M15", "--symbol", "BTC/USDT",
            "--start", "2024-01-01", "--end", "2024-01-05", "--cache", str(tmp_path),
            "--no-manifest",
        ]
    )  # fmt: skip
    assert rc == 0
    cached = tmp_path / "nobitex" / "BTC_USDT.M15.csv"
    assert cached.exists()

    class Args:
        timeframe = "M15"

    d1 = _load(Args(), load_system_config("config/system.yaml"), "BTC/USDT", str(cached), BTC)
    assert d1.timeframe == "D1" and len(d1) == 4


def test_weekly_bars_keep_the_week_close_label_across_a_data_gap():
    df = m15(96 * 28).df  # Mon 1 Jan .. Sun 28 Jan
    hole = (df.index > pd.Timestamp("2024-01-10", tz="UTC")) & (
        df.index <= pd.Timestamp("2024-01-20", tz="UTC")
    )
    base = BarFrame(df[~hole], "BTC/USDT", timeframe="M15", price_venue="x")
    w1 = resample(base, "W1", instrument=BTC, session=SessionConfig())
    # The week of 8 January is labelled at its close (Monday 15th), never mid-week.
    assert list(w1.index) == [
        pd.Timestamp(d, tz="UTC") for d in ("2024-01-08", "2024-01-15", "2024-01-22", "2024-01-29")
    ]
    assert w1.volume[1] == 96 * 2  # only the two days that exist
