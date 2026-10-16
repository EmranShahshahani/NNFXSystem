"""Backtest harness: drives the engine over history (doc 02 §2, §7 step 4).

Contract arrays are computed once on full history and the engine is handed a
moving ``end`` - valid only because Gate 1 proves every registered indicator
is causal; the parity harness re-proves it against truncated computation.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.brokers.sim import BacktestBroker, Trade
from nnfx.config import SystemConfig
from nnfx.data.bars import BarFrame, ns
from nnfx.data.gates import ensure_clean
from nnfx.data.universe import UniverseSchedule
from nnfx.engine.history import SymbolHistory
from nnfx.env import fingerprint
from nnfx.harness.conversion import Conversion
from nnfx.harness.loop import TradingLoop
from nnfx.indicators.slots import IndicatorSet, SlotOutputs
from nnfx.instruments import InstrumentSpec
from nnfx.journal.journal import Journal


@dataclass
class BacktestResult:
    config_digest: str
    env_digest: str
    trades: list[Trade]
    equity: pd.Series
    initial_equity: float
    blocked: Counter[str] = field(default_factory=Counter)
    rejected: Counter[str] = field(default_factory=Counter)
    symbols: tuple[str, ...] = ()
    volume_flags: tuple[str, ...] = ()
    spliced_symbols: tuple[str, ...] = ()

    def to_json(self, include_env: bool = True) -> str:
        payload = {
            "config": self.config_digest,
            "env": self.env_digest if include_env else None,
            "symbols": list(self.symbols),
            "volume_flags": list(self.volume_flags),
            "trades": [asdict(t) for t in self.trades],
            "equity": [
                [t.isoformat(), round(float(v), 8)]
                for t, v in zip(
                    pd.DatetimeIndex(self.equity.index), self.equity.to_numpy(), strict=True
                )
            ],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        """Digest of the *outputs*; the environment is compared separately."""
        return hashlib.sha256(self.to_json(include_env=False).encode()).hexdigest()

    def write(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8", newline="\n")

    def trade_table(self) -> str:
        head = f"{'symbol':<10} {'leg':<8} {'dir':>3} {'type':<13} {'entry':<26} {'exit':<26} {'entry_px':>12} {'exit_px':>12} {'R':>7} reason"
        rows = [head]
        for t in self.trades:
            rows.append(
                f"{t.symbol:<10} {t.leg:<8} {t.direction:>3} {t.entry_type:<13} {t.entry_time:<26} {t.exit_time:<26} "
                f"{t.entry_price:>12.6g} {t.exit_price:>12.6g} {t.r_multiple:>7.2f} {t.exit_reason}"
            )
        return "\n".join(rows)

    def equity_table(self, every: int = 1) -> str:
        pts = list(zip(pd.DatetimeIndex(self.equity.index), self.equity.to_numpy(), strict=True))[
            ::every
        ]
        return "\n".join(f"{t.date()} {v:,.2f}" for t, v in pts)


def precompute(config: SystemConfig, frames: Mapping[str, BarFrame]) -> dict[str, SlotOutputs]:
    ind = IndicatorSet(config.slots)
    return {s: ind.compute(f) for s, f in frames.items()}


class BacktestHarness:
    def __init__(
        self,
        config: SystemConfig,
        instruments: Mapping[str, InstrumentSpec],
        frames: Mapping[str, BarFrame],
        *,
        costs: CostModel | None = None,
        journal: Journal | None = None,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
        universe: UniverseSchedule | None = None,
        run_gates: bool = True,
        gate_kwargs: Mapping[str, object] | None = None,
        outputs: Mapping[str, SlotOutputs] | None = None,
    ) -> None:
        self.config = config
        self.instruments = dict(instruments)
        self.frames = {s: frames[s] for s in sorted(frames)}
        self.costs = costs.with_toggles(config.costs) if costs is not None else CostModel.zero()
        self.journal = journal
        self.start = start
        self.end = end
        self.universe = universe
        if run_gates:
            # Gates run automatically before any research, not on request.
            for s, f in self.frames.items():
                ensure_clean(
                    f,
                    self.instruments[s],
                    close_tz=config.session.close_tz,
                    **dict(gate_kwargs or {}),
                )
        self.outputs = dict(outputs) if outputs is not None else precompute(config, self.frames)

    def run(self) -> BacktestResult:
        cfg = self.config
        broker = BacktestBroker(
            self.instruments,
            self.costs,
            cfg.account.initial_equity,
            cfg.account.currency,
            Conversion(cfg.account.currency, self.frames),
        )
        loop = TradingLoop(cfg, self.instruments, broker, self.journal)
        if self.journal is not None:
            self.journal.start_run(kind="backtest", config=cfg.digest())
        hist = {
            s: SymbolHistory.from_frame(f, self.outputs[s], self.instruments[s])
            for s, f in self.frames.items()
        }
        extras = {
            s: {c: f.column(c) for c in ("mark_high", "mark_low", "funding") if f.has(c)}
            for s, f in self.frames.items()
        }
        pos_of = {s: {t.value: i for i, t in enumerate(f.index)} for s, f in self.frames.items()}
        timeline = sorted({int(t) for f in self.frames.values() for t in ns(f.index)})
        if self.end is not None:
            timeline = [t for t in timeline if t <= self.end.value]
        global_last = timeline[-1] if timeline else 0
        last_bar = {s: (int(ns(f.index)[-1]) if len(f) else 0) for s, f in self.frames.items()}

        eq_t: list[pd.Timestamp] = []
        eq_v: list[float] = []
        blocked: Counter[str] = Counter()
        rejected: Counter[str] = Counter()
        delisted: set[str] = set()
        for tv in timeline:
            ts = pd.Timestamp(tv, tz="UTC")
            live = [s for s in self.frames if tv in pos_of[s] and s not in delisted]
            for s in live:
                loop.feed_bar(hist[s].at(pos_of[s][tv]), extras[s])
            # Delisting: force-close at the last valid price; never drop the coin.
            for s in live:
                if last_bar[s] == tv and tv < global_last:
                    broker.force_close(s, float(hist[s].close[pos_of[s][tv]]), ts, "delisted")
                    delisted.add(s)
            live = [s for s in live if s not in delisted]
            in_window = self.start is None or ts >= self.start
            if in_window and live:
                histories = {s: hist[s].at(pos_of[s][tv]) for s in live}
                allowed = set(self.universe.members_at(ts)) if self.universe is not None else None
                rep = loop.decide(ts, histories, allowed)
                for ev in rep.evaluations:
                    blocked.update(b.split(":")[0] for b in ev.blocked)
                rejected.update(r["reason"].split(":")[0].split(" ")[0] for r in rep.rejected)
            if in_window:
                eq_t.append(ts)
                eq_v.append(broker.equity())
        if timeline:
            ts = pd.Timestamp(timeline[-1], tz="UTC")
            for s in self.frames:
                if s in delisted:
                    continue
                k = pos_of[s].get(timeline[-1])
                if k is None:
                    k = (
                        int(np.searchsorted(ns(self.frames[s].index), timeline[-1], side="right"))
                        - 1
                    )
                if k >= 0:
                    broker.force_close(s, float(hist[s].close[k]), ts, "end_of_data")
            if eq_v:
                eq_v[-1] = broker.equity()
        trades = sorted(broker.trades, key=lambda t: (t.exit_time, t.position_id, t.leg))
        return BacktestResult(
            config_digest=cfg.digest(),
            env_digest=fingerprint().digest,
            trades=trades,
            equity=pd.Series(eq_v, index=pd.DatetimeIndex(eq_t), dtype="float64", name="equity"),
            initial_equity=cfg.account.initial_equity,
            blocked=blocked,
            rejected=rejected,
            symbols=tuple(self.frames),
            volume_flags=tuple(s for s, f in self.frames.items() if f.volume_kind == "tick"),
            spliced_symbols=tuple(s for s, f in self.frames.items() if f.splice_points),
        )
