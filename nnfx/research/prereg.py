"""Pre-registration files (``research/*.frozen.json``) and their trial budgets (T30).

A pre-registration freezes a hypothesis - its rules, canonical parameters,
ablation list and trial budget - before any price data is seen. This module
only reads and checks; nothing here can write a frozen file.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

from nnfx.research.trials import ResearchState


class PreregError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def canonical_digest(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _rule_refs(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "rule" and isinstance(v, str):
                yield v
            elif k == "rules" and isinstance(v, list):
                yield from (r for r in v if isinstance(r, str))
            else:
                yield from _rule_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _rule_refs(v)


def planned_trials(group: Mapping[str, Any]) -> int:
    """Canonical run plus one trial per ablation (or risk-layer) value."""
    rows = group.get("ablations", group.get("variants", []))
    extra = sum(len(r.get("values", [None])) for r in rows)
    return extra + (1 if "canonical" in group else 0)


class Prereg:
    def __init__(self, path: Path | str, root: Path | str = ".") -> None:
        self.path = Path(path)
        self.root = Path(root)
        self.data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        self.validate()

    @property
    def digest(self) -> str:
        return canonical_digest(self.data)

    def ledger_ids(self) -> set[str]:
        ledger = yaml.safe_load((self.root / self.data["ledger"]).read_text(encoding="utf-8"))
        return {r["id"] for r in ledger["rules"]}

    def validate(self) -> None:
        d = self.data
        if d.get("status") != "frozen":
            raise PreregError(f"{self.path} is not frozen")
        ledger = self.root / d["ledger"]
        got = hashlib.sha256(ledger.read_bytes()).hexdigest()
        if got != d["ledger_sha256"]:
            raise PreregError(
                f"{ledger} changed after the pre-registration was frozen ({got[:12]} != {d['ledger_sha256'][:12]})"
            )
        ids = self.ledger_ids()
        refs = set(_rule_refs(d["hypotheses"])) | set(d.get("excluded", {}))
        unknown = sorted(refs - ids)
        if unknown:
            raise PreregError(f"rules not in the ledger: {unknown}")
        b = d["trial_budget"]
        groups = [k for k in d["hypotheses"]]
        if sum(b[g] for g in groups) != b["total"]:
            raise PreregError("trial budgets do not add up to the total")
        for g in groups:
            n = planned_trials(d["hypotheses"][g])
            if n > b[g]:
                raise PreregError(f"{g} plans {n} trials but its budget is {b[g]}")

    def remaining(self, research: ResearchState, group: str) -> int:
        budget = int(self.data["trial_budget"][group])
        used = sum(
            1
            for r in research.trials.distinct().values()
            if str(r.get("stage", "")).split("/")[0] == group
        )
        return budget - used

    def require_budget(self, research: ResearchState, group: str) -> None:
        if self.remaining(research, group) <= 0:
            raise BudgetExceeded(
                f"{group}: trial budget of {self.data['trial_budget'][group]} is spent; "
                "a further run is a new hypothesis with its own pre-registration"
            )
