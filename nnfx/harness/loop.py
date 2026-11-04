"""The one decision step both harnesses run (doc 02 P1).

Backtest and live differ only in where bars and contract arrays come from and
which ``SimBroker`` subclass fills orders. Everything between "a bar closed" and
"orders submitted" is this module, so a backtest/live divergence can only be a
harness data bug - which is exactly what the parity harness tests for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

import numpy as np
import pandas as pd

from nnfx.brokers.sim import Order, SimBroker
from nnfx.config import SystemConfig
from nnfx.engine.core import Decision, Evaluation, StrategyEngine
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    AccountState,
    CancelIntent,
    CloseIntent,
    EngineState,
    ModifyIntent,
    OpenIntent,
    PendingOrderIntent,
    PositionView,
)
from nnfx.instruments import InstrumentSpec
from nnfx.journal.journal import Journal
from nnfx.risk.manager import RiskManager, SizedOrder


class Engine(Protocol):
    """The pure decision contract every engine family implements (ADR 09 §2)."""

    def decide(
        self,
        history: Mapping[str, SymbolHistory],
        open_positions: Sequence[PositionView],
        account_state: AccountState,
        config: SystemConfig,
        state: EngineState | None = None,
    ) -> Decision: ...


@dataclass
class StepReport:
    time: str
    evaluations: list[Evaluation]
    submitted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    closes: list[dict[str, Any]] = field(default_factory=list)
    modifies: list[dict[str, Any]] = field(default_factory=list)
    cancels: list[dict[str, Any]] = field(default_factory=list)


def bar_kwargs(h: SymbolHistory, frame_cols: Mapping[str, np.ndarray], i: int) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    for c in ("mark_high", "mark_low", "funding"):
        if c in frame_cols:
            v = float(frame_cols[c][i])
            kw[c] = None if np.isnan(v) else v
    return kw


def evaluation_record(ev: Evaluation) -> dict[str, Any]:
    return {
        "symbol": ev.symbol,
        "time": ev.time,
        "inputs": ev.inputs,
        "values": ev.values,
        "state_before": ev.state_before.model_dump(mode="json"),
        "state_after": ev.state_after.model_dump(mode="json"),
        "intents": [i.model_dump(mode="json") for i in ev.intents],
        "conditions": ev.conditions,
        "blocked": ev.blocked,
    }


class TradingLoop:
    def __init__(
        self,
        config: SystemConfig,
        instruments: dict[str, InstrumentSpec],
        broker: SimBroker,
        journal: Journal | None = None,
        engine: Engine | None = None,
        state: EngineState | None = None,
    ) -> None:
        self.config = config
        self.instruments = instruments
        self.broker = broker
        self.journal = journal
        self.engine: Engine = engine or StrategyEngine()
        self.risk = RiskManager(config.risk)
        self.state = state or EngineState()
        # Broker events up to here belong to earlier cycles.
        self._event_mark = len(broker.s.events)

    def feed_bar(self, h: SymbolHistory, extras: Mapping[str, np.ndarray]) -> None:
        i = h.end
        self.broker.process_bar(
            h.symbol,
            h.index[i],
            float(h.open[i]),
            float(h.high[i]),
            float(h.low[i]),
            float(h.close[i]),
            **bar_kwargs(h, extras, i),
        )

    def decide(
        self,
        ts: pd.Timestamp,
        histories: Mapping[str, SymbolHistory],
        entries_allowed: set[str] | None = None,
    ) -> StepReport:
        account = self.broker.account()
        positions = self.broker.positions()
        decision: Decision = self.engine.decide(
            histories, positions, account, self.config, self.state
        )
        report = StepReport(ts.isoformat(), decision.evaluations)
        approved: list[SizedOrder] = []
        for intent in decision.intents:
            if isinstance(intent, CloseIntent):
                self.broker.close(intent.position_id, 1.0, intent.reason)
                report.closes.append(intent.model_dump(mode="json"))
            elif isinstance(intent, ModifyIntent):
                self.broker.modify_stop(intent.position_id, intent.stop, intent.target)
                report.modifies.append(intent.model_dump(mode="json"))
            elif isinstance(intent, CancelIntent):
                self.broker.cancel(intent.order_key, intent.reason)
                report.cancels.append(intent.model_dump(mode="json"))
            elif isinstance(intent, OpenIntent):  # market entries and pending orders
                self._open(
                    intent,
                    ts,
                    histories[intent.symbol],
                    account,
                    positions,
                    approved,
                    entries_allowed,
                    report,
                )
        self.state = decision.state
        orders = self.broker.s.events[self._event_mark :]
        self._event_mark = len(self.broker.s.events)
        if self.journal is not None:
            # One atomic line per step: a crash can never leave half a step journaled.
            self.journal.append(
                {
                    "type": "cycle",
                    "time": report.time,
                    "evaluations": [evaluation_record(ev) for ev in decision.evaluations],
                    "state": self.state,
                    "positions": self.broker.positions(),
                    "submitted": report.submitted,
                    "rejected": report.rejected,
                    # Placements, fills, cancellations, expiries and closes since the last cycle.
                    "orders": orders,
                    "broker_event_seq": len(self.broker.s.events),
                    "equity": round(self.broker.equity(), 10),
                }
            )
        return report

    def _open(
        self,
        intent: OpenIntent,
        ts: pd.Timestamp,
        h: SymbolHistory,
        account: Any,
        positions: Any,
        approved: list[SizedOrder],
        entries_allowed: set[str] | None,
        report: StepReport,
    ) -> None:
        rec = {"key": intent.idempotency_key, "symbol": intent.symbol, "leg": intent.leg}
        if entries_allowed is not None and intent.symbol not in entries_allowed:
            report.rejected.append({**rec, "reason": "not_in_universe_or_window"})
            return
        inst = self.instruments[intent.symbol]
        sized = self.risk.size(
            intent, account, inst, self.broker.value_per_price_unit(intent.symbol, ts)
        )
        if not sized.approved or sized.order is None:
            report.rejected.append({**rec, "reason": sized.reason})
            return
        dec = self.risk.approve(
            sized.order,
            inst,
            account,
            positions,
            self.instruments,
            approved,
            entry_price=h.px("close"),
        )
        if not dec.approved:
            report.rejected.append({**rec, "reason": dec.reason})
            return
        approved.append(sized.order)
        o = sized.order
        order = Order(
            symbol=intent.symbol,
            direction=intent.direction,
            units=o.units,
            leg=intent.leg,
            entry_type=intent.entry_type,
            signal_time=intent.signal_time,
            atr=intent.atr,
            stop_distance=intent.stop_distance,
            target_distance=intent.target_distance,
            target_fraction=intent.target_fraction,
            risk_cash=o.realized_risk,
        )
        if isinstance(intent, PendingOrderIntent):
            order = replace(
                order,
                trigger=intent.trigger,
                buffer=intent.buffer,
                stop_price=intent.stop,
                target_price=intent.target,
                invalidation=intent.invalidation,
                expires_after_bars=intent.expires_after_bars,
                oco_group=intent.oco_group,
            )
        res = self.broker.submit(order, intent.idempotency_key)
        report.submitted.append(
            {**rec, "status": res.status, "order_id": res.order_id, "units": o.units}
        )
