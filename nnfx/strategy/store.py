"""Where a user's Strategy Documents live, one file per saved version (ticket 13, ADR 10 §17).

``<root>/<owner>/<name>/v0001.json``: both the owner and the name are hashed into
directory names, so no user text becomes a path. A save that changes nothing adds
no version; the version number is the store's, never the client's.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nnfx.strategy.document import StrategyDocument, validate_document

MAX_STRATEGIES = 100  # per user
MAX_VERSIONS = 200  # per strategy


@dataclass(frozen=True)
class Saved:
    name: str
    version: int
    fingerprint: str
    unchanged: bool  # the document equals the latest version, so nothing was added

    def record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "unchanged": self.unchanged,
        }


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class StrategyStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    # --------------------------------------------------------------- paths
    def _owner(self, owner: str) -> Path:
        return self.root / _h(owner)

    def _dir(self, owner: str, name: str) -> Path:
        return self._owner(owner) / _h(name.strip())

    @staticmethod
    def _numbers(d: Path) -> list[int]:
        return sorted(int(p.stem[1:]) for p in d.glob("v*.json")) if d.is_dir() else []

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"فایل ذخیره‌شده خوانا نیست: {e}") from None
        return data

    def _doc(self, path: Path) -> StrategyDocument:
        res = validate_document(self._read(path)["document"])
        if res.document is None:  # the schema moved on; say so rather than guess
            raise ValueError("این نسخه با طرح فعلی سند سازگار نیست:\n" + res.render())
        return res.document

    # ---------------------------------------------------------------- write
    def save(self, owner: str, doc: StrategyDocument) -> Saved:
        name = doc.metadata.name.strip()
        with self._lock:
            d = self._dir(owner, name)
            nums = self._numbers(d)
            if not nums:
                owned = [p for p in self._owner(owner).glob("*") if p.is_dir()]
                if len(owned) >= MAX_STRATEGIES:
                    raise ValueError(f"حداکثر {MAX_STRATEGIES} استراتژی مجاز است؛ یکی را حذف کنید.")
            latest = nums[-1] if nums else 0
            if latest >= MAX_VERSIONS:
                raise ValueError(
                    f"حداکثر {MAX_VERSIONS} نسخه برای هر استراتژی مجاز است؛ آن را با نام دیگری ذخیره کنید."
                )
            stamped = self._stamp(doc, name, latest + 1)
            if latest:
                last = self._doc(d / f"v{latest:04d}.json")
                if last.fingerprint() == self._stamp(doc, name, latest).fingerprint():
                    return Saved(name, latest, last.fingerprint(), True)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"v{latest + 1:04d}.json"
            body = {
                "saved": datetime.now(UTC).isoformat(timespec="seconds"),
                "document": stamped.model_dump(mode="json"),
            }
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            return Saved(name, latest + 1, stamped.fingerprint(), False)

    @staticmethod
    def _stamp(doc: StrategyDocument, name: str, version: int) -> StrategyDocument:
        raw = doc.model_dump(mode="json")
        raw["metadata"]["name"], raw["metadata"]["version"] = name, version
        out = validate_document(raw).document
        assert out is not None  # a valid document stays valid with another number
        return out

    def delete(self, owner: str, name: str) -> None:
        with self._lock:
            d = self._dir(owner, name)
            nums = self._numbers(d)
            if not nums:
                raise KeyError(f"استراتژی «{name.strip()}» پیدا نشد")
            for n in nums:
                (d / f"v{n:04d}.json").unlink()
            d.rmdir()

    # ----------------------------------------------------------------- read
    def load(self, owner: str, name: str, version: int | None = None) -> StrategyDocument:
        d = self._dir(owner, name)
        nums = self._numbers(d)
        if not nums:
            raise KeyError(f"استراتژی «{name.strip()}» پیدا نشد")
        n = nums[-1] if version is None else version
        if n not in nums:
            raise KeyError(f"استراتژی «{name.strip()}» نسخهٔ {n} ندارد؛ نسخه‌ها: {nums}")
        return self._doc(d / f"v{n:04d}.json")

    def versions(self, owner: str, name: str) -> list[dict[str, Any]]:
        d = self._dir(owner, name)
        nums = self._numbers(d)
        if not nums:
            raise KeyError(f"استراتژی «{name.strip()}» پیدا نشد")
        out = []
        for n in nums:
            rec = self._read(d / f"v{n:04d}.json")
            out.append(
                {
                    "version": n,
                    "saved": rec.get("saved"),
                    "fingerprint": self._doc(d / f"v{n:04d}.json").fingerprint(),
                }
            )
        return out

    def list(self, owner: str) -> list[dict[str, Any]]:
        rows = []
        for d in sorted(p for p in self._owner(owner).glob("*") if p.is_dir()):
            nums = self._numbers(d)
            if not nums:
                continue
            doc = self._doc(d / f"v{nums[-1]:04d}.json")
            rows.append(
                {
                    "name": doc.metadata.name,
                    "version": nums[-1],
                    "versions": len(nums),
                    "fingerprint": doc.fingerprint(),
                    "parent": doc.metadata.parent,
                    "parent_version": doc.metadata.parent_version,
                    "saved": self._read(d / f"v{nums[-1]:04d}.json").get("saved"),
                }
            )
        return sorted(rows, key=lambda r: r["name"])
