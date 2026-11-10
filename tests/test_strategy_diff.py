"""Diffing two Strategy Documents (Strategy Builder ticket 13)."""

from __future__ import annotations

from nnfx.strategy import get_template, validate_document
from nnfx.strategy.diff import diff_documents

TCP = get_template("tcp_azizpour")


def variant(edit):
    raw = TCP.clone("v")
    edit(raw)
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return res.document


def by(changes, **match):
    return [c for c in changes if all(c.get(k) == v for k, v in match.items())]


def test_a_clone_has_no_differences_from_its_parent():
    assert diff_documents(TCP.document, variant(lambda r: None)) == []


def test_a_changed_parameter_is_listed_with_old_and_new_values():
    def edit(raw):
        next(b for b in raw["blocks"] if b["type"] == "rsi_momentum")["params"]["weight"] = 2.0

    (c,) = diff_documents(TCP.document, variant(edit))
    assert (c["op"], c["scope"], c["block"], c["path"]) == (
        "changed", "block", "rsi_momentum", "params.weight",
    )  # fmt: skip
    assert (c["old"], c["new"]) == (1.0, 2.0)
    assert "مومنتوم RSI" in c["text"] and "weight" in c["text"]


def test_switching_a_block_off_and_on_is_an_enabled_change():
    def edit(raw):
        for b in raw["blocks"]:
            if b["type"] == "rsi_momentum":
                b["enabled"] = False
            if b["type"] == "box_extremes":
                b["enabled"] = True

    changes = diff_documents(TCP.document, variant(edit))
    assert {(c["block"], c["old"], c["new"]) for c in changes} == {
        ("rsi_momentum", True, False),
        ("box_extremes", False, True),
    }
    assert all(c["path"] == "enabled" for c in changes)


def test_added_and_removed_blocks_are_listed():
    def edit(raw):
        raw["blocks"] = [b for b in raw["blocks"] if b["type"] != "fixed_r"]
        raw["blocks"].append(
            {"kind": "exit", "type": "fixed_r", "enabled": False, "params": {"r": 3.0}}
        )
        raw["blocks"] = [b for b in raw["blocks"] if b["type"] != "volume_expansion"]

    changes = diff_documents(TCP.document, variant(edit))
    removed = by(changes, op="removed")
    assert [c["block"] for c in removed] == ["volume_expansion"]
    assert by(changes, block="fixed_r", path="params.r")[0]["new"] == 3.0


def test_moving_a_block_is_a_reorder():
    def edit(raw):
        i = next(i for i, b in enumerate(raw["blocks"]) if b["type"] == "rsi_momentum")
        raw["blocks"].append(raw["blocks"].pop(i))

    (c,) = diff_documents(TCP.document, variant(edit))
    assert c["op"] == "reordered" and c["new"][-1] == "rsi_momentum"


def test_a_new_block_type_is_added():
    base = variant(
        lambda raw: raw["blocks"].remove(
            next(b for b in raw["blocks"] if b["type"] == "box_extremes")
        )
    )
    changes = diff_documents(base, TCP.document)
    (c,) = by(changes, op="added")
    assert c["block"] == "box_extremes" and "اضافه" in c["text"]


def test_timeframes_risk_and_checklist_changes_are_listed_but_not_the_name():
    def edit(raw):
        raw["metadata"]["name"] = "another name"
        raw["timeframes"]["hwc"] = "W1"
        raw["risk"]["streak"]["halt_after"] = 4
        raw["risk"]["tiers"] = [0.0025, 0.005, 0.0075, 0.009]
        raw["checklist"]["justified_min_score"] = 2.0

    changes = diff_documents(TCP.document, variant(edit))
    assert {(c["scope"], c["path"]) for c in changes} == {
        ("timeframes", "hwc"),
        ("risk", "streak.halt_after"),
        ("risk", "tiers"),
        ("checklist", "justified_min_score"),
    }
    assert by(changes, scope="timeframes")[0]["old"] == "D1"
    assert all("name" not in c["path"] for c in changes)


def test_the_diff_is_deterministic_and_json_safe():
    import json

    def edit(raw):
        raw["risk"]["sizing"] = "fixed"

    a = diff_documents(TCP.document, variant(edit))
    assert a == diff_documents(TCP.document, variant(edit))
    json.dumps(a, allow_nan=False)


def test_a_repeated_block_type_is_diffed_copy_by_copy():
    def twin(raw):
        first = next(b for b in raw["blocks"] if b["type"] == "rsi_momentum")
        raw["blocks"].append({**first, "params": dict(first["params"]), "enabled": False})

    base = variant(twin)

    def edit(raw):
        twin(raw)
        raw["blocks"][-1]["params"]["weight"] = 3.0

    (c,) = diff_documents(base, variant(edit))
    assert (c["block"], c["path"], c["new"]) == ("rsi_momentum", "params.weight", 3.0)
