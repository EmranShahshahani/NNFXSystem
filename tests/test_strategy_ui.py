"""The Strategy Builder UI shows a candidate's checklist (ticket 08), in a real browser.

Runs Playwright through Node when both are installed; skipped otherwise.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from nnfx.data.feeds import write_bars_csv
from nnfx.ui.server import App, serve
from tests.test_strategy_engine import DOC, FILL, RISE, SETUP, TO_TARGET, frame

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "ui" / "strategy_checklist.js"


def _browser_available() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, check=False)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(not _browser_available(), reason="needs Node and Playwright")


@pytest.mark.parametrize("device", ["desktop", "mobile"])
def test_the_ui_shows_each_candidates_checklist_and_decision_path(tmp_path: Path, device: str):
    write_bars_csv(frame([*RISE, SETUP, FILL, *TO_TARGET]), tmp_path / "BTC_USDT.M15.csv")
    httpd = serve(App(ROOT, data_roots=(str(tmp_path),), research=str(tmp_path / "r")), port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    raw = copy.deepcopy(DOC)
    raw["blocks"].insert(
        2,
        {
            "kind": "confirmation",
            "type": "volume_expansion",
            "params": {"lookback": 5, "factor": 0.5},
        },
    )
    raw["blocks"].insert(3, {"kind": "confirmation", "type": "rsi_momentum"})
    try:
        out = subprocess.run(
            [
                "node",
                str(SCRIPT),
                f"http://127.0.0.1:{httpd.server_address[1]}/",
                json.dumps(raw),
                device,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
    finally:
        httpd.shutdown()
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert [r[0] for r in seen["rows"]] == [
        "three_sma_alignment#0",
        "volume_expansion#2",
        "rsi_momentum#3",
    ]
    assert [r[2].split()[-1] for r in seen["rows"]] == [
        "قبول",
        "قبول",
        "نامربوط",
    ]  # RSI: too little history
    assert seen["path"] == ["pass", "pass", "na", "pass", "pass", "pass"]
    assert "سفارش ثبت شد" in seen["summary"]
    assert seen["overflow"] == 0 and seen["errors"] == []
