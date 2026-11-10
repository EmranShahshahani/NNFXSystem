"""The TCP Azizpour Template: listed, read-only, clonable (Strategy Builder ticket 12)."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.cli import main
from nnfx.strategy import REGISTRY, TEMPLATES, BlockKind, get_template, validate_document
from nnfx.ui.server import App, serve
from tests.test_strategy_engine import DOC
from tests.test_ui import get, post

ROOT = Path(__file__).resolve().parents[1]
TCP = get_template("tcp_azizpour")
SCRIPT = ROOT / "tests" / "ui" / "strategy_template.js"


def enabled(types: set[str] | None = None) -> set[str]:
    return {b.type for b in TCP.document.blocks if b.enabled and (types is None or b.type in types)}


# ------------------------------------------------------------------ the document
def test_the_template_validates_and_has_a_stable_fingerprint():
    assert validate_document(TCP.document.model_dump(mode="json")).ok
    assert len(TCP.document.fingerprint()) == 16
    assert TCP.listing()["read_only"] is True


def test_timeframe_roles_follow_the_blueprint():
    tf = TCP.document.timeframes
    assert (tf.hwc, tf.mwc, tf.lwc, tf.management) == ("D1", "H4", "M15", "H4")


def test_every_block_of_the_library_is_in_the_template_with_its_source():
    """From ticket 12 on, a new Block ticket adds its Block here, enabled or not."""
    listed = [b.type for b in TCP.document.blocks]
    registered = {t for t, c in REGISTRY.items() if c.kind not in (BlockKind.RISK,)}
    assert set(listed) == registered
    pairs = {t for t in listed if listed.count(t) > 1}
    assert pairs <= {"binary_scenario"}  # a two-sided setup is one Block per side
    assert len(TCP.sources) == len(TCP.document.blocks)
    assert all(s.videos or s.note for s in TCP.sources) and (TCP.risk_sources.videos)
    assert all(v > 0 for s in TCP.sources for v in s.videos)


def test_the_blueprint_defaults_are_what_is_switched_on():
    assert enabled() >= {
        "wave_cycles", "three_sma_alignment", "choppy_regime", "sma_baseline_filter",
        "candle_setup", "box_breakout", "rsi_momentum", "touch_count", "breakout_body_close",
        "breakout_range", "stop_market", "structural_stop", "profit_chain",
    }  # fmt: skip
    # The other setups are present but disabled, so a clone can switch them on.
    assert not enabled({"box_extremes", "dow_trend", "overextension_guard", "fixed_r"})
    exits = [b for b in TCP.document.blocks if b.kind == BlockKind.EXIT and b.enabled]
    assert [b.type for b in exits] == ["profit_chain"]


def test_the_profit_chain_the_risk_tiers_and_the_governors_are_the_blueprints():
    chain = next(b for b in TCP.document.blocks if b.type == "profit_chain").params
    assert (chain["r1"], chain["f1"], chain["r2"], chain["f2"]) == (2.0, 0.35, 5.0, 0.40)
    assert (chain["r3"], chain["f3"], chain["runner"]) == (10.0, 0.15, 0.10)  # 15%, not 20%
    r = TCP.document.risk
    assert (r.sizing, r.tiers) == ("tiered", [0.0025, 0.005, 0.0075, 0.01])
    assert (r.streak.reduce_after, r.streak.reduced_risk) == (3, 0.0025)
    assert (r.streak.halt_after, r.streak.halt_hours) == (5, 48)
    assert r.loss_limits.daily == 0.015 and r.leverage.leverage == 1.0


def test_candle_confirmations_do_not_judge_box_breakouts_and_the_other_way_round():
    by = {b.type: b.params["only_setups"] for b in TCP.document.blocks if "only_setups" in b.params}
    assert by["rsi_momentum"] == ["candle_setup"] and by["touch_count"] == ["box_breakout"]


# ---------------------------------------------------------------------- cloning
def test_a_clone_is_an_independent_valid_document_that_names_its_parent():
    raw = TCP.clone("my variant")
    assert raw["metadata"] == {
        "name": "my variant", "version": 1, "parent": "tcp_azizpour", "parent_version": 1,
        "description": "",
    }  # fmt: skip
    res = validate_document(raw)
    assert res.ok and res.document is not None
    assert res.document.fingerprint() != TCP.document.fingerprint()
    raw["blocks"][0]["enabled"] = False
    raw["risk"]["tiers"][0] = 0.001
    assert TCP.clone()["blocks"][0]["enabled"] and TCP.document.risk.tiers[0] == 0.0025
    assert TCP.clone()["metadata"]["name"].startswith("TCP Azizpour")


def test_a_clone_keeps_the_disabled_blocks_so_they_can_be_switched_on():
    clone = TCP.clone()
    assert [(b["type"], b["enabled"]) for b in clone["blocks"]] == [
        (b.type, b.enabled) for b in TCP.document.blocks
    ]


def test_a_template_cannot_be_edited_in_place():
    with pytest.raises(Exception, match="frozen"):
        TCP.document.metadata.name = "x"  # type: ignore[misc]
    with pytest.raises(Exception, match="frozen"):
        TCP.document.risk = TCP.document.risk  # type: ignore[misc]
    with pytest.raises(KeyError, match="nope"):
        get_template("nope")


# ------------------------------------------------------------ scoped Confirmations
def test_an_unknown_setup_in_only_setups_is_a_persian_error():
    raw = copy.deepcopy(DOC)
    raw["blocks"].insert(
        2,
        {
            "kind": "confirmation",
            "type": "rsi_momentum",
            "params": {"only_setups": ["rsi_momentum"]},
        },
    )
    res = validate_document(raw)
    assert not res.ok
    assert res.issues[0].path == "blocks[2].params.only_setups"
    assert "ستاپ" in res.issues[0].message


# -------------------------------------------------------------------- API and CLI
@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    httpd = serve(App(ROOT, research=str(tmp_path_factory.mktemp("research"))), port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_templates_are_listed_and_cloned_over_the_api(base: str):
    (t,) = get(base + "/api/strategy/templates")
    assert t["slug"] == "tcp_azizpour" and t["read_only"] and t["fingerprint"]
    assert t["document"]["timeframes"]["lwc"] == "M15"
    by = {b["type"]: b for b in t["blocks"]}
    assert by["candle_setup"]["sources"]["videos"] == [35, 36, 37] and by["candle_setup"]["enabled"]
    assert not by["box_extremes"]["enabled"]
    code, res = post(base + "/api/strategy/clone", {"template": "tcp_azizpour", "name": "mine"})
    assert code == 200 and res["ok"] and res["document"]["metadata"]["parent"] == "tcp_azizpour"
    code, ok = post(base + "/api/strategy/validate", {"document": res["document"]})
    assert code == 200 and ok["ok"]
    assert post(base + "/api/strategy/clone", {"template": "nope"})[0] == 400
    assert post(base + "/api/strategy/clone", {"template": "tcp_azizpour", "name": " "})[0] == 400


def test_the_template_endpoints_need_an_account_when_accounts_are_on(tmp_path: Path):
    from nnfx.ui.auth import Auth
    from tests.test_beta_auth import _call, _client

    httpd = serve(App(ROOT, auth=Auth(tmp_path / "beta.db"), research=str(tmp_path / "r")), port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        anon = _client()
        assert _call(anon, base + "/api/strategy/templates")[0] == 401
        assert _call(anon, base + "/api/strategy/clone", {"template": "tcp_azizpour"})[0] == 401
    finally:
        httpd.shutdown()


def test_the_cli_lists_and_clones_a_template(tmp_path: Path, capsys):
    assert main(["strategy", "templates", "-v"]) == 0
    out = capsys.readouterr().out
    assert "tcp_azizpour" in out and "read-only" in out
    assert "[x] setup" in out and "candle_setup" in out and "video 35, video 36, video 37" in out
    assert "[ ] setup" in out and "box_extremes" in out
    path = tmp_path / "mine.json"
    assert main(["strategy", "clone", "tcp_azizpour", str(path), "--name", "mine"]) == 0
    assert "cloned" in capsys.readouterr().out
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["metadata"]["name"] == "mine" and saved["metadata"]["parent"] == "tcp_azizpour"
    assert main(["strategy", "validate", str(path)]) == 0
    assert main(["strategy", "clone", "tcp_azizpour", str(path)]) == 1  # never overwrites
    assert "exists" in capsys.readouterr().out
    assert main(["strategy", "clone", "tcp_azizpour", str(path), "--force"]) == 0
    assert main(["strategy", "clone", "nope", str(tmp_path / "x.json")]) == 1


# ------------------------------------------------------------------------- the UI
def _browser_available() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, check=False)
    return probe.returncode == 0


@pytest.mark.skipif(not _browser_available(), reason="needs Node and Playwright")
@pytest.mark.parametrize("device", ["desktop", "mobile"])
def test_the_ui_lists_the_template_with_its_videos_and_clones_it(base: str, device: str):
    out = subprocess.run(
        ["node", str(SCRIPT), base + "/", device],
        capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert "فقط‌خواندنی" in seen["detail"] and TCP.document.fingerprint() in seen["detail"]
    rows = {r[2]: r for r in seen["rows"] if len(r) == 4}
    assert rows["candle_setup"][0] == "✓" and "35" in rows["candle_setup"][3]
    assert rows["box_extremes"][0] == "—"
    assert seen["doc"]["metadata"]["parent"] == "tcp_azizpour"
    assert "معتبر" in seen["verdict"] and seen["overflow"] <= 0 and seen["errors"] == []


# ----------------------------------------------------------- a separate hypothesis family
def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_template_backtests_are_strategy_trials_and_touch_no_preregistration(tmp_path: Path):
    from nnfx.research.trials import ResearchState
    from nnfx.strategy.run import backtest_document
    from tests.test_strategy_engine import BTC, RISE, SETUP, SYM, frame

    frozen = sorted((ROOT / "research").glob("*.frozen.json"))
    assert frozen
    before = {p.name: _digest(p) for p in frozen}
    research = ResearchState(tmp_path)
    doc = validate_document(TCP.clone("t")).document
    assert doc is not None
    out = backtest_document(
        doc, {SYM: frame([*RISE, SETUP])}, {SYM: BTC}, research=research, stage="template"
    )
    rows = [json.loads(ln) for ln in (tmp_path / "strategy_trials.jsonl").read_text().splitlines()]
    assert [r["document"] for r in rows] == [out.fingerprint]
    assert research.trial_count() == 0  # NNFX's trial log (and its DSR) is untouched
    assert before == {p.name: _digest(p) for p in frozen}  # no pre-registration changed
    assert not (tmp_path / "trials.jsonl").exists()
    assert TEMPLATES["tcp_azizpour"].document.fingerprint() != out.fingerprint
