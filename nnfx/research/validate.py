"""Assemble the verdict evidence for a finalist from one command (doc 03 §5-§8).

Every performance number in the evidence comes from a counted trial on the
development or validation segment, except criterion 12, which needs the
one-time holdout touch and only runs when explicitly asked for. Criterion 15
(cross-market consistency) needs a run in the other market and is passed in.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nnfx.config import SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.data.gates import ensure_clean
from nnfx.harness.backtest import BacktestHarness
from nnfx.indicators.base import create
from nnfx.research.evaluate import Evaluator, TrialResult
from nnfx.research.metrics import compute_metrics, entries_from_trades
from nnfx.research.montecarlo import bootstrap, classify_regimes, regime_report, trade_returns
from nnfx.research.overfitting import deflated_sharpe, pbo_cscv, walk_forward
from nnfx.research.partition import Partition
from nnfx.research.selection import SLOT_KINDS, sweep_neighbourhood
from nnfx.research.verdict import Evidence


@dataclass
class ValidationReport:
    evidence: Evidence
    details: dict[str, Any] = field(default_factory=dict)

    def evidence_json(self) -> str:
        return json.dumps(asdict(self.evidence), indent=1, sort_keys=True, default=float)


def _daily_returns(t: TrialResult) -> pd.Series:
    eq = t.result.equity
    return eq.pct_change().dropna() if len(eq) > 1 else pd.Series(dtype="float64")


def _load_checkpoint(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    data: dict[str, Any] = json.loads(Path(path).read_text())
    return data


def _candidates(
    ck: Mapping[str, Any], *, exclude_random: bool = True
) -> list[tuple[float, SystemConfig]]:
    out = []
    for row in ck.get("evaluated", {}).values():
        if exclude_random and str(row.get("label", "")).startswith("random#"):
            continue
        score = row.get("score")
        s = float(score) if isinstance(score, (int, float)) and np.isfinite(score) else -np.inf
        out.append((s, SystemConfig.model_validate(row["config"])))
    out.sort(key=lambda x: (-x[0], x[1].digest()))
    return out


def run_validation(
    finalist: SystemConfig,
    dev: Evaluator,
    val: Evaluator,
    *,
    checkpoint: Path | None = None,
    pbo_max_configs: int = 30,
    wf_candidates: int = 5,
    wf_train_years: int = 4,
    plateau_slots: Sequence[str] = ("c1", "baseline"),
    cost_stress: float = 1.5,
    risk_per_position: float | None = None,
    touch_holdout: str | None = None,
    raw_frames: Mapping[str, BarFrame] | None = None,
    cross_market_consistent: bool | None = None,
    seed: int = 0,
) -> ValidationReport:
    if dev.segment_name != "development" or val.segment_name != "validation":
        raise ValueError("dev must be the development evaluator and val the validation evaluator")
    if dev.market != val.market:
        raise ValueError("dev and val evaluators must be for the same market")
    research = val.research
    market = val.market
    part = Partition.for_market(market)
    details: dict[str, Any] = {}
    ev = Evidence(market=market, cross_market_consistent=cross_market_consistent)
    risk = risk_per_position if risk_per_position is not None else finalist.risk.risk_per_position

    # 1-3, 7, 8: the finalist on validation.
    dev_t = dev.evaluate(finalist, stage="validate/development", label="finalist dev")
    val_t = val.evaluate(finalist, stage="validate/validation", label="finalist val")
    m = val_t.metrics
    ev.expectancy_ci_lower = float(m.expectancy_ci[0])
    ev.expectancy = m.expectancy_r
    ev.n_eff = m.n_eff
    ev.mar = m.mar
    entries = entries_from_trades(val_t.result.trades)
    ev.bootstrap_p95_dd = bootstrap(
        trade_returns(entries, risk), rng=np.random.default_rng(seed)
    ).p95_drawdown
    ev.development_expectancy = dev_t.metrics.expectancy_r
    details["validation"] = val_t.row()
    details["development"] = dev_t.row()

    # 10: cost stress on validation.
    stressed = finalist.with_overrides(
        {"costs.stress_multiplier": finalist.costs.stress_multiplier * cost_stress}
    )
    st = val.evaluate(stressed, stage="validate/cost_stress", label=f"costs x{cost_stress}")
    ev.stress_ci_lower = float(st.metrics.expectancy_ci[0])
    ev.stress_expectancy = st.metrics.expectancy_r

    ck = _load_checkpoint(checkpoint)
    cands = _candidates(ck)

    # 9: random control (from the selection run's own random configurations).
    rnd = [
        float(r["expectancy_r"])
        for r in ck.get("evaluated", {}).values()
        if str(r.get("label", "")).startswith("random#")
    ]
    if rnd:
        ev.random_percentile = float(np.mean(np.array(rnd) < dev_t.metrics.expectancy_r))
        details["random_control"] = {"n": len(rnd), "p90": float(np.quantile(rnd, 0.9))}

    # 5: PBO over the configurations the selection compared, on development.
    pbo_cfgs = [finalist] + [c for _, c in cands if c.digest() != finalist.digest()]
    pbo_cfgs = pbo_cfgs[:pbo_max_configs]
    if len(pbo_cfgs) >= 2:
        series = {
            f"c{k}": _daily_returns(dev.evaluate(c, stage="validate/pbo"))
            for k, c in enumerate(pbo_cfgs)
        }
        mat = pd.DataFrame(series).fillna(0.0)
        if len(mat) >= 32:
            blocks = 16 if len(mat) >= 160 else 8
            res = pbo_cscv(mat.to_numpy(), n_blocks=blocks)
            ev.pbo = res.pbo
            details["pbo"] = {"configs": len(pbo_cfgs), "splits": res.n_splits}

    # 6: walk-forward across development + validation years.
    others = [c for _, c in cands if c.digest() != finalist.digest()]
    wf_cfgs = [finalist, *others[: wf_candidates - 1]]
    span_start, span_end = part.development.start, part.validation.end
    yearly: dict[int, dict[int, float]] = {}
    for k, c in enumerate(wf_cfgs):
        t = val.evaluate_window(c, span_start, span_end, stage="validate/walk_forward")
        by_year: dict[int, list[float]] = {}
        for e in entries_from_trades(t.result.trades):
            by_year.setdefault(pd.Timestamp(e.entry_time).year, []).append(e.r)
        yearly[k] = {y: float(np.sum(v)) for y, v in by_year.items()}
    years = list(range(span_start.year, span_end.year + 1))

    def wf_eval(c: object, y0: int, y1: int) -> float:
        ys = range(y0, y1 + 1)
        return float(np.mean([yearly[int(c)].get(y, 0.0) for y in ys]))  # type: ignore[call-overload]

    wf = walk_forward(list(range(len(wf_cfgs))), wf_eval, years, train_years=wf_train_years)
    if np.isfinite(wf.efficiency):
        ev.wfe = wf.efficiency
    details["walk_forward"] = {"folds": len(wf.folds), "candidates": len(wf_cfgs)}

    # 11: plateau around the finalist, worst slot.
    ratios = {}
    for slot in plateau_slots:
        spec = getattr(finalist.slots, slot, None)
        if spec is None or not create(SLOT_KINDS[slot], spec.name, spec.params).grid:  # type: ignore[arg-type]
            continue
        res, _ = sweep_neighbourhood(finalist, slot, dev)
        if res.neighbours:
            ratios[slot] = res.worst_neighbour_ratio
    if ratios:
        ev.plateau_ratio = float(min(ratios.values()))
        details["plateau"] = ratios

    # 13 (crypto): expectancy by regime; 14 (fx): share of profitable instruments.
    if market == "crypto":
        frames = val.frames(finalist)
        pooled: dict[str, list[float]] = {}
        for sym, f in frames.items():
            sym_entries = [e for e in entries if e.symbol == sym]
            for name, row in regime_report(sym_entries, classify_regimes(f)).items():
                pooled.setdefault(name, []).extend([row["expectancy_r"]] * int(row["entries"]))
        ev.regime_expectancy = {k: float(np.mean(v)) for k, v in pooled.items() if v}
    if market == "fx" and m.per_symbol:
        ev.instrument_breadth = float(
            np.mean([v["expectancy_r"] > 0 for v in m.per_symbol.values()])
        )

    # 12: the one-time holdout touch, only on explicit request.
    if touch_holdout:
        if research is None or raw_frames is None:
            raise ValueError("touching the holdout needs a ResearchState and the raw frames")
        research.touch_holdout(market, finalist, touch_holdout)
        hseg = part.holdout
        frames = {}
        for s, f in sorted(raw_frames.items()):
            ensure_clean(
                f, val.instruments[s], close_tz=finalist.session.close_tz, **val.gate_kwargs
            )
            frames[s] = f.between(None, hseg.end)
        hres = BacktestHarness(
            finalist,
            {s: val.instruments[s] for s in frames},
            frames,
            costs=val.costs,
            start=hseg.start,
            end=hseg.end,
            run_gates=False,
        ).run()
        hm = compute_metrics(hres.trades, hres.equity, rng=np.random.default_rng(seed), n_boot=200)
        ev.holdout_expectancy = hm.expectancy_r
        details["holdout"] = {"entries": hm.n_entries, "expectancy_r": hm.expectancy_r}

    # 4: deflated Sharpe against the trial count as it stands after all of the above.
    if research is not None:
        n = research.trial_count()
        # Trials log annualised Sharpe; the DSR works per period, like the returns it is given.
        per_period = [x / np.sqrt(252.0) for x in research.trial_sharpes()]
        dsr = deflated_sharpe(_daily_returns(val_t).to_numpy(), n, trial_sharpes=per_period)
        ev.dsr_probability = dsr.probability
        ev.dsr_trial_count = n
        details["dsr"] = {"sr": dsr.sr, "sr0": dsr.sr0, "trials": n}
    return ValidationReport(ev, details)
