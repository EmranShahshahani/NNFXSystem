"""Trial counter, validation-pass log and the touch-once holdout (doc 03 §3, §5.2; ADR 08 §2).

* The trial count is **derived**: distinct trial ids in ``research/trials.jsonl``.
  A trial id is a hash of (config, data scope), so re-running the same
  configuration on the same data - on any workstation, or after resuming a
  checkpoint - never double-counts.
* Every pass over the validation segment is logged. A long log means the
  segment has been contaminated by iteration and must be discounted.
* The holdout is touched exactly once, ever. The first touch is logged; any
  later attempt raises, whichever workstation makes it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from nnfx.config import SystemConfig
from nnfx.env import fingerprint, workstation_id
from nnfx.research.logs import (
    HOLDOUT_LOG,
    RESEARCH_DIR,
    TRIALS_LOG,
    VALIDATION_LOG,
    AppendOnlyLog,
    canonical_json,
)
from nnfx.research.partition import _HOLDOUT_TOKEN, HoldoutAccessError, Market, SegmentName

THRESHOLDS_FILE = "thresholds.frozen.json"


def trial_id(config: SystemConfig, scope: Mapping[str, Any]) -> str:
    payload = canonical_json({"config": config.model_dump(mode="json"), "scope": dict(scope)})
    return "t_" + hashlib.sha256(payload.encode()).hexdigest()[:20]


class ResearchState:
    def __init__(self, root: Path = RESEARCH_DIR) -> None:
        self.root = Path(root)
        self.trials = AppendOnlyLog(self.root / TRIALS_LOG)
        self.validation = AppendOnlyLog(self.root / VALIDATION_LOG)
        self.holdout = AppendOnlyLog(self.root / HOLDOUT_LOG)

    # ---------------------------------------------------------------- trials
    def record_trial(
        self,
        config: SystemConfig,
        *,
        market: Market,
        segment: SegmentName,
        symbols: Sequence[str],
        stage: str,
        metrics: Mapping[str, Any] | None = None,
    ) -> str:
        if segment == "holdout":
            raise HoldoutAccessError("holdout runs are not trials; use HoldoutGuard")
        scope = {"market": market, "segment": segment, "symbols": sorted(symbols)}
        tid = trial_id(config, scope)
        if tid not in self.trials.distinct():
            self.trials.append(
                {
                    "id": tid,
                    "stage": stage,
                    "config": config.digest(),
                    **scope,
                    "metrics": dict(metrics or {}),
                }
            )
        if segment == "validation":
            self.log_validation_pass(tid, stage)
        return tid

    def trial_count(self) -> int:
        return self.trials.count()

    def trial_sharpes(self) -> list[float]:
        out = []
        for rec in self.trials.distinct().values():
            s = rec.get("metrics", {}).get("sharpe")
            if isinstance(s, (int, float)):
                out.append(float(s))
        return out

    # ------------------------------------------------------------ validation
    def log_validation_pass(self, trial: str, purpose: str) -> None:
        n = self.validation.count() + 1
        self.validation.append(
            {"id": f"v_{trial}_{purpose}", "trial": trial, "purpose": purpose, "pass_number": n}
        )

    def validation_passes(self) -> int:
        return self.validation.count()

    # --------------------------------------------------------------- holdout
    def touch_holdout(self, market: Market, config: SystemConfig, reason: str) -> object:
        """Return the one-time holdout token. Raises if this market's holdout was ever touched."""
        prior = [r for r in self.holdout.distinct().values() if r.get("market") == market]
        if prior:
            p = prior[0]
            raise HoldoutAccessError(
                f"the {market} holdout was already touched by {p.get('workstation')} "
                f"(config {p.get('config')}, reason {p.get('reason')!r}). It is touched exactly once, ever."
            )
        self.holdout.append(
            {
                "id": f"h_{market}",
                "market": market,
                "config": config.digest(),
                "reason": reason,
                "workstation": workstation_id(),
            }
        )
        return _HOLDOUT_TOKEN

    # ----------------------------------------------------------- thresholds
    def thresholds(self) -> dict[str, Any]:
        path = self.root / THRESHOLDS_FILE
        data: dict[str, Any] = json.loads(path.read_text())
        if data.get("status") != "frozen":
            raise ValueError(f"{path} is not frozen; thresholds must be pre-registered (doc 03 §8)")
        return data


def env_line() -> dict[str, str]:
    return {"workstation": workstation_id(), "env": fingerprint().digest}
