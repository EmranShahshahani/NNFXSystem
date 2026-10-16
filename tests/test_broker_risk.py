"""Tickets 15-18: money management fills, capabilities, cost model, risk manager."""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from nnfx.brokers.costs import CostModel, CostSpec
from nnfx.brokers.sim import BacktestBroker, Order
from nnfx.config import CostToggles, RiskConfig
from nnfx.data.synthetic import regime_walk
from nnfx.engine.types import AccountState, OpenIntent
from nnfx.harness.backtest import BacktestHarness
from nnfx.instruments import crypto_spec, fx_spec
from nnfx.research.metrics import compute_metrics, entries_from_trades
from nnfx.risk.manager import RiskManager
from tests.helpers import config

T0 = pd.Timestamp("2024-01-02 22:00", tz="UTC")
EUR = fx_spec("EURUSD")


def order(
    direction=1, leg="tp1", target=0.01, frac=1.0, units=10_000.0, stop=0.015, symbol="EURUSD"
):
    return Order(
        symbol, direction, units, leg, "standard", T0.isoformat(), 0.01, stop, target, frac, 150.0
    )  # type: ignore[arg-type]


def broker(inst=EUR, costs=None):
    return BacktestBroker({inst.symbol: inst}, costs or CostModel.zero(), 10_000)


def bar(b, i, o, h, lo, c, **kw):
    b.process_bar(
        b.instruments and next(iter(b.instruments)), T0 + pd.Timedelta(days=i), o, h, lo, c, **kw
    )


# ------------------------------------------------------------- fills/legs
def test_fill_at_next_open_then_target_and_runner():
    b = broker()
    b.submit(order(leg="tp1"), "k0")
    b.submit(order(leg="runner", target=None), "k1")
    assert not b.positions()  # nothing fills until the next bar's open
    bar(b, 1, 1.0, 1.005, 0.995, 1.0)
    ps = b.positions()
    assert [p.entry_price for p in ps] == [1.0, 1.0] and ps[0].stop == pytest.approx(0.985)
    bar(b, 2, 1.0, 1.012, 0.999, 1.011)  # TP1 at 1.01
    assert [p.leg for p in b.positions()] == ["runner"]
    assert b.trades[0].exit_reason == "target" and b.trades[0].r_multiple == pytest.approx(
        100 / 150
    )


def test_idempotent_submit_never_duplicates():
    b = broker()
    r1 = b.submit(order(), "same")
    r2 = b.submit(order(), "same")
    assert r1.status == "accepted" and r2.status == "duplicate" and r2.order_id == r1.order_id
    bar(b, 1, 1.0, 1.001, 0.999, 1.0)
    assert len(b.positions()) == 1


def test_stop_gap_fills_at_open_not_at_stop():
    b = broker()
    b.submit(order(target=None, leg="runner"), "k")
    bar(b, 1, 1.0, 1.001, 0.999, 1.0)
    bar(b, 2, 0.97, 0.975, 0.96, 0.965)  # gapped through 0.985
    t = b.trades[0]
    assert (
        t.exit_reason == "stop_gap" and t.exit_price == pytest.approx(0.97) and t.r_multiple < -1.5
    )


def test_stop_and_target_same_bar_assumes_stop():
    b = broker()
    b.submit(order(), "k")
    bar(b, 1, 1.0, 1.001, 0.999, 1.0)
    bar(b, 2, 1.0, 1.02, 0.98, 1.0)
    assert b.trades[0].exit_reason == "stop"


def test_no_hedging_partial_close_at_tp1():
    fifo = fx_spec("EURUSD", supports_hedging=False)
    b = broker(fifo)
    b.submit(order(leg="combined", frac=0.5, units=20_000), "k")
    bar(b, 1, 1.0, 1.001, 0.999, 1.0)
    bar(b, 2, 1.0, 1.011, 0.999, 1.01)
    (p,) = b.positions()
    assert p.scaled_out and p.units == pytest.approx(10_000) and p.target is None
    assert b.trades[0].exit_reason == "target_partial" and b.trades[0].units == pytest.approx(
        10_000
    )


def test_no_hedging_end_to_end_backtest_runs_single_position():
    f = regime_walk(900, seed=21, symbol="EURUSD")
    res = BacktestHarness(
        config(**{"slots.c1": {"name": "macd", "params": {}}}),
        {"EURUSD": fx_spec("EURUSD", supports_hedging=False)},
        {"EURUSD": f},
    ).run()
    assert res.trades and {t.leg for t in res.trades} == {"combined"}


def test_mark_price_stops_ignore_last_price_wicks():
    perp = crypto_spec("BTC/USDT:USDT")
    last = crypto_spec("BTC/USDT:USDT", stop_trigger_price="last")
    for inst, survives in ((perp, True), (last, False)):
        b = broker(inst)
        b.submit(order(symbol=inst.symbol, units=0.1, stop=1500.0, target=None, leg="runner"), "k")
        bar(b, 1, 40000, 40100, 39900, 40000, mark_high=40050, mark_low=39950)
        bar(
            b, 2, 40000, 40100, 38000, 40000, mark_high=40050, mark_low=39900
        )  # wick to 38000 on last only
        assert bool(b.positions()) is survives
    with pytest.raises(ValueError, match="mark"):
        b = broker(perp)
        bar(b, 1, 1, 1, 1, 1)


