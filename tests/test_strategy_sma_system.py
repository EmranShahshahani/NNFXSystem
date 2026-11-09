"""The 3-SMA system and the full Candle Setup (Strategy Builder ticket 10).

Every rule gets a fixture where it makes the setup fire and one where it does
not. Rules that act on a decision run through the backtest harness; the rest
read a Block's output on hand-built 15m bars.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

import numpy as np

from nnfx.config import SessionConfig
from nnfx.journal.journal import Journal
from nnfx.strategy import REGISTRY, StrategyData, validate_document
from nnfx.strategy.blocks import SetupBlock, SetupCandidate
from nnfx.strategy.library import (
    CandleSetup,
    CandleSetupParams,
    ChoppyRegime,
    ChoppyRegimeParams,
    OverextensionGuard,
    OverextensionParams,
    SecondWave,
    SecondWaveParams,
    SmaBaselineFilter,
    SmaCrossover,
    SmaCrossoverParams,
    SmaSlopeGate,
    VolumeContinuation,
    VolumeContinuationParams,
)
from nnfx.strategy.run import backtest_document
from nnfx.strategy.structure import waves
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, SYM, TO_TARGET, frame
from tests.test_strategy_structure import path

Row = tuple[float, float, float, float]
ROLES = {"hwc": "M15", "mwc": "M15", "lwc": "M15", "management": "M15"}


def data(rows: list[Row]) -> StrategyData:
    return StrategyData.build(frame(rows), ROLES, BTC, SessionConfig())


def slow_fall(bars: int = 12, start: float = 112.0) -> list[Row]:
    rows, c = [], start
    for _ in range(bars):
        o, c = c, c - 1.0
        rows.append((o, o + 0.05, c - 0.05, c))
    return rows


def candidate(d: StrategyData, direction: int = 1, bar: int | None = None) -> SetupCandidate:
    i = len(d) - 1 if bar is None else bar
    c = float(d.base.close[i])
    return SetupCandidate(
        SYM, "candle_setup", 1, i, d.base.index[i].isoformat(), direction, c, c, c
    )


# ------------------------------------------------------- Candle Setup slope
def fire(rows: list[Row], **kw: Any) -> int:
    return int(CandleSetup(CandleSetupParams(**kw)).compute(data(rows)).direction[-1])


def test_the_candle_setup_needs_the_sma_to_slope_with_the_trade():
    bounce: Row = (102.8, 103.4, 101.0, 103.3)  # SMA 7 behind the wick, but still falling
    assert fire([*RISE, SETUP]) == 1  # rising SMA: fires
    assert fire([*slow_fall(), bounce]) == 0  # falling SMA: no setup
    assert fire([*slow_fall(), bounce], sma_slope=False) == 1  # the rule is switchable


def test_the_candle_setup_placement_and_geometry_rules_still_hold():
    wick_through_body: Row = (111.0, 111.3, 106.0, 107.0)  # SMA 7 (~108) cuts the body
    assert fire([*RISE, wick_through_body]) == 0
    short_wick: Row = (111.0, 111.3, 109.0, 111.2)  # lower wick 2.0 vs body 0.2: fires...
    assert fire([*RISE, short_wick]) == 0  # ...but the SMA is not inside the wick
    small: Row = (111.0, 111.3, 110.5, 111.2)  # wick 0.5 < 1.5 x body 0.2? no: 0.5 >= 0.3
    assert fire([*RISE, small], wick_to_body=3.0) == 0  # a stricter ratio refuses it


# -------------------------------------------------------------- slope gate
def slope_gate(rows: list[Row], **kw: Any) -> tuple[bool, bool]:
    d = data(rows)
    out = SmaSlopeGate(replace_params(**kw)).compute(d)
    return bool(out.long_ok[-1]), bool(out.short_ok[-1])


def replace_params(**kw: Any):
    from nnfx.strategy.library import SlopeGateParams

    return SlopeGateParams(timeframe="lwc", **kw)


def test_a_flattening_sma_7_stops_new_entries():
    flat = [(130.0, 130.4, 129.6, 130.0)] * 12
    assert slope_gate(LONG_RISE + flat) == (False, False)  # the SMA has gone flat
    assert slope_gate(LONG_RISE) == (True, False)  # still rising: longs only
    assert slope_gate(slow_fall(30, 150.0)) == (False, True)
    assert slope_gate(LONG_RISE + flat, min_slope_atr=0.0) == (
        False,
        False,
    )  # exactly flat is not up


# ---------------------------------------------------------- 99 SMA filter
def test_the_baseline_filter_blocks_longs_below_and_shorts_above_the_sma():
    below = SmaBaselineFilter(BaselineParams_(period=5, timeframe="lwc")).compute(data(slow_fall()))
    assert (bool(below.long_ok[-1]), bool(below.short_ok[-1])) == (False, True)
    above = SmaBaselineFilter(BaselineParams_(period=5, timeframe="lwc")).compute(data(RISE))
    assert (bool(above.long_ok[-1]), bool(above.short_ok[-1])) == (True, False)
    # Before the SMA exists nothing is allowed (it cannot be judged).
    warm = SmaBaselineFilter(BaselineParams_(period=50, timeframe="lwc")).compute(data(RISE))
    assert not warm.long_ok.any() and not warm.short_ok.any()


def BaselineParams_(**kw: Any):
    from nnfx.strategy.library import BaselineParams

    return BaselineParams(**kw)


# ------------------------------------------------------ overextension guard
def test_the_overextension_guard_refuses_trades_in_the_direction_of_a_stretch():
    stretched = [*LONG_RISE, *path(190.0, start=LONG_RISE[-1][3], per=5.0)]
    g = OverextensionGuard(OverextensionParams(period=5, timeframe="lwc", max_atr=2.0))
    out = g.compute(data(stretched))
    assert (bool(out.long_ok[-1]), bool(out.short_ok[-1])) == (False, True)
    assert out.flags["extension_atr"][-1] > 2.0
    calm = g.compute(data(LONG_RISE))
    assert calm.long_ok[-1] and calm.short_ok[-1]  # within range: both directions
    # It lifts when price pulls back toward the SMA.
    pulled = [*stretched, *path(135.0, start=stretched[-1][3], per=5.0)]
    assert g.compute(data(pulled)).long_ok[-1]


# ---------------------------------------------------------- crossover only
def test_a_crossover_only_confirms_and_never_enters():
    assert REGISTRY["sma_crossover"].kind.value == "confirmation"
    assert not issubclass(REGISTRY["sma_crossover"], SetupBlock)
    d = data(RISE)
    both = SmaCrossover(SmaCrossoverParams(fast=2, mid=3, slow=4, timeframe="lwc", pairs="both"))
    assert both.check(candidate(d), d).outcome == "pass"  # fast over mid over slow
    assert both.check(candidate(d, -1), d).outcome == "fail"
    young = data(RISE[:3])
    assert both.check(candidate(young), young).outcome == "na"
    # A golden cross with no Candle Setup places nothing.
    raw = copy.deepcopy(DOC)
    raw["blocks"].insert(
        2,
        {
            "kind": "confirmation",
            "type": "sma_crossover",
            "params": {"fast": 2, "mid": 3, "slow": 4, "timeframe": "lwc"},
        },
    )
    res = validate_document(raw)
    assert res.document is not None
    cross = [(100.0 + 0.1 * k, 100.3 + 0.1 * k, 99.9 + 0.1 * k, 100.1 + 0.1 * k) for k in range(8)]
    cross += [(100.8 + k, 101.9 + k, 100.7 + k, 101.8 + k) for k in range(8)]
    out = backtest_document(res.document, {SYM: frame(cross)}, {SYM: BTC}, journal=Journal())
    assert out.candidates == [] and out.result.trades == []


# --------------------------------------------------------- volume (continuation)
def test_volume_continuation_wants_a_quieter_setup_than_the_impulse():
    d = data([*RISE, SETUP])
    i = len(d) - 1
    block = VolumeContinuation(VolumeContinuationParams(impulse_bars=5))
    f = d.base
    v = np.asarray(f.volume).copy()
    quiet = StrategyData.build(_with_volume(f, v * 1.0), ROLES, BTC, SessionConfig())
    v[i] = 0.4
    quiet = StrategyData.build(_with_volume(f, v), ROLES, BTC, SessionConfig())
    assert block.check(candidate(quiet), quiet).outcome == "pass"
    v[i] = 2.0
    loud = StrategyData.build(_with_volume(f, v), ROLES, BTC, SessionConfig())
    assert block.check(candidate(loud), loud).outcome == "fail"
    v[i] = 1.0  # equal to the average is not quieter
    even = StrategyData.build(_with_volume(f, v), ROLES, BTC, SessionConfig())
    assert block.check(candidate(even), even).outcome == "fail"
    assert block.check(candidate(d, bar=2), d).outcome == "na"  # too little history


def _with_volume(f, v):
    import pandas as pd

    from nnfx.data.bars import BarFrame

    df = pd.DataFrame(
        {"open": f.open, "high": f.high, "low": f.low, "close": f.close, "volume": v},
        index=f.index,
    )
    return BarFrame(df, f.symbol, timeframe=f.timeframe, volume_kind="traded", price_venue="x")


# -------------------------------------------------------------- Second Wave
LONG_RISE: list[Row] = [(100.0 + k, 101.1 + k, 99.9 + k, 101.0 + k) for k in range(30)]
LEG_ONE = path(110, 105, 115, 110, 120)  # first leg, a pullback to 110, then 120...


def test_waves_count_legs_from_confirmed_structure():
    rows = [*LEG_ONE, *path(113, 125, start=LEG_ONE[-1][3])]
    a = np.asarray(rows)
    state, wave = waves(a[:, 2], a[:, 1], a[:, 3], 2)
    assert wave[0] == 0 and state[0] == 0
    first = int(np.argmax(state == 1))
    assert wave[first] == 1  # a trend starts in its first leg
    assert wave[-1] == 2 and state[-1] == 1  # the continuation leg after a confirmed pullback
    assert (wave[state == 0] == 0).all()  # no wave outside a trend
    # Prefixes agree with the full series: waves never change their past.
    w_full = wave
    for n in range(10, len(rows)):
        assert np.array_equal(waves(a[:n, 2], a[:n, 1], a[:n, 3], 2)[1], w_full[:n])


def test_the_second_wave_check_passes_in_the_second_leg_only():
    block = SecondWave(SecondWaveParams(timeframe="lwc"))
    rows = [*LEG_ONE, *path(113, 125, start=LEG_ONE[-1][3])]
    first_leg = LEG_ONE[: int(np.argmax(waves(*_hlc(LEG_ONE), 2)[0] == 1)) + 3]
    d1 = data(first_leg)
    r1 = block.check(candidate(d1), d1)
    assert r1.outcome == "fail" and "wave 1" in r1.reason
    d2 = data(rows)
    assert block.check(candidate(d2), d2).outcome == "pass"
    assert block.check(candidate(d2, -1), d2).outcome == "fail"  # a short has no downtrend
    capped = SecondWave(SecondWaveParams(timeframe="lwc", max_wave=1))
    assert capped.check(candidate(d2), d2).outcome == "fail"
    early = data(RISE[:2])
    assert block.check(candidate(early), early).outcome == "fail"  # no trend yet


def _hlc(rows: list[Row]):
    a = np.asarray(rows)
    return a[:, 2], a[:, 1], a[:, 3]


# ----------------------------------------------------------- Choppy Regime
def choppy(rows: list[Row], **kw: Any):
    p = ChoppyRegimeParams(fast=2, mid=3, slow=4, timeframe="lwc", lookback=6, **kw)
    return ChoppyRegime(p).compute(data(rows))


def weave(bars: int, centre: float = 120.0) -> list[Row]:
    """Closes weaving up and down around ``centre``: the SMAs cross back and forth."""
    out, prev = [], centre
    for k in range(bars):
        c = centre + (0.6 if k % 2 == 0 else -0.6)
        out.append((prev, max(prev, c) + 0.2, min(prev, c) - 0.2, c))
        prev = c
    return out


def test_the_choppy_regime_starts_when_the_smas_flatten_and_cross_repeatedly():
    trend = choppy(RISE, min_crosses=2, flat_atr=5.0)
    assert not trend.flags["choppy"].any()  # a clean trend never reads as chop
    rows = [*RISE, *weave(16)]
    out = choppy(rows, min_crosses=2, flat_atr=5.0)
    assert out.flags["choppy"][-1] and not out.long_ok[-1] and not out.short_ok[-1]
    assert out.cancels_orders is not None and out.cancels_orders[-1]
    # A stricter crossing count (or a tighter flatness) is not met by the same weave.
    assert not choppy(rows, min_crosses=40, flat_atr=5.0).flags["choppy"].any()
    loose, tight = (
        choppy(rows, min_crosses=2, flat_atr=5.0),
        choppy(rows, min_crosses=2, flat_atr=0),
    )
    assert tight.flags["choppy"].sum() < loose.flags["choppy"].sum()  # moving SMAs are not chop
    assert choppy(rows, min_crosses=2, flat_atr=5.0, cancel_orders=False).cancels_orders is None


def test_the_choppy_regime_lasts_until_separation_resumes():
    rows = [
        *RISE,
        *weave(16),
        *[(120.0 + 3 * k, 123.2 + 3 * k, 119.9 + 3 * k, 123.0 + 3 * k) for k in range(8)],
    ]
    out = choppy(rows, min_crosses=2, flat_atr=5.0, separation_atr=0.5)
    chop = out.flags["choppy"]
    assert chop[len(RISE) + 15] and not chop[-1]
    ends = int(np.argmax(~chop[len(RISE) + 15 :])) + len(RISE) + 15
    # It ended on a bar where the SMAs are ordered and apart (not just on any bar).
    d = data(rows)
    a, b, s = (d.sma("lwc", k)[ends] for k in (2, 3, 4))
    assert a > b > s


def test_a_resting_breakout_order_is_cancelled_when_chop_sets_in():
    raw = copy.deepcopy(DOC)
    raw["blocks"][0] = {
        "kind": "context",
        "type": "choppy_regime",
        "params": {
            "fast": 2,
            "mid": 3,
            "slow": 4,
            "timeframe": "lwc",
            "lookback": 6,
            "min_crosses": 2,
            "flat_atr": 5.0,
        },
    }
    raw["blocks"][2]["params"] = {"buffer_pct": 0, "expiry_bars": 30}
    res = validate_document(raw)
    assert res.document is not None, res.render()
    # The setup rests above the weave (trigger 111.3); chop begins at the weave.
    rows = [*RISE, SETUP, *weave(12, centre=108.0)]
    journal = Journal()
    out = backtest_document(res.document, {SYM: frame(rows)}, {SYM: BTC}, journal=journal)
    (cand,) = [c for c in out.candidates if c["decision"] == "placed"]
    assert cand["checklist"][0]["outcome"] == "pass"  # not chop yet when it was placed
    events = [e for r in journal.records("cycle") for e in r["orders"]]
    cancels = [e for e in events if e["e"] == "cancel"]
    assert [c["reason"] for c in cancels] == ["context_disabled_orders"]
    assert out.result.trades == []
    marks = [
        ev["values"]
        for r in journal.records("cycle")
        for ev in r["evaluations"]
        if ev["values"].get("event") == "cancel_orders"
    ]
    assert len(marks) == 1 and marks[0]["keys"] == [cancels[0]["key"]]


# ------------------------------------------------------- SMA 25 flattening
def test_the_sma_25_flattening_takes_profit_after_the_first_step():
    raw = copy.deepcopy(DOC)
    raw["timeframes"]["management"] = "M15"
    raw["blocks"][-1] = {
        "kind": "exit",
        "type": "profit_chain",
        "params": {"sma_flatten_exit": True, "sma_period": 3, "sma_slope_bars": 2},
    }
    res = validate_document(raw)
    assert res.document is not None, res.render()
    flat = [(121.8, 122.0, 121.6, 121.8)] * 6
    out = backtest_document(
        res.document,
        {SYM: frame([*RISE, SETUP, FILL, *TO_TARGET, *flat])},
        {SYM: BTC},
        journal=Journal(),
    )
    first, rest = out.result.trades
    assert first.exit_reason == "target_partial"  # 2R, the 35% step
    assert rest.exit_reason == "sma3_flatten" and rest.exit_price > first.entry_price
    # Without the option the rest keeps running (to the end of the data).
    raw["blocks"][-1]["params"] = {}
    kept = backtest_document(
        validate_document(raw).document,
        {SYM: frame([*RISE, SETUP, FILL, *TO_TARGET, *flat])},
        {SYM: BTC},
        journal=Journal(),
    )
    assert kept.result.trades[1].exit_reason != "sma3_flatten"
    # And it never acts before the first step: the 2R floor stands.
    before = backtest_document(
        res.document,
        {SYM: frame([*RISE, SETUP, FILL, *[(112.4, 112.6, 112.2, 112.4)] * 8])},
        {SYM: BTC},
        journal=Journal(),
    )
    assert all(t.exit_reason != "sma3_flatten" for t in before.result.trades)


def test_every_new_block_is_a_registered_switchable_rule():
    names = {
        "choppy_regime",
        "sma_baseline_filter",
        "overextension_guard",
        "sma_slope_gate",
        "sma_crossover",
        "second_wave",
        "volume_continuation",
    }
    assert names <= set(REGISTRY)
    assert replace(candidate(data([*RISE, SETUP])), tags=("x",)).tags == ("x",)


def test_the_second_wave_rule_through_the_harness():
    raw = copy.deepcopy(DOC)
    raw["blocks"][0] = {"kind": "context", "type": "dow_trend", "params": {"timeframe": "lwc"}}
    raw["blocks"].insert(
        2, {"kind": "confirmation", "type": "second_wave", "params": {"timeframe": "lwc"}}
    )
    res = validate_document(raw)
    assert res.document is not None, res.render()

    def decide(rows: list[Row]) -> dict[str, Any]:
        c = rows[-1][3]
        candle: Row = (c, c + 0.3, c - 8.0, c + 0.2)  # SMA 7 sits behind the long lower wick
        out = backtest_document(res.document, {SYM: frame([*rows, candle])}, {SYM: BTC})
        return out.candidates[-1]

    state, _ = waves(*_hlc(LEG_ONE), 2)
    first_leg = LEG_ONE[: int(np.argmax(state == 1)) + 3]
    second = [*LEG_ONE, *path(113, 125, start=LEG_ONE[-1][3])]
    early, late = decide(first_leg), decide(second)
    assert early["checklist"][1]["outcome"] == "fail" and early["decision"] == "refused"
    assert early["reasons"] == ["confirmation:second_wave#2"]
    assert late["checklist"][1]["outcome"] == "pass" and late["decision"] == "placed"
