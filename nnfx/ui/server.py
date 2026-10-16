"""``nnfx ui``: a local, read-mostly dashboard over the same code the CLI runs.

Standard library only (``http.server``), bound to 127.0.0.1 by default. The UI
never holds its own logic: a backtest from the browser is ``BacktestHarness``
on the same config and costs as ``nnfx backtest``. It reads data files only from
the configured data roots, and it never opens the holdout or writes trials -
browser backtests are exploration, not research (doc 03 §8).
"""

from __future__ import annotations

import json
import math
import traceback
from collections.abc import Mapping
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.config import SystemConfig, load_system_config
from nnfx.data.bars import BarFrame
from nnfx.data.feeds import read_bars_csv
from nnfx.data.session import resample_to_daily
from nnfx.instruments import InstrumentRegistry


def _clean(o: Any) -> Any:
    """JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _clean_dict(o: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = _clean(o)
    return out


class App:
    def __init__(
        self,
        root: Path,
        *,
        config: str = "config/system.yaml",
        instruments: str = "config/instruments.yaml",
        venue: str = "config/venues/backtest.yaml",
        data_roots: tuple[str, ...] = ("data/sample", "data/cache"),
        research: str = "research",
        live_state: str = "runs/live",
        reports: str = "reports/daily",
    ) -> None:
        self.root = root.resolve()
        self.config_path = self.root / config
        self.instruments_path = self.root / instruments
        self.venue_path = self.root / venue
        self.data_roots = [(self.root / d).resolve() for d in data_roots]
        self.research = self.root / research
        self.live_state = self.root / live_state
        self.reports = self.root / reports

    # ------------------------------------------------------------- endpoints
    def datasets(self) -> list[dict[str, str]]:
        out = []
        for d in self.data_roots:
            if not d.exists():
                continue
            for p in sorted(d.rglob("*.csv")):
                parts = p.name.split(".")
                tf = parts[1] if len(parts) > 2 and parts[1] in ("D1", "H1") else "D1"
                sym = parts[0]
                if "_" in sym:  # cached crypto names: BTC_USDT_USDT -> BTC/USDT:USDT
                    bits = sym.split("_")
                    sym = f"{bits[0]}/{bits[1]}" + (f":{bits[2]}" if len(bits) > 2 else "")
                out.append({"path": str(p.relative_to(self.root)), "symbol": sym, "timeframe": tf})
        return out

    def _safe_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not any(p.is_relative_to(d) for d in self.data_roots):
            raise PermissionError(f"{rel} is outside the data roots")
        return p

    def catalogue(self) -> list[dict[str, Any]]:
        from nnfx.indicators.catalogue import catalogue

        return [
            {
                "kind": e.kind,
                "name": e.name,
                "family": e.family,
                "defaults": e.defaults,
                "grid": {k: list(v) for k, v in e.grid.items()},
                "implemented": e.implemented,
            }
            for e in catalogue()
        ]

    def config(self) -> dict[str, Any]:
        return load_system_config(self.config_path).model_dump(mode="json")

    def backtest(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.harness.backtest import BacktestHarness, precompute
        from nnfx.research.metrics import compute_metrics

        cfg: SystemConfig = load_system_config(self.config_path)
        overrides = dict(req.get("overrides") or {})
        if overrides:
            cfg = cfg.with_overrides(overrides)
        reg = InstrumentRegistry.load(self.instruments_path)
        frames: dict[str, BarFrame] = {}
        inst = {}
        for ds in req.get("datasets") or []:
            sym, tf = ds["symbol"], ds.get("timeframe", "D1")
            spec = reg.spec(sym)
            f = read_bars_csv(
                self._safe_path(ds["path"]), sym, timeframe=tf, volume_kind=spec.volume_kind
            )
            if tf == "H1":
                f = resample_to_daily(f, spec, cfg.session)
            frames[sym], inst[sym] = f, spec
        if not frames:
            raise ValueError("pick at least one dataset")
        costs = None if req.get("zero_costs") else CostModel.from_venue(self.venue_path)
        outputs = precompute(cfg, frames)
        res = BacktestHarness(
            cfg,
            inst,
            frames,
            costs=costs,
            outputs=outputs,
            gate_kwargs={"max_missing_sessions": int(req.get("max_missing_sessions", 0))},
        ).run()
        met = compute_metrics(res.trades, res.equity, volume_flags=res.volume_flags)
        charts = {}
        for sym, f in frames.items():
            o = outputs[sym]
            charts[sym] = {
                "t": [ts.isoformat() for ts in f.index],
                "o": f.open,
                "h": f.high,
                "l": f.low,
                "c": f.close,
                "baseline": o.baseline,
                "c1": o.c1_state,
                "volume_gate": o.volume_gate,
            }
        return _clean_dict(
            {
                "config": cfg.model_dump(mode="json"),
                "config_digest": res.config_digest,
                "digest": res.digest()[:16],
                "summary": met.summary(),
                "metrics": asdict(met),
                "equity": [
                    [t.isoformat(), float(v)]
                    for t, v in zip(
                        pd.DatetimeIndex(res.equity.index), res.equity.to_numpy(), strict=True
                    )
                ],
                "trades": [asdict(t) for t in res.trades],
                "blocked": dict(res.blocked),
                "rejected": dict(res.rejected),
                "charts": charts,
            }
        )

    def research_state(self) -> dict[str, Any]:
        from nnfx.research.trials import ResearchState

        rs = ResearchState(self.research)
        try:
            thresholds: dict[str, Any] | str = rs.thresholds()
        except (OSError, ValueError) as e:
            thresholds = f"unavailable: {e}"
        trials = list(rs.trials.distinct().values())
        return _clean_dict(
            {
                "trial_count": rs.trial_count(),
                "validation_passes": rs.validation_passes(),
                "holdout": list(rs.holdout.distinct().values()),
                "trials": trials[-500:],
                "thresholds": thresholds,
            }
        )

    def live(self) -> dict[str, Any]:
        from nnfx.journal.journal import Journal

        jpath = self.live_state / "journal.jsonl"
        cycles: list[dict[str, Any]] = []
        if jpath.exists():
            cycles = [r for r in Journal(jpath).records() if r.get("type") == "cycle"][-60:]
        reports = []
        if self.reports.exists():
            for p in sorted(self.reports.glob("*.md"))[-30:]:
                reports.append({"name": p.name, "text": p.read_text(encoding="utf-8")})
        broker = self.live_state / "paper_broker.json"
        return _clean_dict(
            {
                "journal": str(jpath.relative_to(self.root)),
                "cycles": cycles,
                "reports": reports,
                "broker": json.loads(broker.read_text()) if broker.exists() else None,
            }
        )


def _index_html() -> bytes:
    return resources.files("nnfx.ui").joinpath("static/index.html").read_bytes()


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "nnfx-ui"

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any) -> None:
            self._send(code, json.dumps(obj, allow_nan=False).encode())

        def _dispatch(self, fn: Any, *a: Any) -> None:
            try:
                self._json(200, fn(*a))
            except PermissionError as e:
                self._json(403, {"error": str(e)})
            except (ValueError, KeyError, FileNotFoundError) as e:
                self._json(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:
                self._json(
                    500, {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}
                )

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            routes = {
                "/api/datasets": app.datasets,
                "/api/catalogue": app.catalogue,
                "/api/config": app.config,
                "/api/research": app.research_state,
                "/api/live": app.live,
            }
            if path in ("/", "/index.html"):
                self._send(200, _index_html(), "text/html; charset=utf-8")
            elif path in routes:
                self._dispatch(routes[path])
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError as e:
                self._json(400, {"error": f"bad JSON: {e}"})
                return
            if path == "/api/backtest":
                self._dispatch(app.backtest, body)
            else:
                self._json(404, {"error": "not found"})

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(app))
