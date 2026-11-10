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
4. journals one evaluation per candidate with every check's outcome;
5. asks the Exit Block to manage each open position (conditional breakeven,
   Runner trail) and emits a ``ModifyIntent`` for every move that tightens
   the stop, journaled as a ``stop_move`` evaluation.

No exit plan may close the whole position below 2R: such a candidate is
refused (``exit_below_2r``).

Pending orders, fills, cancellations and exits are the shared broker's
(ADR 09 §4, §5); nothing here duplicates them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from nnfx.config import SessionConfig, SystemConfig
from nnfx.data.bars import BarFrame
from nnfx.engine.core import Decision, Evaluation, Intent
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    AccountState,
    CancelIntent,
    CloseIntent,
    EngineState,
    GovernorState,
    ModifyIntent,
    OpenIntent,
    PendingOrderIntent,
    PositionView,
    SymbolState,
)
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.blocks import (
    MIN_FULL_CLOSE_R,
    BlockKind,
    ChecklistItem,
    CloseMove,
    ConfirmationBlock,
    ContextBlock,
    ContextOutput,
    ExecutionBlock,
    ExitBlock,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StageStatus,
    StopBlock,
    StrategyData,
    closes_all_below,
)
from nnfx.strategy.document import StrategyDocument
from nnfx.strategy.market import MarketData
from nnfx.strategy.risk import govern, leverage_problem, margin, update_state
from nnfx.strategy.series import atr


