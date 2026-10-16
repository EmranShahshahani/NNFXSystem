"""Append-only, union-mergeable research logs (ADR 08 §2).

Every line is a JSON object with a unique ``id``. Counts are always *derived*
by counting distinct ids - there is no counter file two machines could each
overwrite. Union merge may leave duplicate lines after an awkward merge;
``reconcile`` removes them and reports who contributed what.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nnfx.env import fingerprint, workstation_id

RESEARCH_DIR = Path("research")
TRIALS_LOG = "trials.jsonl"
VALIDATION_LOG = "validation_passes.jsonl"
HOLDOUT_LOG = "holdout_touches.jsonl"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AppendOnlyLog:
    """A JSONL file that is only ever appended to."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if "id" not in record:
            raise ValueError("every research log line needs a unique 'id'")
        line = dict(record)
        line.setdefault("workstation", workstation_id())
        line.setdefault("env", fingerprint().digest)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical_json(line) + "\n")
        return line

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for n, raw in enumerate(fh, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{self.path}:{n}: corrupt line ({exc})") from exc
                yield rec

    def distinct(self) -> dict[str, dict[str, Any]]:
        """First occurrence of each id, in file order."""
        seen: dict[str, dict[str, Any]] = {}
        for rec in self.records():
            seen.setdefault(str(rec["id"]), rec)
        return seen

    def count(self) -> int:
        return len(self.distinct())


@dataclass(frozen=True)
class ReconcileReport:
    path: Path
    lines_before: int
    distinct: int
    duplicates_removed: int
    per_workstation: dict[str, int]

    def render(self) -> str:
        per = ", ".join(f"{k}={v}" for k, v in sorted(self.per_workstation.items())) or "none"
        return (
            f"{self.path}: {self.distinct} distinct ids "
            f"({self.duplicates_removed} duplicate lines removed); by workstation: {per}"
        )


def reconcile(path: Path, write: bool = True) -> ReconcileReport:
    """Dedupe one log by id (keeping first occurrence) and count contributions."""
    log = AppendOnlyLog(path)
    records = list(log.records())
    distinct = log.distinct()
    per = Counter(str(r.get("workstation", "unknown")) for r in distinct.values())
    if write and len(records) != len(distinct):
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            for rec in distinct.values():
                fh.write(canonical_json(rec) + "\n")
        tmp.replace(path)
    return ReconcileReport(
        path=path,
        lines_before=len(records),
        distinct=len(distinct),
        duplicates_removed=len(records) - len(distinct),
        per_workstation=dict(per),
    )


def reconcile_all(research_dir: Path = RESEARCH_DIR, write: bool = True) -> list[ReconcileReport]:
    return [reconcile(p, write=write) for p in sorted(research_dir.glob("*.jsonl"))]
