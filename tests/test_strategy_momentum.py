"""MACD, ROC and ADX/DMI rules (Strategy Builder ticket 16): fire / no-fire fixtures per rule."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, block_catalogue
from nnfx.strategy.library import (
    AdxOrderType,
    AdxOrderTypeParams,
    ProfitChain,
    ProfitChainParams,
)
from nnfx.strategy.momentum import (
    MacdCross,
    MacdCrossParams,
    RocBoxBreakout,
    RocBoxParams,
    RocCeiling,
    RocCeilingParams,
    di_state,
    dmi_of,
    macd_of,
)
from nnfx.strategy.series import dmi, ema, macd
from tests.test_strategy_engine import DOC, FILL, RISE, SETUP, TO_TARGET, run
from tests.test_strategy_oscillators import FLAT, cand, data, outcomes, ramp

NEW = {"macd_cross", "roc_ceiling", "roc_box_breakout", "adx_order_type"}


def walk(n: int, seed: int = 11, sigma: float = 0.3) -> list[float]:
    """A quiet random walk: ROC has a ceiling and a floor, ADX stays low."""
    rng = np.random.default_rng(seed)
    return list(100.0 + np.cumsum(rng.normal(0.0, sigma, n)))


QUIET = walk(320)
SURGE = [QUIET[-1] + 2.0 * (k + 1) for k in range(12)]
CRASH = [QUIET[-1] - 2.0 * (k + 1) for k in range(12)]


# ------------------------------------------------------------ the series
def test_ema_macd_and_dmi_match_their_definitions():
    x = np.arange(1.0, 60.0)
    e = ema(x, 5)
    assert np.isnan(e[3]) and np.isfinite(e[4])
    line, sig, hist = macd(x, 12, 26, 9)
    assert np.isnan(line[24]) and np.isfinite(line[25]) and np.isfinite(sig[33])
    np.testing.assert_allclose(hist[40:], (line - sig)[40:])
    assert (line[30:] > 0).all()  # a rising series: the fast EMA is above the slow one
    hi, lo = x + 0.5, x - 0.5
    pdi, mdi, adx = dmi(hi, lo, x, 5)
    assert (pdi[10:] > mdi[10:]).all() and mdi[10] == pytest.approx(0.0)
    assert adx[-1] > 90  # a pure trend: all of the movement is directional
    pdi, mdi, adx = dmi(lo[::-1] + 100, lo[::-1] - 1 + 100, x[::-1] + 100, 5)
    assert (mdi[10:] > pdi[10:]).all()


# ---------------------------------------------------------------- the rule
def test_the_new_blocks_are_registered_flat_and_only_filters_are_oscillators():
    assert set(REGISTRY) >= NEW
    catalogue = {b["type"]: b for b in block_catalogue()}
    for t in NEW:
        schema = catalogue[t]["params"]
        assert "$defs" not in schema
        for name, prop in schema["properties"].items():
            assert prop.get("description"), f"{t}.{name}"
    assert REGISTRY["adx_order_type"].kind == BlockKind.EXECUTION
    assert not REGISTRY["adx_order_type"].oscillator  # it places the order; it never decides one
    for t in ("macd_cross", "roc_ceiling", "roc_box_breakout"):
        assert REGISTRY[t].oscillator


# ------------------------------------------------------------- macd cross
TREND_THEN_CHOP = ramp(90, 100.0, 1.0) + [190.0 + (0.4 if k % 2 else -0.4) for k in range(80)]
DIP_THEN_RESUME = ramp(80, 100.0, 1.0) + [179.0 - 0.8 * k for k in range(14)] + ramp(30, 168.0, 1.5)


def test_a_macd_cross_away_from_zero_passes_for_a_long_and_not_a_short():
    d = data(DIP_THEN_RESUME)
    block = MacdCross(MacdCrossParams(cross_bars=3))
    out = outcomes(block, d)
    assert "pass" in out[94:]
    assert "pass" not in outcomes(block, d, direction=-1)[94:]


def test_a_macd_cross_away_from_zero_passes_for_a_short_on_the_mirror_path():
    mirror = [200.0 - (c - 100.0) for c in DIP_THEN_RESUME]
    out = outcomes(MacdCross(MacdCrossParams(cross_bars=3)), data(mirror), direction=-1)
    assert "pass" in out[94:]


def test_crosses_hugging_the_zero_line_are_chop_and_fail():
    d = data(TREND_THEN_CHOP)
    on = MacdCross(MacdCrossParams(cross_bars=2, zero_band=0.2))
    off = MacdCross(MacdCrossParams(cross_bars=2, zero_band=0.0))
    late = slice(140, None)  # the trend's MACD has faded: whatever crosses now is near zero
    results = [on.check(cand(d, i), d) for i in range(len(d))][late]
    assert "pass" not in [r.outcome for r in results]
    assert any("نزدیک خط صفر" in r.reason for r in results)
    assert "pass" in outcomes(off, d)[late] + outcomes(off, d, -1)[late]  # but are valid without it


def test_macd_cross_is_na_until_it_exists_and_validates_its_periods():
    d = data(DIP_THEN_RESUME)
    assert MacdCross().check(cand(d, 5), d).outcome == "na"
    with pytest.raises(ValidationError):
        MacdCrossParams(fast=26, slow=12)


# ------------------------------------------------------------ roc ceiling
def test_the_roc_ceiling_disables_longs_at_the_ceiling_and_leaves_shorts_alone():
    d = data(QUIET + SURGE)
    out = RocCeiling(RocCeilingParams(role="lwc")).compute(d)
    n = len(QUIET)
    assert not out.long_ok[n + 2 :].any()  # the surge is at the ceiling for as long as it runs
    assert out.short_ok[n:].all()  # a ceiling is no floor
    assert out.flags["roc_at_ceiling"][n + 2 :].all()
    assert out.long_ok[:60].all()  # no ceiling yet: nothing is forbidden
    assert out.long_ok[:n].mean() > 0.7  # and the quiet walk mostly sits below it


def test_the_roc_floor_disables_shorts_when_mirrored():
    d = data(QUIET + CRASH)
    block = RocCeiling(RocCeilingParams(role="lwc"))
    out = block.compute(d)
    assert not out.short_ok[len(QUIET) + 2 :].any() and out.long_ok[len(QUIET) :].all()
    solo = RocCeiling(RocCeilingParams(role="lwc", mirror=False)).compute(d)
    assert solo.short_ok.all() and not out.short_ok.all()


def test_the_roc_ceiling_reads_a_higher_role_only_once_it_has_closed():
    roles = {"hwc": "M15", "mwc": "H1", "lwc": "M15", "management": "H1"}
    d = data(walk(900) + [100 + 60 + 3.0 * k for k in range(60)], roles)
    out = RocCeiling(RocCeilingParams(role="mwc", period=4, extreme_window=40)).compute(d)
    h1 = d.frames["mwc"]
    assert len(h1) < len(d) and not out.long_ok.all()
    # Within one H1 bar the answer never changes between its first and last 15m bar.
    pos = d.positions["mwc"]
    for k in np.unique(pos[pos >= 0])[:-1]:
        assert len(set(out.long_ok[pos == k])) == 1


# ------------------------------------------------------- roc box breakout
def test_roc_leaving_its_box_confirms_in_that_direction_only():
    block = RocBoxBreakout(RocBoxParams(box_bars=30, fresh_bars=3))
    up = data(QUIET + SURGE)
    n = len(QUIET)
    got = outcomes(block, up, start=n)
    assert got[1] == "pass" and "pass" in got
    assert "pass" not in outcomes(block, up, direction=-1, start=n)
    down = data(QUIET + CRASH)
    assert "pass" in outcomes(block, down, direction=-1, start=n)
    assert "pass" not in outcomes(block, down, start=n)


def test_roc_inside_its_box_fails_and_a_stale_breakout_expires():
    block = RocBoxBreakout(RocBoxParams(box_bars=30, fresh_bars=2))
    d = data(QUIET + SURGE + [SURGE[-1] + 0.1 * k for k in range(40)])
    res = [block.check(cand(d, i), d) for i in range(len(d))]
    assert res[len(QUIET) + 1].outcome == "pass"
    assert res[-1].outcome != "pass"  # the surge is long gone and ROC is back in a calm range
    assert res[10].outcome == "na"  # not enough ROC history for a box yet


# --------------------------------------------------------- the profit exits
def moves(params: ProfitChainParams, closes: list[float], filled: int, direction: int = 1):
    """Every (bar, move reason) the Profit Chain asks for on the management bars."""
    from tests.test_strategy_blocks import position

    d = data(closes)
    c = cand(d, 30, direction)
    block = ProfitChain(params)
    pv = position(block, c, d, filled)
    out = []
    for j in range(35, len(d)):
        mv = block.manage(pv, d, j)
        if mv is not None:
            out.append((j, getattr(mv, "reason", "")))
    return out


def reasons(params: ProfitChainParams, closes: list[float], filled: int, direction: int = 1):
    return {r for _, r in moves(params, closes, filled, direction)}


ACCELERATING = [100.0 + 0.02 * k * k for k in range(60)]
DECELERATING = [ACCELERATING[-1] + 8.0 * np.sqrt(k + 1) for k in range(40)]


def test_macd_deceleration_takes_profit_at_a_new_high_and_only_after_a_step():
    path = ACCELERATING + DECELERATING
    on = ProfitChainParams(macd_decel_exit=True, macd_decel_bars=3)
    assert "macd_decel" in reasons(on, path, filled=1)
    assert "macd_decel" not in reasons(on, path, filled=0)  # the 2R floor
    assert "macd_decel" not in reasons(ProfitChainParams(), path, filled=1)  # off by default
    assert "macd_decel" not in reasons(on, path, filled=1, direction=-1)
    close_bars = [j for j, r in moves(on, path, 1) if r == "macd_decel"]
    d = data(path)
    hist = macd_of(d, "management", 12, 26, 9)[2]
    assert all(hist[j] > 0 for j in close_bars)  # a contraction, never a reversal


def test_macd_deceleration_needs_a_new_price_extreme():
    pullback = [ACCELERATING[-1] - 0.5 * k for k in range(1, 40)]  # histogram shrinks, price falls
    on = ProfitChainParams(macd_decel_exit=True, macd_decel_bars=3, macd_extreme_bars=5)
    far = [j for j, r in moves(on, ACCELERATING + pullback, 1) if r == "macd_decel"]
    assert all(j <= 62 for j in far)  # none once the last new high is out of the window


def test_the_roc_ceiling_exit_closes_at_the_ceiling_after_a_step():
    path = QUIET + SURGE
    on = ProfitChainParams(roc_ceiling_exit=True)
    got = [j for j, r in moves(on, path, 1) if r == "roc_ceiling"]
    assert got and max(got) >= len(QUIET)
    assert "roc_ceiling" not in reasons(on, path, filled=0)
    assert "roc_ceiling" not in reasons(ProfitChainParams(), path, filled=1)
    assert "roc_ceiling" not in {r for j, r in moves(on, QUIET + CRASH, 1) if j >= len(QUIET)}
    mirror = {r for j, r in moves(on, QUIET + CRASH, 1, -1) if j >= len(QUIET)}
    assert "roc_ceiling" in mirror  # a short takes profit at the floor


STRONG_THEN_SIDEWAYS = ramp(120, 100.0, 1.0) + [219.0 + (0.5 if k % 2 else -0.5) for k in range(60)]


def test_adx_exhaustion_closes_or_tightens_once_adx_curls_down_from_a_high():
    path = STRONG_THEN_SIDEWAYS
    close = ProfitChainParams(adx_exhaustion="close", adx_level=45.0)
    tighten = ProfitChainParams(adx_exhaustion="tighten", adx_level=45.0)
    closed = [j for j, r in moves(close, path, 1) if r == "adx_exhaustion"]
    assert closed and min(closed) >= 120  # only after the strong leg has ended
    assert "adx_exhaustion" not in reasons(close, path, filled=0)
    assert "adx_exhaustion_tighten" in reasons(tighten, path, filled=0)  # a tighter stop is safe
    assert "adx_exhaustion" not in reasons(tighten, path, filled=1)  # and never a close
    assert not reasons(ProfitChainParams(), path, filled=1) & {"adx_exhaustion"}
    high = ProfitChainParams(adx_exhaustion="close", adx_level=60.0)
    assert "adx_exhaustion" not in reasons(high, QUIET, filled=1)  # ADX never gets that high


# ------------------------------------------------------- adx order type
TREND = list(100 + np.cumsum(np.random.default_rng(5).normal(0.4, 0.5, 120)))  # DI far apart
TANGLED = FLAT * 3


def order_specs(closes: list[float], bar: int, params: AdxOrderTypeParams, direction: int = 1):
    d = data(closes)
    return AdxOrderType(params).orders(cand(d, bar, direction), d), d


def test_di_state_names_a_trend_and_a_tangle():
    up, tangled = data(TREND), data(TANGLED)
    kw = {"separation": 10.0, "tangled": 5.0, "slope_bars": 3}
    assert di_state(up, "lwc", 14, 52, **kw) == "separated"
    assert di_state(tangled, "lwc", 14, 100, **kw) == "tangled"
    assert di_state(up, "lwc", 14, 3, **kw) == "unknown"
    pdi, mdi, adx = dmi_of(up, "lwc", 14)
    assert pdi[52] > mdi[52] and adx[52] > adx[49]


def test_separated_di_with_rising_adx_places_the_usual_stop_order():
    specs, d = order_specs(TREND, 52, AdxOrderTypeParams())
    (spec,) = specs
    assert not spec.market and spec.level == pytest.approx(float(d.base.close[52]))
    assert spec.expires_after_bars == 4 and spec.invalidation is not None


def test_tangled_di_waits_for_a_body_close_beyond_the_boundary():
    closes = TANGLED
    d = data(closes)
    c = cand(d, 100)  # invalidation: one below the close, so the close is beyond it
    block = AdxOrderType()
    (spec,) = block.orders(c, d)
    assert spec.market and spec.level == pytest.approx(float(d.base.close[100]))
    waiting = SetupCandidateWith(c, invalidation=float(d.base.close[100]) + 1.0)
    assert block.orders(waiting, d) == []  # the close has not got beyond the boundary


def SetupCandidateWith(c, **changes: Any):
    from dataclasses import replace

    return replace(c, **changes)


def test_the_same_candidate_changes_order_type_with_the_adx_thresholds():
    d = data(TREND)
    c = cand(d, 52)
    default = AdxOrderType().orders(c, d)
    forced = AdxOrderType(AdxOrderTypeParams(tangled=150.0, separation=200.0)).orders(c, d)
    assert [s.market for s in default] == [False] and [s.market for s in forced] == [True]
    between = AdxOrderType(AdxOrderTypeParams(between="close", separation=200.0)).orders(c, d)
    assert [s.market for s in between] == [True]


def test_adx_order_type_validates_its_thresholds():
    with pytest.raises(ValidationError):
        AdxOrderTypeParams(tangled=12.0, separation=10.0)


def adx_doc(**params: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["blocks"][2] = {
        "kind": "execution",
        "type": "adx_order_type",
        "params": {"buffer_pct": 0, "expiry_bars": 4, "period": 2, "slope_bars": 1, **params},
    }
    return raw


def first_intent(journal) -> dict[str, Any]:
    (ev,) = [e for r in journal.records("cycle") for e in r["evaluations"]]
    return ev


def test_the_engine_turns_the_same_candle_setup_into_a_stop_or_a_market_entry():
    rows = [*RISE, SETUP, FILL, *TO_TARGET]
    _out, journal = run(rows, adx_doc())
    ev = first_intent(journal)
    assert ev["intents"][0]["kind"] == "pending" and ev["blocked"] == []
    out2, journal2 = run(rows, adx_doc(tangled=150.0, separation=200.0))
    ev2 = first_intent(journal2)
    assert ev2["blocked"] == [] and ev2["intents"][0]["kind"] == "open"
    assert ev2["intents"][0]["stop_distance"] == pytest.approx(111.2 - 106.0)
    assert out2.result.trades  # and the market entry trades


def test_adx_exhaustion_both_tightens_and_closes():
    both = ProfitChainParams(adx_exhaustion="both", adx_level=45.0)
    assert {"adx_exhaustion", "adx_exhaustion_tighten"} & reasons(both, STRONG_THEN_SIDEWAYS, 1)
    assert "adx_exhaustion" not in reasons(both, STRONG_THEN_SIDEWAYS, 0)
