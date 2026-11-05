"""Strategy Document schema, validation and fingerprint (Strategy Builder ticket 05)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from nnfx.strategy import load_document, validate_document

TRACER: dict[str, Any] = {
    "metadata": {"name": "tracer", "version": 1},
    "timeframes": {"hwc": "D1", "mwc": "H4", "lwc": "M15"},
    "universe": ["BTC/USDT"],
    "blocks": [
        {"kind": "context", "type": "three_sma_alignment", "params": {"timeframe": "mwc"}},
        {"kind": "setup", "type": "candle_setup"},
        {"kind": "execution", "type": "stop_market", "params": {"expiry_bars": 4}},
        {"kind": "stop", "type": "structural_stop"},
        {"kind": "exit", "type": "fixed_r", "params": {"r": 2.0}},
    ],
    "risk": {"risk_per_trade": 0.005},
}


def issues(raw: dict[str, Any]) -> list[tuple[str, str]]:
    res = validate_document(raw)
    assert res.document is None
    return [(i.path, i.code) for i in res.issues]


def test_the_tracer_document_is_valid():
    res = validate_document(TRACER)
    assert res.ok and res.issues == []
    doc = res.document
    assert doc is not None and [b.type for b in doc.blocks][:2] == [
        "three_sma_alignment",
        "candle_setup",
    ]
    # Every parameter is resolved, with its default where the document left it out.
    assert doc.blocks[1].params["sma"] == 7


def test_unknown_types_and_parameters_are_errors_in_persian():
    raw = copy.deepcopy(TRACER)
    raw["blocks"][1]["type"] = "moon_phase"
    raw["blocks"][2]["params"]["slippage_magic"] = 1
    raw["blocks"][4]["params"]["r"] = "two"
    res = validate_document(raw)
    assert [(i.path, i.code) for i in res.issues] == [
        ("blocks[1].type", "unknown_block_type"),
        ("blocks[2].params.slippage_magic", "unknown_param"),
        ("blocks[4].params.r", "bad_param"),
    ]
    assert "moon_phase" in res.issues[0].message and "شناخته نشده" in res.issues[0].message
    assert "slippage_magic" in res.issues[1].message
    assert "عدد" in res.issues[2].message


def test_a_block_under_the_wrong_kind_is_an_error():
    raw = copy.deepcopy(TRACER)
    raw["blocks"][0]["kind"] = "setup"
    assert ("blocks[0].kind", "wrong_kind") in issues(raw)


def test_every_role_a_strategy_needs_must_be_present_and_enabled():
    raw = copy.deepcopy(TRACER)
    raw["blocks"] = [b for b in raw["blocks"] if b["kind"] != "stop"]
    raw["blocks"][1]["enabled"] = False  # the only setup
    found = issues(raw)
    assert ("blocks", "missing_kind:setup") in found and ("blocks", "missing_kind:stop") in found


def test_timeframe_roles_must_be_known_and_ordered():
    raw = copy.deepcopy(TRACER)
    raw["timeframes"] = {"hwc": "M15", "mwc": "H4", "lwc": "H3"}
    found = issues(raw)
    assert ("timeframes.lwc", "bad_timeframe") in found
    raw["timeframes"] = {"hwc": "M15", "mwc": "H4", "lwc": "M15"}
    assert ("timeframes", "role_order") in issues(raw)
    raw["timeframes"] = {"hwc": "D1", "mwc": "H4", "lwc": "H4"}
    assert ("timeframes.lwc", "lwc_not_base") in issues(raw)


def test_missing_fields_and_bad_risk_are_reported_with_paths():
    raw = copy.deepcopy(TRACER)
    del raw["metadata"]["name"]
    raw["risk"]["risk_per_trade"] = 0.5  # 50% of equity per trade
    found = issues(raw)
    assert ("metadata.name", "required") in found and ("risk.risk_per_trade", "bad_value") in found


def test_fingerprint_is_stable_across_key_order_and_explicit_defaults():
    a = validate_document(TRACER).document
    reordered = json.loads(json.dumps(TRACER, sort_keys=True))
    reordered["blocks"][1]["params"] = {"sma": 7}  # the default, written out
    b = validate_document(reordered).document
    assert a is not None and b is not None and a.fingerprint() == b.fingerprint()
    changed = copy.deepcopy(TRACER)
    changed["blocks"][4]["params"]["r"] = 3.0
    c = validate_document(changed).document
    assert c is not None and c.fingerprint() != a.fingerprint()
    assert len(a.fingerprint()) == 16


def test_documents_load_from_json_and_yaml(tmp_path: Path):
    import yaml

    (tmp_path / "s.json").write_text(json.dumps(TRACER))
    (tmp_path / "s.yaml").write_text(yaml.safe_dump(TRACER, allow_unicode=True))
    a, b = load_document(tmp_path / "s.json"), load_document(tmp_path / "s.yaml")
    assert a.fingerprint() == b.fingerprint()
    bad = copy.deepcopy(TRACER)
    bad["blocks"][1]["type"] = "moon_phase"
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="moon_phase"):
        load_document(tmp_path / "bad.json")


# ------------------------------------------------------------ review fixes
def test_types_are_strict_strings_are_not_numbers():
    raw = copy.deepcopy(TRACER)
    raw["blocks"][2]["params"]["expiry_bars"] = "4"
    raw["risk"]["risk_per_trade"] = "0.005"
    found = issues(raw)
    assert ("blocks[2].params.expiry_bars", "bad_param") in found
    assert ("risk.risk_per_trade", "bad_value") in found


def test_errors_in_a_blocks_own_fields_come_back_in_persian():
    raw = copy.deepcopy(TRACER)
    raw["blocks"][1]["enabled"] = "abc"
    raw["blocks"][3]["colour"] = "red"
    res = validate_document(raw)  # never raises
    got = {(i.path, i.code): i.message for i in res.issues}
    assert ("blocks[1].enabled", "bad_value") in got and "درست یا نادرست" in got[
        ("blocks[1].enabled", "bad_value")
    ]
    assert ("blocks[3].colour", "bad_value") in got


def test_one_stop_and_one_exit_block_at_most():
    raw = copy.deepcopy(TRACER)
    raw["blocks"].append({"kind": "stop", "type": "structural_stop"})
    raw["blocks"].append({"kind": "exit", "type": "fixed_r", "params": {"r": 3.0}})
    found = issues(raw)
    assert ("blocks", "too_many:stop") in found and ("blocks", "too_many:exit") in found
    raw["blocks"][-1]["enabled"] = False
    raw["blocks"][-2]["enabled"] = False
    assert validate_document(raw).ok  # disabled extras are fine


def test_a_management_timeframe_role_can_be_set():
    raw = copy.deepcopy(TRACER)
    raw["timeframes"]["management"] = "H4"
    doc = validate_document(raw).document
    assert doc is not None and doc.timeframes.as_dict()["management"] == "H4"
    raw["timeframes"]["management"] = "M5"
    assert ("timeframes.management", "bad_timeframe") in issues(raw)


def test_fingerprint_is_the_same_in_another_process():
    import subprocess
    import sys

    code = (
        "import json,sys; from nnfx.strategy import validate_document; "
        "print(validate_document(json.loads(sys.stdin.read())).document.fingerprint())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(TRACER),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    doc = validate_document(TRACER).document
    assert doc is not None and out == doc.fingerprint()