def _stop_distance(entry: float, stop: float, direction: int) -> float:
    if (entry - stop) * direction <= 0:
        raise ValueError(f"stop {stop} must be on the losing side of the entry {entry}")
    return abs(entry - stop)


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
    market: MarketData | None = None,
) -> CompiledDocument:
    """Build every symbol's timeframe views and run the document's series Blocks once."""
    contexts = doc.instances(BlockKind.CONTEXT) + doc.instances(BlockKind.MARKET_FILTER)
    setups = doc.instances(BlockKind.SETUP)
    symbols = {}
    for sym, f in sorted(frames.items()):
        data = StrategyData.build(f, doc.timeframes.as_dict(), instruments[sym], session, market)
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

    PLACED_KEPT = 500  # breakouts remembered in the state

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
        placed = dict.fromkeys(state.placed_breakouts)  # insertion-ordered set
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
            for pv in sorted(open_positions, key=lambda x: x.id):
                if pv.symbol == sym:
                    ev = self._manage(pv, comp, i)
                    if ev is not None:
                        intents += ev.intents
                        evaluations.append(ev)
            if any(
                out.cancels_orders is not None and out.cancels_orders[i] for _, out in comp.contexts
            ):
                gone = [o for o in account_state.pending_orders if o.symbol == sym]
                if gone:
                    evaluations.append(self._cancel_orders(sym, comp, i, [o.key for o in gone]))
                    intents += evaluations[-1].intents
                    committed -= sum(o.risk_cash for o in gone)  # the cancelled orders free it
                cancelled = {o.key for o in gone}
            else:
                cancelled = set()
            busy = sum(p.symbol == sym for p in open_positions) + sum(
                o.symbol == sym and o.key not in cancelled for o in account_state.pending_orders
            )
            for bidx, stype, out in comp.setups:
                cand = SetupCandidate.at(out, comp.data, stype, bidx, i)
                if cand is None:
                    continue
                extra = set().union(*(c.tags_for(i, cand.direction) for _, c in comp.contexts))
                if extra - set(cand.tags):  # e.g. counter_trend from the wave cycles
                    cand = replace(cand, tags=tuple(sorted(set(cand.tags) | extra)))
                anchor = cand.fact("anchor")
                breakout = None if anchor is None else f"{sym}|{bidx}|{int(anchor)}"
                ev, risk_cash = self._evaluate(
                    cand,
                    comp,
                    busy >= limit,
                    account_state,
                    committed,
                    state.governor,
                    repeat=breakout in placed,
                )
                if ev.intents:
                    busy += 1
                    committed += risk_cash
                    if breakout is not None:
                        placed[breakout] = None
                intents += ev.intents
                evaluations.append(ev)
        state = state.model_copy(update={"placed_breakouts": tuple(placed)[-self.PLACED_KEPT :]})
        return Decision(intents, state, evaluations)

    def _cancel_orders(self, sym: str, comp: CompiledSymbol, i: int, keys: list[str]) -> Evaluation:
        """A Context (e.g. the Choppy Regime) disables breakout orders: cancel the resting ones."""
        return Evaluation(
            symbol=sym,
            time=comp.data.base.index[i].isoformat(),
            inputs={"bar": i},
            values={"event": "cancel_orders", "reason": "context_disabled_orders", "keys": keys},
            state_before=SymbolState(),
            state_after=SymbolState(),
            intents=[
                CancelIntent(symbol=sym, order_key=k, reason="context_disabled_orders")
                for k in keys
            ],
            conditions={},
            blocked=[],
        )

    def _manage(self, pv: PositionView, comp: CompiledSymbol, i: int) -> Evaluation | None:
        """The Exit Block's stop move (if it tightens the stop) or close for an open position."""
        move = self.compiled.exit.manage(pv, comp.data, i)
        intent: ModifyIntent | CloseIntent
        if move is None:
            return None
        if isinstance(move, CloseMove):
            if pv.steps_filled < 1:  # the 2R floor: only profit already taken may be closed out
                return None
            intent = CloseIntent(symbol=pv.symbol, position_id=pv.id, reason=move.reason)
            values: dict[str, Any] = {"event": "close", "reason": move.reason}
        else:
            if not np.isfinite(move.stop):
                return None
            d, close = pv.direction, float(comp.data.base.close[i])
            if (move.stop - pv.stop) * d <= 1e-12 or (close - move.stop) * d <= 0:
                return None  # never looser, and never through the price
            intent = ModifyIntent(
                symbol=pv.symbol, position_id=pv.id, stop=move.stop, reason=move.reason
            )
            values = {"event": "stop_move", "from": pv.stop, "to": move.stop, "reason": move.reason}
        return Evaluation(
            symbol=pv.symbol,
            time=comp.data.base.index[i].isoformat(),
            inputs={"bar": i},
            values={**values, "position_id": pv.id, "steps_filled": pv.steps_filled},
            state_before=SymbolState(),
            state_after=SymbolState(),
            intents=[intent],
            conditions={},
            blocked=[],
        )

    def _checklist(
        self, cand: SetupCandidate, comp: CompiledSymbol
    ) -> tuple[list[ChecklistItem], float]:
        """Every Context and Confirmation check, and the Confluence Score."""
        side = "longs" if cand.direction > 0 else "shorts"
        items = [
            ChecklistItem(name, "context", "na", 0.0, True, "no market data for this bar")
            if not out.known(cand.bar)
            else ChecklistItem(
                name,
                "context",
                "pass" if (ok := out.allows(cand.bar, cand.direction)) else "fail",
                0.0,
                True,
                f"{side} {'allowed' if ok else 'not allowed'} here",
            )
            for name, out in comp.contexts
        ]
        for name, block in self.compiled.confirmations:
            if not block.applies_to(cand.setup):
                continue  # scoped to other setups: not part of this candidate's checklist
            res = block.check(cand, comp.data)
            items.append(
                ChecklistItem(
                    name, "confirmation", res.outcome, block.p.weight, block.p.hard, res.reason
                )
            )
        # Rounded: fractional weights (0.6 + 0.3 + 0.1) must reach their tier in any order.
        score = round(sum(i.weight for i in items if i.outcome == "pass"), 9)
        return items, score

    def _evaluate(
        self,
        cand: SetupCandidate,
        comp: CompiledSymbol,
        full: bool,
        account: AccountState,
        committed: float,
        governor: GovernorState,
        repeat: bool = False,
    ) -> tuple[Evaluation, float]:
        """The Pre-Trade Checklist, then risk, stop and order; returns the evaluation and risk cash.

        Every refusal reason is journaled. The decision path walks context ->
        each Confirmation -> risk -> stop -> order and marks every stage after
        the first refusal as skipped (the checklist still shows its outcomes).
        """
        doc = self.compiled.document
        checklist, score = self._checklist(cand, comp)
        blocked = [r for i in checklist if (r := i.refusal) is not None]

        risk = govern(doc.risk, account, pd.Timestamp(cand.time), math.floor(score), governor)
        risk_cash = risk.risk_fraction * account.equity
        record = risk.record()
        risk_refusals: list[str] = []
        if cand.direction < 0 and not comp.data.instrument.can_short:
            risk_refusals.append("cannot_short")
        if full:
            risk_refusals.append("position_limit")
        if repeat:
            risk_refusals.append("already_placed")  # one order per breakout
        risk_refusals += risk.blocked
        cap = doc.risk.max_open_risk
        if cap is not None and committed + risk_cash > cap * account.equity * (1 + 1e-9):
            risk_refusals.append("open_risk_cap")
        refused_by_checklist = bool(blocked)
        blocked += risk_refusals  # always journaled, even after a checklist refusal

        intents: list[Intent] = []
        stop_status: StageStatus = "skipped"
        order_status: StageStatus = "skipped"
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
            stop_status = "fail" if blocked else "pass"
            if not blocked:
                intents, problems = self._orders(cand, comp, stop, risk.risk_fraction)
                blocked += problems
                order_status = "fail" if problems else "pass"

        path: list[tuple[str, StageStatus]] = []
        refused = False
        context = [i for i in checklist if i.kind == "context"]
        context_ok = all(i.outcome != "fail" for i in context)
        path.append(("context", "pass" if context_ok else "fail"))
        refused = not context_ok
        for i in checklist:
            if i.kind == "confirmation":
                path.append((i.block, "skipped" if refused else i.outcome))
                refused = refused or i.refusal is not None
        risk_status: StageStatus = (
            "skipped" if refused_by_checklist else ("fail" if risk_refusals else "pass")
        )
        path += [("risk", risk_status), ("stop", stop_status), ("order", order_status)]

        placed = not blocked
        applicable = [i for i in checklist if i.outcome != "na"]
        justified = (
            all(i.outcome == "pass" for i in applicable)
            and score >= doc.checklist.justified_min_score
            if placed
            else None
        )
        evaluation = Evaluation(
            symbol=cand.symbol,
            time=cand.time,
            inputs={"bar": cand.bar},
            values={
                **cand.record(),
                "checklist": [i.record() for i in checklist],
                "score": score,
                "risk_tier": risk.base_risk,
                "risk": record,
                "decision": "placed" if placed else "refused",
                "reasons": blocked,
                # On a placed setup: would a stop here be a normal loss (ADR 10 §11)?
                "justified": justified,
                "decision_path": [{"stage": s, "status": st} for s, st in path],
            },
            state_before=SymbolState(),
            state_after=SymbolState(),
            intents=intents if placed else [],
            conditions={
                "context": {i.block: i.outcome == "pass" for i in context},
                "risk": {"allowed": risk.allowed},
            },
            blocked=blocked,
        )
        return evaluation, risk_cash

    def _orders(
        self, cand: SetupCandidate, comp: CompiledSymbol, stop: float, risk_fraction: float
    ) -> tuple[list[Intent], list[str]]:
        data = comp.data
        plan = self.compiled.exit.plan(cand, data, stop)
        if closes_all_below(plan, MIN_FULL_CLOSE_R):
            return [], ["exit_below_2r"]  # Profit Chain rule 1, whatever the Exit Block
        a = float(comp.atr[cand.bar])
        out: list[Intent] = []
        problems: list[str] = []
        k = 0
        for eidx, ex in self.compiled.executions:
            for spec in ex.orders(cand, data):
                try:
                    key = f"{cand.symbol}|{cand.time}|b{cand.block_index}|e{eidx}|{k}"
                    if spec.market:
                        out.append(
                            OpenIntent(
                                symbol=cand.symbol,
                                direction=cand.direction,
                                leg="single",
                                leg_index=k,
                                entry_type="setup",
                                signal_time=cand.time,
                                atr=a if np.isfinite(a) else 0.0,
                                risk_fraction=risk_fraction,
                                idempotency_key=key,
                                stop_distance=_stop_distance(spec.level, stop, cand.direction),
                                target_distance=None,
                                exit_plan=plan,
                            )
                        )
                        k += 1
                        continue
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
                            idempotency_key=key,
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
        if not out and not problems:
            problems.append("no_order")  # every Execution Block is waiting (e.g. for a body close)
        return out, problems
