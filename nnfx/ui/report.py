"""``nnfx report``: one self-contained HTML file for a backtest.

The file embeds the same JSON the web UI renders and the UI's own page, so the
charts and tables are identical and it opens offline with no server.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

from nnfx.ui.server import App


def render_report(result: Mapping[str, Any], title: str = "") -> str:
    page = resources.files("nnfx.ui").joinpath("static/index.html").read_text(encoding="utf-8")
    payload = json.dumps({"result": result, "meta": {"title": title}}, allow_nan=False)
    # "</" cannot appear inside the inline script; JSON allows escaping the slash.
    payload = payload.replace("</", "<\\/")
    inject = f"<script>window.NNFX_STATIC = {payload};</script>\n<script>"
    return page.replace("<script>", inject, 1)


def write_report(
    csvs: list[tuple[str, Path]],
    out: Path,
    *,
    timeframe: str = "D1",
    config: Path = Path("config/system.yaml"),
    instruments: Path = Path("config/instruments.yaml"),
    venue: Path = Path("config/venues/backtest.yaml"),
    overrides: Mapping[str, Any] | None = None,
    zero_costs: bool = False,
    title: str = "",
) -> Path:
    files = [(sym, Path(p).resolve()) for sym, p in csvs]
    app = App(
        Path("/"),
        config=str(config.resolve()),
        instruments=str(instruments.resolve()),
        venue=str(venue.resolve()),
        data_roots=tuple(sorted({str(f.parent) for _, f in files})),
    )
    datasets = [{"path": str(f), "symbol": s, "timeframe": timeframe} for s, f in files]
    result = app.backtest(
        {"datasets": datasets, "overrides": dict(overrides or {}), "zero_costs": zero_costs}
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(result, title or "گزارش بک‌تست NNFX"), encoding="utf-8")
    return out
