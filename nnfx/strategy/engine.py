"""The Strategy Engine: interprets a Strategy Document (ticket 05, ADR 10).

It keeps the platform's pure ``decide()`` contract. Series Blocks (Context,
Setup) are computed once per symbol when the document is compiled; they are
causal (the gate suite proves it), so reading them at bar ``i`` sees only
what was known at that bar's close. Per LWC bar the engine:

1. reads every enabled Setup Block's candidate at the bar;
2. checks it against every Context Block and the position limit;
3. if nothing blocks it, asks the Stop Block for the stop, the Exit Block for
   the exit plan and each Execution Block for its stop-market orders, and
   emits them as ``PendingOrderIntent``s sized at the Risk section's risk;
4. journals one evaluation per candidate with every check's outcome.

Pending orders, fills, cancellations and exits are the shared broker's
(ADR 09 §4, §5); nothing here duplicates them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from nnfx.config import SessionConfig, SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.engine.core import Decision, Evaluation, Intent
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    AccountState,
    EngineState,
    PendingOrderIntent,
    PositionView,
    SymbolState,
)
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.blocks import (
    BlockKind,
    ContextBlock,
    ContextOutput,
    ExecutionBlock,
    ExitBlock,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StopBlock,
    StrategyData,
)
from nnfx.strategy.document import StrategyDocument
from nnfx.strategy.risk import govern, leverage_problem
from nnfx.strategy.series import atr


@dataclass(frozen=True)
class CompiledSymbol:
    data: StrategyData
    contexts: list[tuple[str, ContextOutput]]  # (block label, output)
    setups: list[tuple[int, str, SetupOutput]]  # (document position, type, output)
    atr: np.ndarray


@dataclass(frozen=True)
class CompiledDocument:
    document: StrategyDocument
    symbols: dict[str, CompiledSymbol]
    executions: list[tuple[int, ExecutionBlock[Any]]]
    stop: StopBlock[Any]
    exit: ExitBlock[Any]  # validation allows one enabled Stop and one Exit Block


def block_label(index: int, btype: str) -> str:
    return f"{btype}#{index}"


def compile_document(
    doc: StrategyDocument,
    frames: Mapping[str, BarFrame],
    instruments: Mapping[str, InstrumentSpec],
    session: SessionConfig,
) -> CompiledDocument:
    """Build every symbol's timeframe views and run the document's series Blocks once."""
    contexts = doc.instances(BlockKind.CONTEXT)
    setups = doc.instances(BlockKind.SETUP)
    symbols = {}
    for sym, f in sorted(frames.items()):
        data = StrategyData.build(f, doc.timeframes.as_dict(), instruments[sym], session)
        symbols[sym] = CompiledSymbol(
            data,
            [
                (block_label(i, b.type), b.compute(data))
                for i, b in contexts
                if isinstance(b, ContextBlock)
            ],
            [(i, b.type, b.compute(data)) for i, b in setups if isinstance(b, SetupBlock)],
            atr(f.high, f.low, f.close, doc.risk.atr_period),
        )
    stops = [b for _, b in doc.instances(BlockKind.STOP) if isinstance(b, StopBlock)]
    exits = [b for _, b in doc.instances(BlockKind.EXIT) if isinstance(b, ExitBlock)]
    executions = [
        (i, b) for i, b in doc.instances(BlockKind.EXECUTION) if isinstance(b, ExecutionBlock)
    ]
    return CompiledDocument(doc, symbols, executions, stops[0], exits[0])


class DocumentEngine:
    """A pure engine over a compiled Strategy Document (same contract as StrategyEngine)."""

    def __init__(self, compiled: CompiledDocument) -> None:
        self.compiled = compiled

    def decide(
        self,
        history: Mapping[str, SymbolHistory],
        open_positions: Sequence[PositionView],
        account_state: AccountState,
        config: SystemConfig,
        state: EngineState | None = None,
    ) -> Decision:
        state = state or EngineState()
        intents: list[Intent] = []
        evaluations: list[Evaluation] = []
        limit = self.compiled.document.risk.max_positions_per_symbol
        # Risk already committed: open positions not yet at breakeven, resting orders,
        # and orders placed earlier in this cycle (ADR 09 §6: breakeven releases risk).
        committed = sum(
            p.risk_cash for p in open_positions if (p.entry_price - p.stop) * p.direction > 0
        ) + sum(o.risk_cash for o in account_state.pending_orders)
        for sym in sorted(history):
            comp = self.compiled.symbols.get(sym)
            if comp is None:
                continue
            i = history[sym].end
            if comp.data.base.index[i] != history[sym].index[i]:
                raise ValueError(
                    f"{sym}: engine and harness bars disagree at {history[sym].index[i]}"
                )
            busy = sum(p.symbol == sym for p in open_positions) + sum(
                o.symbol == sym for o in account_state.pending_orders
            )
            for bidx, stype, out in comp.setups:
                cand = SetupCandidate.at(out, comp.data, stype, bidx, i)
                if cand is None:
                    continue
                ev, risk_cash = self._evaluate(cand, comp, busy >= limit, account_state, committed)
                if ev.intents:
                    busy += 1
                    committed += risk_cash
                intents += ev.intents
                evaluations.append(ev)
        return Decision(intents, state, evaluations)

    def _evaluate(
        self,
        cand: SetupCandidate,
        comp: CompiledSymbol,
        full: bool,
        account: AccountState,
        committed: float,
    ) -> tuple[Evaluation, float]:
        """Every check on one candidate, in order; returns its evaluation and its risk cash."""
        doc = self.compiled.document
        context = {name: out.allows(cand.bar, cand.direction) for name, out in comp.contexts}
        blocked = [f"context:{name}" for name, ok in context.items() if not ok]
        if cand.direction < 0 and not comp.data.instrument.can_short:
            blocked.append("cannot_short")
        if full:
            blocked.append("position_limit")
        # Ticket 08's checklist supplies the Confluence Score; until then it is 0.
        risk = govern(doc.risk, account, pd.Timestamp(cand.time), score=0)
        blocked += risk.blocked
        risk_cash = risk.risk_fraction * account.equity
        cap = doc.risk.max_open_risk
        if cap is not None and committed + risk_cash > cap * account.equity * (1 + 1e-9):
            blocked.append("open_risk_cap")
        intents: list[Intent] = []
        if not blocked:
            stop = self.compiled.stop.initial_stop(cand, comp.data)
            if not np.isfinite(stop) or (cand.trigger - stop) * cand.direction <= 0:
                blocked.append("no_stop")  # an entry without a stop is never placed
            else:
                problem = leverage_problem(doc.risk, comp.data.instrument, cand.trigger, stop)
                if problem is not None:
                    blocked.append(problem)
                else:
                    intents, problems = self._orders(cand, comp, stop, risk.risk_fraction)
                    blocked += problems
        evaluation = Evaluation(
            symbol=cand.symbol,
            time=cand.time,
            inputs={"bar": cand.bar},
            values={**cand.record(), "risk": risk.record()},
            state_before=SymbolState(),
            state_after=SymbolState(),
            intents=intents if not blocked else [],
            conditions={"context": context, "risk": {"allowed": risk.allowed}},
            blocked=blocked,
        )
        return evaluation, risk_cash

    def _orders(
        self, cand: SetupCandidate, comp: CompiledSymbol, stop: float, risk_fraction: float
    ) -> tuple[list[Intent], list[str]]:
        data = comp.data
        plan = self.compiled.exit.plan(cand, data)
        a = float(comp.atr[cand.bar])
        out: list[Intent] = []
        problems: list[str] = []
        k = 0
        for eidx, ex in self.compiled.executions:
            for spec in ex.orders(cand, data):
                try:
                    out.append(
                        PendingOrderIntent(
                            symbol=cand.symbol,
                            direction=cand.direction,
                            leg="single",
                            leg_index=k,
                            entry_type="setup",
                            signal_time=cand.time,
                            atr=a if np.isfinite(a) else 0.0,
                            risk_fraction=risk_fraction,
                            idempotency_key=f"{cand.symbol}|{cand.time}|b{cand.block_index}|e{eidx}|{k}",
                            level=spec.level,
                            buffer=spec.buffer,
                            stop=stop,
                            invalidation=spec.invalidation,
                            expires_after_bars=spec.expires_after_bars,
                            oco_group=spec.oco_group,
                            exit_plan=plan,
                        )
                    )
                except ValueError as exc:  # e.g. a stop on the wrong side of the trigger
                    problems.append(f"invalid_order:{str(exc).splitlines()[0][:120]}")
                k += 1
        return out, problems