# ------------------------------------------------------------------ costs
SPEC = CostSpec(
    spread_bps=2,
    commission_rate=0.0005,
    slippage_bps=1,
    stop_slippage_mult=2,
    swap_long_annual=-0.0365,
    swap_short_annual=0.0365,
    funding_rate_8h=0.0001,
    rollover_spread_mult=3,
    reference_depth=1e8,
)


def test_costs_components_and_stress_multiplier():
    base = CostModel({}, SPEC, CostToggles())
    stress = base.with_toggles(CostToggles(stress_multiplier=1.5))
    assert stress.half_spread(EUR, 1.0, False) == pytest.approx(
        1.5 * base.half_spread(EUR, 1.0, False)
    )
    assert stress.slippage(EUR, 1.0, True) == pytest.approx(1.5 * base.slippage(EUR, 1.0, True))
    assert base.slippage(EUR, 1.0, True) == pytest.approx(2 * base.slippage(EUR, 1.0, False))
    assert base.half_spread(EUR, 1.0, True) == pytest.approx(
        3 * base.half_spread(EUR, 1.0, False)
    ), "rollover widening"
    assert CostModel({}, SPEC, CostToggles(enabled=False)).half_spread(EUR, 1.0, False) == 0


def test_swap_triple_wednesday_and_funding_asymmetry():
    m = CostModel({}, SPEC, CostToggles())
    mon, _ = m.carry(EUR, 1, 1e5, 0, None, 24)
    wed, kind = m.carry(EUR, 1, 1e5, 2, None, 24)
    assert kind == "swap" and wed == pytest.approx(3 * mon) and mon == pytest.approx(-10.0)
    perp = crypto_spec("BTC/USDT:USDT")
    longc, k = m.carry(perp, 1, 1e5, 0, None, 24)
    shortc, _ = m.carry(perp, -1, 1e5, 0, None, 24)
    assert k == "funding" and longc == pytest.approx(-30.0) and shortc == pytest.approx(30.0)
    assert m.carry(perp, 1, 1e5, 0, 0.0005, 24)[0] == pytest.approx(-50.0), (
        "bar funding history wins"
    )
    assert m.with_toggles(CostToggles(funding=False)).carry(perp, 1, 1e5, 0, None, 24)[0] == 0
    spot = crypto_spec("BTC/USDT", "crypto_spot")
    assert m.carry(spot, 1, 1e5, 0, None, 24) == (0.0, "none")


def test_depth_scaled_slippage():
    m = CostModel({}, SPEC, CostToggles())
    btc = crypto_spec("BTC/USDT:USDT", depth=1e8)
    alt = crypto_spec("ALT/USDT:USDT", depth=1e6)
    assert m.slippage(alt, 1.0, False) == pytest.approx(10 * m.slippage(btc, 1.0, False))


def test_costs_flow_into_backtest_and_stress_lowers_expectancy():
    f = regime_walk(1500, seed=21, symbol="EURUSD")
    cfg = config(**{"slots.c1": {"name": "macd", "params": {}}})
    costs = CostModel({}, SPEC, CostToggles())
    runs = {}
    for k in (0.0, 1.0, 1.5):
        c = cfg.with_overrides({"costs.stress_multiplier": k, "costs.enabled": k > 0})
        res = BacktestHarness(c, {"EURUSD": EUR}, {"EURUSD": f}, costs=costs).run()
        runs[k] = compute_metrics(res.trades, res.equity, n_boot=50)
        if k:
            assert all(t.commission > 0 for t in res.trades) and any(
                t.carry != 0 for t in res.trades
            )
    assert runs[0.0].expectancy_r > runs[1.0].expectancy_r > runs[1.5].expectancy_r


# ------------------------------------------------------------------- risk
ACCT = AccountState(equity=10_000, balance=10_000, peak_equity=10_000)


def intent(symbol="EURUSD", direction=1, atr=0.01, rf=0.01, leg_index=0):
    return OpenIntent(
        symbol=symbol,
        direction=direction,
        leg="tp1",
        leg_index=leg_index,
        entry_type="standard",
        signal_time="t",
        atr=atr,
        stop_distance=1.5 * atr,
        target_distance=atr,
        risk_fraction=rf,
        idempotency_key=f"{symbol}|t|{leg_index}",
    )


def test_sizing_from_risk_cash_and_value_per_price_unit():
    rm = RiskManager(RiskConfig())
    d = rm.size(intent(), ACCT, EUR, 1.0)
    assert (
        d.approved and d.order.units == 6000 and d.order.realized_risk == pytest.approx(90)
    )  # 100/0.015=6666 -> 6000
    jpy = rm.size(intent("USDJPY", atr=1.0), ACCT, fx_spec("USDJPY"), 1 / 150)
    assert jpy.approved and jpy.order.units == 10000


