"""Committed manifests of fetched history (ADR 08 §1).

Market data never enters git; its manifest does. A second workstation verifies
its re-download against the manifest and refuses to proceed on a mismatch,
because a vendor can revise history under the same name.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from nnfx.data.bars import BarFrame

MANIFEST_DIR = Path("data/manifests")


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    feed: str
    symbol: str
    timeframe: str
    start: str
    end: str
    rows: int
    sha256: str

    @classmethod
    def of(cls, feed: str, frame: BarFrame) -> Manifest:
        return cls(
            feed=feed,
            symbol=frame.symbol,
            timeframe=frame.timeframe,
            start=str(frame.index[0]) if len(frame) else "",
            end=str(frame.index[-1]) if len(frame) else "",
            rows=len(frame),
            sha256=frame.checksum(),
        )


class ManifestMismatch(RuntimeError):
    pass


def manifest_path(feed: str, symbol: str, timeframe: str, root: Path = MANIFEST_DIR) -> Path:
    safe = symbol.replace("/", "_").replace(":", "_")
    return root / feed / f"{safe}.{timeframe}.json"


def write_manifest(feed: str, frame: BarFrame, root: Path = MANIFEST_DIR) -> Path:
    path = manifest_path(feed, frame.symbol, frame.timeframe, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    m = Manifest.of(feed, frame)
    path.write_text(json.dumps(m.model_dump(), indent=2, sort_keys=True) + "\n")
    return path


def verify_manifest(feed: str, frame: BarFrame, root: Path = MANIFEST_DIR) -> Manifest:
    """Raise ``ManifestMismatch`` if ``frame`` differs from the committed manifest."""
    path = manifest_path(feed, frame.symbol, frame.timeframe, root)
    if not path.exists():
        raise ManifestMismatch(
            f"no committed manifest at {path}; fetch on the reference machine first"
        )
    want = Manifest.model_validate_json(path.read_text())
    got = Manifest.of(feed, frame)
    if want != got:
        diffs = [
            f"{k}: committed={getattr(want, k)!r} local={getattr(got, k)!r}"
            for k in Manifest.model_fields
            if getattr(want, k) != getattr(got, k)
        ]
        raise ManifestMismatch(
            f"MANIFEST MISMATCH for {feed}/{frame.symbol} - the vendor may have revised history. "
            "Not proceeding.\n  " + "\n  ".join(diffs)
        )
    return want


def record_or_verify(feed: str, frame: BarFrame, root: Path = MANIFEST_DIR) -> str:
    """Write a manifest on first fetch; verify against it afterwards."""
    path = manifest_path(feed, frame.symbol, frame.timeframe, root)
    if path.exists():
        verify_manifest(feed, frame, root)
        return "verified"
    write_manifest(feed, frame, root)
    return "written"
