"""What changed between two Strategy Documents (Strategy Builder ticket 13, ADR 10 §17).

A plain list of changes, each a dict a UI can show as-is: ``op`` (added, removed,
changed, reordered), ``scope`` (block, timeframes, universe, risk, checklist),
the Block it is about, the ``path`` of the field, ``old``/``new`` and a Persian
``text``. Blocks are matched by (kind, type), the Block's identity in a document.
The name, version, parent and description are not compared: a clone always
differs from its parent in those and nothing about the rules does.
"""

from __future__ import annotations

from typing import Any

from nnfx.strategy.blocks import REGISTRY
from nnfx.strategy.document import StrategyDocument

Change = dict[str, Any]


def _show(v: Any) -> str:
    if v is True:
        return "روشن"
    if v is False:
        return "خاموش"
    if v is None:
        return "—"
    if isinstance(v, list):
        return "[" + "، ".join(_show(x) for x in v) + "]"
    return str(v)


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    """Leaves of nested dicts as dotted paths; lists and scalars are leaves."""
    if not isinstance(d, dict):
        return {prefix: d}
    out: dict[str, Any] = {}
    for k, v in d.items():
        out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    return out


def _title(type_: str) -> str:
    cls = REGISTRY.get(type_)
    return f"{cls.title_fa} ({type_})" if cls is not None else type_


def _fields(scope: str, label: str, old: Any, new: Any) -> list[Change]:
    a, b = _flat(old), _flat(new)
    out: list[Change] = []
    for path in sorted(a.keys() | b.keys()):
        if a.get(path) != b.get(path):
            out.append(
                {
                    "op": "changed",
                    "scope": scope,
                    "block": None,
                    "path": path,
                    "old": a.get(path),
                    "new": b.get(path),
                    "text": f"{label}: {path} از {_show(a.get(path))} به {_show(b.get(path))}",
                }
            )
    return out


def diff_documents(old: StrategyDocument, new: StrategyDocument) -> list[Change]:
    """Every difference of ``new`` from ``old``, in a stable order."""
    o, n = old.model_dump(mode="json"), new.model_dump(mode="json")
    changes: list[Change] = []
    changes += _fields("timeframes", "نقش تایم‌فریم", o["timeframes"], n["timeframes"])
    changes += _fields(
        "universe", "بازارها", {"symbols": o["universe"]}, {"symbols": n["universe"]}
    )
    changes += _blocks(o["blocks"], n["blocks"])
    changes += _fields("risk", "ریسک", o["risk"], n["risk"])
    changes += _fields("checklist", "چک‌لیست", o["checklist"], n["checklist"])
    return changes


def _keys(blocks: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    """(kind, type, n): the n-th copy of a Block type is its own Block, so none is dropped."""
    seen: dict[tuple[str, str], int] = {}
    out = []
    for b in blocks:
        k = (b["kind"], b["type"])
        out.append((*k, seen.get(k, 0)))
        seen[k] = seen.get(k, 0) + 1
    return out


def _blocks(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[Change]:
    a = dict(zip(_keys(old), old, strict=True))
    b = dict(zip(_keys(new), new, strict=True))
    out: list[Change] = []
    for k in sorted(a.keys() - b.keys()):
        out.append(_block_op("removed", a[k]))
    for k in sorted(b.keys() - a.keys()):
        out.append(_block_op("added", b[k]))
    for k in sorted(a.keys() & b.keys()):
        x, y = a[k], b[k]
        t = k[1]
        if x["enabled"] != y["enabled"]:
            out.append(
                {
                    "op": "changed",
                    "scope": "block",
                    "kind": k[0],
                    "block": t,
                    "path": "enabled",
                    "old": x["enabled"],
                    "new": y["enabled"],
                    "text": f"بلوک {_title(t)}: از {_show(x['enabled'])} به {_show(y['enabled'])}",
                }
            )
        for c in _fields(
            "block", f"بلوک {_title(t)}", {"params": x["params"]}, {"params": y["params"]}
        ):
            out.append({**c, "kind": k[0], "block": t})
    common_old = [k for k in _keys(old) if k in b]
    common_new = [k for k in _keys(new) if k in a]
    if common_old != common_new:
        out.append(
            {
                "op": "reordered",
                "scope": "block",
                "block": None,
                "path": "blocks",
                "old": [k[1] for k in common_old],
                "new": [k[1] for k in common_new],
                "text": "بلوک‌ها جابه‌جا شدند",
            }
        )
    out.sort(key=lambda c: (c["op"] != "removed", c["op"] != "added", c["op"] == "reordered"))
    return out


def _block_op(op: str, block: dict[str, Any]) -> Change:
    verb = "اضافه شد" if op == "added" else "حذف شد"
    on = "روشن" if block["enabled"] else "خاموش"
    return {
        "op": op,
        "scope": "block",
        "kind": block["kind"],
        "block": block["type"],
        "path": block["type"],
        "old": None if op == "added" else block["enabled"],
        "new": block["enabled"] if op == "added" else None,
        "text": f"بلوک {_title(block['type'])} {verb} ({on})",
    }