def test_quantization_guard_rejects_small_accounts():
    rm = RiskManager(RiskConfig(sizing_tolerance=0.05))
    assert not rm.size(intent(), ACCT, EUR, 1.0).approved  # 10% off after rounding
    tiny = AccountState(equity=50, balance=50, peak_equity=50)
    rej = RiskManager(RiskConfig()).size(intent(), tiny, EUR, 1.0)
    assert not rej.approved and "below_min_size" in rej.reason
    cent = fx_spec("EURUSD", size_step=Decimal("1"), min_size=Decimal("1"))
    assert RiskManager(RiskConfig()).size(intent(), tiny, cent, 1.0).approved
    btc = crypto_spec("BTC/USDT:USDT")
    d = RiskManager(RiskConfig(sizing_tolerance=0.0001)).size(
        intent(btc.symbol, atr=1500.0), tiny, btc, 1.0
    )
    assert d.approved and abs(d.order.realized_risk - 0.5) < 1e-4, (
        "crypto quantization is a non-issue"
    )


def test_currency_exposure_cap():
    rm = RiskManager(RiskConfig(max_positions_per_ccy=2))
    insts = {s: fx_spec(s) for s in ("EURUSD", "GBPUSD", "AUDUSD", "USDJPY")}
    approved = []
    for s in ("EURUSD", "GBPUSD"):
        for k in (0, 1):
            sized = rm.size(intent(s, leg_index=k), ACCT, insts[s], 1.0).order
            assert rm.approve(sized, insts[s], ACCT, [], insts, approved).approved
            approved.append(sized)
    third = rm.size(intent("AUDUSD"), ACCT, insts["AUDUSD"], 1.0).order
    dec = rm.approve(third, insts["AUDUSD"], ACCT, [], insts, approved)
    assert not dec.approved and "short USD" in dec.reason
    # USDJPY long is long USD: not the same bet.
    j = rm.size(intent("USDJPY", atr=1.0), ACCT, insts["USDJPY"], 1 / 150).order
    assert rm.approve(j, insts["USDJPY"], ACCT, [], insts, approved).approved


def test_btc_beta_weighted_cap():
    rm = RiskManager(RiskConfig(max_beta_weighted_risk=0.05, max_positions_per_ccy=None))
    insts = {s: crypto_spec(s, btc_beta=1.2) for s in ("A/USDT", "B/USDT", "C/USDT")}
    approved = []
    for s in ("A/USDT", "B/USDT"):
        o = rm.size(intent(s, atr=10.0, rf=0.02), ACCT, insts[s], 1.0).order
        assert rm.approve(o, insts[s], ACCT, [], insts, approved).approved
        approved.append(o)
    o = rm.size(intent("C/USDT", atr=10.0, rf=0.02), ACCT, insts["C/USDT"], 1.0).order
    dec = rm.approve(o, insts["C/USDT"], ACCT, [], insts, approved)
    assert not dec.approved and "beta" in dec.reason


def test_liquidation_must_sit_beyond_three_atr():
    perp = crypto_spec("BTC/USDT:USDT")
    o = RiskManager(RiskConfig()).size(intent(perp.symbol, atr=1500.0), ACCT, perp, 1.0).order
    ok = RiskManager(RiskConfig(leverage=3.0)).approve(
        o, perp, ACCT, [], {perp.symbol: perp}, entry_price=40000
    )
    bad = RiskManager(RiskConfig(leverage=10.0)).approve(
        o, perp, ACCT, [], {perp.symbol: perp}, entry_price=40000
    )
    assert ok.approved and not bad.approved and "sizing bug" in bad.reason
    assert (
        not RiskManager(RiskConfig(leverage=50.0))
        .approve(o, perp, ACCT, [], {perp.symbol: perp}, entry_price=40000)
        .approved
    )


def test_kill_switch_blocks_entries_but_manages_exits():
    rm = RiskManager(RiskConfig(kill_switch_drawdown=0.1, kill_switch_approved=True))
    dd = AccountState(equity=8_900, balance=8_900, peak_equity=10_000)
    o = rm.size(intent(), dd, EUR, 1.0).order
    dec = rm.approve(o, EUR, dd, [], {"EURUSD": EUR})
    assert not dec.approved and "kill_switch" in dec.reason
    # Harness level: after the switch trips, existing positions still exit through the engine.
    f = regime_walk(1500, seed=21, symbol="EURUSD")
    cfg = config(
        **{
            "slots.c1": {"name": "macd", "params": {}},
            "risk.kill_switch_drawdown": 0.0001,
            "risk.kill_switch_approved": True,
        }
    )
    res = BacktestHarness(cfg, {"EURUSD": EUR}, {"EURUSD": f}).run()
    entries = entries_from_trades(res.trades)
    assert res.rejected.get("kill_switch", 0) > 0
    assert entries and all(t.exit_reason != "end_of_data" for t in res.trades[:-2])
