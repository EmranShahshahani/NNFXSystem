"""The Strategy Builder's endpoints: schema, save/load/versions, diff, import, compare (ticket 13)."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.data.feeds import write_bars_csv
from nnfx.strategy import REGISTRY, get_template
from nnfx.ui.server import App, serve
from tests.test_strategy_engine import DOC, FILL, RISE, SETUP, TO_TARGET, frame
from tests.test_ui import get, post

ROOT = Path(__file__).resolve().parents[1]
TCP = get_template("tcp_azizpour")


@pytest.fixture(scope="module")
def dirs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    data = tmp_path_factory.mktemp("data")
    write_bars_csv(frame([*RISE, SETUP, FILL, *TO_TARGET]), data / "BTC_USDT.M15.csv")
    return data, tmp_path_factory.mktemp("research"), tmp_path_factory.mktemp("strategies")


@pytest.fixture(scope="module")
def base(dirs: tuple[Path, Path, Path]) -> Iterator[str]:
    data, research, strategies = dirs
    app = App(ROOT, data_roots=(str(data),), research=str(research), strategies=str(strategies))
    httpd = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def dataset(dirs: tuple[Path, Path, Path]) -> dict[str, str]:
    return {"path": str(dirs[0] / "BTC_USDT.M15.csv"), "symbol": "BTC/USDT", "timeframe": "M15"}


def clone(name: str, **edits) -> dict:
    raw = TCP.clone(name)
    for path, value in edits.items():
        node = raw
        *head, last = path.split("__")
        for k in head:
            node = node[k]
        node[last] = value
    return raw


# ------------------------------------------------------------------ the palette
def test_every_registered_block_is_in_the_palette_with_a_form_the_ui_can_draw(base: str):
    blocks = get(base + "/api/strategy/blocks")
    assert {b["type"] for b in blocks} == set(REGISTRY)  # a new Block needs no change here
    allowed = {"boolean", "integer", "number", "string", "array"}
    for b in blocks:
        props = b["params"].get("properties", {})
        assert "$defs" not in b["params"], b["type"]  # no nested models: flat forms suffice
        for k, p in props.items():
            kinds = {p.get("type")} | {a.get("type") for a in p.get("anyOf", [])}
            assert (kinds - {None, "null"}) <= allowed, (b["type"], k, p)
            assert "default" in p or "array" in kinds, (b["type"], k, p)  # lists default to []


def test_the_schema_endpoint_describes_the_risk_section_and_the_timeframes(base: str):
    schema = get(base + "/api/strategy/schema")
    assert "risk_per_trade" in schema["risk"]["properties"]
    assert {"D1", "H4", "M15"} <= set(schema["timeframes"]["all"])
    assert set(schema["timeframes"]["base"]) <= set(schema["timeframes"]["all"])
    assert schema["timeframes"]["roles"] == ["hwc", "mwc", "lwc", "management"]
    assert "justified_min_score" in schema["checklist"]["properties"]


# --------------------------------------------------------- save, load, versions
def test_save_load_versions_and_delete_one_users_strategies(base: str):
    code, a = post(base + "/api/strategy/save", {"document": clone("alpha")})
    assert code == 200 and (a["name"], a["version"], a["unchanged"]) == ("alpha", 1, False)
    code, b = post(
        base + "/api/strategy/save", {"document": clone("alpha", risk__risk_per_trade=0.004)}
    )
    assert b["version"] == 2 and b["fingerprint"] != a["fingerprint"]
    code, same = post(
        base + "/api/strategy/save", {"document": clone("alpha", risk__risk_per_trade=0.004)}
    )
    assert same["unchanged"] and same["version"] == 2
    listed = get(base + "/api/strategy/documents")
    assert [(r["name"], r["version"]) for r in listed if r["name"] == "alpha"] == [("alpha", 2)]
    code, got = post(base + "/api/strategy/load", {"name": "alpha"})
    assert got["document"]["metadata"]["version"] == 2
    assert [v["version"] for v in got["versions"]] == [1, 2]
    code, old = post(base + "/api/strategy/load", {"name": "alpha", "version": 1})
    assert old["document"]["risk"]["risk_per_trade"] != got["document"]["risk"]["risk_per_trade"]
    assert post(base + "/api/strategy/load", {"name": "alpha", "version": 9})[0] == 400
    assert post(base + "/api/strategy/load", {"name": "nobody"})[0] == 400
    assert post(base + "/api/strategy/delete", {"name": "alpha"})[1]["ok"]
    assert post(base + "/api/strategy/load", {"name": "alpha"})[0] == 400


def test_saving_an_invalid_document_returns_the_issues_and_stores_nothing(base: str):
    bad = clone("broken")
    bad["blocks"][0]["type"] = "moon_phase"
    code, res = post(base + "/api/strategy/save", {"document": bad})
    assert code == 200 and not res["ok"] and "شناخته نشده" in res["issues"][0]["message"]
    assert all(r["name"] != "broken" for r in get(base + "/api/strategy/documents"))


# ----------------------------------------------------------------------- diff
def test_a_clone_is_diffed_against_its_parent_template_by_default(base: str):
    raw = clone("variant", risk__risk_per_trade=0.004)
    next(b for b in raw["blocks"] if b["type"] == "rsi_momentum")["enabled"] = False
    code, res = post(base + "/api/strategy/diff", {"document": raw})
    assert code == 200 and res["ok"] and res["base"] == {"template": "tcp_azizpour", "version": 1}
    assert {(c["scope"], c["path"]) for c in res["changes"]} == {
        ("risk", "risk_per_trade"),
        ("block", "enabled"),
    }
    assert all(c["text"] for c in res["changes"])


def test_a_document_is_diffed_against_a_saved_version_or_another_document(base: str):
    post(base + "/api/strategy/save", {"document": clone("gamma")})
    post(base + "/api/strategy/save", {"document": clone("gamma", risk__risk_per_trade=0.003)})
    cur = clone("gamma", risk__risk_per_trade=0.003)
    code, res = post(
        base + "/api/strategy/diff", {"document": cur, "base": {"name": "gamma", "version": 1}}
    )
    assert code == 200 and [c["path"] for c in res["changes"]] == ["risk_per_trade"]
    assert res["changes"][0]["old"] == 0.005 and res["changes"][0]["new"] == 0.003
    other = clone("other")
    code, res = post(base + "/api/strategy/diff", {"document": cur, "base": {"document": other}})
    assert code == 200 and [c["path"] for c in res["changes"]] == ["risk_per_trade"]
    code, res = post(
        base + "/api/strategy/diff", {"document": cur, "base": {"template": "tcp_azizpour"}}
    )
    assert code == 200 and len(res["changes"]) == 1


def test_diff_refuses_what_it_cannot_compare_in_persian(base: str):
    orphan = copy.deepcopy(DOC)  # no parent
    code, res = post(base + "/api/strategy/diff", {"document": orphan})
    assert code == 400 and "والد" in res["error"]
    code, res = post(
        base + "/api/strategy/diff", {"document": clone("x"), "base": {"template": "zz"}}
    )
    assert code == 400 and "قالب" in res["error"]
    bad = clone("x")
    bad["blocks"][0]["type"] = "moon_phase"
    code, res = post(base + "/api/strategy/diff", {"document": bad})
    assert code == 200 and not res["ok"] and res["issues"]


# --------------------------------------------------------------------- import
def test_import_accepts_an_exported_file_and_returns_the_resolved_document(base: str):
    text = json.dumps(clone("shared"), ensure_ascii=False, indent=2)
    code, res = post(base + "/api/strategy/import", {"text": text})
    assert code == 200 and res["ok"] and res["document"]["metadata"]["name"] == "shared"
    assert len(res["fingerprint"]) == 16


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("{not json", "JSON"),
        ("[1, 2]", "شیء"),
        ("", "خالی"),
        (json.dumps({"schema_version": 2, "metadata": {"name": "x"}, "blocks": []}), ""),
    ],
)
def test_import_rejects_invalid_files_with_persian_messages(base: str, text: str, needle: str):
    code, res = post(base + "/api/strategy/import", {"text": text})
    assert code == 200 and not res["ok"] and res["issues"]
    msgs = " ".join(i["message"] for i in res["issues"])
    assert needle in msgs and any("؀" <= ch <= "ۿ" for ch in msgs)


def test_import_lists_every_problem_of_a_well_formed_but_wrong_document(base: str):
    raw = clone("x")
    raw["blocks"][0]["type"] = "moon_phase"
    raw["blocks"][1]["params"]["nope"] = 1
    _, res = post(base + "/api/strategy/import", {"text": json.dumps(raw)})
    assert not res["ok"] and {i["path"] for i in res["issues"]} >= {
        "blocks[0].type",
        "blocks[1].params.nope",
    }
    assert post(base + "/api/strategy/import", {"text": 5})[0] == 400


# -------------------------------------------------------------------- compare
def test_compare_runs_both_documents_on_the_same_data_and_lists_metrics(
    base: str, dirs: tuple[Path, Path, Path]
):
    a, b = copy.deepcopy(DOC), copy.deepcopy(DOC)
    a["metadata"]["name"], b["metadata"]["name"] = "plain", "wide stop"
    next(x for x in b["blocks"] if x["type"] == "stop_market")["params"]["expiry_bars"] = 1
    code, res = post(
        base + "/api/strategy/compare",
        {"documents": [a, b], "datasets": [dataset(dirs)], "zero_costs": True},
    )
    assert code == 200 and res["ok"], res
    r1, r2 = res["runs"]
    assert (r1["name"], r2["name"]) == ("plain", "wide stop")
    assert r1["fingerprint"] != r2["fingerprint"] and r1["trial_id"] != r2["trial_id"]
    assert r1["trades"] == 1 and r1["metrics"]["expectancy_r"] == pytest.approx(2.0)
    assert {"win_rate", "profit_factor", "max_drawdown", "sharpe", "total_return"} <= set(
        r1["metrics"]
    )
    assert res["datasets"] == ["BTC/USDT"]
    assert [c["path"] for c in res["changes"]] == ["params.expiry_bars"]
    rows = (dirs[1] / "strategy_trials.jsonl").read_text().splitlines()
    assert {json.loads(x)["id"] for x in rows} >= {r1["trial_id"], r2["trial_id"]}


def test_compare_refuses_what_it_cannot_run_in_persian(base: str, dirs: tuple[Path, Path, Path]):
    code, res = post(base + "/api/strategy/compare", {"documents": [DOC], "datasets": []})
    assert code == 400 and "دو" in res["error"]
    code, res = post(base + "/api/strategy/compare", {"documents": [DOC, DOC], "datasets": []})
    assert code == 400 and "دیتاست" in res["error"]
    other = copy.deepcopy(DOC)
    other["timeframes"]["lwc"] = "H1"
    code, res = post(
        base + "/api/strategy/compare",
        {"documents": [DOC, other], "datasets": [dataset(dirs)]},
    )
    assert code == 400 and "LWC" in res["error"]
    bad = copy.deepcopy(DOC)
    bad["blocks"][1]["type"] = "moon_phase"
    code, res = post(
        base + "/api/strategy/compare",
        {"documents": [DOC, bad], "datasets": [dataset(dirs)]},
    )
    assert code == 200 and not res["ok"] and res["which"] == 2 and res["issues"]


# --------------------------------------------------------------------- accounts
def test_the_endpoints_need_an_account_and_strategies_are_private(
    tmp_path: Path, dirs: tuple[Path, Path, Path]
):
    from nnfx.ui.auth import Auth
    from tests.test_beta_auth import _call, _client

    auth = Auth(tmp_path / "beta.db")
    app = App(
        ROOT,
        auth=auth,
        data_roots=(str(dirs[0]),),
        research=str(tmp_path / "r"),
        strategies=str(tmp_path / "s"),
    )
    httpd = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        anon = _client()
        for path in ("schema", "documents"):
            assert _call(anon, f"{base}/api/strategy/{path}")[0] == 401
        for path in ("save", "load", "delete", "diff", "import", "compare"):
            assert _call(anon, f"{base}/api/strategy/{path}", {})[0] == 401
        clients = []
        for name in ("ali", "sara"):
            auth.signup(auth.create_invites()[0], name, "password-1")
            c = _client()
            _call(c, base + "/api/login", {"username": name, "password": "password-1"})
            clients.append(c)
        ali, sara = clients
        assert _call(ali, base + "/api/strategy/save", {"document": clone("secret")})[0] == 200
        assert _call(ali, base + "/api/strategy/documents")[1][0]["name"] == "secret"
        assert _call(sara, base + "/api/strategy/documents")[1] == []
        assert _call(sara, base + "/api/strategy/load", {"name": "secret"})[0] == 400
    finally:
        httpd.shutdown()
