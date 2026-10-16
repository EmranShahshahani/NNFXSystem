"""Live harness: the daily cycle (doc 02 §6, ticket 27).

Once, shortly after the session close: fetch -> verify -> load state ->
reconcile -> process the new bar -> reconcile -> evaluate -> size/approve ->
submit -> journal -> report. State lives in the journal and the broker, never
in memory, so the process may be killed at any point and simply re-run:
bars are never applied twice and order keys make resubmission a no-op.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from nnfx.brokers.paper import PaperBroker
from nnfx.config import SystemConfig
from nnfx.data.bars import BarFrame, BarFrameError
from nnfx.data.gates import ensure_clean
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import EngineState
from nnfx.harness.loop import StepReport, TradingLoop
from nnfx.indicators.slots import IndicatorSet
from nnfx.instruments import InstrumentSpec
from nnfx.journal.journal import Journal

BarSource = Callable[[str, pd.Timestamp], BarFrame]
Clock = Callable[[], pd.Timestamp]


class ReconciliationError(RuntimeError):
    pass


@dataclass
class DailyReport:
    run_at: str
    processed: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    open_risk: float = 0.0
    equity: float = 0.0
    expected_equity: float | None = None
    funding_or_swap: float = 0.0
    halted: str | None = None

    def render(self) -> str:
        lines = [f"# Daily report - run at {self.run_at}", ""]
        if self.halted:
            lines += [f"**HALTED:** {self.halted}", ""]
        lines.append(f"Bars processed: {', '.join(self.processed) or 'none (no new bar)'}")
        exp = (
            f" (backtest expectation {self.expected_equity:,.2f})"
            if self.expected_equity is not None
            else ""
        )
        lines.append(
            f"Equity: {self.equity:,.2f}{exp}; open risk: {self.open_risk:,.2f}; accrued carry: {self.funding_or_swap:+,.2f}"
        )
        lines += ["", "## Decisions"]
        lines += [
            f"- {d['time']} {d['symbol']}: {d['phase']} intents={d['intents']}"
            for d in self.decisions
        ] or ["- none"]
        lines += ["", "## Orders placed"]
        lines += [f"- {o['key']} {o['status']} units={o['units']}" for o in self.orders] or [
            "- none"
        ]
        lines += ["", "## Blocked by rules"]
        lines += [f"- {b}" for b in self.blocked] or ["- none"]
        lines += [f"- rejected {r['key']}: {r['reason']}" for r in self.rejected]
        return "\n".join(lines) + "\n"


class LiveHarness:
    def __init__(
        self,
        config: SystemConfig,
        instruments: Mapping[str, InstrumentSpec],
        symbols: Sequence[str],
        bars: BarSource,
        broker: PaperBroker,
        journal: Journal,
        clock: Clock,
        *,
        alert: Callable[[str], None] | None = None,
        expected_equity: pd.Series | None = None,
        report_dir: Path | None = None,
        run_gates: bool = True,
    ) -> None:
        self.config = config
        self.instruments = dict(instruments)
        self.symbols = sorted(symbols)
        self.bars = bars
        self.broker = broker
        self.journal = journal
        self.clock = clock
        self.alert = alert or (lambda msg: None)
        self.expected_equity = expected_equity
        self.report_dir = report_dir
        self.run_gates = run_gates
        self.indicators = IndicatorSet(config.slots)

    # ------------------------------------------------------------ reconcile
    def _expected_after_events(self, last: dict[str, Any] | None) -> dict[str, float]:
        expected = {p["id"]: float(p["units"]) for p in (last or {}).get("positions", [])}
        # A key we submitted is ours whether the venue accepted it then or reported it as a
        # duplicate on a resubmission after a restart.
        ours = {
            s["key"]
            for c in self.journal.records("cycle")
            for s in c.get("submitted", [])
            if s.get("status") in ("accepted", "duplicate")
        }
        seq = int((last or {}).get("broker_event_seq", 0))
        for ev in self.broker.s.events[seq:]:
            if ev["e"] == "fill":
                if ev["key"] not in ours:
                    continue  # unknown fill: left out so the comparison flags it
                expected[ev["pid"]] = float(ev["units"])
            elif ev["e"] == "close" and ev["pid"] in expected:
                expected[ev["pid"]] -= float(ev["units"])
                if expected[ev["pid"]] <= 1e-12:
                    del expected[ev["pid"]]
        return expected

    def reconcile(self, last: dict[str, Any] | None) -> None:
        expected = self._expected_after_events(last)
        actual = {p.id: p.units for p in self.broker.positions()}
        problems = []
        for pid in sorted(set(expected) | set(actual)):
            e, a = expected.get(pid), actual.get(pid)
            if e is None:
                problems.append(f"broker reports unknown position {pid} ({a} units)")
            elif a is None:
                problems.append(f"expected position {pid} ({e} units) missing at broker")
            elif abs(e - a) > 1e-9 * max(1.0, abs(e)):
                problems.append(f"{pid}: expected {e} units, broker has {a}")
        if problems:
            msg = "reconciliation failed - halting: " + "; ".join(problems)
            self.journal.append({"type": "halt", "reason": msg, "run_at": self.clock().isoformat()})
            self.alert(msg)
            raise ReconciliationError(msg)

    # --------------------------------------------------------------- cycle
    def run_cycle(self) -> DailyReport:
        now = self.clock()
        report = DailyReport(run_at=now.isoformat())
        frames: dict[str, BarFrame] = {}
        for s in self.symbols:
            f = self.bars(s, now)
            if len(f) and f.index[-1] > now:
                raise BarFrameError(
                    "partial_final_bar", s, [f.index[-1]], f"bar closes after now={now}"
                )
            if self.run_gates:
                ensure_clean(f, self.instruments[s], close_tz=self.config.session.close_tz)
            frames[s] = f

        last = self.journal.last("cycle")
        state = EngineState.model_validate(last["state"]) if last else EngineState()
        try:
            self.reconcile(last)
        except ReconciliationError as exc:
            report.halted = str(exc)
            return self._finish(report)

        loop = TradingLoop(self.config, self.instruments, self.broker, self.journal, state=state)
        last_time = pd.Timestamp(last["time"]) if last else None
        new_times = sorted(
            {t for f in frames.values() for t in f.index if last_time is None or t > last_time}
        )
        if last_time is None and new_times:
            new_times = new_times[-1:]  # first ever cycle: start from the latest bar
        for ts in new_times:
            histories: dict[str, SymbolHistory] = {}
            for s, f in frames.items():
                if ts not in f.index:
                    continue
                hist_f = f.between(None, ts)
                h = SymbolHistory.from_frame(
                    hist_f, self.indicators.compute(hist_f), self.instruments[s]
                )
                extras = {
                    c: hist_f.column(c)
                    for c in ("mark_high", "mark_low", "funding")
                    if hist_f.has(c)
                }
                loop.feed_bar(h, extras)
                histories[s] = h
            try:
                self.reconcile(self.journal.last("cycle"))
            except ReconciliationError as exc:
                report.halted = str(exc)
                return self._finish(report)
            step = loop.decide(ts, histories)
            self._add(report, step)
        report.equity = self.broker.equity()
        if self.expected_equity is not None and len(self.expected_equity):
            k = self.expected_equity.index.searchsorted(now, side="right") - 1
            report.expected_equity = float(self.expected_equity.iloc[max(int(k), 0)])
        return self._finish(report)

    def _add(self, report: DailyReport, step: StepReport) -> None:
        report.processed.append(step.time)
        for ev in step.evaluations:
            report.decisions.append(
                {
                    "time": ev.time,
                    "symbol": ev.symbol,
                    "phase": ev.state_after.phase.value,
                    "intents": [i.kind for i in ev.intents],
                }
            )
            report.blocked += [f"{ev.time} {ev.symbol}: {b}" for b in ev.blocked]
        report.orders += step.submitted
        report.rejected += step.rejected

    def _finish(self, report: DailyReport) -> DailyReport:
        b = self.broker
        risk = 0.0
        carry = 0.0
        for p in b.s.positions.values():
            risk += (
                max(0.0, (p.entry_price - p.stop) * p.direction)
                * p.units
                * float(self.instruments[p.symbol].value_per_price_unit)
                * b.s.last_conv.get(p.symbol, 1.0)
            )
            carry += p.carry
        report.open_risk = risk
        report.funding_or_swap = carry
        report.equity = b.equity()
        if self.report_dir is not None:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            name = report.run_at[:10] + ".md"
            (self.report_dir / name).write_text(report.render(), encoding="utf-8", newline="\n")
        return report
