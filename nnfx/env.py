"""Environment fingerprint and workstation identity (ADR 08 §3).

The fingerprint is Python version plus the resolved version of every installed
distribution. It is a stable, serialisable value: identical lockfile installs
produce identical fingerprints, so a determinism failure can be told apart from
an environment mismatch.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from functools import lru_cache
from importlib import metadata

from pydantic import BaseModel, ConfigDict

# Installer plumbing that can differ between otherwise identical environments.
_IGNORED = frozenset({"pip", "setuptools", "wheel", "uv", "nnfx"})


class EnvironmentFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    python: str
    implementation: str
    packages: tuple[tuple[str, str], ...]

    @property
    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def differs_from(self, other: EnvironmentFingerprint) -> list[str]:
        """Human-readable list of what differs, for ENVIRONMENT MISMATCH reports."""
        diffs: list[str] = []
        if self.python != other.python:
            diffs.append(f"python {other.python} -> {self.python}")
        mine, theirs = dict(self.packages), dict(other.packages)
        for name in sorted(set(mine) | set(theirs)):
            if mine.get(name) != theirs.get(name):
                diffs.append(f"{name} {theirs.get(name, '-')} -> {mine.get(name, '-')}")
        return diffs


@lru_cache(maxsize=1)
def fingerprint() -> EnvironmentFingerprint:
    pkgs: dict[str, str] = {}
    for dist in metadata.distributions():
        name = (dist.metadata["Name"] or "").lower().replace("_", "-")
        if name and name not in _IGNORED:
            pkgs[name] = dist.version
    return EnvironmentFingerprint(
        python=".".join(str(v) for v in sys.version_info[:3]),
        implementation=platform.python_implementation(),
        packages=tuple(sorted(pkgs.items())),
    )


def workstation_id() -> str:
    """The id stamped on research log lines. Set NNFX_WORKSTATION_ID per machine."""
    return os.environ.get("NNFX_WORKSTATION_ID") or platform.node() or "unknown"
