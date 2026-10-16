"""Staged selection pipeline and the random-combination control (doc 05 §10, ticket 25).

Staged reduction, never exhaustive search. Every evaluation is a counted trial.
The run is checkpointed after every evaluation and is resumable on another
machine: completed evaluations are reloaded from the checkpoint and trial ids
are content hashes, so a resume can neither restart nor double-count (ADR 08 §4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from nnfx.config import SlotSpec, SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.indicators.base import create
from nnfx.research.ablation import AblationReport, run_ablation
from nnfx.research.evaluate import Evaluator, TrialResult
from nnfx.research.lookahead import determinism_in_process, no_lookahead
from nnfx.research.screening import gate3, gate4, gate5

Pool = Mapping[
    str, Sequence[SlotSpec]
]  # slot kind name ("baseline", "confirmation", ...) -> candidates


def _label(spec: SlotSpec | None) -> str:
    if spec is None:
        return "none"
    return spec.name + (json.dumps(spec.params, sort_keys=True) if spec.params else "")


@dataclass
class StageRecord:
    stage: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    chosen: list[str] = field(default_factory=list)


@dataclass
class SelectionReport:
    finalist: SystemConfig
    finalist_score: float
    finalist_expectancy: float
    stages: list[StageRecord]
    random_expectancies: list[float]
    random_percentile: float
    trial_count: int | None
    ablation: AblationReport | None = None
    screened_out: list[str] = field(default_factory=list)

    def render(self) -> str:
        out = ["# Selection report", ""]
        for st in self.stages:
            out += [
                f"## {st.stage}",
                "",
                "| label | entries | E[R] | BCa lo | BCa hi | trial |",
                "|---|---|---|---|---|---|",
            ]
            for r in st.rows:
                out.append(
                    f"| {r['label']} | {r['entries']} | {r['expectancy_r']} | {r['ci_lo']} | {r['ci_hi']} | {r['trial']} |"
                )
            out += ["", f"chosen: {', '.join(st.chosen)}", ""]
        rnd = np.array(self.random_expectancies)
        p90 = float(np.quantile(rnd, 0.9)) if len(rnd) else float("nan")
        out += [
            "## Random-combination control",
            "",
            f"{len(rnd)} random configurations; 90th percentile E[R] = {p90:+.3f}; "
            f"finalist E[R] = {self.finalist_expectancy:+.3f} sits at the {self.random_percentile:.0%} percentile.",
            "",
            f"Screened out before any performance test: {', '.join(self.screened_out) or 'none'}",
            f"Logged trial count: {self.trial_count}",
        ]
        if self.ablation is not None:
            out += ["", "## Rule ablation on the finalist", "", self.ablation.render()]
        return "\n".join(out)


class Checkpoint:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, Any] = {"evaluated": {}, "stages": {}}
        if path is not None and path.exists():
            self.data = json.loads(path.read_text())

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, sort_keys=True, indent=1))
        tmp.replace(self.path)


class SelectionPipeline:
    def __init__(
        self,
        base: SystemConfig,
        pool: Pool,
        evaluator: Evaluator,
        *,
        screening_frames: Sequence[BarFrame],
        checkpoint: Path | None = None,
        shortlist: int = 5,
        random_controls: int = 100,
        seed: int = 0,
        lookahead_stride: int = 25,
        run_ablation_stage: bool = True,
    ) -> None:
        self.base = base
        self.pool = {k: list(v) for k, v in pool.items()}
        self.ev = evaluator
        self.frames = list(screening_frames)
        self.ck = Checkpoint(checkpoint)
        self.shortlist = shortlist
        self.n_random = random_controls
        self.seed = seed
        self.stride = lookahead_stride
        self.run_ablation_stage = run_ablation_stage
        self.screened_out: list[str] = []

    # ------------------------------------------------------------ evaluation
    def _eval(self, cfg: SystemConfig, stage: str, label: str) -> dict[str, Any]:
        key = cfg.digest()
        done = self.ck.data["evaluated"].get(key)
        if done is not None:
            return dict(done)
        t: TrialResult = self.ev.evaluate(cfg, stage=stage, label=label)
        row = t.row() | {"score": t.score, "config": cfg.model_dump(mode="json")}
        self.ck.data["evaluated"][key] = row
        self.ck.save()
        return row

    @staticmethod
    def _score(row: Mapping[str, Any]) -> float:
        s = row.get("score")
        return float(s) if isinstance(s, (int, float)) and np.isfinite(s) else -np.inf

    def _stage(
        self, name: str, configs: list[tuple[str, SystemConfig]], keep: int
    ) -> tuple[StageRecord, list[SystemConfig]]:
        rows = [self._eval(c, name, lbl) for lbl, c in configs]
        order = sorted(range(len(rows)), key=lambda i: (-self._score(rows[i]), rows[i]["label"]))
        chosen = order[:keep]
        rec = StageRecord(name, rows, [rows[i]["label"] for i in chosen])
        self.ck.data["stages"][name] = {"chosen": rec.chosen}
        self.ck.save()
        return rec, [configs[i][1] for i in chosen]

    # -------------------------------------------------------------- screening
    def screen(self) -> None:
        """Stage 0: Gates 1, 2, 3, 5 - pass/fail, no performance data touched."""
        if not self.frames:
            return
        f0 = self.frames[0]
        kinds = {
            "baseline": "baseline",
            "confirmation": "confirmation",
            "volume": "volume",
            "exit": "exit",
        }
        for slot, kind in kinds.items():
            keep = []
            for spec in self.pool.get(slot, []):
                ind = create(kind, spec.name, spec.params)  # type: ignore[arg-type]
                ok = (
                    no_lookahead(ind, f0, stride=self.stride).passed
                    and determinism_in_process(ind, f0).passed
                )
                ok = ok and gate5(ind, f0).passed
                if ok and slot == "confirmation":
                    ok = gate3(ind, self.frames).passed
                if ok:
                    keep.append(spec)
                else:
                    self.screened_out.append(f"{slot}/{_label(spec)}")
            self.pool[slot] = keep

    # -------------------------------------------------------------------- run
    def run(self) -> SelectionReport:
        self.screen()
        isolate = {
            "slots.c2": None,
            "slots.volume": None,
            "slots.exit": None,
            "slots.continuation": None,
            "rules.baseline_filter": False,
            "rules.exit_on_baseline_cross": False,
            "rules.baseline_entries": False,
            "rules.pullback": False,
            "rules.continuation": False,
            "rules.bridge_too_far": False,
        }
        stages: list[StageRecord] = []
        b = self.base
        # Stage 1-2: C1 in isolation against the naked ATR exit; shortlist by BCa lower bound.
        c1s = [
            (f"c1={_label(s)}", b.with_overrides({**isolate, "slots.c1": s.model_dump()}))
            for s in self.pool["confirmation"]
        ]
        rec, short = self._stage("1 C1 in isolation", c1s, self.shortlist)
        stages.append(rec)
        short_c1 = [c.slots.c1 for c in short]
        # Stage 3: baseline sweep against each shortlisted C1 (full NNFX rules, no C2/volume/exit yet).
        bare = {"slots.c2": None, "slots.volume": None, "slots.exit": None}
        cands = [
            (
                f"c1={_label(c1)} baseline={_label(bl)}",
                b.with_overrides(
                    {**bare, "slots.c1": c1.model_dump(), "slots.baseline": bl.model_dump()}
                ),
            )
            for c1 in short_c1
            for bl in self.pool["baseline"]
        ]
        rec, best = self._stage("3 baseline sweep", cands, 1)
        stages.append(rec)
        cur = best[0]
        # Stage 4: C2 sweep, Gate-4 filtered against the chosen C1 (development segment only).
        dev = self.ev.partition.development
        c1_ind = create("confirmation", cur.slots.c1.name, cur.slots.c1.params)
        c2_ok = []
        for s in self.pool["confirmation"]:
            if s == cur.slots.c1:
                continue
            row = gate4(c1_ind, create("confirmation", s.name, s.params), self.frames, dev)
            if row.passed:
                c2_ok.append(s)
            else:
                self.screened_out.append(f"c2/{_label(s)} ({row.measured})")
        cands = [
            (f"c2={_label(s)}", cur.with_overrides({"slots.c2": s.model_dump()})) for s in c2_ok
        ] + [("c2=none", cur)]
        rec, best = self._stage("4 C2 sweep (Gate-4 filtered)", cands, 1)
        stages.append(rec)
        cur = best[0]
        # Stage 5: volume gate sweep.
        cands = [
            (f"volume={_label(s)}", cur.with_overrides({"slots.volume": s.model_dump()}))
            for s in self.pool["volume"]
        ] + [("volume=none", cur)]
        rec, best = self._stage("5 volume sweep", cands, 1)
        stages.append(rec)
        cur = best[0]
        # Stage 6: exit sweep jointly with the trailing stop on/off.
        exits: list[SlotSpec | None] = [*self.pool["exit"], None]
        cands = [
            (
                f"exit={_label(s)} trail={'on' if tr else 'off'}",
                cur.with_overrides(
                    {"slots.exit": s.model_dump() if s else None, "risk.trailing": tr}
                ),
            )
            for s in exits
            for tr in (True, False)
        ]
        rec, best = self._stage("6 exit x trailing sweep", cands, 1)
        stages.append(rec)
        finalist = best[0]
        fin_row = self._eval(finalist, "finalist", "finalist")
        # Stage 7: ablation on the finalist.
        abl = (
            run_ablation(
                finalist,
                self.ev,
                rules=[
                    "bridge_too_far",
                    "seven_candle_rule",
                    "continuation",
                    "c2_requirement",
                    "position_split",
                    "one_candle_rule",
                ],
                include_exit_trailing=False,
            )
            if self.run_ablation_stage
            else None
        )
        # Stage 8: random-combination control.
        rnd = self.random_control()
        fin_e = float(fin_row["expectancy_r"])
        pct = float(np.mean(np.array(rnd) < fin_e)) if rnd else float("nan")
        research = self.ev.research
        return SelectionReport(
            finalist=finalist,
            finalist_score=self._score(fin_row),
            finalist_expectancy=fin_e,
            stages=stages,
            random_expectancies=rnd,
            random_percentile=pct,
            trial_count=research.trial_count() if research is not None else None,
            ablation=abl,
            screened_out=self.screened_out,
        )

    def random_control(self) -> list[float]:
        """~100 configurations assembled at random from the same (screened) pool."""
        rng = np.random.default_rng(self.seed + 7919)

        def pick(xs: Sequence[SlotSpec]) -> SlotSpec:
            return xs[int(rng.integers(0, len(xs)))]

        out = []
        for k in range(self.n_random):
            c1 = pick(self.pool["confirmation"])
            c2_pool = [s for s in self.pool["confirmation"] if s != c1]
            ov: dict[str, Any] = {
                "slots.c1": c1.model_dump(),
                "slots.baseline": pick(self.pool["baseline"]).model_dump(),
                "slots.c2": pick(c2_pool).model_dump() if c2_pool else None,
                "slots.volume": pick(self.pool["volume"]).model_dump()
                if self.pool["volume"]
                else None,
                "slots.exit": pick(self.pool["exit"]).model_dump() if self.pool["exit"] else None,
            }
            row = self._eval(self.base.with_overrides(ov), "random_control", f"random#{k}")
            out.append(float(row["expectancy_r"]))
        return out
