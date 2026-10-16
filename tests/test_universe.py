"""Ticket 06: point-in-time universe, delisting, splice marking."""

from __future__ import annotations

import pandas as pd
import pytest

from nnfx.data.bars import BarFrame
from nnfx.data.synthetic import regime_walk
from nnfx.data.universe import (
    LookaheadError,
    UniverseConfig,
    build_universe,
    end_of_sample_basket,
    validate_point_in_time,
)
from nnfx.harness.backtest import BacktestHarness
from nnfx.instruments import crypto_spec
from nnfx.research.metrics import (
    SplicePoolingError,
    entries_from_trades,
    require_unpooled,
    split_by_splice,
    tag_spliced_from_frames,
)
from tests.helpers import config


def coin(sym: str, n: int, seed: int, vol_scale: float, start: str = "2018-01-01") -> BarFrame:
    f = regime_walk(
        n,
        seed=seed,
        symbol=sym,
        start_price=100,
        vol=0.03,
        drift=0.01,
        freq="D",
        hour=0,
        start=start,
        venue="binance",
    )
    df = f.df
    df["volume"] *= vol_scale
    return BarFrame(df, sym, price_venue="binance")


def universe_frames() -> dict[str, BarFrame]:
    return {
        "DEAD/USDT": coin("DEAD/USDT", 400, 1, 50.0),  # most liquid early, delists after 400 days
        "BIG/USDT": coin("BIG/USDT", 900, 2, 10.0),
        "MID/USDT": coin("MID/USDT", 900, 3, 5.0),
        "LATE/USDT": coin(
            "LATE/USDT", 500, 4, 200.0, start="2019-03-01"
        ),  # lists later, dominates at the end
    }


CFG = UniverseConfig(rebalance="MS", window_days=60, top_n=2, min_history_days=30)


def test_point_in_time_selection_and_end_of_sample_basket_rejected():
    frames = universe_frames()
    sched = build_universe(
        frames, pd.Timestamp("2018-03-01", tz="UTC"), pd.Timestamp("2020-06-01", tz="UTC"), CFG
    )
    assert "DEAD/USDT" in sched.members_at(pd.Timestamp("2018-06-15", tz="UTC"))
    assert "LATE/USDT" not in sched.members_at(pd.Timestamp("2018-06-15", tz="UTC"))
    validate_point_in_time(sched, frames, CFG)
    biased = end_of_sample_basket(frames, CFG)
    assert "DEAD/USDT" not in biased and set(biased) != set(
        sched.members_at(pd.Timestamp("2018-06-15", tz="UTC"))
    )
    from nnfx.data.universe import static_schedule

    with pytest.raises(LookaheadError):
        validate_point_in_time(
            static_schedule(biased, pd.Timestamp("2018-03-01", tz="UTC")), frames, CFG
        )


def test_delisted_coin_stays_in_backtest_and_is_force_closed():
    frames = universe_frames()
    sched = build_universe(
        frames, pd.Timestamp("2018-03-01", tz="UTC"), pd.Timestamp("2020-06-01", tz="UTC"), CFG
    )
    insts = {s: crypto_spec(s, "crypto_spot", stop_trigger_price="last") for s in frames}
    cfg = config(
        **{
            "slots.c1": {"name": "macd", "params": {}},
            "slots.c2": None,
            "slots.volume": None,
            "rules.allow_short": False,
            "risk.max_positions_per_ccy": None,
        }
    )
    # Force a position open into the delisting by making the final DEAD bars trend up.
    res = BacktestHarness(cfg, insts, frames, universe=sched).run()
    dead = [t for t in res.trades if t.symbol == "DEAD/USDT"]
    assert dead, "the delisting coin must be traded while it was in the universe"
    last = frames["DEAD/USDT"].index[-1].isoformat()
    assert all(t.exit_time <= last for t in dead)
    closed_at_delist = [t for t in dead if t.exit_reason == "delisted"]
    if closed_at_delist:
        assert closed_at_delist[0].exit_price == pytest.approx(frames["DEAD/USDT"].close[-1])
    assert "DEAD/USDT" in res.symbols


def test_forced_delisting_close_at_last_valid_price():
    from nnfx.brokers.costs import CostModel
    from nnfx.brokers.sim import BacktestBroker, Order

    inst = crypto_spec("DEAD/USDT", "crypto_spot", stop_trigger_price="last")
    b = BacktestBroker({inst.symbol: inst}, CostModel.zero(), 1000)
    t0 = pd.Timestamp("2020-01-01", tz="UTC")
    b.submit(Order(inst.symbol, 1, 1.0, "runner", "standard", "t", 1.0, 1.5, None, 1.0, 1.5), "k")
    b.process_bar(inst.symbol, t0, 10, 10, 10, 10)
    b.force_close(inst.symbol, 7.25, t0, "delisted")
    assert (
        b.trades[0].exit_reason == "delisted"
        and b.trades[0].exit_price == 7.25
        and not b.positions()
    )


def test_splice_marked_and_never_pooled():
    f = coin("BTC/USDT:USDT", 300, 9, 1.0)
    df = f.df
    df["spliced"] = [True] * 150 + [False] * 150
    spliced = BarFrame(df, f.symbol, price_venue="binance", volume_venue="binance")
    assert spliced.splice_points == [df.index[150]]
    res = BacktestHarness(
        config(**{"slots.c1": {"name": "macd", "params": {}}}),
        {f.symbol: crypto_spec(f.symbol, stop_trigger_price="last")},
        {f.symbol: spliced},
    ).run()
    assert res.spliced_symbols == (f.symbol,)
    from nnfx.research.metrics import Entry

    def mk(i):
        return Entry(
            f.symbol,
            "s",
            1,
            "standard",
            df.index[i].isoformat(),
            df.index[i + 3].isoformat(),
            1.0,
            1.0,
            1.0,
            0.0,
        )

    entries = tag_spliced_from_frames(
        [mk(20), mk(200), *entries_from_trades(res.trades)], {f.symbol: spliced}
    )
    native, sp = split_by_splice(entries)
    assert native and sp
    with pytest.raises(SplicePoolingError):
        require_unpooled(entries)
    require_unpooled(native)
