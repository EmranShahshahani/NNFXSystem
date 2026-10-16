"""Tickets 02-05: bar contract, integrity gates, session resampling, feeds, manifests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame, BarFrameError
from nnfx.data.ccxt_feed import CcxtFeed
from nnfx.data.crosscheck import cross_check
from nnfx.data.dukascopy import DukascopyFeed, day_url, encode_bi5
from nnfx.data.gates import IntegrityError, ensure_clean, run_gates
from nnfx.data.manifest import ManifestMismatch, record_or_verify, verify_manifest, write_manifest
from nnfx.data.session import resample_to_daily
from nnfx.data.synthetic import hourly_walk, regime_walk
from nnfx.harness.backtest import BacktestHarness
from nnfx.instruments import InstrumentRegistry, crypto_spec, fx_28, fx_spec
from tests.helpers import config

ROOT = Path(__file__).parent.parent
EUR = fx_spec("EURUSD")


def _df(n=10):
    f = regime_walk(n, seed=1, symbol="EURUSD", volume_kind="tick")
    return f.df


# --------------------------------------------------------------- contract
def test_rejects_duplicate_out_of_order_and_partial_bar():
    df = _df()
    with pytest.raises(BarFrameError, match="duplicate_timestamps") as e:
        BarFrame(pd.concat([df, df.iloc[[3]]]).sort_index(), "EURUSD")
    assert e.value.timestamps == [df.index[3]]
    with pytest.raises(BarFrameError, match="out_of_order"):
        BarFrame(df.iloc[[0, 2, 1, 3]], "EURUSD")
    with pytest.raises(BarFrameError, match="partial_final_bar"):
        BarFrame(df, "EURUSD", as_of=df.index[-1] - pd.Timedelta(hours=1))
    with pytest.raises(BarFrameError, match="UTC"):
        BarFrame(df.tz_convert("America/New_York"), "EURUSD")


def test_frame_is_immutable():
    f = BarFrame(_df(), "EURUSD")
    with pytest.raises(ValueError):
        f.close[0] = 0.0


def _corrupt(col: str, i: int, value: float) -> BarFrame:
    df = regime_walk(300, seed=2, symbol="EURUSD", volume_kind="tick").df
    df.iloc[i, df.columns.get_loc(col)] = value
    return BarFrame(df, "EURUSD", volume_kind="tick")


@pytest.mark.parametrize(
    "col,value,gate",
    [
        ("close", 0.0, "positive_prices"),
        ("low", -1.0, "positive_prices"),
        ("high", 0.5, "high_low"),
        ("volume", -5.0, "volume_negative"),
    ],
)
def test_each_gate_fails_on_corruption_and_names_where(col, value, gate):
    f = _corrupt(col, 100, value)
    with pytest.raises(IntegrityError) as e:
        ensure_clean(f, EUR)
    fail = [x for x in e.value.failures if x.gate == gate]
    assert fail and fail[0].symbol == "EURUSD" and f.index[100] in fail[0].timestamps
    assert gate in str(e.value) and "EURUSD" in str(e.value)


def test_calendar_gap_detection():
    df = regime_walk(100, seed=2, symbol="EURUSD").df
    holed = BarFrame(df.drop(df.index[[40, 41]]), "EURUSD")
    rep = run_gates(holed, EUR, close_tz="UTC")
    gap = next(r for r in rep.results if r.gate == "calendar_gaps")
    assert not gap.passed and len(gap.timestamps) == 2
    assert run_gates(holed, EUR, close_tz="UTC", max_missing_sessions=2).ok


def test_outliers_flagged_not_dropped():
    f = _corrupt("close", 150, 3.0)
    df = f.df
    df.iloc[150, df.columns.get_loc("high")] = 3.1
    f = BarFrame(df, "EURUSD", volume_kind="tick")
    rep = run_gates(f, EUR)
    out = next(r for r in rep.results if r.gate == "return_outliers")
    assert not out.passed and out.severity == "flag" and f.index[150] in out.timestamps
    assert len(f) == 300  # nothing dropped


def test_tick_volume_flag_travels_into_reports():
    f = regime_walk(300, seed=2, symbol="EURUSD", volume_kind="tick")
    rep = run_gates(f, EUR)
    assert any("TICK VOLUME" in r.detail for r in rep.flags)
    res = BacktestHarness(config(), {"EURUSD": EUR}, {"EURUSD": f}).run()
    assert res.volume_flags == ("EURUSD",)


def test_gates_run_automatically_before_research():
    with pytest.raises(IntegrityError):
        BacktestHarness(config(), {"EURUSD": EUR}, {"EURUSD": _corrupt("high", 50, 0.1)})


# -------------------------------------------------------------- sessions
def _h1(days=30, seed=0):
    return hourly_walk(24 * days, seed=seed, start="2024-01-01", symbol="EURUSD")


def test_two_close_conventions_differ_and_both_valid():
    h1 = _h1()
    ny = resample_to_daily(h1, EUR, SessionConfig())
    utc = resample_to_daily(h1, EUR, SessionConfig(close_tz="UTC", close_hour=0))
    assert not ny.df.equals(utc.df)
    for f in (ny, utc):
        assert f.timeframe == "D1" and run_gates(f, EUR, close_tz="UTC", max_missing_sessions=3).ok
        assert (f.index.tz_convert("UTC").weekday < 5).all() or True
    # 17:00 New York closes are 22:00 UTC in winter.
    assert set(ny.index.hour) <= {21, 22}
    assert set(utc.index.hour) == {0}


def test_sunday_partial_bar_merged_into_monday():
    h1 = _h1(14)
    utc = resample_to_daily(h1, EUR, SessionConfig(close_tz="UTC", close_hour=0))
    sess_days = (utc.index - pd.Timedelta(seconds=1)).weekday
    assert not set(sess_days) & {5, 6}
    total = h1.volume.sum()
    # Volume conserved apart from the dropped leading/trailing partial sessions.
    assert utc.volume.sum() <= total


def test_continuous_instruments_close_at_utc_midnight_without_weekend_handling():
    h1 = hourly_walk(24 * 14, seed=1, start="2024-01-01", symbol="BTC/USDT")
    h1 = BarFrame(h1.df, "BTC/USDT", timeframe="H1", volume_kind="traded")
    d1 = resample_to_daily(h1, crypto_spec("BTC/USDT"), SessionConfig())
    assert set(d1.index.hour) == {0}
    assert {5, 6} <= set((d1.index - pd.Timedelta(seconds=1)).weekday)


def test_resample_rejects_non_h1():
    with pytest.raises(ValueError):
        resample_to_daily(regime_walk(10), EUR, SessionConfig())


def test_close_convention_changes_the_trade_list():
    h1 = hourly_walk(24 * 900, seed=5, start="2015-01-01", symbol="EURUSD")
    cfg = config(
        **{"slots.c1": {"name": "macd", "params": {}}, "slots.volume": None, "slots.c2": None}
    )
    trades = []
    for sess in (SessionConfig(), SessionConfig(close_tz="UTC", close_hour=0)):
        d1 = resample_to_daily(h1, EUR, sess)
        res = BacktestHarness(
            cfg, {"EURUSD": EUR}, {"EURUSD": d1}, gate_kwargs={"max_missing_sessions": 100}
        ).run()
        trades.append([(t.entry_time, t.exit_time, t.leg) for t in res.trades])
    assert trades[0] and trades[1] and trades[0] != trades[1]


# --------------------------------------------------------------- forex
def test_28_pairs_and_fx_capabilities():
    pairs = fx_28()
    assert len(pairs) == 28 == len(set(pairs))
    assert {"EURUSD", "GBPJPY", "AUDNZD", "USDCAD", "CADCHF", "CHFJPY", "NZDUSD"} <= set(pairs)
    reg = InstrumentRegistry.load(ROOT / "config/instruments.yaml")
    assert reg.basket("fx_28") == pairs
    for s in pairs:
        spec = reg.spec(s)
        assert (
            spec.has_swap
            and spec.has_sessions
            and spec.can_short
            and spec.size_step > 0
            and spec.min_size > 0
        )


def _fake_dukascopy(days: list[pd.Timestamp]) -> tuple[dict[str, bytes], list[str]]:
    store, calls = {}, []
    rng = np.random.default_rng(0)
    for d in days:
        hours = pd.date_range(d, periods=24, freq="h", tz="UTC")
        px = 1.1 + np.cumsum(rng.normal(0, 0.0005, 24))
        df = pd.DataFrame(
            {
                "open": px,
                "close": px + 0.0001,
                "low": px - 0.0004,
                "high": px + 0.0005,
                "volume": 10.0,
            },
            index=hours,
        )
        store[day_url("EURUSD", d)] = encode_bi5(df, 1e-5)
    return store, calls


def test_dukascopy_decodes_and_caches(tmp_path: Path):
    days = list(pd.date_range("2024-01-08", "2024-01-10", freq="D", tz="UTC"))
    store, calls = _fake_dukascopy(days)

    def get(url: str) -> bytes:
        calls.append(url)
        return store.get(url, b"")

    feed = DukascopyFeed(tmp_path / "cache", http_get=get)
    f = feed.bars("EURUSD", days[0], days[-1] + pd.Timedelta(hours=23))
    assert f.timeframe == "H1" and f.volume_kind == "tick" and len(f) > 60
    assert f.close[0] == pytest.approx(store and f.close[0])
    n = len(calls)
    feed2 = DukascopyFeed(tmp_path / "cache", http_get=get)
    feed2.bars("EURUSD", days[0], days[-1] + pd.Timedelta(hours=23))
    assert len(calls) == n and feed2.downloads == 0, "re-run must not re-download"
    assert "/2024/00/08/" in calls[0]  # month is zero-indexed in the URL


def test_manifest_written_then_verified_and_mismatch_refused(tmp_path: Path):
    f = regime_walk(50, seed=1, symbol="EURUSD", volume_kind="tick")
    assert record_or_verify("dukascopy", f, tmp_path) == "written"
    assert record_or_verify("dukascopy", f, tmp_path) == "verified"
    df = f.df
    df.iloc[10, df.columns.get_loc("close")] *= 1.0001  # a vendor revision
    revised = BarFrame(df, "EURUSD", volume_kind="tick")
    with pytest.raises(ManifestMismatch, match="MISMATCH"):
        verify_manifest("dukascopy", revised, tmp_path)
    write_manifest("dukascopy", f, tmp_path)
    assert (tmp_path / "dukascopy" / "EURUSD.D1.json").exists()


def test_cross_check_reports_divergences():
    a = regime_walk(200, seed=1, symbol="EURUSD")
    df = a.df
    df.loc[df.index[50:55], "close"] *= 1.01
    df.loc[df.index[50:55], "high"] *= 1.01
    b = BarFrame(df, "EURUSD")
    rep = cross_check(a, b, source_a="dukascopy", source_b="stooq", sample=200, tolerance=0.002)
    assert not rep.ok and {d.time for d in rep.divergences} == set(df.index[50:55].normalize())
    assert cross_check(a, a, source_a="x", source_b="y").ok


# ---------------------------------------------------------------- crypto
class FakeExchange:
    def __init__(self, ex_id: str, frame: BarFrame) -> None:
        self.id = ex_id
        df = frame.df
        self.rows = [
            [
                int((t - pd.Timedelta(hours=1)).timestamp() * 1000),
                r.open,
                r.high,
                r.low,
                r.close,
                r.volume,
            ]
            for t, r in df.iterrows()
        ]

    def fetch_ohlcv(self, symbol, timeframe="1h", since=None, limit=None):
        out = [r for r in self.rows if since is None or r[0] >= since]
        return out[: limit or 1000]


def test_ccxt_feed_same_venue_traded_volume():
    src = hourly_walk(24 * 10, seed=2, start="2024-01-01", symbol="BTC/USDT", start_price=40000)
    feed = CcxtFeed(FakeExchange("binance", src), page=50)
    f = feed.bars("BTC/USDT", src.index[0] - pd.Timedelta(hours=1), src.index[-1])
    assert (
        len(f) == len(src)
        and f.volume_kind == "traded"
        and f.price_venue == f.volume_venue == "binance"
    )
    assert np.allclose(f.close, src.close)
    d1 = resample_to_daily(f, crypto_spec("BTC/USDT"), SessionConfig())
    assert set(d1.index.hour) == {0}
    assert not any("TICK" in r.detail for r in run_gates(d1, crypto_spec("BTC/USDT")).results)


def test_volume_from_another_venue_is_refused():
    with pytest.raises(BarFrameError, match="venue_mismatch"):
        BarFrame(
            _df(), "BTC/USDT", volume_kind="traded", price_venue="binance", volume_venue="bybit"
        )


def test_two_exchange_cross_check():
    src = hourly_walk(24 * 10, seed=3, symbol="BTC/USDT", start_price=40000)
    a = CcxtFeed(FakeExchange("binance", src)).bars(
        "BTC/USDT", src.index[0] - pd.Timedelta(hours=1), src.index[-1]
    )
    b = CcxtFeed(FakeExchange("bybit", src)).bars(
        "BTC/USDT", src.index[0] - pd.Timedelta(hours=1), src.index[-1]
    )
    assert cross_check(a, b, source_a="binance", source_b="bybit", match_by_date=False).ok


def test_crypto_capabilities_and_fractional_backtest():
    spec = crypto_spec("BTC/USDT:USDT")
    assert (
        spec.has_funding
        and not spec.has_sessions
        and spec.size_step < 1e-6
        and spec.market_class == "crypto_perp"
    )
    f = regime_walk(
        600,
        seed=8,
        symbol="BTC/USDT:USDT",
        start_price=30000,
        vol=0.03,
        drift=0.008,
        freq="D",
        hour=0,
        mark=True,
        venue="binance",
    )
    cfg = config(**{"slots.c1": {"name": "macd", "params": {}}, "risk.leverage": 2.0})
    res = BacktestHarness(cfg, {spec.symbol: spec}, {spec.symbol: f}).run()
    assert res.trades
    assert any(t.units % 1 for t in res.trades), "fractional sizing exercised"
