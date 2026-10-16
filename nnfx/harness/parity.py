"""Parity harness: live decisions must equal backtest decisions, every day (doc 03 §9, ticket 28).

The live harness is restarted from disk for every day - a fresh process
image each time - and computes indicators on truncated history; the backtest
uses precomputed arrays. Any difference in any decision is a bug and blocks
progress. Zero exceptions.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.brokers.paper import PaperBroker
from nnfx.config import SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.harness.backtest import BacktestHarness
from nnfx.harness.conversion import Conversion
from nnfx.harness.live import LiveHarness
from nnfx.instruments import InstrumentSpec
from nnfx.journal.journal import Journal

COMPARED = ("time", "evaluations", "state", "positions", "submitted", "rejected", "equity")


@dataclass
class ParityReport:
    days: int
    divergences: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.divergences and self.days > 0

    def render(self) -> str:
        if self.ok:
            return f"PARITY OK: {self.days} days, identical decisions every day."
        d = self.divergences[0]
        return f"PARITY FAILURE on {d['time']} ({len(self.divergences)} divergent day(s)); first field: {d['field']}\n  backtest: {d['backtest']}\n  live:     {d['live']}"


def _clock(day: pd.Timestamp) -> Callable[[], pd.Timestamp]:
    return lambda: day + pd.Timedelta(minutes=5)


def _cycles(journal: Journal) -> dict[str, dict[str, Any]]:
    return {r["time"]: {k: r[k] for k in COMPARED} for r in journal.records("cycle")}


def run_parity(
    config: SystemConfig,
    instruments: Mapping[str, InstrumentSpec],
    frames: Mapping[str, BarFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
    workdir: Path,
    costs: CostModel | None = None,
) -> ParityReport:
    costs_t = costs.with_toggles(config.costs) if costs is not None else CostModel.zero()
    bt_journal = Journal()
    BacktestHarness(
        config, instruments, frames, costs=costs, journal=bt_journal, start=start, end=end
    ).run()
    bt = _cycles(bt_journal)

    workdir.mkdir(parents=True, exist_ok=True)
    jpath, bpath = workdir / "live_journal.jsonl", workdir / "paper_broker.json"
    for p in (jpath, bpath):
        p.unlink(missing_ok=True)
    days = sorted({t for f in frames.values() for t in f.index if start <= t <= end})
    conv = Conversion(config.account.currency, frames)
    for day in days:
        # A fresh harness, broker and journal object every day: restart safety is part of parity.
        broker = PaperBroker(
            dict(instruments),
            costs_t,
            config.account.initial_equity,
            config.account.currency,
            conv,
            state_path=bpath,
        )
        harness = LiveHarness(
            config,
            instruments,
            list(frames),
            lambda s, now: frames[s].between(None, now),
            broker,
            Journal(jpath),
            clock=_clock(day),
        )
        harness.run_cycle()
    live = _cycles(Journal(jpath))
    report = ParityReport(days=len(days))
    for t in sorted(set(bt) | set(live)):
        a, b = bt.get(t), live.get(t)
        if a is None or b is None:
            report.divergences.append(
                {"time": t, "field": "missing", "backtest": a is not None, "live": b is not None}
            )
            continue
        for k in COMPARED:
            if json.dumps(a[k], sort_keys=True) != json.dumps(b[k], sort_keys=True):
                report.divergences.append(
                    {
                        "time": t,
                        "field": k,
                        "backtest": json.dumps(a[k])[:400],
                        "live": json.dumps(b[k])[:400],
                    }
                )
                break
    return report
