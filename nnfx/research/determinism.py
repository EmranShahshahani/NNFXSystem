"""Cross-machine determinism against a committed reference run (ticket 08, ADR 08 §3).

A mismatch whose environment fingerprint differs from the reference is an
ENVIRONMENT MISMATCH, not a determinism failure: they are different problems
and confusing them costs days.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nnfx.brokers.costs import CostModel
from nnfx.config import load_system_config
from nnfx.data.synthetic import regime_walk
from nnfx.env import EnvironmentFingerprint, fingerprint
from nnfx.harness.backtest import BacktestHarness
from nnfx.instruments import fx_spec

REFERENCE = Path("tests/golden/reference_run.json")
Status = Literal["OK", "DETERMINISM FAILURE", "ENVIRONMENT MISMATCH", "NO REFERENCE"]


def reference_digest(root: Path = Path(".")) -> str:
    cfg = load_system_config(root / "config/system.yaml")
    frames = {
        "EURUSD": regime_walk(1200, seed=11, symbol="EURUSD", volume_kind="tick"),
        "USDJPY": regime_walk(
            1200, seed=12, symbol="USDJPY", volume_kind="tick", start_price=110.0
        ),
    }
    inst = {s: fx_spec(s) for s in frames}
    costs = CostModel.from_venue(root / "config/venues/backtest.yaml")
    return BacktestHarness(cfg, inst, frames, costs=costs).run().digest()


@dataclass(frozen=True)
class DeterminismCheck:
    status: Status
    detail: str


def write_reference(path: Path = REFERENCE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"digest": reference_digest(), "fingerprint": fingerprint().model_dump(mode="json")},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )


def check(path: Path = REFERENCE) -> DeterminismCheck:
    if not path.exists():
        return DeterminismCheck(
            "NO REFERENCE",
            f"{path} missing; run `nnfx determinism --write-reference` on the reference machine",
        )
    ref = json.loads(path.read_text())
    digest = reference_digest()
    if digest == ref["digest"]:
        return DeterminismCheck("OK", f"reproduced reference run {digest[:16]}")
    ref_fp = EnvironmentFingerprint.model_validate(ref["fingerprint"])
    diffs = fingerprint().differs_from(ref_fp)
    if diffs:
        return DeterminismCheck(
            "ENVIRONMENT MISMATCH",
            "output differs and so does the environment: "
            + "; ".join(diffs[:20])
            + " - run `uv sync --frozen`",
        )
    return DeterminismCheck(
        "DETERMINISM FAILURE",
        f"same environment, different output ({digest[:16]} != {ref['digest'][:16]}): hidden state or non-determinism in the engine",
    )
