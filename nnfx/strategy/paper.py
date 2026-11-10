"""Paper runs of a Strategy Document on live bars (Strategy Builder ticket 22, ADR 10 §26).

A paper run is the live harness (ticket 27) with the document engine: every cycle fetches the
closed bars, compiles the document over them, and lets ``LiveHarness`` apply the new bars to a
persistent ``PaperBroker`` and journal each step. State lives on disk (broker, journal and
``run.json``), never in memory, so a restarted server resumes every running run and decides
exactly as an uninterrupted one (the parity test restarts on every bar).

Alerts are derived from the journaled cycles and handed to the ``Notifier``, which never raises
and never waits for a channel, so a Bale outage cannot change or delay a decision.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import pandas as pd

from nnfx.alerts import Alert, Notifier, alerts_from_cycle, book_alert, halt_alert, owner_hash
from nnfx.brokers.costs import CostModel
from nnfx.brokers.paper import PaperBroker
from nnfx.brokers.sim import Trade
from nnfx.config import SystemConfig
from nnfx.data.bars import TIMEFRAMES, BarFrame
from nnfx.data.feeds import BarFeed
from nnfx.harness.conversion import Conversion
from nnfx.harness.live import LiveHarness
from nnfx.instruments import InstrumentRegistry, InstrumentSpec
from nnfx.journal.journal import Journal
from nnfx.orderbook.sources import BOOK_HISTORY
from nnfx.strategy.analytics import journal_report, journal_rows
from nnfx.strategy.book import BookData
from nnfx.strategy.document import StrategyDocument, validate_document
from nnfx.strategy.engine import DocumentEngine, compile_document
from nnfx.strategy.run import book_gaps, document_config, stale_books

BarSource = Callable[[str, pd.Timestamp], BarFrame]
MAX_RUNS = 3  # running paper runs per user
MAX_SYMBOLS = 5
TRANSIENT_ROUNDS = 3  # consecutive rounds with the bar source unreachable before a run errors


def paper_symbols(reg: InstrumentRegistry) -> list[str]:
    """The symbols a Paper Run may trade: Nobitex ``/USDT`` pairs (the account is in USDT).

    The order-book recorder must record exactly these (same names), so their books exist.
    """
    return [s for s in reg.basket("nobitex") if s.endswith("/USDT")]


class PaperError(ValueError):
    """A request the user can fix; the message is shown as is (Persian)."""


@dataclass(frozen=True)
class PaperRunInfo:
    id: str
    owner: str
    name: str  # the saved strategy it came from
    version: int
    symbols: list[str]
    created: str
    document: dict[str, Any]
    status: str = "running"  # running | stopped | error
    error: str = ""
    last_cycle: str = ""  # the latest bar processed
    alerted_through: str = ""  # the latest cycle whose alerts were handed over
    # Stretches of the recent window with no fresh order-book snapshot (order-book Blocks only).
    book_gaps: list[dict[str, str]] = field(default_factory=list)
    # Symbols whose books are stale as of the latest cycle (one alert per outage, ticket 26).
    book_stale: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        d = asdict(self)
        del d["document"], d["owner"], d["alerted_through"]
        return d


class LiveBars:
    """Closed M15 bars from Nobitex, fetched in full once and then only what is new."""

    def __init__(
        self, feed: BarFeed | None = None, *, timeframe: str = "M15", history_bars: int = 3000
    ) -> None:
        from nnfx.data.udf import nobitex

        self.feed = feed or nobitex(timeframe=timeframe)
        self.timeframe, self.history = timeframe, history_bars
        self._cache: dict[str, BarFrame] = {}

    def __call__(self, symbol: str, now: pd.Timestamp) -> BarFrame:
        bar = TIMEFRAMES[self.timeframe]
        have = self._cache.get(symbol)
        start = now - self.history * bar if have is None else have.index[-1] - 2 * bar
        new = self.feed.bars(symbol, start, now)
        if have is None or not len(have):
            merged = new
        else:  # the last bars are fetched again so a late correction replaces them
            df = pd.concat([have.df, new.df])
            df = df[~df.index.duplicated(keep="last")].sort_index().iloc[-self.history :]
            merged = BarFrame(
                df,
                symbol,
                timeframe=self.timeframe,
                volume_kind=new.volume_kind,
                price_venue=new.price_venue,
            )
        self._cache[symbol] = merged
        return merged.between(None, now)


@dataclass(frozen=True)
class BookWatch:
    """What a cycle learned about the order book: gaps, who is stale now, and what to announce."""

    gaps: list[dict[str, str]] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)


class PaperManager:
    def __init__(
        self,
        root: Path,
        instruments: Mapping[str, InstrumentSpec],
        bars: BarSource,
        notifier: Notifier,
        *,
        config: SystemConfig | None = None,
        costs: CostModel | None = None,
        book: BookData | None = None,
        gates: bool = True,
    ) -> None:
        self.root = root
        self.instruments = dict(instruments)
        self.bars = bars
        self.notifier = notifier
        self.config, self.costs, self.book, self.gates = config, costs, book, gates
        self._lock = threading.Lock()
        self._misses: dict[str, int] = {}

    # --------------------------------------------------------------- storage
    def run_dir(self, owner: str, run_id: str) -> Path:
        return self.root / owner_hash(owner) / run_id

    def _save(self, info: PaperRunInfo) -> None:
        d = self.run_dir(info.owner, info.id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "run.tmp"
        tmp.write_text(json.dumps(asdict(info), ensure_ascii=False), encoding="utf-8")
        tmp.replace(d / "run.json")

    def _all(self) -> list[PaperRunInfo]:
        out = []
        for p in sorted(self.root.glob("*/*/run.json")) if self.root.exists() else []:
            try:
                out.append(PaperRunInfo(**json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError):
                continue
        return sorted(out, key=lambda r: (r.created, r.id))

    def runs(self, owner: str) -> list[PaperRunInfo]:
        return [r for r in self._all() if r.owner == owner]

    def _get(self, owner: str, run_id: str) -> PaperRunInfo:
        for r in self.runs(owner):
            if r.id == run_id:
                return r
        raise PaperError("اجرای کاغذی پیدا نشد")

    # ------------------------------------------------------------- start/stop
    def start(
        self, owner: str, name: str, version: int, raw: Any, symbols: list[str]
    ) -> PaperRunInfo:
        res = validate_document(raw)
        if res.document is None:
            raise PaperError("سند معتبر نیست: " + "؛ ".join(i.message for i in res.issues[:3]))
        if not symbols or len(symbols) > MAX_SYMBOLS or len(set(symbols)) != len(symbols):
            raise PaperError(f"یک تا {MAX_SYMBOLS} نماد (بدون تکرار) انتخاب کنید")
        unknown = [s for s in symbols if s not in self.instruments]
        if unknown:
            raise PaperError(f"نماد ناشناخته: {unknown[0]}")
        with self._lock:
            if sum(r.status == "running" for r in self.runs(owner)) >= MAX_RUNS:
                raise PaperError(f"حداکثر {MAX_RUNS} اجرای کاغذی هم‌زمان مجاز است")
            info = PaperRunInfo(
                uuid.uuid4().hex[:12],
                owner,
                name,
                int(version),
                list(symbols),
                pd.Timestamp.now(tz="UTC").isoformat(),
                res.document.model_dump(mode="json"),
            )
            self._save(info)
        return info

    def stop(self, owner: str, run_id: str) -> None:
        with self._lock:
            info = self._get(owner, run_id)
            if info.status == "running":
                self._save(replace(info, status="stopped"))

    # ---------------------------------------------------------------- journal
    def journal(self, owner: str, run_id: str, now: pd.Timestamp | None = None) -> dict[str, Any]:
        """The run's trade journal, statistics and review status (forward trades: all of them).

        The adverse excursion needs the bars; it is left out for a trade the bar source no
        longer reaches or when the source is down.
        """
        info = self._get(owner, run_id)
        d = self.run_dir(owner, run_id)
        try:
            state = json.loads((d / "broker.json").read_text(encoding="utf-8"))
            trades = [Trade(**t) for t in state.get("trades", [])]
        except (OSError, ValueError):
            trades = []
        cycles = list(Journal(d / "journal.jsonl").records("cycle"))
        try:
            at = now or pd.Timestamp.now(tz="UTC")
            frames: dict[str, BarFrame] | None = {s: self.bars(s, at) for s in info.symbols}
        except OSError:
            frames = None
        lwc = TIMEFRAMES[str(info.document["timeframes"]["lwc"])]
        rows = journal_rows(trades, cycles, frames, source="paper", bar=lwc)
        return journal_report(rows, forward=len(rows))  # every paper trade is a forward trade

    # ------------------------------------------------------------------ cycle
    def tick(self, now: pd.Timestamp) -> None:
        """One cycle for every running run; one run's failure never reaches another."""
        for info in self._all():
            if info.status != "running":
                continue
            lwc = TIMEFRAMES[str(info.document["timeframes"]["lwc"])]
            if info.last_cycle and pd.Timestamp(info.last_cycle) >= now.floor(lwc):
                continue  # the latest closed bar is already in
            try:
                self._cycle(info, now)
                self._misses.pop(info.id, None)
            except OSError as e:  # the bar source is unreachable: wait, give up after a few rounds
                n = self._misses[info.id] = self._misses.get(info.id, 0) + 1
                if n >= TRANSIENT_ROUNDS:
                    self._fail(info, now, f"{type(e).__name__}: {e}")
            except Exception as e:
                self._fail(info, now, f"{type(e).__name__}: {e}")

    def _fail(self, info: PaperRunInfo, now: pd.Timestamp, reason: str) -> None:
        with self._lock:
            cur = self._get(info.owner, info.id)
            if cur.status != "running":
                return
            self._save(replace(cur, status="error", error=reason))
        self.notifier.submit(info.owner, [halt_alert(info.id, now.isoformat(), reason)])

    def _cycle(self, info: PaperRunInfo, now: pd.Timestamp) -> None:
        if self._get(info.owner, info.id).status != "running":
            return  # stopped since this round began
        doc = StrategyDocument.model_validate(info.document)
        frames = {s: self.bars(s, now) for s in info.symbols}
        if any(not len(f) for f in frames.values()):
            return  # no closed bar yet
        inst = {s: self.instruments[s] for s in info.symbols}
        cfg = document_config(doc, self.config)
        if self.book is not None:
            self.book.refresh(now, BOOK_HISTORY)  # what the recorder wrote since the last cycle
        compiled = compile_document(doc, frames, inst, cfg.session, None, self.book)
        watch = BookWatch()
        if compiled.book_blocks and self.book is not None:
            first = max(min(f.index[0] for f in frames.values()), now - BOOK_HISTORY)
            gaps = book_gaps(compiled, frames, self.book, first, None)
            stale = stale_books(compiled, frames, self.book)
            before = set(info.book_stale)
            alerts = [
                book_alert(info.id, t.isoformat(), s, True)
                for s, t in stale.items()
                if s not in before
            ] + [
                book_alert(info.id, frames[s].index[-1].isoformat(), s, False)
                for s in sorted(before - set(stale))
                if s in frames
            ]
            watch = BookWatch(gaps, sorted(stale), alerts)
        d = self.run_dir(info.owner, info.id)
        costs = self.costs.with_toggles(cfg.costs) if self.costs else CostModel.zero()
        broker = PaperBroker(
            inst,
            costs,
            cfg.account.initial_equity,
            cfg.account.currency,
            Conversion(cfg.account.currency, frames),
            state_path=d / "broker.json",
        )
        harness = LiveHarness(
            cfg,
            inst,
            info.symbols,
            lambda s, _now: frames[s],
            broker,
            Journal(d / "journal.jsonl"),
            clock=lambda: now,
            run_gates=self.gates,
            engine=DocumentEngine(compiled),
        )
        report = harness.run_cycle()
        self._announce(info, now, report.halted, watch)

    def _announce(
        self, info: PaperRunInfo, now: pd.Timestamp, halted: str | None, watch: BookWatch
    ) -> None:
        """Hand the new cycles' alerts over, then remember how far we got."""
        cycles = list(Journal(self.run_dir(info.owner, info.id) / "journal.jsonl").records("cycle"))
        symbols = {
            s["key"]: s["symbol"] for c in cycles for s in c.get("submitted", []) if "key" in s
        }
        through = pd.Timestamp(info.alerted_through) if info.alerted_through else None
        fresh = [c for c in cycles if through is None or pd.Timestamp(c["time"]) > through]
        for c in fresh:
            self.notifier.submit(info.owner, alerts_from_cycle(info.id, c, symbols))
        self.notifier.submit(info.owner, watch.alerts)
        with self._lock:
            cur = self._get(info.owner, info.id)
            if cur.status == "running":
                last = cycles[-1]["time"] if cycles else cur.last_cycle
                self._save(
                    replace(
                        cur,
                        last_cycle=last,
                        alerted_through=last,
                        book_gaps=watch.gaps,
                        book_stale=watch.stale,
                    )
                )
        if halted:
            self._fail(info, now, halted)
