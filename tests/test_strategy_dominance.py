"""Dominance Regime and Relative-Strength Sieve (Strategy Builder ticket 20)."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
from nnfx.instruments import crypto_spec
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, MarketFilterBlock, StrategyData
from nnfx.strategy.dominance import (
    DominanceParams,
    DominanceRegime,
    RelativeStrengthSieve,
    SieveParams,
)
from nnfx.strategy.market import MarketData, pair_state
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, TO_TARGET, run
from tests.test_strategy_oscillators import ROLES, rows_of

N = 90
ALT = "SOL/USDT"
BTCUSDT = "BTC/USDT"
ETHUSDT = "ETH/USDT"
LAST = N - 1


def wave(direction: int, n: int = N, start: float = 100.0) -> list[float]:
    """Closes zigzagging with higher highs and higher lows (direction 1), mirrored for -1,
    flat between fixed bounds for 0."""
    out, x = [], start
    for k in range(n):
        if direction == 0:
            x = start + (3.0 if (k // 6) % 2 else -3.0)
        else:
            x += direction * (2.0 if k % 9 < 6 else -1.0)
        out.append(x)
    return out


def bars(name: str, closes: list[float], kind: str = "none") -> BarFrame:
    """15m bars of ``closes`` (labelled like the tests' other frames)."""
    from tests.test_strategy_engine import frame

    f = frame(rows_of(closes))
    return BarFrame(f.df, name, timeframe="M15", volume_kind=kind)  # type: ignore[arg-type]


def build(symbol: str, closes: list[float], series: dict[str, list[float]]) -> StrategyData:
    market = MarketData({name: bars(name, c) for name, c in series.items()})
    spec = crypto_spec(symbol, "crypto_spot")
    return StrategyData.build(bars(symbol, closes, "traded"), ROLES, spec, SessionConfig(), market)


def regime(
    symbol: str, btc: int, dom: int, params: DominanceParams | None = None, **extra: list[float]
):
    series = {BTCUSDT: wave(btc), "BTC.D": wave(dom), **extra}
    own = wave(btc) if symbol == BTCUSDT else wave(btc, start=50.0)
    data = build(symbol, own, series)
    return DominanceRegime(params or DominanceParams(role="lwc")).compute(data)


def verdict(out, side: str = "long") -> bool:
    return bool((out.long_ok if side == "long" else out.short_ok)[LAST])


# ------------------------------------------------------------------ matrix
def test_market_filter_is_a_registered_kind_with_its_own_contract():
    assert issubclass(DominanceRegime, MarketFilterBlock)
    assert REGISTRY["dominance_regime"].kind == BlockKind.MARKET_FILTER
    assert REGISTRY["relative_strength"].kind == BlockKind.MARKET_FILTER


@pytest.mark.parametrize(
    ("symbol", "long_ok", "short_ok"),
    [(BTCUSDT, True, False), (ALT, False, True)],
)
def test_btc_led_regime_sends_the_longs_to_bitcoin(symbol, long_ok, short_ok):
    out = regime(symbol, btc=1, dom=1)
    assert (verdict(out), verdict(out, "short")) == (long_ok, short_ok)
    assert out.tags_for(LAST, 1) == {"btc_led"} and out.tags_for(LAST, -1) == {"btc_led"}


@pytest.mark.parametrize("btc", [1, 0])
def test_altseason_sends_the_longs_to_altcoins(btc):
    alt, bitcoin = regime(ALT, btc=btc, dom=-1), regime(BTCUSDT, btc=btc, dom=-1)
    assert (verdict(alt), verdict(alt, "short")) == (True, True)  # the table says nothing of shorts
    assert (verdict(bitcoin), verdict(bitcoin, "short")) == (False, True)
    assert alt.tags_for(LAST, 1) == {"altseason"}


def test_altseason_can_still_trade_bitcoin_when_asked():
    out = regime(
        BTCUSDT, btc=1, dom=-1, params=DominanceParams(role="lwc", altseason_trades_btc=True)
    )
    assert verdict(out) is True


def test_altcoin_flush_never_shorts_bitcoin_and_shorts_altcoins_only():
    alt, bitcoin = regime(ALT, btc=-1, dom=1), regime(BTCUSDT, btc=-1, dom=1)
    assert (verdict(alt), verdict(alt, "short")) == (False, True)
    assert (verdict(bitcoin), verdict(bitcoin, "short")) == (True, False)
    assert alt.tags_for(LAST, -1) == {"alt_flush"}


@pytest.mark.parametrize(("btc", "dom"), [(-1, -1), (1, 0), (0, 1), (-1, 0)])
def test_combinations_outside_the_table_restrict_nothing(btc, dom):
    for symbol in (ALT, BTCUSDT):
        out = regime(symbol, btc=btc, dom=dom)
        assert (verdict(out), verdict(out, "short")) == (True, True)
        assert out.tags_for(LAST, 1) == set()


# ------------------------------------------------------------- missing data
def test_without_the_dominance_series_the_block_is_not_applicable_everywhere():
    base = bars(BTCUSDT, wave(1), "traded")
    data = StrategyData.build(base, ROLES, BTC, SessionConfig())
    out = DominanceRegime(DominanceParams(role="lwc")).compute(data)
    assert out.available is not None and not out.available.any()
    assert out.long_ok.all() and out.short_ok.all()  # never a refusal for want of data
    assert not out.known(LAST)


def test_a_series_that_starts_late_or_stops_early_is_not_applicable_there():
    closes = wave(1)
    dom = bars("BTC.D", wave(1)).df.iloc[20:60]
    market = MarketData(
        {
            BTCUSDT: bars(BTCUSDT, closes),
            "BTC.D": BarFrame(dom, "BTC.D", timeframe="M15", volume_kind="none"),
        }
    )
    data = StrategyData.build(bars(BTCUSDT, closes, "traded"), ROLES, BTC, SessionConfig(), market)
    out = DominanceRegime(DominanceParams(role="lwc", max_stale_bars=3)).compute(data)
    avail = out.available
    assert avail is not None
    assert not avail[:20].any() and avail[40:60].all()  # starts at bar 20
    assert not avail[64:].any()  # silent for more than 3 bars after bar 59


def test_a_run_with_a_market_filter_but_no_series_is_flagged_incomplete():
    raw = copy.deepcopy(DOC)
    raw["blocks"].insert(
        1, {"kind": "market_filter", "type": "dominance_regime", "params": {"role": "lwc"}}
    )
    out, journal = run([*RISE, SETUP, FILL, *TO_TARGET], raw)
    assert out.incomplete and out.incomplete_blocks == ["dominance_regime#1"]
    assert len(out.result.trades) == 1  # still traded: not-applicable is not a refusal
    (ev,) = [e for r in journal.records("cycle") for e in r["evaluations"]]
    item = next(i for i in ev["values"]["checklist"] if i["block"] == "dominance_regime#1")
    assert item["outcome"] == "na" and ev["blocked"] == []


def test_a_run_without_market_filters_is_complete():
    out, _ = run([*RISE, SETUP, FILL, *TO_TARGET])
    assert not out.incomplete and out.incomplete_blocks == []


# -------------------------------------------------------------------- sieve
def sieve(symbol, alt_closes, btc_closes, params=None, **extra):
    series = {BTCUSDT: btc_closes, **extra}
    data = build(symbol, alt_closes, series)
    return RelativeStrengthSieve(params or SieveParams(role="lwc")).compute(data)


def test_an_altcoin_outrunning_bitcoin_is_admitted_long_only():
    out = sieve(ALT, wave(1, start=50.0), [100.0] * N)
    assert (verdict(out), verdict(out, "short")) == (True, False)


def test_an_altcoin_sinking_against_bitcoin_is_admitted_short_only():
    out = sieve(ALT, wave(-1, start=500.0), [100.0 + 0.001 * k for k in range(N)])
    assert (verdict(out), verdict(out, "short")) == (False, True)


def test_a_ranging_ratio_admits_neither():
    out = sieve(ALT, wave(0), [100.0] * N)
    assert (verdict(out), verdict(out, "short")) == (False, False)


def test_the_ratio_is_what_counts_not_the_dollar_chart():
    rising_with_btc = wave(1, start=50.0)
    out = sieve(ALT, rising_with_btc, [2 * c for c in rising_with_btc])  # ALT/BTC is flat
    assert (verdict(out), verdict(out, "short")) == (False, False)


def test_a_given_cross_pair_replaces_the_derived_ratio():
    alt = wave(1, start=50.0)
    derived_up = sieve(ALT, alt, [100.0] * N)
    given_down = sieve(ALT, alt, [100.0] * N, **{"SOL/BTC": wave(-1, start=500.0)})
    assert verdict(derived_up) and not verdict(given_down)
    assert verdict(given_down, "short")


def test_the_second_condition_needs_eth_to_agree():
    alt = wave(1, start=50.0)
    strong_eth = sieve(
        ALT, alt, [100.0] * N, SieveParams(role="lwc", second="alt_eth"), **{ETHUSDT: [100.0] * N}
    )
    assert verdict(strong_eth)
    same_as_alt = sieve(
        ALT, alt, [100.0] * N, SieveParams(role="lwc", second="alt_eth"), **{ETHUSDT: alt}
    )
    assert not verdict(same_as_alt)  # ALT/ETH is flat: not a trend up
    eth_btc_up = sieve(
        ALT,
        alt,
        [100.0] * N,
        SieveParams(role="lwc", second="eth_btc"),
        **{ETHUSDT: wave(1, start=50.0)},
    )
    assert verdict(eth_btc_up)
    eth_btc_down = sieve(
        ALT,
        alt,
        [100.0] * N,
        SieveParams(role="lwc", second="eth_btc"),
        **{ETHUSDT: wave(-1, start=500.0)},
    )
    assert not verdict(eth_btc_down)


def test_missing_ratio_inputs_make_the_sieve_not_applicable():
    out = sieve(ALT, wave(1, start=50.0), [100.0] * N, SieveParams(role="lwc", second="alt_eth"))
    assert out.available is not None and not out.available.any()  # no ETH series
    assert out.long_ok.all()


def test_bitcoin_itself_is_outside_the_sieve():
    base = bars(BTCUSDT, wave(1), "traded")
    data = StrategyData.build(base, ROLES, BTC, SessionConfig())
    out = RelativeStrengthSieve(SieveParams(role="lwc")).compute(data)
    assert (
        out.long_ok.all()
        and out.short_ok.all()
        and out.available is not None
        and out.available.all()
    )


def test_pair_state_is_causal_by_construction():
    alt = wave(1, start=50.0)
    full = build(ALT, alt, {BTCUSDT: [100.0] * N})
    part = full.head(60)
    a, ok_a = pair_state(full, ALT, BTCUSDT, "lwc", 2, 3)
    b, ok_b = pair_state(part, ALT, BTCUSDT, "lwc", 2, 3)
    assert np.array_equal(a[:60], b) and np.array_equal(ok_a[:60], ok_b)
    assert pd.Series(ok_a).all()


def test_an_asset_against_itself_is_no_ratio():
    eth = wave(1, start=50.0)
    out = sieve("ETH/USDT", eth, [100.0] * N, SieveParams(role="lwc", second="alt_eth"))
    assert out.available is not None and not out.available.any()
