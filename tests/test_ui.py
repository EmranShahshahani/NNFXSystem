"""``nnfx ui``: the dashboard's API runs the same harness as the CLI and stays inside its data roots."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.ui.server import App, serve

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def base() -> Iterator[str]:
    httpd = serve(App(ROOT), port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url: str) -> object:
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def post(url: str, body: object) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_index_and_read_endpoints(base: str):
    with urllib.request.urlopen(base + "/") as r:
        assert b"NNFX Workbench" in r.read()
    ds = get(base + "/api/datasets")
    assert {"path": "data/sample/EURUSD.D1.csv", "symbol": "EURUSD", "timeframe": "D1"} in ds
    cat = get(base + "/api/catalogue")
    assert len(cat) >= 60 and all(e["implemented"] for e in cat)
    res = get(base + "/api/research")
    assert res["thresholds"]["status"] == "frozen"
    assert "cycles" in get(base + "/api/live")


def test_backtest_matches_the_cli_harness(base: str):
    from nnfx.brokers.costs import CostModel
    from nnfx.config import load_system_config
    from nnfx.data.feeds import read_bars_csv
    from nnfx.harness.backtest import BacktestHarness
    from nnfx.instruments import InstrumentRegistry

    code, r = post(
        base + "/api/backtest",
        {
            "datasets": [
                {"path": "data/sample/EURUSD.D1.csv", "symbol": "EURUSD", "timeframe": "D1"}
            ]
        },
    )
    assert code == 200, r
    cfg = load_system_config(ROOT / "config/system.yaml")
    spec = InstrumentRegistry.load(ROOT / "config/instruments.yaml").spec("EURUSD")
    f = read_bars_csv(ROOT / "data/sample/EURUSD.D1.csv", "EURUSD", volume_kind=spec.volume_kind)
    ref = BacktestHarness(
        cfg,
        {"EURUSD": spec},
        {"EURUSD": f},
        costs=CostModel.from_venue(ROOT / "config/venues/backtest.yaml"),
    ).run()
    assert r["digest"] == ref.digest()[:16]
    assert len(r["charts"]["EURUSD"]["c"]) == len(f)


def test_overrides_and_errors(base: str):
    ds = [{"path": "data/sample/EURUSD.D1.csv", "symbol": "EURUSD"}]
    code, r = post(base + "/api/backtest", {"datasets": ds, "overrides": {"slots.c2": None}})
    assert code == 200 and r["config"]["slots"]["c2"] is None
    code, r = post(base + "/api/backtest", {"datasets": ds, "overrides": {"rules.nope": True}})
    assert code in (400, 500) and "error" in r
    code, r = post(
        base + "/api/backtest", {"datasets": [{"path": "../../etc/passwd", "symbol": "EURUSD"}]}
    )
    assert code == 403
    code, r = post(base + "/api/backtest", {"datasets": []})
    assert code == 400


def test_ui_logs_no_trials(base: str):
    from nnfx.research.trials import ResearchState

    before = ResearchState(ROOT / "research").trial_count()
    post(
        base + "/api/backtest",
        {"datasets": [{"path": "data/sample/GBPUSD.D1.csv", "symbol": "GBPUSD"}]},
    )
    assert ResearchState(ROOT / "research").trial_count() == before
