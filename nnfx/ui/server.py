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
import threading
import traceback
from collections.abc import Callable, Mapping
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.config import SystemConfig, load_system_config
from nnfx.data.bars import BASE_TIMEFRAMES, BarFrame
from nnfx.data.feeds import read_bars_csv
from nnfx.data.session import resample_to_daily
from nnfx.instruments import InstrumentRegistry
from nnfx.ui.auth import Auth, AuthError, User

COOKIE = "nnfx_session"
MAX_BODY = 64 * 1024


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
        rules: str = "research/tcp_rules.yaml",
        auth: Auth | None = None,
        secure_cookies: bool = False,
        max_concurrent_backtests: int = 2,
        trust_proxy: bool = False,
    ) -> None:
        self.auth = auth
        self.trust_proxy = trust_proxy
        self.secure_cookies = secure_cookies
        self.rules_path = root.resolve() / rules
        self._bt_slots = threading.BoundedSemaphore(max_concurrent_backtests)
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
                tf = parts[1] if len(parts) > 2 and parts[1] in ("D1", *BASE_TIMEFRAMES) else "D1"
                sym = parts[0]
                if "_" in sym:  # cached crypto names: BTC_USDT_USDT -> BTC/USDT:USDT
                    bits = sym.split("_")
                    sym = f"{bits[0]}/{bits[1]}" + (f":{bits[2]}" if len(bits) > 2 else "")
                rel = p.relative_to(self.root) if p.is_relative_to(self.root) else p
                out.append({"path": str(rel), "symbol": sym, "timeframe": tf})
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
            if tf in BASE_TIMEFRAMES:
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

    def rules(self) -> dict[str, Any]:
        import yaml

        data: dict[str, Any] = yaml.safe_load(self.rules_path.read_text(encoding="utf-8"))
        return data

    def backtest_limited(self, req: Mapping[str, Any]) -> dict[str, Any]:
        return self._limited(self.backtest, req)

    def _limited(
        self, fn: Callable[[Mapping[str, Any]], dict[str, Any]], req: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not self._bt_slots.acquire(timeout=30):
            raise RuntimeError("سرور مشغول است؛ چند لحظه بعد دوباره امتحان کنید")
        try:
            return fn(req)
        finally:
            self._bt_slots.release()

    # ------------------------------------------------------ Strategy Builder
    def strategy_blocks(self) -> list[dict[str, Any]]:
        from nnfx.strategy import block_catalogue

        return block_catalogue()

    def strategy_validate(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.strategy import validate_document

        res = validate_document(req.get("document"))
        if res.document is None:
            return {"ok": False, "issues": [asdict(i) for i in res.issues]}
        return {
            "ok": True,
            "fingerprint": res.document.fingerprint(),
            "document": res.document.model_dump(mode="json"),
        }

    def strategy_backtest(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.journal.journal import Journal
        from nnfx.research.metrics import compute_metrics
        from nnfx.research.trials import ResearchState
        from nnfx.strategy import validate_document
        from nnfx.strategy.run import backtest_document

        res = validate_document(req.get("document"))
        doc = res.document
        if doc is None:
            return {"ok": False, "issues": [asdict(i) for i in res.issues]}
        reg = InstrumentRegistry.load(self.instruments_path)
        frames: dict[str, BarFrame] = {}
        inst = {}
        for ds in req.get("datasets") or []:
            sym, tf = ds["symbol"], ds.get("timeframe", doc.timeframes.lwc)
            spec = reg.spec(sym)
            frames[sym] = read_bars_csv(
                self._safe_path(ds["path"]), sym, timeframe=tf, volume_kind=spec.volume_kind
            )
            inst[sym] = spec
        if not frames:
            raise ValueError("pick at least one dataset")
        costs = None if req.get("zero_costs") else CostModel.from_venue(self.venue_path)
        journal = Journal()
        run = backtest_document(
            doc,
            frames,
            inst,
            costs=costs,
            journal=journal,
            research=ResearchState(self.research),
            stage="strategy/ui",
        )
        r = run.result
        met = compute_metrics(r.trades, r.equity, volume_flags=r.volume_flags, r_per_entry=1.0)
        candidates = [ev for rec in journal.records("cycle") for ev in rec["evaluations"]]
        return _clean_dict(
            {
                "ok": True,
                "fingerprint": run.fingerprint,
                "config_digest": r.config_digest,
                "trial_id": run.trial_id,
                "summary": met.summary(),
                "trades": [asdict(t) for t in r.trades],
                "candidates": len(candidates),
                "blocked": dict(r.blocked),
                "rejected": dict(r.rejected),
                "equity": [
                    [t.isoformat(), float(v)]
                    for t, v in zip(
                        pd.DatetimeIndex(r.equity.index), r.equity.to_numpy(), strict=True
                    )
                ],
            }
        )

    # ------------------------------------------------------------ beta accounts
    def _accounts(self) -> Auth:
        if self.auth is None:
            raise KeyError("accounts are not enabled on this server")
        return self.auth

    def _require_admin(self, user: User | None) -> Auth:
        auth = self._accounts()
        if user is None or not user.is_admin:
            raise PermissionError("فقط مدیر")
        return auth

    def add_feedback(self, user: User, body: Mapping[str, Any]) -> dict[str, bool]:
        self._accounts().add_feedback(user, str(body.get("text", "")), str(body.get("page", "")))
        return {"ok": True}

    def admin_feedback(self, user: User | None) -> list[dict[str, object]]:
        return self._require_admin(user).feedback()

    def admin_invites(self, user: User | None) -> list[dict[str, str | None]]:
        return [
            {"code": c, "note": n, "used_by": u} for c, n, u in self._require_admin(user).invites()
        ]

    def create_invites(self, user: User | None, body: Mapping[str, Any]) -> dict[str, list[str]]:
        n = min(max(int(body.get("n", 1)), 1), 50)
        return {
            "codes": self._require_admin(user).create_invites(n, str(body.get("note", ""))[:100])
        }

    def research_state(self) -> dict[str, Any]:
        from nnfx.research.trials import ResearchState

        rs = ResearchState(self.research)
        try:
            thresholds: dict[str, Any] | str = rs.thresholds()
        except (OSError, ValueError) as e:
            thresholds = f"unavailable: {e}"
        trials = list(rs.trials.distinct().values())
        prereg: dict[str, Any] | None = None
        pre_path = self.research / "tcp_prereg.frozen.json"
        if pre_path.exists():
            from nnfx.research.prereg import Prereg, PreregError

            try:
                p = Prereg(pre_path, self.root)
                prereg = {
                    "frozen_on": p.data["frozen_on"],
                    "budgets": {
                        g: {"budget": b, "remaining": p.remaining(rs, g)}
                        for g, b in p.data["trial_budget"].items()
                        if g in p.data["hypotheses"]
                    },
                }
            except (PreregError, OSError, KeyError) as e:
                prereg = {"frozen_on": "?", "error": str(e)}
        return _clean_dict(
            {
                "trial_count": rs.trial_count(),
                "validation_passes": rs.validation_passes(),
                "holdout": list(rs.holdout.distinct().values()),
                "trials": trials[-500:],
                "prereg": prereg,
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
    public_get = {"/", "/index.html", "/api/me"}
    public_post = {"/api/login", "/api/signup", "/api/logout"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "nnfx-ui"

        def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
            pass

        def _send(
            self,
            code: int,
            body: bytes,
            ctype: str = "application/json",
            headers: Mapping[str, str] | None = None,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: Any, headers: Mapping[str, str] | None = None) -> None:
            self._send(code, json.dumps(obj, allow_nan=False).encode(), headers=headers)

        def _dispatch(self, fn: Any, *a: Any) -> None:
            try:
                self._json(200, fn(*a))
            except AuthError as e:
                self._json(400, {"error": str(e)})
            except PermissionError as e:
                self._json(403, {"error": str(e)})
            except (ValueError, KeyError, FileNotFoundError) as e:
                self._json(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:
                body: dict[str, str] = {"error": f"{type(e).__name__}: {e}"}
                if app.auth is None:  # local single-user mode only: never leak traces to beta users
                    body["trace"] = traceback.format_exc()
                self._json(500, body)

        # ------------------------------------------------------------ auth
        def _token(self) -> str | None:
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c[COOKIE].value if COOKIE in c else None

        def _user(self) -> User | None:
            if app.auth is None:
                return User(0, "local", True)
            return app.auth.user_for(self._token())

        def _client(self) -> str:
            fwd = self.headers.get("X-Forwarded-For") if app.trust_proxy else None
            return fwd.split(",")[0].strip() if fwd else self.client_address[0]

        def _cookie(self, token: str, max_age: int) -> dict[str, str]:
            secure = "; Secure" if app.secure_cookies else ""
            return {
                "Set-Cookie": f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}{secure}"
            }

        def _guard(self, path: str, public: set[str]) -> User | None:
            user = self._user()
            if user is None and path not in public:
                self._json(401, {"error": "ابتدا وارد شوید", "login": True})
            return user

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            user = self._guard(path, public_get)
            if user is None and path not in public_get:
                return
            routes = {
                "/api/datasets": app.datasets,
                "/api/catalogue": app.catalogue,
                "/api/config": app.config,
                "/api/research": app.research_state,
                "/api/live": app.live,
                "/api/rules": app.rules,
                "/api/strategy/blocks": app.strategy_blocks,
            }
            if path in ("/", "/index.html"):
                self._send(200, _index_html(), "text/html; charset=utf-8")
            elif path == "/api/me":
                self._json(
                    200,
                    {
                        "user": user.username if user else None,
                        "admin": bool(user and user.is_admin),
                        "auth": app.auth is not None,
                    },
                )
            elif path == "/api/admin/feedback":
                self._dispatch(app.admin_feedback, user)
            elif path == "/api/admin/invites":
                self._dispatch(app.admin_invites, user)
            elif path in routes:
                self._dispatch(routes[path])
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                self._json(413, {"error": "request too large"})
                return
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError as e:
                self._json(400, {"error": f"bad JSON: {e}"})
                return
            if app.auth is not None and path in public_post:
                self._auth_post(path, body)
                return
            user = self._guard(path, set())
            if user is None:
                return
            if path == "/api/backtest":
                self._dispatch(app.backtest_limited, body)
            elif path == "/api/strategy/validate":
                self._dispatch(app.strategy_validate, body)
            elif path == "/api/strategy/backtest":
                self._dispatch(app._limited, app.strategy_backtest, body)
            elif path == "/api/feedback":
                self._dispatch(app.add_feedback, user, body)
            elif path == "/api/admin/invites":
                self._dispatch(app.create_invites, user, body)
            else:
                self._json(404, {"error": "not found"})

        def _auth_post(self, path: str, body: Mapping[str, Any]) -> None:
            auth = app.auth
            assert auth is not None
            try:
                if path == "/api/logout":
                    auth.logout(self._token())
                    self._json(200, {"ok": True}, self._cookie("", 0))
                    return
                if path == "/api/signup":
                    auth.signup(
                        str(body.get("invite", "")).strip(),
                        str(body.get("username", "")).strip(),
                        str(body.get("password", "")),
                    )
                token = auth.login(
                    str(body.get("username", "")).strip(),
                    str(body.get("password", "")),
                    self._client(),
                )
                self._json(200, {"ok": True}, self._cookie(token, 30 * 86400))
            except AuthError as e:
                self._json(400, {"error": str(e)})

    return Handler


def serve(app: App, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(app))
