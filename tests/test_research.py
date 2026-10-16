"""Tickets 20-26: ablation, metrics, partitions, trial counter, overfitting, MC, selection, verdict."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nnfx.brokers.sim import Trade
from nnfx.config import SlotSpec
from nnfx.data.synthetic import regime_walk
from nnfx.instruments import fx_spec
from nnfx.research.ablation import ABLATIONS, run_ablation
from nnfx.research.evaluate import Evaluator
from nnfx.research.metrics import (
    Entry,
    bca_interval,
    compute_metrics,
    drawdown,
    effective_sample_size,
    entries_from_trades,
    losing_streak,
)
from nnfx.research.montecarlo import (
    bootstrap,
    classify_regimes,
    correlation_stress,
    propose_kill_switch,
    regime_report,
    stress_report,
)
from nnfx.research.overfitting import (
    deflated_sharpe,
    expected_max_sharpe,
    pbo_cscv,
    plateau,
    walk_forward,
)
from nnfx.research.partition import HoldoutAccessError, Partition
from nnfx.research.selection import SelectionPipeline
from nnfx.research.trials import ResearchState
from nnfx.research.verdict import Evidence, evaluate
from tests.helpers import config

ROOT = Path(__file__).parent.parent
CFG = config(**{"slots.c1": {"name": "macd", "params": {}}})


def dev_frames(n=1400):
    # 2010-2015 sits inside the FX development segment (2004-2015).
    return {
        "EURUSD": regime_walk(n, seed=21, symbol="EURUSD", start="2010-01-04"),
        "GBPUSD": regime_walk(n, seed=22, symbol="GBPUSD", start="2010-01-04", start_price=1.5),
    }


def evaluator(tmp: Path, **kw):
    frames = dev_frames()
    return Evaluator(
        {s: fx_spec(s) for s in frames},
        frames,
        market="fx",
        research=ResearchState(tmp),
        n_boot=200,
        **kw,
    )


# ---------------------------------------------------------------- ablation
def test_ablation_runner_toggles_rules_and_counts_trials(tmp_path: Path):
    ev = evaluator(tmp_path)
    rep = run_ablation(
        CFG,
        ev,
        rules=[
            "bridge_too_far",
            "continuation",
            "one_candle_rule",
            "position_split",
            "direction",
            "exit_x_trailing",
        ],
    )
    rules = {r.rule for r in rep.rows}
    assert rules == {
        "bridge_too_far",
        "continuation",
        "one_candle_rule",
        "position_split",
        "direction",
        "exit_x_trailing",
    }
    assert sum(r.is_base for r in rep.rows if r.rule == "bridge_too_far") == 1
    variants = {r.trial.config.digest() for r in rep.rows}
    assert ev.research.trial_count() == len(variants)
    off = next(r for r in rep.rows if r.rule == "bridge_too_far" and r.variant == "off")
    assert off.trial.metrics.n_entries != rep.base.metrics.n_entries
    assert "| bridge_too_far | off |" in rep.render()
    # Re-running is free: same ids, no double counting.
    run_ablation(CFG, ev, rules=["bridge_too_far"])
    assert ev.research.trial_count() == len(variants)
    assert {
        "session_close",
        "funding",
        "seven_candle_rule",
        "c2_requirement",
        "bridge_multiple",
    } <= set(ABLATIONS)


def test_session_close_ablation_needs_a_resampling_provider(tmp_path: Path):
    from nnfx.data.session import resample_to_daily
    from nnfx.data.synthetic import hourly_walk

    h1 = hourly_walk(24 * 1000, seed=5, start="2011-01-03", symbol="EURUSD")
    inst = {"EURUSD": fx_spec("EURUSD")}
    ev = Evaluator(
        inst,
        lambda cfg: {"EURUSD": resample_to_daily(h1, inst["EURUSD"], cfg.session)},
        market="fx",
        n_boot=50,
        gate_kwargs={"max_missing_sessions": 50},
    )
    rep = run_ablation(CFG, ev, rules=["session_close"], include_exit_trailing=False)
    a, b = (r.trial.result for r in rep.rows)
    assert [t.entry_time for t in a.trades] != [t.entry_time for t in b.trades]


def test_ablation_only_on_development(tmp_path: Path):
    frames = dev_frames()
    ev = Evaluator({s: fx_spec(s) for s in frames}, frames, market="fx", segment="validation")
    with pytest.raises(ValueError, match="development"):
        run_ablation(CFG, ev)


# ----------------------------------------------------------------- metrics
def _trade(sym, sig, r, leg="tp1", t0="2020-01-01", t1="2020-01-05", d=1):
    return Trade(
        f"{sym}#{sig}{leg}",
        sym,
        leg,
        d,
        "standard",
        sig,
        t0,
        t1,
        1.0,
        1.0,
        1,
        r * 100,
        0,
        0,
        0,
        0,
        "none",
        r * 100,
        100,
        r,
        "x",
        3,
    )  # type: ignore[arg-type]


def test_entry_r_sums_legs_and_metrics_are_correct():
    trades = [
        _trade("A", "s1", 0.67),
        _trade("A", "s1", 2.0, "runner"),
        _trade("A", "s2", -1.0, t0="2020-02-01", t1="2020-02-03"),
        _trade("A", "s2", -1.0, "runner", t0="2020-02-01", t1="2020-02-03"),
    ]
    es = entries_from_trades(trades)
    assert [e.r for e in es] == pytest.approx([2.67, -2.0])
    eq = pd.Series(
        [100, 110, 99, 120], index=pd.date_range("2020-01-01", periods=4, tz="UTC"), dtype=float
    )
    m = compute_metrics(trades, eq, n_boot=100)
    assert m.n_entries == 2 and m.win_rate == 0.5 and m.profit_factor == pytest.approx(2.67 / 2)
    assert m.max_drawdown == pytest.approx(0.1) and m.provisional
    assert drawdown(eq) == (pytest.approx(0.1), 1) and losing_streak([1, -1, -1, 2, -1]) == 2


def test_bca_interval_covers_and_is_skew_aware():
    rng = np.random.default_rng(1)
    x = rng.lognormal(0, 1, 400) - 1.2
    lo, hi = bca_interval(x, rng=np.random.default_rng(2), n_boot=2000)
    assert lo < x.mean() < hi
    assert (hi - x.mean()) > (x.mean() - lo), "right skew -> longer upper arm"
    assert bca_interval(x, rng=np.random.default_rng(2), n_boot=500) == bca_interval(
        x, rng=np.random.default_rng(2), n_boot=500
    )


def test_effective_sample_size_formula():
    es = [
        Entry(f"S{i}", "s", 1, "standard", "2020-01-01", "2020-01-10", 1, 1, 1, 0) for i in range(8)
    ]
    n_eff, m, _rho = effective_sample_size(es, rho_override=0.6)
    assert m == 8 and n_eff == pytest.approx(8 / 5.2)
    # 800 raw trades at design effect 5.2 carry the weight of ~154 (doc 03 §8.1).
    assert pytest.approx(153.8, abs=0.1) == 800 / (1 + 7 * 0.6)


def test_effective_sample_from_correlated_returns():
    idx = pd.date_range("2020-01-01", periods=60, tz="UTC")
    base = np.cumsum(np.random.default_rng(0).normal(0, 0.01, 60))
    closes = {
        "A": pd.Series(np.exp(base), index=idx),
        "B": pd.Series(np.exp(base * 1.01), index=idx),
    }
    es = [
        Entry(s, "s", 1, "standard", idx[0].isoformat(), idx[-1].isoformat(), 1, 1, 1, 0)
        for s in ("A", "B")
    ]
    n_eff, _m, rho = effective_sample_size(es, closes)
    assert rho > 0.95 and n_eff == pytest.approx(1.0, abs=0.05)


# ------------------------------------------------------ partitions / trials
def test_partitions_and_touch_once_holdout(tmp_path: Path):
    fx, cr = Partition.for_market("fx"), Partition.for_market("crypto")
    assert (fx.development.start.year, fx.validation.start.year, fx.holdout.start.year) == (
        2004,
        2016,
        2022,
    )
    assert (cr.development.start.year, cr.validation.start.year, cr.holdout.start.year) == (
        2017,
        2022,
        2025,
    )
    f = regime_walk(5000, start="2004-01-01")
    with pytest.raises(HoldoutAccessError):
        fx.segment(f, "holdout")
    rs = ResearchState(tmp_path)
    token = rs.touch_holdout("fx", CFG, "final verdict")
    assert len(fx.segment(f, "holdout", _holdout_token=token)) > 0
    with pytest.raises(HoldoutAccessError, match="exactly once"):
        rs.touch_holdout("fx", CFG, "just one more look")
    with pytest.raises(HoldoutAccessError):
        ResearchState(tmp_path).touch_holdout(
            "fx", CFG.with_overrides({"rules.continuation": False}), "other config"
        )
    rs.touch_holdout("crypto", CFG, "separate market")
    with pytest.raises(HoldoutAccessError):
        rs.record_trial(CFG, market="fx", segment="holdout", symbols=["EURUSD"], stage="x")
    with pytest.raises(PermissionError):
        Evaluator({}, {}, market="fx", segment="holdout")


def test_trial_count_is_derived_and_validation_passes_logged(tmp_path: Path):
    rs = ResearchState(tmp_path)
    a = rs.record_trial(CFG, market="fx", segment="development", symbols=["EURUSD"], stage="s1")
    b = rs.record_trial(CFG, market="fx", segment="development", symbols=["EURUSD"], stage="s1")
    c = rs.record_trial(
        CFG.with_overrides({"rules.pullback": False}),
        market="fx",
        segment="development",
        symbols=["EURUSD"],
        stage="s1",
    )
    assert a == b != c and rs.trial_count() == 2
    assert not list(tmp_path.glob("*count*")), "no counter file"
    rs.record_trial(CFG, market="fx", segment="validation", symbols=["EURUSD"], stage="confirm")
    rs.record_trial(CFG, market="fx", segment="validation", symbols=["EURUSD"], stage="confirm2")
    assert rs.validation_passes() == 2 and rs.trial_count() == 3
    lines = [json.loads(x) for x in (tmp_path / "trials.jsonl").read_text().splitlines()]
    assert all({"id", "workstation", "env"} <= set(x) for x in lines)


def test_thresholds_file_is_frozen():
    th = ResearchState(ROOT / "research").thresholds()
    assert th["frozen_on"] == "2026-08-27" and len(th["criteria"]) == 15
    assert (
        th["criteria"]["5_pbo"]["value"] == 0.30
        and th["criteria"]["10_cost_stress"]["multiplier"] == 1.5
    )


# ------------------------------------------------------------- overfitting
def test_dsr_deflates_with_trial_count():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0008, 0.01, 2000)
    one, many = deflated_sharpe(r, 1), deflated_sharpe(r, 1000)
    assert one.probability > many.probability and many.sr0 > one.sr0 == 0.0
    assert expected_max_sharpe(100, 0.01) > expected_max_sharpe(10, 0.01) > 0
    assert deflated_sharpe(rng.normal(0, 0.01, 2000), 200).probability < 0.95


def test_pbo_noise_vs_skill():
    rng = np.random.default_rng(4)
    noise = rng.normal(0, 0.01, (1600, 20))
    assert pbo_cscv(noise, 8).pbo > 0.3, "no skill: at or above the coin-flip region"
    skilled = noise.copy()
    skilled[:, 0] += 0.004
    assert pbo_cscv(skilled, 8).pbo < 0.1
    with pytest.raises(ValueError):
        pbo_cscv(noise[:, :1])


def test_walk_forward_efficiency():
    perf = {
        "good": {y: 0.10 for y in range(2004, 2016)},
        "lucky": {y: (0.3 if y < 2008 else -0.05) for y in range(2004, 2016)},
    }
    res = walk_forward(
        list(perf),
        lambda c, a, b: float(np.mean([perf[c][y] for y in range(a, b + 1)])),
        range(2004, 2016),
        train_years=4,
    )
    assert len(res.folds) == 8 and res.folds[0]["chosen"] == "lucky"
    assert res.efficiency < 1.0


def test_parameter_plateau():
    grid = [(10, 14, 20), (1.0, 2.0, 3.0)]
    flat = {(a, b): 0.2 for a in grid[0] for b in grid[1]}
    flat[(14, 2.0)] = 0.25
    spike = {(a, b): 0.02 for a in grid[0] for b in grid[1]}
    spike[(14, 2.0)] = 0.3
    assert plateau(flat, grid).passes() and plateau(
        flat, grid
    ).worst_neighbour_ratio == pytest.approx(0.8)
    assert not plateau(spike, grid).passes()
    assert len(plateau(flat, grid).neighbours) == 4


# -------------------------------------------------------------- monte carlo
def test_bootstrap_and_kill_switch_proposal():
    r = np.r_[np.full(60, 0.012), np.full(40, -0.01)]
    bs = bootstrap(r, n_sims=500, rng=np.random.default_rng(0))
    assert bs.p95_drawdown > 0.05 and bs.p95_streak >= 4
    ks = propose_kill_switch(bs)
    assert ks.threshold is not None and ks.p95 < ks.threshold < 0.35
    awful = bootstrap(np.full(100, -0.01), n_sims=50)
    assert propose_kill_switch(awful).threshold is None


def test_regimes_stress_windows_and_correlation_stress():
    f = regime_walk(1500, seed=2, start="2006-01-02")
    reg = classify_regimes(f)
    assert {"bull", "bear", "chop", "unknown"} >= set(reg.unique()) and {"bull", "bear"} <= set(
        reg.unique()
    )
    es = [
        Entry("X", "s", 1, "standard", t.isoformat(), t.isoformat(), 1.0, 1, 1, 0)
        for t in f.index[250::50]
    ]
    rep = regime_report(es, reg)
    assert sum(v["entries"] for v in rep.values()) == len(es)
    st = stress_report(es)
    assert (
        set(st) == {"2008_gfc", "2015_chf", "2020_covid", "2022_rates"}
        and st["2008_gfc"]["entries"] > 0
    )
    cs = correlation_stress(
        [fx_spec(s) for s in ("EURUSD", "GBPUSD", "AUDUSD", "USDJPY", "EURGBP")], cap=2
    )
    usd = next(c for c in cs if c.currency == "USD")
    assert (
        usd.pairs == 4
        and usd.uncapped_risk == pytest.approx(0.08)
        and usd.capped_risk == pytest.approx(0.04)
    )


# ---------------------------------------------------------------- selection
POOL = {
    "baseline": [SlotSpec(name="kama"), SlotSpec(name="kijun")],
    "confirmation": [
        SlotSpec(name="macd"),
        SlotSpec(name="cmo"),
        SlotSpec(name="vortex"),
        SlotSpec(name="ssl"),
    ],
    "volume": [SlotSpec(name="adx")],
    "exit": [SlotSpec(name="chandelier")],
}


def test_selection_pipeline_is_resumable_without_double_counting(tmp_path: Path):
    frames = list(dev_frames().values())
    ev = evaluator(tmp_path / "research")
    ck = tmp_path / "checkpoint.json"
    pipe = SelectionPipeline(
        CFG,
        POOL,
        ev,
        screening_frames=frames,
        checkpoint=ck,
        shortlist=2,
        random_controls=6,
        run_ablation_stage=False,
    )
    rep = pipe.run()
    n = ev.research.trial_count()
    assert n > 0 and ck.exists() and len(rep.random_expectancies) == 6
    assert 0.0 <= rep.random_percentile <= 1.0 and rep.trial_count == n
    assert next(s.stage for s in rep.stages) == "1 C1 in isolation"
    text = rep.render()
    assert "Random-combination control" in text and "Logged trial count" in text
    # A fresh process on "another machine" resumes from the checkpoint: nothing re-run, nothing re-counted.
    calls = []
    ev2 = evaluator(tmp_path / "research")
    orig = ev2.evaluate
    ev2.evaluate = lambda *a, **k: calls.append(1) or orig(*a, **k)  # type: ignore[method-assign]
    rep2 = SelectionPipeline(
        CFG,
        POOL,
        ev2,
        screening_frames=frames,
        checkpoint=ck,
        shortlist=2,
        random_controls=6,
        run_ablation_stage=False,
    ).run()
    assert not calls and ev2.research.trial_count() == n
    assert rep2.finalist.digest() == rep.finalist.digest()


# ------------------------------------------------------------------ verdict
def _evidence(**kw):
    base = dict(
        market="fx",
        expectancy_ci_lower=0.02,
        n_eff=900,
        expectancy=0.14,
        dsr_probability=0.97,
        dsr_trial_count=120,
        pbo=0.2,
        wfe=0.6,
        mar=0.7,
        bootstrap_p95_dd=0.25,
        random_percentile=0.95,
        stress_ci_lower=0.01,
        stress_expectancy=0.11,
        plateau_ratio=0.7,
        holdout_expectancy=0.09,
        development_expectancy=0.14,
        instrument_breadth=0.7,
        cross_market_consistent=True,
    )
    base.update(kw)
    return Evidence(**base)


TH = json.loads((ROOT / "research/thresholds.frozen.json").read_text())


def test_verdict_passes_only_when_every_criterion_holds():
    v = evaluate(_evidence(), TH, logged_trial_count=120)
    assert v.passed and len(v.rows) == 15
    assert next(r for r in v.rows if r.criterion.startswith("13")).status == "N/A"
    assert "VERDICT: PASS" in v.render()


@pytest.mark.parametrize(
    "kw,crit",
    [
        ({"expectancy_ci_lower": -0.001}, "1_"),
        ({"n_eff": 399}, "2_"),
        ({"expectancy": 0.0999}, "3_"),
        ({"pbo": 0.30}, "5_"),  # a near miss is a fail
        ({"bootstrap_p95_dd": 0.35}, "8_"),
        ({"random_percentile": 0.90}, "9_"),
        ({"stress_expectancy": 0.09}, "10_"),
        ({"holdout_expectancy": 0.06}, "12_"),
        ({"instrument_breadth": 0.6}, "14_"),
        ({"cross_market_consistent": False}, "15_"),
    ],
)
def test_verdict_fails_on_each_threshold(kw, crit):
    v = evaluate(_evidence(**kw), TH, logged_trial_count=120)
    assert not v.passed and next(r for r in v.rows if r.criterion.startswith(crit)).status == "FAIL"


def test_verdict_missing_evidence_and_trial_count_mismatch():
    v = evaluate(_evidence(pbo=None), TH, logged_trial_count=120)
    assert (
        not v.passed and next(r for r in v.rows if r.criterion.startswith("5_")).status == "MISSING"
    )
    v = evaluate(_evidence(dsr_trial_count=40), TH, logged_trial_count=120)
    assert next(r for r in v.rows if r.criterion.startswith("4_")).status == "FAIL"
    crypto = evaluate(
        _evidence(market="crypto", regime_expectancy={"bull": 0.2, "bear": -0.01}),
        TH,
        logged_trial_count=120,
    )
    assert next(r for r in crypto.rows if r.criterion.startswith("13")).status == "FAIL"
    assert next(r for r in crypto.rows if r.criterion.startswith("14")).status == "N/A"
