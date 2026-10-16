"""Screening Gates 1 and 2 (doc 05 §2): no lookahead, determinism.

Both run against the exact implementation that ships, across every registered
indicator, with no per-indicator test to write. Repainting is an implementation
property, not a property of the concept.

Families needing extra scrutiny under Gate 1:
  * centred or displaced smoothing (e.g. a centred MA, a forward-displaced Ichimoku span)
  * zig-zag and pivot logic (a pivot is only known N bars after it happens)
  * swing high/low reconstruction
  * DSP filters whose published forms are non-causal (zero-phase, filtfilt, Ehlers variants)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nnfx.data.bars import BarFrame
from nnfx.indicators.base import Indicator, SlotKind, create, registered

SCRUTINY_FAMILIES = (
    "centred or displaced smoothing",
    "zig-zag and pivot logic",
    "swing high/low reconstruction",
    "non-causal DSP filters",
)


@dataclass(frozen=True)
class GateOutcome:
    gate: str
    indicator: str
    passed: bool
    first_divergent_bar: int | None = None
    first_divergent_time: str | None = None
    detail: str = ""

    def render(self) -> str:
        where = (
            f" first diverges at bar {self.first_divergent_bar} ({self.first_divergent_time})"
            if not self.passed
            else ""
        )
        return f"{'PASS' if self.passed else 'FAIL'} {self.gate:<12} {self.indicator}{where} {self.detail}".rstrip()


def _same(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if a.dtype.kind == "f" or b.dtype.kind == "f":
        a, b = a.astype("float64"), b.astype("float64")
        both_nan = np.isnan(a) & np.isnan(b)
        close = np.isclose(a, b, rtol=1e-10, atol=0.0)
        out: np.ndarray = both_nan | close
        return out
    return np.asarray(a == b)


def no_lookahead(
    ind: Indicator, bars: BarFrame, *, tail: int = 3, start: int | None = None, stride: int = 1
) -> GateOutcome:
    """Recompute on history truncated at each bar t; tail values must match the full run."""
    full = ind.outputs(bars)
    n = len(bars)
    first = start if start is not None else min(n - 1, 5)
    worst: int | None = None
    for t in range(first, n, stride):
        trunc = ind.outputs(bars.head(t + 1))
        lo = max(0, t + 1 - tail)
        for key, arr in trunc.items():
            ok = _same(arr[lo : t + 1], full[key][lo : t + 1])
            if not ok.all():
                bad = lo + int(np.argmin(ok))
                worst = bad if worst is None else min(worst, bad)
        if worst is not None:
            break
    if worst is None:
        return GateOutcome("no_lookahead", repr(ind), True)
    return GateOutcome(
        "no_lookahead",
        repr(ind),
        False,
        worst,
        str(bars.index[worst]),
        "value at this bar changes when later bars are added (repaint / future leak)",
    )


def output_digest(ind: Indicator, bars: BarFrame) -> str:
    h = hashlib.sha256()
    for key, arr in sorted(ind.outputs(bars).items()):
        h.update(key.encode())
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def determinism_in_process(ind: Indicator, bars: BarFrame, runs: int = 3) -> GateOutcome:
    digests = {output_digest(ind, bars) for _ in range(runs)}
    # A fresh instance must agree too: no state carried on the object.
    digests.add(output_digest(type(ind)(**ind.params), bars))
    ok = len(digests) == 1
    return GateOutcome(
        "determinism",
        repr(ind),
        ok,
        detail="" if ok else f"{len(digests)} distinct outputs across runs",
    )


def determinism_across_processes(
    specs: list[tuple[SlotKind, str]], csv_path: Path
) -> dict[str, str]:
    """Digests computed in a fresh interpreter, to catch state hidden across restarts."""
    code = (
        "import json,sys\n"
        "from nnfx.data.feeds import read_bars_csv\n"
        "from nnfx.indicators.base import create\n"
        "from nnfx.research.lookahead import output_digest\n"
        "b=read_bars_csv(sys.argv[1],'X')\n"
        "specs=json.loads(sys.argv[2])\n"
        "print(json.dumps({f'{k}/{n}':output_digest(create(k,n),b) for k,n in specs}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(csv_path), json.dumps(specs)],
        check=True,
        capture_output=True,
        text=True,
    )
    result: dict[str, str] = json.loads(out.stdout)
    return result


def run_gate_1_2(
    bars: BarFrame, *, stride: int = 1, kinds: tuple[SlotKind, ...] | None = None
) -> list[GateOutcome]:
    out: list[GateOutcome] = []
    for kind, name in registered():
        if kinds and kind not in kinds:
            continue
        ind = create(kind, name)
        out.append(no_lookahead(ind, bars, stride=stride))
        out.append(determinism_in_process(ind, bars))
    return out
