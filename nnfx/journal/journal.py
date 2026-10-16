"""Append-only decision journal.

Every evaluation records the inputs it saw, the indicator values it computed,
the state before and after, and the intents it produced. Every record carries
the environment fingerprint digest; the full fingerprint is written once per
run in an ``environment`` record. Records contain no wall-clock time unless a
clock is injected, so a backtest journal is byte-identical across runs.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nnfx.env import fingerprint


def _default(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"not journal-serialisable: {type(o)}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default, allow_nan=False)


class Journal:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._mem: list[str] = []
        self._seq = 0
        if self.path is not None and self.path.exists():
            for rec in self.records():
                self._seq = max(self._seq, int(rec.get("seq", 0)))
        self._env = fingerprint()

    def start_run(self, **meta: Any) -> None:
        self.append(
            {"type": "environment", "fingerprint": self._env.model_dump(mode="json"), **meta}
        )

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        rec = {"seq": self._seq, "env": self._env.digest, **record}
        line = dumps(rec)
        if self.path is None:
            self._mem.append(line)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
        return rec

    def lines(self) -> list[str]:
        if self.path is None:
            return list(self._mem)
        if not self.path.exists():
            return []
        return [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def records(self, type_: str | None = None) -> Iterator[dict[str, Any]]:
        for ln in self.lines():
            rec: dict[str, Any] = json.loads(ln)
            if type_ is None or rec.get("type") == type_:
                yield rec

    def last(self, type_: str) -> dict[str, Any] | None:
        out = None
        for rec in self.records(type_):
            out = rec
        return out

    def text(self) -> str:
        return "".join(ln + "\n" for ln in self.lines())
