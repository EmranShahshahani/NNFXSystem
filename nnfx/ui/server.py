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
import os
import re
import threading
import traceback
from collections.abc import Callable, Mapping
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from nnfx.alerts import AlertSettings, AlertStore, BaleSender, Notifier, default_post
from nnfx.brokers.costs import CostModel
from nnfx.config import SystemConfig, load_system_config
from nnfx.data.bars import BASE_TIMEFRAMES, BarFrame
from nnfx.data.feeds import read_bars_csv
from nnfx.data.session import resample_to_daily
from nnfx.instruments import InstrumentRegistry
from nnfx.orderbook import LiveRecordedOrderBook
from nnfx.strategy.analytics import journal_report
from nnfx.strategy.book import BookData
from nnfx.strategy.paper import LiveBars, PaperError, PaperManager, paper_symbols
from nnfx.strategy.store import StrategyStore
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


def _name_version(req: Mapping[str, Any]) -> tuple[str, int | None]:
    name, version = req.get("name"), req.get("version")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("نام استراتژی را بنویسید")
    if version is not None and (not isinstance(version, int) or isinstance(version, bool)):
        raise ValueError("شمارهٔ نسخه باید عدد صحیح باشد")
    return name, version


def _template_slugs() -> list[str]:
    from nnfx.strategy import TEMPLATES

    return list(TEMPLATES)


