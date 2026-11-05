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
from dataclasses import dataclass, field
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
    GovernorState,
    PendingOrderIntent,
    PositionView,
    SymbolState,
)
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.blocks import (
    BlockKind,
    ConfirmationBlock,
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
from nnfx.strategy.risk import govern, leverage_problem, margin, update_state
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
    confirmations: list[tuple[str, ConfirmationBlock[Any]]] = field(default_factory=list)


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
    confirmations = [
        (block_label(i, b.type), b)
        for i, b in doc.instances(BlockKind.CONFIRMATION)
        if isinstance(b, ConfirmationBlock)
    ]
    return CompiledDocument(doc, symbols, executions, stops[0], exits[0], confirmations)


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
        committed = sum(p.risk_cash for p in open_positions if p.at_risk) + sum(
            o.risk_cash for o in account_state.pending_orders
        )
        # The governor's memory advances once per bar, candidates or not.
        if history:
            now = max(h.index[h.end] for h in history.values())
            state = state.model_copy(
                update={
                    "governor": update_state(
                        self.compiled.document.risk, account_state, now, state.governor
                    )
                }
            )
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
                ev, risk_cash = self._evaluate(
                    cand, comp, busy >= limit, account_state, committed, state.governor
                )
                if ev.intents:
                    busy += 1
                    committed += risk_cash
                intents += ev.intents
                evaluations.append(ev)
        return Decision(intents, state, evaluations)

    def _checklist(
        self, cand: SetupCandidate, comp: CompiledSymbol
    ) -> tuple[list[dict[str, Any]], float, list[str]]:
        """Every Context and Confirmation check: (checklist, Confluence Score, hard failures)."""
        items: list[dict[str, Any]] = []
        for name, out in comp.contexts:
            ok = out.allows(cand.bar, cand.direction)
            side = "long" if cand.direction > 0 else "short"
            items.append(
                {
                    "block": name,
                    "kind": "context",
                    "outcome": "pass" if ok else "fail",
                    "weight": 0.0,
                    "hard": True,
                    "reason": f"{side}s {'allowed' if ok else 'not allowed'} here",
                }
            )
        score = 0.0
        for name, block in self.compiled.confirmations:
            res = block.check(cand, comp.data)
            weight, hard = float(block.p.weight), bool(block.p.hard)
            if res.outcome == "pass":
                score += weight
            items.append(
                {
                    "block": name,
                    "kind": "confirmation",
                    "outcome": res.outcome,
                    "weight": weight,
                    "hard": hard,
                    "reason": res.reason,
                }
            )
        hard_fails = [
            f"{i['kind'] if i['kind'] == 'context' else 'checklist'}:{i['block']}"
            for i in items
            if i["hard"] and i["outcome"] == "fail"
        ]
        return items, score, hard_fails

    def _evaluate(
        self,
        cand: SetupCandidate,
        comp: CompiledSymbol,
        full: bool,
        account: AccountState,
        committed: float,
        governor: GovernorState,
    ) -> tuple[Evaluation, float]:
        """The Pre-Trade Checklist, then risk, stop and order; returns the evaluation and risk cash.

        The decision path walks context -> each confirmation -> risk -> stop ->
        order; once something refuses the candidate, later stages are skipped.
        """
        doc = self.compiled.document
        checklist, score, hard_fails = self._checklist(cand, comp)
        blocked = list(hard_fails)
        path: list[dict[str, str]] = [
            {
                "stage": "context",
                "status": "fail"
                if any(i["kind"] == "context" and i["outcome"] == "fail" for i in checklist)
                else "pass",
            }
        ]
        path += [
            {"stage": i["block"], "status": i["outcome"]}
            for i in checklist
            if i["kind"] == "confirmation"
        ]

        risk = govern(doc.risk, account, pd.Timestamp(cand.time), int(score), governor)
        risk_cash = risk.risk_fraction * account.equity
        record = risk.record()
        risk_refusals: list[str] = []
        if cand.direction < 0 and not comp.data.instrument.can_short:
            risk_refusals.append("cannot_short")
        if full:
            risk_refusals.append("position_limit")
        risk_refusals += risk.blocked
        cap = doc.risk.max_open_risk
        if cap is not None and committed + risk_cash > cap * account.equity * (1 + 1e-9):
            risk_refusals.append("open_risk_cap")

        intents: list[Intent] = []
        stages = {"risk": "skipped", "stop": "skipped", "order": "skipped"}
        if not blocked:
            stages["risk"] = "fail" if risk_refusals else "pass"
            blocked += risk_refusals
        if not blocked:
            stop = self.compiled.stop.initial_stop(cand, comp.data)
            if not np.isfinite(stop) or (cand.trigger - stop) * cand.direction <= 0:
                blocked.append("no_stop")  # an entry without a stop is never placed
            else:
                record["leverage"] = doc.risk.leverage.leverage
                record["margin"] = margin(doc.risk, risk_cash, cand.trigger, stop)
                problem = leverage_problem(doc.risk, comp.data.instrument, cand.trigger, stop)
                if problem is not None:
                    blocked.append(problem[0])
                    record["leverage_detail"] = problem[1]
            stages["stop"] = "fail" if blocked else "pass"
            if not blocked:
                intents, problems = self._orders(cand, comp, stop, risk.risk_fraction)
                blocked += problems
                stages["order"] = "fail" if problems else "pass"
        path += [{"stage": k, "status": v} for k, v in stages.items()]

        applicable = [i for i in checklist if i["outcome"] != "na"]
        evaluation = Evaluation(
            symbol=cand.symbol,
            time=cand.time,
            inputs={"bar": cand.bar},
            values={
                **cand.record(),
                "checklist": checklist,
                "score": score,
                "tier": risk.base_risk,
                "risk": record,
                "decision": "refused" if blocked else "placed",
                "reasons": blocked,
                # A stop on a setup that passed every applicable check is a normal loss.
                "justified": all(i["outcome"] == "pass" for i in applicable),
                "decision_path": path,
            },
            state_before=SymbolState(),
            state_after=SymbolState(),
            intents=intents if not blocked else [],
            conditions={
                "context": {
                    i["block"]: i["outcome"] == "pass" for i in checklist if i["kind"] == "context"
                },
                "risk": {"allowed": risk.allowed},
            },
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
