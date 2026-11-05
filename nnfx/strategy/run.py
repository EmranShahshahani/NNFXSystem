"""Backtest a Strategy Document on the shared harness and log the Trial (ticket 05)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.config import Slots, SlotSpec, SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.data.feeds import read_bars_csv
from nnfx.harness.backtest import BacktestHarness, BacktestResult
from nnfx.indicators.slots import SlotOutputs
from nnfx.instruments import InstrumentRegistry, InstrumentSpec
from nnfx.journal.journal import Journal
from nnfx.research.metrics import Metrics, compute_metrics
from nnfx.research.partition import HoldoutAccessError, Market, Partition, SegmentName
from nnfx.research.trials import ResearchState
from nnfx.strategy.document import StrategyDocument
from nnfx.strategy.engine import DocumentEngine, compile_document

# The harness wants an NNFX config for the account, costs and portfolio caps it
# shares with every engine; its indicator slots are unused by the document engine.
UNUSED_SLOTS = Slots(
    atr=SlotSpec(name="atr"), baseline=SlotSpec(name="kama"), c1=SlotSpec(name="supertrend")
)


def document_config(doc: StrategyDocument, base: SystemConfig | None = None) -> SystemConfig:
    """The harness config for a document: its leverage reaches the risk manager and broker."""
    cfg = base or SystemConfig(slots=UNUSED_SLOTS)
    return cfg.with_overrides({"risk.leverage": doc.risk.leverage.leverage})


@dataclass(frozen=True)
class DocumentRun:
    fingerprint: str
    result: BacktestResult
    trial_id: str | None
    candidates: list[dict[str, Any]] = field(default_factory=list)  # one per Setup Candidate
    stop_labels: dict[str, str] = field(default_factory=dict)  # losing position -> (un)justified

    def metrics(self) -> Metrics:
        """Performance in R, where one entry risks its whole 1R (ADR 10 §8)."""
        r = self.result
        return compute_metrics(r.trades, r.equity, volume_flags=r.volume_flags, r_per_entry=1.0)


def market_of(instruments: Mapping[str, InstrumentSpec]) -> Market:
    """The research market of a run, from its instruments' class."""
    markets = {"fx" if i.market_class == "fx_spot" else "crypto" for i in instruments.values()}
    if len(markets) != 1:
        raise ValueError(f"a run covers one market; got {sorted(markets)}")
    return "fx" if markets == {"fx"} else "crypto"


def load_frames(
    datasets: Iterable[tuple[str, Path | str]], registry: InstrumentRegistry, timeframe: str
) -> tuple[dict[str, BarFrame], dict[str, InstrumentSpec]]:
    """Read (symbol, CSV path) pairs as ``timeframe`` bars with their instruments."""
    frames, inst = {}, {}
    for sym, path in datasets:
        spec = registry.spec(sym)
        frames[sym] = read_bars_csv(path, sym, timeframe=timeframe, volume_kind=spec.volume_kind)
        inst[sym] = spec
    return frames, inst


def _unused_outputs(n: int) -> SlotOutputs:
    z = np.zeros(n)
    return SlotOutputs(atr=z, baseline=z, c1_signal=z.astype("int8"), c1_state=z.astype("int8"))


def segment_of(
    market: Market, frames: Mapping[str, BarFrame], end: pd.Timestamp | None
) -> SegmentName:
    """The research segment a run's data falls in; reaching the holdout is refused."""
    part = Partition.for_market(market)
    last = max(f.index[-1] for f in frames.values() if len(f))
    if end is not None:
        last = min(last, pd.Timestamp(end))
    if last >= part.holdout.start:
        raise HoldoutAccessError(
            f"data reaches {last}, inside the {market} holdout (from {part.holdout.start.date()}); "
            "Strategy Document runs stop before it (doc 03 §3)"
        )
    return "development" if last <= part.development.end else "validation"


def backtest_document(
    doc: StrategyDocument,
    frames: Mapping[str, BarFrame],
    instruments: Mapping[str, InstrumentSpec],
    *,
    costs: CostModel | None = None,
    journal: Journal | None = None,
    research: ResearchState | None = None,
    stage: str = "strategy/backtest",
    config: SystemConfig | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> DocumentRun:
    if not frames:
        raise ValueError("no bars to run on")
    for sym, f in frames.items():
        if f.timeframe != doc.timeframes.lwc:
            raise ValueError(
                f"{sym}: bars are {f.timeframe} but the document's LWC is {doc.timeframes.lwc}"
            )
    # Always, logged or not: the holdout is touch-once (doc 03 §3).
    market = market_of({s: instruments[s] for s in frames})
    segment = segment_of(market, frames, end)
    journal = journal if journal is not None else Journal()  # the candidates live in it
    cfg = document_config(doc, config)
    compiled = compile_document(doc, frames, instruments, cfg.session)
    result = BacktestHarness(
        cfg,
        {s: instruments[s] for s in frames},
        frames,
        costs=costs,
        journal=journal,
        start=start,
        end=end,
        outputs={s: _unused_outputs(len(f)) for s, f in frames.items()},
        engine=DocumentEngine(compiled),
    ).run()
    fp = doc.fingerprint()
    result = replace(result, config_digest=fp)
    candidates, labels = _candidates_and_labels(journal, result)
    trial = None
    if research is not None:
        rs = [t.r_multiple for t in result.trades]
        trial = research.record_document_trial(
            fp,
            market=market,
            segment=segment,
            symbols=list(frames),
            stage=stage,
            metrics={
                "trades": len(result.trades),
                "expectancy_r": float(np.mean(rs)) if rs else None,
                "net_pnl": float(sum(t.net_pnl for t in result.trades)),
            },
        )
    return DocumentRun(fp, result, trial, candidates, labels)


def _candidates_and_labels(
    journal: Journal, result: BacktestResult
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every candidate's record, and justified/unjustified labels for the losing positions.

    The journal ties them together: a candidate's order key -> the broker's fill
    of that key -> the position the trades belong to.
    """
    candidates, justified_by_key, position_key = [], {}, {}
    for rec in journal.records("cycle"):
        for ev in rec["evaluations"]:
            candidates.append({"symbol": ev["symbol"], "time": ev["time"], **ev["values"]})
            for intent in ev["intents"]:
                justified_by_key[intent["idempotency_key"]] = bool(ev["values"].get("justified"))
        for e in rec.get("orders", []):
            if e.get("e") == "fill":
                position_key[e["pid"]] = e["key"]
    net: dict[str, float] = {}
    for t in result.trades:
        net[t.position_id] = net.get(t.position_id, 0.0) + t.net_pnl
    labels = {
        pid: "justified"
        if justified_by_key.get(position_key.get(pid, ""), False)
        else "unjustified"
        for pid, pnl in net.items()
        if pnl < 0
    }
    return candidates, labels
