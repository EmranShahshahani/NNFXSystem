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


def key(b: dict[str, Any]) -> tuple[str, str]:
    return (b["kind"], b["type"])


def _blocks(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[Change]:
    a, b = {key(x): x for x in old}, {key(x): x for x in new}
    out: list[Change] = []
    for k in a.keys() - b.keys():
        out.append(_block_op("removed", a[k], "حذف شد"))
    for k in b.keys() - a.keys():
        out.append(_block_op("added", b[k], "اضافه شد"))
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
    common = [key(x) for x in old if key(x) in b]
    if common != [key(x) for x in new if key(x) in a]:
        out.append(
            {
                "op": "reordered",
                "scope": "block",
                "block": None,
                "path": "blocks",
                "old": [t for _, t in common],
                "new": [key(x)[1] for x in new if key(x) in a],
                "text": "بلوک‌ها جابه‌جا شدند",
            }
        )
    out.sort(key=lambda c: (c["op"] != "removed", c["op"] != "added", c["op"] == "reordered"))
    return out


def _block_op(op: str, block: dict[str, Any], verb: str) -> Change:
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
