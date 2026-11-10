"""The daily screener on recorded ticker data (Strategy Builder ticket 20), offline."""

from __future__ import annotations

from typing import Any

import pytest

from nnfx.strategy.screener import (
    AssetStats,
    screen,
    stats_from_exchange,
    vs_btc,
)

BTC = AssetStats("BTC/USDT", 50_000.0, 2.0e9, 0.01, 0.02)  # +1% / +2%


def coin(sym: str, volume_btc: float, d1: float, d7: float) -> AssetStats:
    return AssetStats(f"{sym}/USDT", 1.0, volume_btc * BTC.last, d1, d7)


def test_performance_is_valued_in_btc():
    assert vs_btc(0.02, 0.01) == pytest.approx(1.02 / 1.01 - 1)
    assert vs_btc(0.01, 0.01) == pytest.approx(0.0)


def test_a_coin_passes_with_enough_volume_and_a_lead_over_btc_on_both_windows():
    ok = coin("SOL", 1500, 0.03, 0.05)
    wl = screen([ok], BTC)
    assert wl.symbols == ["SOL/USDT"]
    e = wl.entries[0]
    assert e.volume_btc == pytest.approx(1500) and e.vs_btc_24h > 0 and e.vs_btc_7d > 0


@pytest.mark.parametrize(
    ("asset", "why"),
    [
        (coin("THIN", 999, 0.05, 0.10), "volume"),
        (coin("LAG24", 5000, 0.005, 0.10), "24 hours"),  # +0.5% against BTC's +1%
        (coin("LAG7", 5000, 0.05, 0.01), "7 days"),
        (coin("FLAT24", 5000, 0.01, 0.10), "24 hours"),  # equal to BTC is not ahead
    ],
)
def test_each_threshold_rejects_with_its_reason(asset, why):
    wl = screen([asset], BTC)
    assert wl.entries == () and why in wl.rejected[asset.symbol]


def test_the_volume_floor_is_inclusive_and_configurable():
    assert screen([coin("AT", 1000, 0.05, 0.1)], BTC).symbols == ["AT/USDT"]
    assert screen([coin("LOW", 400, 0.05, 0.1)], BTC, min_volume_btc=500).symbols == []


def test_btc_stablecoins_and_other_quotes_are_never_listed():
    stable = AssetStats("USDC/USDT", 1.0, 9e9, 0.0, 0.0)
    eth_quoted = AssetStats("SOL/ETH", 0.05, 9e9, 0.5, 0.5)
    wl = screen([BTC, stable, eth_quoted, coin("SOL", 2000, 0.04, 0.09)], BTC)
    assert wl.symbols == ["SOL/USDT"] and wl.considered == 1


def test_a_falling_btc_does_not_let_a_stablecoin_in():
    falling = AssetStats("BTC/USDT", 50_000.0, 2.0e9, -0.05, -0.10)
    stable = AssetStats("USDC/USDT", 1.0, 9e9, 0.0, 0.0)
    assert screen([stable, coin("SOL", 2000, -0.01, -0.02)], falling).symbols == ["SOL/USDT"]


def test_the_list_is_ranked_by_the_week_then_the_day_then_the_name_and_capped():
    assets = [coin(f"C{k}", 2000, 0.02 + 0.001 * k, 0.05 + 0.01 * (k % 4)) for k in range(8)]
    wl = screen(assets, BTC)
    assert len(wl.entries) == 5
    keys = [(-e.vs_btc_7d, -e.vs_btc_24h, e.symbol) for e in wl.entries]
    assert keys == sorted(keys)
    assert screen(assets, BTC, max_assets=3).symbols == wl.symbols[:3]
    assert screen(list(reversed(assets)), BTC).symbols == wl.symbols  # input order is irrelevant


@pytest.mark.parametrize("n", [0, 6])
def test_the_watchlist_is_one_to_five_assets(n):
    with pytest.raises(ValueError, match="1 to 5"):
        screen([], BTC, max_assets=n)


def test_btc_must_have_its_own_figures():
    with pytest.raises(ValueError, match="BTC"):
        screen([], AssetStats("BTC/USDT", 0.0, 0.0, 0.0, 0.0))


# ---------------------------------------------------------- the exchange
class FakeExchange:
    """Recorded tickers and daily closes; counts the bar requests."""

    id = "fake"

    def __init__(self, tickers: dict[str, dict[str, Any]], weeks: dict[str, float]) -> None:
        self.tickers, self.weeks, self.calls = tickers, weeks, []

    def fetch_tickers(self):
        return self.tickers

    def fetch_ohlcv(self, symbol, timeframe="1d", since=None, limit=None):
        self.calls.append(symbol)
        ref = self.weeks[symbol]
        return [
            [k * 86_400_000, ref, ref, ref, ref if k == 1 else ref * 1.01, 1.0]
            for k in range(limit)
        ]


def tick(last: float, quote_volume: float, pct: float) -> dict[str, Any]:
    return {"last": last, "quoteVolume": quote_volume, "percentage": pct}


def test_stats_come_from_the_tickers_and_daily_bars_only_for_pairs_worth_it():
    ex = FakeExchange(
        {
            "BTC/USDT": tick(50_000.0, 2.0e9, 1.0),
            "SOL/USDT": tick(110.0, 1.0e8, 3.0),  # 2000 BTC, +3%: worth a week
            "DOGE/USDT": tick(0.2, 1.0e7, 5.0),  # 200 BTC: too thin
            "ADA/USDT": tick(0.5, 1.0e8, 0.5),  # liquid but behind BTC today
            "SOL/ETH": tick(0.05, 9e9, 9.0),  # not a USDT pair
            "XRP/USDT": {"last": None, "quoteVolume": 1e8, "percentage": 2.0},  # no price
        },
        {"BTC/USDT": 49_000.0, "SOL/USDT": 100.0},
    )
    assets, btc = stats_from_exchange(ex)
    assert ex.calls == ["BTC/USDT", "SOL/USDT"]
    assert btc.change_24h == pytest.approx(0.01) and btc.change_7d == pytest.approx(
        50_000 / 49_000 - 1
    )
    by = {a.symbol: a for a in assets}
    assert set(by) == {"ADA/USDT", "DOGE/USDT", "SOL/USDT"}
    assert by["SOL/USDT"].change_7d == pytest.approx(0.10)
    wl = screen(assets, btc)
    assert wl.symbols == ["SOL/USDT"]
    assert "volume" in wl.rejected["DOGE/USDT"] and "24 hours" in wl.rejected["ADA/USDT"]


def test_an_exchange_without_btc_cannot_screen():
    ex = FakeExchange({"SOL/USDT": tick(1.0, 1e9, 1.0)}, {})
    with pytest.raises(ValueError, match="BTC/USDT"):
        stats_from_exchange(ex)
