"""T29-T31: the TCP pre-registration is frozen, consistent with its ledger and within budget."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nnfx.config import SystemConfig
from nnfx.research.prereg import BudgetExceeded, Prereg, PreregError, planned_trials
from nnfx.research.trials import ResearchState
from tests.helpers import config

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "research/tcp_prereg.frozen.json"


def test_frozen_prereg_validates_against_its_ledger():
    p = Prereg(PREREG, ROOT)
    d = p.data
    assert d["status"] == "frozen" and d["trial_budget"]["total"] == 60
    for g in ("H2021", "H2026", "risk_layer"):
        assert planned_trials(d["hypotheses"][g]) <= d["trial_budget"][g]
    assert "R14" in p.ledger_ids() and len(p.ledger_ids()) == 42


def test_ledger_edit_breaks_the_freeze(tmp_path: Path):
    shutil.copytree(ROOT / "research", tmp_path / "research")
    led = tmp_path / "research/tcp_rules.yaml"
    led.write_text(led.read_text(encoding="utf-8") + "\n# moved a goalpost\n", encoding="utf-8")
    with pytest.raises(PreregError, match="changed after"):
        Prereg(tmp_path / "research/tcp_prereg.frozen.json", tmp_path)


def test_unknown_rule_and_overbudget_are_refused(tmp_path: Path):
    shutil.copytree(ROOT / "research", tmp_path / "research")
    path = tmp_path / "research/tcp_prereg.frozen.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    d["hypotheses"]["H2026"]["modules"]["mystery"] = {"rule": "R99", "enabled": True}
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PreregError, match="R99"):
        Prereg(path, tmp_path)
    del d["hypotheses"]["H2026"]["modules"]["mystery"]
    d["hypotheses"]["H2021"]["ablations"] += [{"param": "x", "values": list(range(10))}]
    path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PreregError, match="budget"):
        Prereg(path, tmp_path)


def test_budget_counts_distinct_trials_per_group(tmp_path: Path):
    p = Prereg(PREREG, ROOT)
    rs = ResearchState(tmp_path)
    cfg: SystemConfig = config()
    for k in range(20):
        c = cfg.with_overrides({"risk.risk_per_position": 0.001 * (k + 1)})
        rs.record_trial(
            c, market="crypto", segment="development", symbols=["BTC"], stage="H2021/ablation"
        )
        rs.record_trial(
            c, market="crypto", segment="development", symbols=["BTC"], stage="H2021/ablation"
        )
    assert p.remaining(rs, "H2021") == 0 and p.remaining(rs, "H2026") == 32
    with pytest.raises(BudgetExceeded):
        p.require_budget(rs, "H2021")


def test_call_replay_policy_is_frozen_and_small():
    d = json.loads((ROOT / "research/tcp_callreplay.frozen.json").read_text(encoding="utf-8"))
    assert d["status"] == "frozen" and len(d["variants"]) <= 12
    assert d["sealed"]["from"] == "2025-01-01"
