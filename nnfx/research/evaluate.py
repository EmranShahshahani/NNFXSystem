"""Run one configuration on one segment, count it as a trial, return its metrics.

Every research path (ablation, selection stages, random control) goes through
``Evaluator.evaluate`` so no evaluation can escape the trial counter.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.config import SLOT_KIND, SlotSpec, SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.data.gates import ensure_clean
from nnfx.harness.backtest import BacktestHarness, BacktestResult
from nnfx.indicators.base import create
from nnfx.indicators.slots import SlotOutputs
from nnfx.instruments import InstrumentSpec
from nnfx.research.metrics import Metrics, compute_metrics
from nnfx.research.partition import Market, Partition, SegmentName
from nnfx.research.trials import ResearchState

DataProvider = Callable[[SystemConfig], Mapping[str, BarFrame]]


@dataclass
class TrialResult:
    label: str
    config: SystemConfig
    trial_id: str | None
    metrics: Metrics
    result: BacktestResult

    @property
    def score(self) -> float:
        """Selection score: the BCa lower bound, which penalises small-sample flukes."""
        lo = self.metrics.expectancy_ci[0]
        return float(lo) if np.isfinite(lo) else -np.inf

    def row(self) -> dict[str, Any]:
        m = self.metrics
        return {
            "label": self.label,
            "entries": m.n_entries,
            "expectancy_r": round(m.expectancy_r, 4),
            "ci_lo": round(m.expectancy_ci[0], 4) if np.isfinite(m.expectancy_ci[0]) else None,
            "ci_hi": round(m.expectancy_ci[1], 4) if np.isfinite(m.expectancy_ci[1]) else None,
            "win_rate": round(m.win_rate, 4),
            "sharpe": round(m.sharpe, 4),
            "max_dd": round(m.max_drawdown, 4),
            "trial": self.trial_id,
        }


def _spec_key(slot_kind: str, spec: SlotSpec) -> str:
    return f"{slot_kind}/{spec.name}/{json.dumps(spec.params, sort_keys=True)}"


class Evaluator:
    def __init__(
        self,
        instruments: Mapping[str, InstrumentSpec],
        data: DataProvider | Mapping[str, BarFrame],
        *,
        market: Market,
        segment: SegmentName = "development",
        costs: CostModel | None = None,
        research: ResearchState | None = None,
        n_boot: int = 1000,
        seed: int = 0,
        gate_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        if segment == "holdout":
            raise PermissionError(
                "Evaluator never runs on the holdout; use HoldoutGuard explicitly"
            )
        self.instruments = dict(instruments)
        self._data = data
        self.market = market
        self.segment_name: SegmentName = segment
        self.partition = Partition.for_market(market)
        self.costs = costs
        self.research = research
        self.n_boot = n_boot
        self.seed = seed
        self.gate_kwargs = dict(gate_kwargs or {})
        self._frames: dict[str, dict[str, BarFrame]] = {}
        self._ind_cache: dict[tuple[str, str, str], dict[str, np.ndarray]] = {}

    def frames(self, config: SystemConfig) -> dict[str, BarFrame]:
        key = config.session.model_dump_json()
        if key not in self._frames:
            raw = self._data(config) if callable(self._data) else self._data
            seg = self.partition.get(self.segment_name)
            out = {}
            for s, f in sorted(raw.items()):
                ensure_clean(
                    f, self.instruments[s], close_tz=config.session.close_tz, **self.gate_kwargs
                )
                out[s] = f.between(None, seg.end)
            self._frames[key] = out
        return self._frames[key]

    def _outputs(
        self, config: SystemConfig, frames: Mapping[str, BarFrame]
    ) -> dict[str, SlotOutputs]:
        res: dict[str, SlotOutputs] = {}
        sess = config.session.model_dump_json()
        for sym, f in frames.items():
            per: dict[str, dict[str, np.ndarray]] = {}
            for slot in ("atr", "baseline", "c1", "c2", "volume", "exit", "continuation"):
                spec = getattr(config.slots, slot)
                if spec is None:
                    continue
                kind = SLOT_KIND[slot]
                k = (sym, sess, _spec_key(kind, spec))
                if k not in self._ind_cache:
                    self._ind_cache[k] = create(kind, spec.name, spec.params).outputs(f)  # type: ignore[arg-type]
                per[slot] = self._ind_cache[k]

            def g(
                slot: str, key: str, per: dict[str, dict[str, np.ndarray]] = per
            ) -> np.ndarray | None:
                return per[slot][key] if slot in per else None

            res[sym] = SlotOutputs(
                atr=per["atr"]["value"],
                baseline=per["baseline"]["line"],
                c1_signal=per["c1"]["signal"],
                c1_state=per["c1"]["state"],
                c2_signal=g("c2", "signal"),
                c2_state=g("c2", "state"),
                volume_gate=g("volume", "gate"),
                exit=g("exit", "exit"),
                cont_signal=g("continuation", "signal"),
                cont_state=g("continuation", "state"),
            )
        return res

    def evaluate(self, config: SystemConfig, *, stage: str, label: str = "") -> TrialResult:
        frames = self.frames(config)
        seg = self.partition.get(self.segment_name)
        harness = BacktestHarness(
            config,
            {s: self.instruments[s] for s in frames},
            frames,
            costs=self.costs,
            start=seg.start,
            end=seg.end,
            run_gates=False,
            outputs=self._outputs(config, frames),
        )
        result = harness.run()
        closes = {s: pd.Series(f.close, index=f.index) for s, f in frames.items()}
        metrics = compute_metrics(
            result.trades,
            result.equity,
            closes=closes,
            rng=np.random.default_rng(self.seed),
            n_boot=self.n_boot,
            volume_flags=result.volume_flags,
        )
        tid = None
        if self.research is not None:
            tid = self.research.record_trial(
                config,
                market=self.market,
                segment=self.segment_name,
                symbols=list(frames),
                stage=stage,
                metrics={
                    "expectancy_r": metrics.expectancy_r,
                    "sharpe": metrics.sharpe,
                    "entries": metrics.n_entries,
                },
            )
        return TrialResult(label or config.digest(), config, tid, metrics, result)
