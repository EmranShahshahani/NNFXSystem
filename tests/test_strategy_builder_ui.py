"""The Strategy Builder in a real browser, desktop and phone (ticket 13)."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.data.feeds import write_bars_csv
from nnfx.ui.server import App, serve
from tests.test_strategy_engine import FILL, RISE, SETUP, TO_TARGET, frame

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "ui" / "strategy_builder.js"


def _browser_available() -> bool:
    node = shutil.which("node")
    if node is None:
        return False
    probe = subprocess.run([node, "-e", "require('playwright')"], capture_output=True, check=False)
    return probe.returncode == 0


@pytest.fixture
def base(tmp_path: Path) -> Iterator[str]:
    data = tmp_path / "data"
    data.mkdir()
    write_bars_csv(frame([*RISE, SETUP, FILL, *TO_TARGET]), data / "BTC_USDT.M15.csv")
    app = App(
        ROOT,
        data_roots=(str(data),),
        research=str(tmp_path / "research"),
        strategies=str(tmp_path / "strategies"),
    )
    httpd = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


@pytest.mark.skipif(not _browser_available(), reason="needs Node and Playwright")
@pytest.mark.parametrize("device", ["desktop", "mobile"])
def test_the_builder_edits_saves_versions_diffs_exports_imports_and_compares(
    base: str, device: str
):
    out = subprocess.run(
        ["node", str(SCRIPT), base, device, "with-data"],
        capture_output=True, text=True, timeout=240, check=True,
    )  # fmt: skip
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    # Every Block of the Template has a form; the palette has no free Block until one is removed.
    assert seen["blockCount"] == 47 and seen["offCount"] == 30
    assert seen["paletteTotal"] == 46 and seen["paletteFree"] == 0
    assert (seen["afterRemove"], seen["freedUp"], seen["afterAdd"]) == (46, True, 47)
    # Editing through the forms is editing the document.
    assert seen["weightEdited"] == 2.5 and seen["touchOff"] is False and seen["risk"] == 0.004
    assert seen["rowMarked"] >= 1 and seen["badge"] == 1
    # Versions: a first save, an identical save adds none, a change makes version 2.
    assert "نسخهٔ 1" in seen["saved1"] and "تغییری نبود" in seen["saved1again"]
    assert [v for v in seen["versions"]] == ["نسخهٔ 2", "نسخهٔ 1"]
    assert seen["v1weight"] == 2.5  # opening version 1 brings back its parameters
    # The diff against the parent lists every change a person made.
    d = seen["diffParent"]
    assert all(
        x in d
        for x in (
            "hwc",
            "weight",
            "rsi_momentum",
            "touch_count",
            "level_location",
            "risk_per_trade",
        )
    )
    # Export, then import the same file.
    assert seen["exportName"].endswith("-v1.json") and seen["exported"] == "my variant"
    assert seen["imported"] == "my variant"
    assert "JSON" in seen["badImport"] and "فایل وارد نشد" in seen["badStatus"]
    # Two strategies on the same data, side by side.
    assert (
        "الف" in seen["compare"]
        and "میانگین R" in seen["compare"]
        and "اثر انگشت" in seen["compare"]
    )
    assert seen["deleted"] == [""]
    assert seen["overflow"] <= 0 and seen["errors"] == []
