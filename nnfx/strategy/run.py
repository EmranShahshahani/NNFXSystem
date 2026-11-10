"""Backtest a Strategy Document on the shared harness and log the Trial (ticket 05)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.brokers.sim import Trade
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
from nnfx.strategy.analytics import JournalRow, journal_rows
from nnfx.strategy.book import BookData
from nnfx.strategy.document import StrategyDocument
from nnfx.strategy.engine import CompiledDocument, DocumentEngine, compile_document
from nnfx.strategy.library import ProfitChain
from nnfx.strategy.market import MarketData

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
class SpotTransfer:
    """Realised profit recorded as moved from futures to spot when a position closed."""

    position_id: str
    symbol: str
    time: str  # the position's last exit
    r: float  # the whole position's result in R
    amount: float  # its net profit


def spot_transfers(trades: Sequence[Trade], min_r: float) -> list[SpotTransfer]:
    """One transfer per closed position whose whole result reached ``min_r`` R.

    The blueprint's Capital Recycling Engine (video 61-70): on a +5R-10R close,
    the realised net profit goes to the asset's spot balance.
    """
    by_pos: dict[str, list[Trade]] = {}
    for t in trades:
        by_pos.setdefault(t.position_id, []).append(t)
    out = []
    for pid, ts in by_pos.items():
        net, risk = sum(t.net_pnl for t in ts), sum(t.risk_cash for t in ts)
        r = net / risk if risk > 0 else 0.0
        if r >= min_r and net > 0:
            last = max(ts, key=lambda t: t.exit_time)
            out.append(SpotTransfer(pid, last.symbol, last.exit_time, r, net))
    return sorted(out, key=lambda t: (t.time, t.position_id))


@dataclass(frozen=True)
class DocumentRun:
    fingerprint: str
    result: BacktestResult
    trial_id: str | None
    candidates: list[dict[str, Any]] = field(default_factory=list)  # one per Setup Candidate
    # Position with a losing exit -> "justified" / "unjustified" / "unknown" (untraceable).
    stop_labels: dict[str, str] = field(default_factory=dict)
    # Futures-to-spot recycling record (Profit Chain option), oldest first.
    spot_transfers: list[SpotTransfer] = field(default_factory=list)
    # Stretches of the run with no order-book snapshot, for the order-book Blocks (ticket 21):
    # {"symbol", "start", "end"}. Empty when the document has no such Block or the book was full.
    book_gaps: list[dict[str, str]] = field(default_factory=list)
    # One row per closed position with the blueprint's journal fields (ticket 23).
    journal: list[JournalRow] = field(default_factory=list)

    @property
    def incomplete(self) -> bool:
        """Whether a Market Filter or order-book Block lacked its data at some candidate.

        A Market Filter's check was not-applicable there instead of a pass (ADR 10 §9, §24); an
        order-book Block acted as its plain counterpart (§25): the result rests on less than
        the document asked for.
        """
        return bool(self.incomplete_blocks)

    @property
    def incomplete_blocks(self) -> list[str]:
        return sorted(
            {
                item["block"]
                for c in self.candidates
                for item in c.get("checklist", [])
                if item["kind"] == "context" and item["outcome"] == "na"
            }
            | {name for c in self.candidates for name in c.get("book_missing", [])}
        )

    @property
    def book_missing_candidates(self) -> int:
        """Candidates at which some order-book Block had no book."""
        return sum(bool(c.get("book_missing")) for c in self.candidates)

    def spot_balance(self) -> float:
        return sum(t.amount for t in self.spot_transfers)

    def split_equity(self) -> pd.DataFrame:
        """The equity curve split into the trading account and the spot ledger.

        A record, not a cash flow the backtest sized on: sizing used the whole
        equity, as the broker reported it.
        """
        eq = self.result.equity
        spot = pd.Series(0.0, index=eq.index)
        for t in self.spot_transfers:
            spot[eq.index >= pd.Timestamp(t.time)] += t.amount
        return pd.DataFrame({"trading": eq - spot, "spot": spot})

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
    market_data: MarketData | None = None,
    book_data: BookData | None = None,
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
    compiled = compile_document(doc, frames, instruments, cfg.session, market_data, book_data)
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
    ex = compiled.exit
    transfers = (
        spot_transfers(result.trades, ex.p.recycle_min_r)
        if isinstance(ex, ProfitChain) and ex.p.recycle_to_spot
        else []
    )
    gaps = book_gaps(compiled, frames, book_data or BookData(), start, end)
    rows = journal_rows(result.trades, journal.records("cycle"), frames, source="backtest")
    return DocumentRun(fp, result, trial, candidates, labels, transfers, gaps, rows)


def book_gaps(
    compiled: CompiledDocument,
    frames: Mapping[str, BarFrame],
    book: BookData,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> list[dict[str, str]]:
    """Where each symbol's run had no order-book snapshot fresh enough for the book Blocks."""
    if not compiled.book_blocks:
        return []
    fresh = max(b.p.max_age_seconds for _, b in compiled.book_blocks)
    out = []
    for sym, f in sorted(frames.items()):
        if not len(f):
            continue
        first, last = f.index[0], f.index[-1]
        if start is not None:
            first = max(first, pd.Timestamp(start))
        if end is not None:
            last = min(last, pd.Timestamp(end))
        for a, b in book.gaps(sym, first, last, pd.Timedelta(seconds=fresh)):
            out.append({"symbol": sym, "start": a.isoformat(), "end": b.isoformat()})
    return out


def stale_books(
    compiled: CompiledDocument, frames: Mapping[str, BarFrame], book: BookData
) -> dict[str, pd.Timestamp]:
    """Symbols with no snapshot fresher than the Blocks allow at their latest bar -> that bar."""
    if not compiled.book_blocks:
        return {}
    fresh = pd.Timedelta(seconds=max(b.p.max_age_seconds for _, b in compiled.book_blocks))
    out = {}
    for sym, f in sorted(frames.items()):
        if len(f) and not book.has_snapshot(sym, f.index[-1] - fresh, f.index[-1]):
            out[sym] = f.index[-1]
    return out


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
            if "event" in ev["values"]:
                continue  # a management event (stop move, close, cancel), not a Setup Candidate
            candidates.append({"symbol": ev["symbol"], "time": ev["time"], **ev["values"]})
            for intent in ev["intents"]:
                justified_by_key[intent["idempotency_key"]] = ev["values"].get("justified") is True
        for e in rec.get("orders", []):
            if e.get("e") == "fill":
                position_key[e["pid"]] = e["key"]
    labels = {
        t.position_id: (
            "unknown"
            if (key := position_key.get(t.position_id)) is None or key not in justified_by_key
            else ("justified" if justified_by_key[key] else "unjustified")
        )
        for t in result.trades
        if t.net_pnl < 0  # every losing exit's position is labelled, partial ones included
    }
    return candidates, labels
