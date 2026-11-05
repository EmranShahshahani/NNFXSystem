"""Strategy Documents over HTTP and the CLI (Strategy Builder ticket 05, seam 2)."""

from __future__ import annotations

import copy
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.cli import main
from nnfx.data.feeds import write_bars_csv
from nnfx.ui.server import App, serve
from tests.test_strategy_engine import DOC, FILL, RISE, SETUP, TO_TARGET, frame
from tests.test_ui import get, post

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dirs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    data, research = tmp_path_factory.mktemp("data"), tmp_path_factory.mktemp("research")
    write_bars_csv(frame([*RISE, SETUP, FILL, *TO_TARGET]), data / "BTC_USDT.M15.csv")
    return data, research


@pytest.fixture(scope="module")
def base(dirs: tuple[Path, Path]) -> Iterator[str]:
    data, research = dirs
    httpd = serve(App(ROOT, data_roots=(str(data),), research=str(research)), port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def dataset(dirs: tuple[Path, Path]) -> dict[str, str]:
    return {"path": str(dirs[0] / "BTC_USDT.M15.csv"), "symbol": "BTC/USDT", "timeframe": "M15"}


def test_blocks_are_listed_with_their_parameter_schemas(base: str):
    blocks = get(base + "/api/strategy/blocks")
    assert isinstance(blocks, list)
    setup = next(b for b in blocks if b["type"] == "candle_setup")
    assert setup["kind"] == "setup" and setup["title_fa"]
    assert setup["params"]["properties"]["sma"]["default"] == 7


def test_validate_returns_the_fingerprint_or_persian_issues(base: str):
    code, ok = post(base + "/api/strategy/validate", {"document": DOC})
    assert code == 200 and ok["ok"] and len(ok["fingerprint"]) == 16
    bad = copy.deepcopy(DOC)
    bad["blocks"][1]["type"] = "moon_phase"
    code, res = post(base + "/api/strategy/validate", {"document": bad})
    assert code == 200 and not res["ok"]
    assert (
        res["issues"][0]["path"] == "blocks[1].type"
        and "شناخته نشده" in res["issues"][0]["message"]
    )


def test_backtest_runs_the_document_and_logs_a_trial(base: str, dirs: tuple[Path, Path]):
    datasets = get(base + "/api/datasets")
    assert {"symbol": "BTC/USDT", "timeframe": "M15"}.items() <= datasets[0].items()  # type: ignore[index]
    code, res = post(
        base + "/api/strategy/backtest",
        {"document": DOC, "datasets": [dataset(dirs)], "zero_costs": True},
    )
    assert code == 200 and res["ok"], res
    assert [(t["exit_reason"], t["r_multiple"]) for t in res["trades"]] == [
        ("target", pytest.approx(2.0))
    ]
    assert len(res["candidates"]) == 1 and res["fingerprint"] == res["config_digest"]
    assert "E[R]=+2.000" in res["summary"]  # one position carries the whole 1R
    rows = (dirs[1] / "strategy_trials.jsonl").read_text().splitlines()
    assert json.loads(rows[-1])["id"] == res["trial_id"]


def test_backtest_of_an_invalid_document_returns_the_issues(base: str, dirs: tuple[Path, Path]):
    bad = copy.deepcopy(DOC)
    del bad["blocks"][3]
    code, res = post(
        base + "/api/strategy/backtest", {"document": bad, "datasets": [dataset(dirs)]}
    )
    assert code == 200 and not res["ok"] and res["issues"][0]["code"] == "missing_kind:stop"


def test_backtest_refuses_bars_on_the_wrong_timeframe(base: str, dirs: tuple[Path, Path]):
    raw = copy.deepcopy(DOC)
    raw["timeframes"]["lwc"] = "H1"
    code, res = post(
        base + "/api/strategy/backtest", {"document": raw, "datasets": [dataset(dirs)]}
    )
    assert code == 400 and "LWC" in res["error"]


def test_cli_validates_and_backtests_a_document(tmp_path: Path, dirs: tuple[Path, Path], capsys):
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(DOC))
    assert main(["strategy", "validate", str(path)]) == 0
    assert "fingerprint" in capsys.readouterr().out
    bad = copy.deepcopy(DOC)
    bad["blocks"][1]["type"] = "moon_phase"
    (tmp_path / "bad.json").write_text(json.dumps(bad))
    assert main(["strategy", "validate", str(tmp_path / "bad.json")]) == 1
    assert "moon_phase" in capsys.readouterr().out
    rc = main(
        [
            "strategy", "backtest", str(path), "--csv", f"BTC/USDT={dirs[0] / 'BTC_USDT.M15.csv'}",
            "--research", str(tmp_path / "research"), "--zero-costs",
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert rc == 0 and "trades: 1" in out and "trial s_" in out and "E[R]=+2.000" in out
    assert (tmp_path / "research" / "strategy_trials.jsonl").exists()


def test_strategy_endpoints_need_an_account_when_accounts_are_on(
    tmp_path: Path, dirs: tuple[Path, Path]
):
    from nnfx.ui.auth import Auth
    from tests.test_beta_auth import _call, _client

    auth = Auth(tmp_path / "beta.db")
    httpd = serve(
        App(ROOT, auth=auth, data_roots=(str(dirs[0]),), research=str(tmp_path / "r")), port=0
    )
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        anon = _client()
        assert _call(anon, base + "/api/strategy/blocks")[0] == 401
        assert _call(anon, base + "/api/strategy/validate", {"document": DOC})[0] == 401
        assert _call(anon, base + "/api/strategy/backtest", {"document": DOC})[0] == 401
        auth.signup(auth.create_invites()[0], "trader1", "password-1")
        me = _client()
        _call(me, base + "/api/login", {"username": "trader1", "password": "password-1"})
        code, res = _call(
            me,
            base + "/api/strategy/backtest",
            {"document": DOC, "datasets": [dataset(dirs)], "zero_costs": True},
        )
        assert code == 200 and res["ok"] and len(res["trades"]) == 1
    finally:
        httpd.shutdown()


def test_the_backtest_returns_each_candidates_checklist(base: str, dirs: tuple[Path, Path]):
    raw = copy.deepcopy(DOC)
    raw["blocks"].insert(
        2,
        {
            "kind": "confirmation",
            "type": "volume_expansion",
            "params": {"lookback": 5, "factor": 0.5},
        },
    )
    code, res = post(
        base + "/api/strategy/backtest",
        {"document": raw, "datasets": [dataset(dirs)], "zero_costs": True},
    )
    assert code == 200 and res["ok"], res
    (cand,) = res["candidates"]
    assert [(c["block"], c["outcome"]) for c in cand["checklist"]] == [
        ("three_sma_alignment#0", "pass"),
        ("volume_expansion#2", "pass"),
    ]
    assert cand["decision"] == "placed" and cand["score"] == 1.0
    assert [p["stage"] for p in cand["decision_path"]][-3:] == ["risk", "stop", "order"]
    assert res["trades"][0]["stop_label"] is None  # a winner carries no stop label


def test_the_backtest_returns_the_latest_candidates_with_the_total(
    base: str, dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
):
    import nnfx.ui.server as server

    monkeypatch.setattr(server, "MAX_CANDIDATES", 0)
    code, res = post(
        base + "/api/strategy/backtest",
        {"document": DOC, "datasets": [dataset(dirs)], "zero_costs": True},
    )
    assert code == 200 and res["ok"], res
    assert res["candidates"] == []
    assert res["candidate_count"] == 1
    assert res["spot_transfers"] == [] and res["spot_balance"] == 0


def test_the_backtest_reports_the_spot_recycling_record(base: str, dirs: tuple[Path, Path]):
    raw = copy.deepcopy(DOC)
    raw["blocks"][-1] = {
        "kind": "exit",
        "type": "profit_chain",
        "params": {"recycle_to_spot": True, "recycle_min_r": 2.0},
    }
    raw["blocks"][-1]["params"].update(f1=1.0, f2=0, f3=0, runner=0)
    code, res = post(
        base + "/api/strategy/backtest",
        {"document": raw, "datasets": [dataset(dirs)], "zero_costs": True},
    )
    assert code == 200 and res["ok"], res
    (t,) = res["spot_transfers"]
    assert t["r"] == pytest.approx(2.0) and res["spot_balance"] == pytest.approx(t["amount"])