MAX_CANDIDATES = 500  # candidates returned per backtest (about 1 KB each)


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
        strategies: str = "runs/strategies",
        auth: Auth | None = None,
        secure_cookies: bool = False,
        max_concurrent_backtests: int = 2,
        trust_proxy: bool = False,
        paper: str = "runs/paper",
        alerts: str = "runs/alerts",
        paper_bars: Callable[[str, pd.Timestamp], BarFrame] | None = None,
        bale_token: str | None = None,
        bale_post: Callable[[str, dict[str, Any]], None] | None = None,
        orderbook: str | None = None,
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
        self.strategies = StrategyStore(self.root / strategies)
        self.paper_root = self.root / paper
        self.paper_bars = paper_bars
        # Where the order-book recorder writes; None: no recordings (paper runs see no book).
        self.orderbook_root = None if orderbook is None else self.root / orderbook
        token = bale_token if bale_token is not None else os.environ.get("NNFX_BALE_TOKEN", "")
        self.notifier = Notifier(
            AlertStore(self.root / alerts),
            BaleSender(token, post=bale_post or default_post) if token else None,
        )
        self._paper: PaperManager | None = None
        self._paper_lock = threading.Lock()

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
        return self.limited(self.backtest, req)

    def strategy_backtest_limited(self, req: Mapping[str, Any]) -> dict[str, Any]:
        return self.limited(self.strategy_backtest, req)

    def limited(
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

    def strategy_schema(self) -> dict[str, Any]:
        """The shapes of the document's non-Block sections, for the builder's forms."""
        from nnfx.data.bars import TIMEFRAMES
        from nnfx.strategy.document import ChecklistSection, RiskSection

        return {
            "risk": RiskSection.model_json_schema(),
            "checklist": ChecklistSection.model_json_schema(),
            "timeframes": {
                "all": list(TIMEFRAMES),
                "base": list(BASE_TIMEFRAMES),
                "roles": ["hwc", "mwc", "lwc", "management"],
            },
        }

    def strategy_documents(self, user: User) -> list[dict[str, Any]]:
        return self.strategies.list(user.username)

    def strategy_save(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.strategy import validate_document

        res = validate_document(req.get("document"))
        if res.document is None:
            return {"ok": False, "issues": [asdict(i) for i in res.issues]}
        saved = self.strategies.save(user.username, res.document)
        doc = self.strategies.load(user.username, saved.name, saved.version)
        return {"ok": True, **saved.record(), "document": doc.model_dump(mode="json")}

    def strategy_load(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        name, version = _name_version(req)
        doc = self.strategies.load(user.username, name, version)
        return {
            "ok": True,
            "document": doc.model_dump(mode="json"),
            "versions": self.strategies.versions(user.username, name),
        }

    def strategy_delete(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        name, _ = _name_version(req)
        self.strategies.delete(user.username, name)
        return {"ok": True}

    def _diff_base(
        self, user: User, doc: Any, base: Any
    ) -> tuple[Any, dict[str, Any]] | dict[str, Any]:
        """The document to diff against, and how it was found; or the issues of a bad base."""
        from nnfx.strategy import get_template, validate_document

        if base is None:
            slug = doc.metadata.parent
            if slug is None:
                raise ValueError(
                    "این سند والد ندارد؛ یک قالب یا نسخهٔ ذخیره‌شده را برای مقایسه انتخاب کنید"
                )
            base = (
                {"template": slug}
                if slug in _template_slugs()
                else {"name": slug, "version": doc.metadata.parent_version}
            )
        if not isinstance(base, Mapping):
            raise ValueError("مبنای مقایسه باید یک شیء باشد")
        if "document" in base:
            res = validate_document(base["document"])
            if res.document is None:
                return {"ok": False, "which": "base", "issues": [asdict(i) for i in res.issues]}
            return res.document, {"document": res.document.metadata.name}
        if "template" in base:
            try:
                t = get_template(str(base["template"]))
            except KeyError:
                raise ValueError(f"قالب «{base['template']}» شناخته نشده است") from None
            return t.document, {"template": t.slug, "version": t.version}
        name, version = _name_version(base)
        loaded = self.strategies.load(user.username, name, version)
        return loaded, {"name": name, "version": loaded.metadata.version}

    def strategy_diff(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.strategy import validate_document
        from nnfx.strategy.diff import diff_documents

        res = validate_document(req.get("document"))
        if res.document is None:
            return {"ok": False, "which": "document", "issues": [asdict(i) for i in res.issues]}
        found = self._diff_base(user, res.document, req.get("base"))
        if isinstance(found, dict):
            return found
        base_doc, how = found
        return _clean_dict(
            {"ok": True, "base": how, "changes": diff_documents(base_doc, res.document)}
        )

    def strategy_import(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.strategy import validate_document

        text = req.get("text")
        if not isinstance(text, str):
            raise ValueError("متن فایل باید به‌صورت رشته ارسال شود")

        def refuse(code: str, message: str) -> dict[str, Any]:
            return {"ok": False, "issues": [{"path": "", "code": code, "message": message}]}

        if not text.strip():
            return refuse("empty_file", "فایل خالی است.")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            return refuse(
                "bad_json", f"فایل JSON معتبر نیست (خط {e.lineno}، ستون {e.colno}): {e.msg}"
            )
        if not isinstance(raw, dict):
            return refuse("bad_value", "فایل باید یک شیء JSON باشد (نه فهرست یا عدد).")
        res = validate_document(raw)
        if res.document is None:
            return {"ok": False, "issues": [asdict(i) for i in res.issues]}
        return {
            "ok": True,
            "fingerprint": res.document.fingerprint(),
            "document": res.document.model_dump(mode="json"),
        }

    def strategy_compare_limited(self, req: Mapping[str, Any]) -> dict[str, Any]:
        return self.limited(self.strategy_compare, req)

    def strategy_compare(self, req: Mapping[str, Any]) -> dict[str, Any]:
        """Two documents on the same bars, their metrics side by side."""
        from nnfx.journal.journal import Journal
        from nnfx.research.trials import ResearchState
        from nnfx.strategy import validate_document
        from nnfx.strategy.diff import diff_documents
        from nnfx.strategy.run import backtest_document

        raws = req.get("documents")
        if not isinstance(raws, list) or len(raws) != 2:
            raise ValueError("برای مقایسه دقیقاً دو سند لازم است")
        docs = []
        for i, raw in enumerate(raws, 1):
            res = validate_document(raw)
            if res.document is None:
                return {"ok": False, "which": i, "issues": [asdict(x) for x in res.issues]}
            docs.append(res.document)
        a, b = docs
        if a.timeframes.lwc != b.timeframes.lwc:
            raise ValueError(
                f"تایم‌فریم اجرا (LWC) دو سند یکی نیست ({a.timeframes.lwc} و {b.timeframes.lwc}) "
                "و روی داده‌های یکسان اجرا نمی‌شوند"
            )
        frames, inst = self._strategy_frames(a.timeframes.lwc, req.get("datasets"))
        costs = None if req.get("zero_costs") else CostModel.from_venue(self.venue_path)
        research = ResearchState(self.research)
        runs = []
        for doc in docs:
            run = backtest_document(
                doc,
                frames,
                inst,
                costs=costs,
                journal=Journal(),
                research=research,
                stage="strategy/compare",
            )
            m = run.metrics()
            runs.append(
                {
                    "name": doc.metadata.name,
                    "fingerprint": run.fingerprint,
                    "trial_id": run.trial_id,
                    "trades": len(run.result.trades),
                    "candidates": len(run.candidates),
                    "summary": m.summary(),
                    "metrics": {
                        k: getattr(m, k)
                        for k in (
                            "n_entries",
                            "expectancy_r",
                            "win_rate",
                            "profit_factor",
                            "sharpe",
                            "sortino",
                            "max_drawdown",
                            "mar",
                            "total_return",
                            "longest_losing_streak",
                            "time_in_market",
                            "provisional",
                        )
                    },
                }
            )
        return _clean_dict(
            {
                "ok": True,
                "datasets": list(frames),
                "runs": runs,
                "changes": diff_documents(a, b),
            }
        )

    def strategy_templates(self) -> list[dict[str, Any]]:
        from nnfx.strategy import list_templates

        return list_templates(full=True)

    def strategy_clone(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.strategy import get_template

        try:
            t = get_template(str(req.get("template")))
        except KeyError:
            raise ValueError(f"قالب «{req.get('template')}» شناخته نشده است") from None
        name = req.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("نام باید متن غیرخالی باشد")
        return {"ok": True, "document": t.clone(name.strip() if name else None)}

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

    def _strategy_frames(
        self, lwc: str, datasets: Any
    ) -> tuple[dict[str, BarFrame], dict[str, Any]]:
        """The bars of the picked datasets, all on the document's LWC."""
        from nnfx.strategy.run import load_frames

        if not isinstance(datasets, list) or not datasets:
            raise ValueError("دست‌کم یک دیتاست انتخاب کنید")
        if len(datasets) > 20 or not all(isinstance(d, dict) for d in datasets):
            raise ValueError("دیتاست‌ها نامعتبرند (حداکثر ۲۰ مورد)")
        for ds in datasets:
            if ds.get("timeframe", lwc) != lwc:
                raise ValueError(
                    f"{ds['symbol']}: دیتاست {ds.get('timeframe')} است ولی LWC سند {lwc} است"
                )
        return load_frames(
            [(ds["symbol"], self._safe_path(ds["path"])) for ds in datasets],
            InstrumentRegistry.load(self.instruments_path),
            lwc,
        )

    def strategy_backtest(self, req: Mapping[str, Any]) -> dict[str, Any]:
        from nnfx.journal.journal import Journal
        from nnfx.research.trials import ResearchState
        from nnfx.strategy import validate_document
        from nnfx.strategy.run import backtest_document

        res = validate_document(req.get("document"))
        doc = res.document
        if doc is None:
            return {"ok": False, "issues": [asdict(i) for i in res.issues]}
        frames, inst = self._strategy_frames(doc.timeframes.lwc, req.get("datasets"))
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
        met = run.metrics()
        return _clean_dict(
            {
                "ok": True,
                "fingerprint": run.fingerprint,
                "config_digest": r.config_digest,
                "trial_id": run.trial_id,
                "summary": met.summary(),
                "trades": [
                    {**asdict(t), "stop_label": run.stop_labels.get(t.position_id)}
                    for t in r.trades
                ],
                # The latest candidates, each with its Pre-Trade Checklist, and the total.
                "candidates": run.candidates[max(0, len(run.candidates) - MAX_CANDIDATES) :],
                "candidate_count": len(run.candidates),
                # Futures-to-spot recycling record (Profit Chain option); empty when off.
                "spot_transfers": [asdict(t) for t in run.spot_transfers],
                "spot_balance": run.spot_balance(),
                # The blueprint's journal fields per position, statistics, review prompts.
                **journal_report(run.journal, forward=0),  # a backtest has no forward trades
                # A Market Filter lacked its series at some candidate (checked n/a): see ADR 10 §24.
                "incomplete": run.incomplete,
                "incomplete_blocks": run.incomplete_blocks,
                # The equity curve less the profit recorded as moved to spot.
                "equity_trading": (
                    [
                        [t.isoformat(), float(v)]
                        for t, v in zip(
                            pd.DatetimeIndex(r.equity.index),
                            run.split_equity()["trading"].to_numpy(),
                            strict=True,
                        )
                    ]
                    if run.spot_transfers
                    else []
                ),
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

    # ------------------------------------------------------- paper runs, alerts
    def _manager(self) -> PaperManager:
        with self._paper_lock:
            if self._paper is None:
                reg = InstrumentRegistry.load(self.instruments_path)
                specs = {s: reg.spec(s, "crypto_spot") for s in paper_symbols(reg)}
                self._paper = PaperManager(
                    self.paper_root,
                    specs,
                    self.paper_bars or LiveBars(),
                    self.notifier,
                    costs=CostModel.from_venue(self.venue_path),
                    book=(
                        None
                        if self.orderbook_root is None
                        else BookData(LiveRecordedOrderBook(self.orderbook_root))
                    ),
                )
            return self._paper

    def paper_tick(self, now: pd.Timestamp) -> None:
        """One cycle of every running paper run (the server's timer calls this)."""
        self._manager().tick(now)

    def paper_runs(self, user: User) -> dict[str, Any]:
        return {"runs": [r.public() for r in self._manager().runs(user.username)]}

    def paper_start(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        name, version = _name_version(req)
        doc = self.strategies.load(user.username, name, version)  # KeyError: not found
        saved = self.strategies.versions(user.username, name)
        symbols = req.get("symbols")
        if symbols is None:
            symbols = list(doc.universe)
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise ValueError("نمادها نامعتبرند")
        try:
            info = self._manager().start(
                user.username,
                name,
                version or int(saved[-1]["version"]),
                doc.model_dump(mode="json"),
                symbols,
            )
        except PaperError as e:
            raise ValueError(str(e)) from None
        return {"ok": True, "run": info.public()}

    def paper_stop(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        try:
            self._manager().stop(user.username, str(req.get("id", "")))
        except PaperError as e:
            raise ValueError(str(e)) from None
        return {"ok": True}

    def paper_journal(self, user: User, run_id: str) -> dict[str, Any]:
        try:
            return self._manager().journal(user.username, run_id)
        except PaperError as e:
            raise ValueError(str(e)) from None

    def alerts_feed(self, user: User, after: int = 0) -> dict[str, Any]:
        return {"alerts": self.notifier.store.feed(user.username, after)}

    def alert_settings(self, user: User) -> dict[str, Any]:
        s = self.notifier.store.settings(user.username)
        return {**asdict(s), "bale_available": self.notifier.bale is not None}

    def alert_settings_save(self, user: User, req: Mapping[str, Any]) -> dict[str, Any]:
        cur = self.notifier.store.settings(user.username)
        chat = str(req.get("bale_chat", cur.bale_chat)).strip()
        if chat and not re.fullmatch(r"-?\d{1,20}", chat):
            raise ValueError("شناسهٔ چت بله باید عدد باشد")
        new = AlertSettings(
            bool(req.get("in_site", cur.in_site)), bool(req.get("bale", cur.bale)), chat
        )
        if new.bale and not chat:
            raise ValueError("برای دریافت در بله شناسهٔ چت را وارد کنید")
        if new.bale and self.notifier.bale is None:
            raise ValueError("ربات بله روی این سرور تنظیم نشده است")
        self.notifier.store.set_settings(user.username, new)
        return {"ok": True, **asdict(new), "bale_available": self.notifier.bale is not None}

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
                "/api/strategy/templates": app.strategy_templates,
                "/api/strategy/schema": app.strategy_schema,
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
            elif path == "/api/strategy/documents" and user is not None:
                self._dispatch(app.strategy_documents, user)
            elif path == "/api/paper/runs" and user is not None:
                self._dispatch(app.paper_runs, user)
            elif path == "/api/paper/journal" and user is not None:
                q = parse_qs(urlparse(self.path).query)
                self._dispatch(app.paper_journal, user, q.get("id", [""])[0])
            elif path == "/api/alerts" and user is not None:
                q = parse_qs(urlparse(self.path).query)
                try:
                    after = int(q.get("after", ["0"])[0])
                except ValueError:
                    after = 0
                self._dispatch(app.alerts_feed, user, after)
            elif path == "/api/alerts/settings" and user is not None:
                self._dispatch(app.alert_settings, user)
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
            elif path == "/api/strategy/clone":
                self._dispatch(app.strategy_clone, body)
            elif path == "/api/strategy/validate":
                self._dispatch(app.strategy_validate, body)
            elif path == "/api/strategy/backtest":
                self._dispatch(app.strategy_backtest_limited, body)
            elif path == "/api/strategy/compare":
                self._dispatch(app.strategy_compare_limited, body)
            elif path == "/api/strategy/import":
                self._dispatch(app.strategy_import, body)
            elif path in (
                "/api/strategy/save",
                "/api/strategy/load",
                "/api/strategy/delete",
                "/api/strategy/diff",
            ):
                fn = getattr(app, "strategy_" + path.rsplit("/", 1)[1])
                self._dispatch(fn, user, body)
            elif path == "/api/paper/start":
                self._dispatch(app.paper_start, user, body)
            elif path == "/api/paper/stop":
                self._dispatch(app.paper_stop, user, body)
            elif path == "/api/alerts/settings":
                self._dispatch(app.alert_settings_save, user, body)
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
