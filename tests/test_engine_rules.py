"""Tickets 01, 11-15: engine rules driven by hand-built contract arrays."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nnfx.engine import (
    AccountState,
    CloseIntent,
    EngineState,
    ModifyIntent,
    OpenIntent,
    Phase,
    StrategyEngine,
    SymbolState,
)
from nnfx.engine.types import idempotency_key
from nnfx.instruments import crypto_spec, fx_spec
from tests.helpers import ACCOUNT, config, hist, position, run

# Ten bars above a flat baseline at 1.0, ATR 0.01.
ABOVE = [1.004] * 9 + [1.005]


def opens(intents):
    return [i for i in intents if isinstance(i, OpenIntent)]


# --------------------------------------------------------------- standard
def test_standard_entry_opens_two_legs_with_spec_geometry():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    intents, st = run(h)
    o = opens(intents)
    assert [i.leg for i in o] == ["tp1", "runner"]
    assert all(i.direction == 1 and i.entry_type == "standard" for i in o)
    assert o[0].stop_distance == pytest.approx(0.015) and o[0].target_distance == pytest.approx(
        0.01
    )
    assert o[1].target_distance is None
    assert [i.risk_fraction for i in o] == [0.01, 0.01]
    assert st.get("EURUSD").phase == Phase.IN_TRADE


@pytest.mark.parametrize(
    "kw",
    [
        {"c2_state": -1},  # C2 disagrees
        {"volume": False},  # volume gate closed
        {"baseline": 1.01},  # baseline disagrees (close below)
        {"atr": 0.004},  # bridge too far: distance 0.005 > 1.0 x 0.004
    ],
)
def test_standard_entry_blocked_by_each_condition(kw):
    cfg = config(**{"rules.pullback": False})
    intents, _ = run(hist(ABOVE, c1_signal=[0] * 9 + [1], **kw), cfg)
    assert not opens(intents)


def test_bridge_multiple_is_a_parameter():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1], atr=0.004)
    assert not opens(run(h, config(**{"rules.pullback": False}))[0])
    assert opens(run(h, config(**{"rules.bridge_multiple": 1.5}))[0])
    assert opens(run(h, config(**{"rules.bridge_too_far": False}))[0])


def test_short_entry_and_direction_flags():
    below = [0.996] * 9 + [0.995]
    h = hist(below, c1_signal=[0] * 9 + [-1], c2_state=-1)
    assert [i.direction for i in opens(run(h)[0])] == [-1, -1]
    assert not opens(run(h, config(**{"rules.allow_short": False}))[0])
    spot = hist(
        below,
        c1_signal=[0] * 9 + [-1],
        c2_state=-1,
        instrument=crypto_spec("BTC/USDT", "crypto_spot"),
        symbol="BTC/USDT",
    )
    assert not opens(run(spot)[0]), "can_short=False must block shorts with no market-name branch"


def test_c2_signal_mode_requires_firing():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1], c2_state=1)
    assert not opens(run(h, config(**{"rules.c2_mode": "signal", "rules.pullback": False}))[0])
    h2 = hist(ABOVE, c1_signal=[0] * 9 + [1], c2_state=1, c2_signal=[0] * 9 + [1])
    assert opens(run(h2, config(**{"rules.c2_mode": "signal"}))[0])


# --------------------------------------------------------------- baseline
def _cross(signal_at: int) -> list[int]:
    sig = [0] * 12
    sig[signal_at] = 1
    return sig


CROSS = [1.004] * 10 + [0.995, 1.005]  # fresh cross on the last bar


@pytest.mark.parametrize(
    "signal_at,inclusive,expect",
    [(5, True, True), (4, True, False), (4, False, True), (3, False, False)],
)
def test_baseline_entry_and_seven_candle_off_by_one(signal_at, inclusive, expect):
    # last bar index 11; signal at 5 is age 7 inclusive (bar 1 = signal bar), age 6 exclusive.
    h = hist(CROSS, c1_signal=_cross(signal_at), c1_state=[1] * 12)
    cfg = config(**{"rules.seven_candle_inclusive": inclusive, "rules.pullback": False})
    o = opens(run(h, cfg)[0])
    assert bool(o) is expect
    if o:
        assert o[0].entry_type == "baseline"


def test_seven_candle_rule_off_admits_stale_signal():
    h = hist(CROSS, c1_signal=_cross(0), c1_state=[1] * 12)
    assert not opens(run(h, config(**{"rules.pullback": False}))[0])
    assert opens(run(h, config(**{"rules.seven_candle_rule": False}))[0])


# --------------------------------------------------------------- pullback
def test_pullback_arms_then_enters_next_bar():
    close = [1.004] * 9 + [1.02, 1.008]
    h = hist(close, c1_signal=[0] * 9 + [1, 0])
    intents, st = run(h.at(9))
    assert not opens(intents) and st.get("EURUSD").phase == Phase.PENDING_PULLBACK
    assert st.get("EURUSD").pending.setup_time == h.at(9).time()
    intents, st = run(h, state=st)
    o = opens(intents)
    assert o and o[0].entry_type == "pullback"


def test_pullback_expires_after_exactly_one_bar():
    close = [1.004] * 9 + [1.02, 1.02, 1.008]
    h = hist(close, c1_signal=[0] * 9 + [1, 0, 0])
    intents, st = run(h, start=9)
    assert not opens(intents)
    assert st.get("EURUSD").phase == Phase.FLAT and st.get("EURUSD").pending is None


def test_pullback_disabled_when_bridge_rule_off():
    close = [1.004] * 9 + [1.02]
    h = hist(close, c1_signal=[0] * 9 + [1])
    _, st = run(h, config(**{"rules.pullback": False}))
    assert st.get("EURUSD").pending is None


# ---------------------------------------------------------------- 1CR
def test_one_candle_rule_a_grace_for_single_lagging_condition():
    h = hist(
        [1.004] * 9 + [1.005, 1.006], c1_signal=[0] * 9 + [1, 0], volume=[True] * 9 + [False, True]
    )
    cfg = config(**{"rules.one_candle_rule": "A"})
    o = opens(run(h, cfg, start=9)[0])
    assert o and o[0].entry_type == "one_candle_a"
    # Off by default: no entry.
    assert not opens(run(h, config(), start=9)[0])
    # Two lagging conditions: no grace.
    h2 = hist(
        [1.004] * 9 + [1.005, 1.006],
        c1_signal=[0] * 9 + [1, 0],
        volume=[True] * 9 + [False, True],
        c2_state=[1] * 9 + [-1, 1],
    )
    assert not opens(run(h2, cfg, start=9)[0])


@pytest.mark.parametrize("next_close,expect", [(1.004, True), (1.007, False)])
def test_one_candle_rule_b_requires_retracement(next_close, expect):
    h = hist([1.004] * 9 + [1.005, next_close], c1_signal=[0] * 9 + [1, 0])
    cfg = config(**{"rules.one_candle_rule": "B"})
    first, st = run(h.at(9), cfg)
    assert not opens(first) and st.get("EURUSD").phase == Phase.PENDING_ONE_CANDLE
    o = opens(run(h, cfg, state=st)[0])
    assert bool(o) is expect
    if o:
        assert o[0].entry_type == "one_candle_b"


# ----------------------------------------------------------- continuation
def test_continuation_ignores_bridge_and_needs_uncrossed_baseline():
    trend = EngineState(
        symbols={"EURUSD": SymbolState(trend_dir=1, trend_origin="2019-12-01T22:00:00+00:00")}
    )
    far = [1.03] * 10  # 3 ATR from baseline: bridge would block a fresh entry
    h = hist(far, c1_signal=[0] * 9 + [1])
    cfg = config(**{"rules.pullback": False})
    o = opens(run(h, cfg, state=trend)[0])
    assert o and o[0].entry_type == "continuation"
    assert not opens(
        run(h, config(**{"rules.pullback": False, "rules.continuation": False}), state=trend)[0]
    )
    # Baseline crossed since the original entry: trend invalidated, no continuation.
    crossed = hist([1.03] * 5 + [0.99] + [1.03] * 4, c1_signal=[0] * 9 + [1])
    assert not opens(run(crossed, cfg, state=trend, start=0)[0])


def test_continuation_uses_dedicated_slot_when_configured():
    trend = EngineState(symbols={"EURUSD": SymbolState(trend_dir=1, trend_origin="x")})
    h = hist([1.03] * 10, c1_signal=[0] * 10, c1_state=[1] * 10, cont_signal=[0] * 9 + [1])
    o = opens(run(h, config(**{"rules.pullback": False}), state=trend)[0])
    assert o and o[0].entry_type == "continuation"


# -------------------------------------------------------------------- exits
def _in_trade(**kw):
    return EngineState(
        symbols={
            "EURUSD": SymbolState(
                phase=Phase.IN_TRADE, entry_atr=0.01, trend_dir=1, trend_origin="x"
            )
        }
    )


def test_exit_precedence_baseline_before_exit_indicator():
    h = hist([1.004] * 9 + [0.99], c1_signal=[0] * 9 + [-1], exit=[0] * 9 + [1])
    intents, st = run(
        h,
        positions=[position(1, leg="tp1", target=1.01), position(1, pid="EURUSD#2")],
        state=_in_trade(),
    )
    closes = [i for i in intents if isinstance(i, CloseIntent)]
    assert {c.reason for c in closes} == {"baseline_cross"} and len(closes) == 2
    assert st.get("EURUSD").phase == Phase.FLAT and st.get("EURUSD").trend_dir == 0


def test_exit_indicator_then_opposite_signal_only_without_exit_slot():
    h = hist(ABOVE, c1_signal=[0] * 9 + [-1], exit=[0] * 9 + [1])
    intents, _ = run(h, positions=[position(1)], state=_in_trade())
    assert [i.reason for i in intents if isinstance(i, CloseIntent)] == ["exit_indicator"]
    # Exit slot present but not firing: an opposite C1 signal does NOT exit.
    h2 = hist(ABOVE, c1_signal=[0] * 9 + [-1], exit=[0] * 10)
    assert not [
        i
        for i in run(h2, positions=[position(1)], state=_in_trade())[0]
        if isinstance(i, CloseIntent)
    ]
    # No exit slot: opposite C1 signal exits.
    h3 = hist(ABOVE, c1_signal=[0] * 9 + [-1])
    assert [
        i.reason
        for i in run(h3, positions=[position(1)], state=_in_trade())[0]
        if isinstance(i, CloseIntent)
    ] == ["opposite_c1"]


def test_no_reentry_on_the_exit_bar():
    st = EngineState(symbols={"EURUSD": SymbolState(phase=Phase.IN_TRADE, entry_atr=0.01)})
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    acct = AccountState(
        equity=1e4, balance=1e4, peak_equity=1e4, recent_exits=frozenset({"EURUSD"})
    )
    intents, new = run(h, state=st, account=acct)
    assert not opens(intents) and new.get("EURUSD").last_exit_time == h.time()
    # Without the exit, the same bar enters.
    assert opens(run(h, state=EngineState())[0])


def test_rejected_entry_is_not_treated_as_an_exit():
    st = EngineState(
        symbols={
            "EURUSD": SymbolState(
                phase=Phase.IN_TRADE,
                awaiting_fill=True,
                entry_type="standard",
                trend_dir=1,
                trend_origin="x",
            )
        }
    )
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    assert opens(run(h, state=st)[0])


# --------------------------------------------------------- money management
def test_runner_breakeven_then_stepped_trail():
    st = EngineState(symbols={"EURUSD": SymbolState(phase=Phase.IN_TRADE, entry_atr=0.01)})
    runner = position(1, entry=1.0, stop=0.985)
    cfg = config(**{"risk.trail_uses_live_atr": False})

    def stop_after(close: float, stop: float) -> tuple[float | None, Phase]:
        h = hist([1.004] * 9 + [close], baseline=0.99)
        p = position(1, entry=1.0, stop=stop)
        intents, s = run(h, cfg, positions=[p], state=st)
        mods = [i.stop for i in intents if isinstance(i, ModifyIntent)]
        return (mods[0] if mods else None), s.get("EURUSD").phase

    assert stop_after(1.012, 0.985) == (pytest.approx(1.0), Phase.RUNNER_BE)
    assert stop_after(1.016, 1.0) == (None, Phase.TRAILING)
    assert stop_after(1.021, 1.0)[0] == pytest.approx(1.005)
    assert stop_after(1.026, 1.005)[0] == pytest.approx(1.010)
    # Never moves backwards.
    assert stop_after(1.0205, 1.010)[0] is None
    assert runner.leg == "runner"


def test_trail_live_vs_frozen_atr_toggle():
    st = EngineState(
        symbols={"EURUSD": SymbolState(phase=Phase.TRAILING, entry_atr=0.01, best_close=1.03)}
    )
    h = hist([1.004] * 9 + [1.03], baseline=0.99, atr=0.02)
    p = position(1, entry=1.0, stop=1.0)
    frozen = [
        i.stop
        for i in run(h, config(**{"risk.trail_uses_live_atr": False}), positions=[p], state=st)[0]
        if isinstance(i, ModifyIntent)
    ]
    live = [
        i.stop for i in run(h, config(), positions=[p], state=st)[0] if isinstance(i, ModifyIntent)
    ]
    assert (
        frozen == [pytest.approx(1.015)] and live == []
    )  # live ATR 0.02: 1.5 ATR = 0.03 -> stop stays at BE


def test_live_atr_stop_alternative():
    h = hist(ABOVE, atr=0.02)
    p = position(1, leg="tp1", entry=1.0, stop=0.985, target=1.01)
    assert not run(h, positions=[p], state=_in_trade())[0]
    mods = run(h, config(**{"risk.atr_frozen_at_entry": False}), positions=[p], state=_in_trade())[
        0
    ]
    assert mods[0].stop == pytest.approx(0.97) and mods[0].target == pytest.approx(1.02)


def test_single_position_and_no_hedging_variants():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    single = opens(run(h, config(**{"risk.positions_per_entry": 1}))[0])
    assert [(i.leg, i.risk_fraction, i.target_distance) for i in single] == [("single", 0.02, None)]
    fifo = fx_spec("EURUSD", supports_hedging=False)
    combined = opens(run(hist(ABOVE, c1_signal=[0] * 9 + [1], instrument=fifo))[0])
    assert [(i.leg, i.risk_fraction, i.target_fraction) for i in combined] == [
        ("combined", 0.02, 0.5)
    ]


def test_idempotency_keys_are_deterministic():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    a, b = opens(run(h)[0]), opens(run(h)[0])
    assert (
        [i.idempotency_key for i in a]
        == [i.idempotency_key for i in b]
        == [idempotency_key("EURUSD", h.time(), k) for k in (0, 1)]
    )


# ------------------------------------------------------------------- purity
def test_decide_is_pure_and_repeatable():
    h = hist(ABOVE, c1_signal=[0] * 9 + [1])
    eng, cfg, st = StrategyEngine(), config(), EngineState()
    before = (h.close.copy(), st.model_dump_json())
    d1 = eng.decide({"EURUSD": h}, [], ACCOUNT, cfg, st)
    d2 = eng.decide({"EURUSD": h}, [], ACCOUNT, cfg, st)
    assert d1.intents == d2.intents and d1.state == d2.state
    assert (h.close == before[0]).all() and st.model_dump_json() == before[1]


def test_engine_cannot_read_the_future():
    h = hist(ABOVE)
    with pytest.raises(IndexError):
        h.at(5).px("close", -1)


ENGINE = Path(__file__).parent.parent / "nnfx" / "engine"
FORBIDDEN_IMPORTS = {
    "time",
    "datetime",
    "random",
    "os",
    "socket",
    "urllib",
    "requests",
    "nnfx.indicators.library",
    "nnfx.data",
    "nnfx.brokers",
}


def test_engine_performs_no_io_and_knows_no_concrete_names():
    from nnfx.config import SLOT_NAMES
    from nnfx.indicators.base import registered

    names = {n for _, n in registered()} - set(SLOT_NAMES)
    for path in ENGINE.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name for a in node.names} & FORBIDDEN_IMPORTS, path
            if isinstance(node, ast.ImportFrom):
                assert node.module not in FORBIDDEN_IMPORTS, (path, node.module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "print", "input"}, path
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in names, f"{path}: engine names indicator {node.value!r}"
                assert node.value not in {"fx_spot", "crypto_spot", "crypto_perp"}, (
                    f"{path}: branches on market name"
                )
