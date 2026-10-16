"""The StrategyEngine: every NNFX rule lives here and nowhere else (doc 01 §5-§7).

``decide`` is pure. It performs no I/O, reads no clock, draws no randomness and
knows no concrete indicator or market name: it sees contract arrays through
``SymbolHistory``, positions through ``PositionView`` and branches only on
``InstrumentSpec`` capability flags. All state it needs between bars is passed
in as ``EngineState`` and returned, so it can be journaled and restored.

Timing: logic evaluates on the completed bar ``t``; every intent executes at the
open of ``t+1``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from nnfx.config import SystemConfig
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    TRADE_PHASES,
    AccountState,
    CloseIntent,
    EngineState,
    EntryType,
    Leg,
    ModifyIntent,
    OpenIntent,
    PendingSetup,
    Phase,
    PositionView,
    SymbolState,
    idempotency_key,
)

Intent = OpenIntent | CloseIntent | ModifyIntent
EPS = 1e-12


@dataclass
class Evaluation:
    """Everything one symbol's evaluation saw and did - the journal payload."""

    symbol: str
    time: str
    inputs: dict[str, Any]
    values: dict[str, Any]
    state_before: SymbolState
    state_after: SymbolState
    intents: list[Intent]
    conditions: dict[str, dict[str, bool]] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)


@dataclass
class Decision:
    intents: list[Intent]
    state: EngineState
    evaluations: list[Evaluation]


class StrategyEngine:
    """Stateless object; one instance is shared by the backtest and live harnesses."""

    def decide(
        self,
        history: Mapping[str, SymbolHistory],
        open_positions: Sequence[PositionView],
        account_state: AccountState,
        config: SystemConfig,
        state: EngineState | None = None,
    ) -> Decision:
        state = state or EngineState()
        new_symbols = dict(state.symbols)
        intents: list[Intent] = []
        evals: list[Evaluation] = []
        for symbol in sorted(history):
            h = history[symbol]
            pos = sorted((p for p in open_positions if p.symbol == symbol), key=lambda p: p.id)
            ev = _SymbolDecision(h, pos, account_state, config, state.get(symbol)).run()
            new_symbols[symbol] = ev.state_after
            intents.extend(ev.intents)
            evals.append(ev)
        return Decision(intents, EngineState(symbols=new_symbols), evals)


class _SymbolDecision:
    def __init__(
        self,
        h: SymbolHistory,
        positions: list[PositionView],
        account: AccountState,
        cfg: SystemConfig,
        st: SymbolState,
    ) -> None:
        self.h = h
        self.positions = positions
        self.account = account
        self.cfg = cfg
        self.rules = cfg.rules
        self.risk = cfg.risk
        self.st0 = st
        self.st = st.model_copy()
        self.intents: list[Intent] = []
        self.conditions: dict[str, dict[str, bool]] = {}
        self.blocked: list[str] = []

    # ------------------------------------------------------------------ helpers
    def update(self, **kw: Any) -> None:
        self.st = self.st.model_copy(update=kw)

    def warm(self, lag: int = 0) -> bool:
        h = self.h
        if not h.ok(lag):
            return False
        return not (math.isnan(h.v("atr", lag)) or math.isnan(h.v("baseline", lag)))

    def side(self, lag: int = 0) -> int:
        """sign(close - baseline)."""
        d = self.h.px("close", lag) - self.h.v("baseline", lag)
        return 1 if d > 0 else (-1 if d < 0 else 0)

    def direction_allowed(self, d: int) -> bool:
        if d > 0:
            return self.rules.allow_long
        return self.rules.allow_short and self.h.instrument.can_short

    def conds(self, d: int, lag: int = 0) -> dict[str, bool]:
        h, r = self.h, self.rules
        atr = h.v("atr", lag)
        dist = abs(h.px("close", lag) - h.v("baseline", lag))
        c: dict[str, bool] = {
            "c1_signal": h.iv("c1_signal", lag) == d,
            "c1_state": h.iv("c1_state", lag) == d,
            "baseline_agrees": (not r.baseline_filter) or self.side(lag) == d,
            "fresh_cross": h.ok(lag + 1)
            and self.warm(lag + 1)
            and self.side(lag) == d
            and self.side(lag + 1) != d,
            "bridge": (not r.bridge_too_far) or dist <= r.bridge_multiple * atr + EPS,
        }
        if r.c2_required and h.has("c2_state"):
            name = "c2_state" if r.c2_mode == "state" else "c2_signal"
            c["c2"] = h.iv(name, lag) == d
        else:
            c["c2"] = True
        c["volume"] = (
            h.iv("volume_gate", lag) == 1 if (r.volume_required and h.has("volume_gate")) else True
        )
        if r.seven_candle_rule:
            age = h.last_signal_age(
                "c1_signal", d, r.seven_candle_inclusive, r.seven_candle_bars + 1
            )
            c["seven_candle"] = age is not None and age <= r.seven_candle_bars
        else:
            c["seven_candle"] = True
        return c

    @staticmethod
    def standard_ok(c: Mapping[str, bool], *, skip: str = "") -> bool:
        keys = ("c1_signal", "baseline_agrees", "bridge", "c2", "volume")
        return all(c[k] for k in keys if k != skip)

    def baseline_ok(self, c: Mapping[str, bool], *, skip: str = "") -> bool:
        if not self.rules.baseline_entries:
            return False
        keys = ("fresh_cross", "c1_state", "seven_candle", "bridge", "c2", "volume")
        return all(c[k] for k in keys if k != skip)

    # --------------------------------------------------------------------- run
    def run(self) -> Evaluation:
        h = self.h
        if self.warm():
            if self.positions:
                self.manage_open()
            else:
                self.flat()
        else:
            self.blocked.append("warmup")
        return Evaluation(
            symbol=h.symbol,
            time=h.time(),
            inputs=h.inputs(),
            values=h.values(),
            state_before=self.st0,
            state_after=self.st,
            intents=self.intents,
            conditions=self.conditions,
            blocked=self.blocked,
        )

    # ============================================================ open trades
    def manage_open(self) -> None:
        h, st = self.h, self.st
        d = self.positions[0].direction
        if st.awaiting_fill or st.phase not in TRADE_PHASES:
            # First sight of the fill: confirm the trend origin for continuations.
            self.update(awaiting_fill=False, phase=Phase.IN_TRADE)
        close = h.px("close")
        best = (
            close
            if self.st.best_close is None
            else (max(self.st.best_close, close) if d > 0 else min(self.st.best_close, close))
        )
        self.update(best_close=best)

        reason = self.exit_reason(d)
        if reason:
            for p in self.positions:
                self.intents.append(CloseIntent(symbol=h.symbol, position_id=p.id, reason=reason))
            trend_dir = 0 if reason == "baseline_cross" else self.st.trend_dir
            self.update(
                phase=Phase.FLAT,
                last_exit_time=h.time(),
                best_close=None,
                tp1_reached=False,
                trend_dir=trend_dir,
                trend_origin=self.st.trend_origin if trend_dir else None,
            )
            self.blocked.append(f"exit:{reason}")
            return
        self.money_management(d)

    def exit_reason(self, d: int) -> str | None:
        """Deterministic precedence (doc 01 §6). Stop/target fire intrabar in the broker."""
        h = self.h
        if self.rules.exit_on_baseline_cross and self.side() == -d:
            return "baseline_cross"
        if h.has("exit"):
            if h.iv("exit") == (1 if d > 0 else -1):
                return "exit_indicator"
            return None
        if h.iv("c1_signal") == -d:
            return "opposite_c1"
        if h.has("c2_signal") and h.iv("c2_signal") == -d:
            return "opposite_c2"
        return None

    def money_management(self, d: int) -> None:
        h, risk = self.h, self.risk
        legs = {p.leg for p in self.positions}
        entry = self.positions[0].entry_price
        entry_atr = self.positions[0].entry_atr
        live_atr = h.v("atr")

        tp1_reached = self.st.tp1_reached
        if "runner" in legs and "tp1" not in legs:
            tp1_reached = True
        if any(p.leg == "combined" and p.scaled_out for p in self.positions):
            tp1_reached = True
        if legs == {"single"} and not tp1_reached:
            extreme = h.px("high") if d > 0 else h.px("low")
            tp1_reached = (extreme - entry) * d >= risk.tp1_atr_multiple * entry_atr - EPS
        self.update(tp1_reached=tp1_reached)

        if not tp1_reached:
            self.update(phase=Phase.IN_TRADE)
            if not risk.atr_frozen_at_entry:
                # A3 alternative: stop and first target recomputed from live ATR.
                for p in self.positions:
                    stop = entry - d * risk.stop_atr_multiple * live_atr
                    target = (
                        entry + d * risk.tp1_atr_multiple * live_atr
                        if p.target is not None
                        else None
                    )
                    if abs(stop - p.stop) > EPS or (
                        target is not None and p.target is not None and abs(target - p.target) > EPS
                    ):
                        self.intents.append(
                            ModifyIntent(
                                symbol=h.symbol,
                                position_id=p.id,
                                stop=stop,
                                target=target,
                                reason="live_atr",
                            )
                        )
            return

        if not risk.trailing:
            self.update(phase=Phase.RUNNER_BE)
            return
        # Runner management: breakeven, then trail 1.5xATR in 0.5xATR steps.
        a = live_atr if risk.trail_uses_live_atr else entry_atr
        best = self.st.best_close if self.st.best_close is not None else h.px("close")
        excursion = (best - entry) * d
        desired = entry
        phase = Phase.RUNNER_BE
        if excursion >= risk.trail_atr_multiple * a - EPS:
            phase = Phase.TRAILING
            steps = math.floor(
                (excursion - risk.trail_atr_multiple * a) / (risk.trail_step_atr * a) + 1e-9
            )
            desired = entry + d * steps * risk.trail_step_atr * a
        self.update(phase=phase)
        for p in self.positions:
            if p.leg == "tp1":
                continue
            if (desired - p.stop) * d > EPS:
                self.intents.append(
                    ModifyIntent(
                        symbol=h.symbol,
                        position_id=p.id,
                        stop=desired,
                        target=None,
                        reason="breakeven" if abs(desired - entry) <= EPS else "trail",
                    )
                )

    # ===================================================================== flat
    def flat(self) -> None:
        h, st = self.h, self.st
        if st.phase in TRADE_PHASES:
            if h.symbol in self.account.recent_exits:
                # Stopped or targeted out during this bar: no re-entry on the same bar.
                self.update(
                    phase=Phase.FLAT,
                    last_exit_time=h.time(),
                    best_close=None,
                    tp1_reached=False,
                    awaiting_fill=False,
                )
                self.blocked.append("exited_this_bar")
                self.invalidate_trend()
                return
            # The entry never filled (rejected by risk, or not submitted).
            self.update(
                phase=Phase.FLAT,
                awaiting_fill=False,
                best_close=None,
                tp1_reached=False,
                trend_dir=0 if st.entry_type != "continuation" else st.trend_dir,
                trend_origin=None if st.entry_type != "continuation" else st.trend_origin,
            )
        self.invalidate_trend()

        pending = self.st.pending
        if pending is not None:
            self.update(pending=None, phase=Phase.FLAT)
            # Explicit one-bar lifetime: only the bar immediately after the setup bar.
            if h.ok(1) and h.time(1) == pending.setup_time and self.resolve_pending(pending):
                return
            self.blocked.append(f"{pending.kind}_expired")

        for d in (1, -1):
            if self.fresh_setup(d):
                return
        for d in (1, -1):
            if self.continuation(d):
                return

    def invalidate_trend(self) -> None:
        if self.st.trend_dir and self.side() == -self.st.trend_dir:
            self.update(trend_dir=0, trend_origin=None)

    def fresh_setup(self, d: int) -> bool:
        c = self.conds(d)
        self.conditions["long" if d > 0 else "short"] = c
        std, base = self.standard_ok(c), self.baseline_ok(c)
        origin: Literal["standard", "baseline"] | None = (
            "standard" if std else ("baseline" if base else None)
        )
        if origin is not None:
            if not self.direction_allowed(d):
                self.blocked.append(f"{origin}_{'long' if d > 0 else 'short'}:direction_disabled")
                return False
            if self.rules.one_candle_rule == "B":
                self.arm("one_candle_b", d, origin)
                return True
            self.enter(d, origin)
            return True

        triggered = c["c1_signal"] or (self.rules.baseline_entries and c["fresh_cross"])
        if not triggered:
            return False
        tag = "long" if d > 0 else "short"
        if not self.direction_allowed(d):
            return False
        # Pullback: everything except the 1xATR distance filter.
        if self.rules.pullback and self.rules.bridge_too_far and not c["bridge"]:
            for kind_origin in ("standard", "baseline"):
                ok = (
                    self.standard_ok(c, skip="bridge")
                    if kind_origin == "standard"
                    else self.baseline_ok(c, skip="bridge")
                )
                if ok:
                    self.arm("pullback", d, kind_origin)
                    return True
        # 1CR-A: exactly one of {volume, c2} unmet, everything else satisfied.
        if self.rules.one_candle_rule == "A":
            for missing in ("volume", "c2"):
                other = "c2" if missing == "volume" else "volume"
                if c[missing] or not c[other]:
                    continue
                for kind_origin in ("standard", "baseline"):
                    ok = (
                        self.standard_ok(c, skip=missing)
                        if kind_origin == "standard"
                        else self.baseline_ok(c, skip=missing)
                    )
                    if ok:
                        self.arm("one_candle_a", d, kind_origin, missing=missing)
                        return True
        failed = [
            k for k, v in c.items() if not v and k not in ("fresh_cross", "c1_signal", "c1_state")
        ]
        self.blocked.append(f"{tag}:{'+'.join(failed) or 'conditions'}")
        return False

    def arm(self, kind: str, d: int, origin: str, missing: str | None = None) -> None:
        h = self.h
        setup = PendingSetup(
            kind=kind,
            direction=d,
            origin=origin,
            setup_time=h.time(),
            missing=missing,
            setup_close=h.px("close"),
        )
        phase = Phase.PENDING_PULLBACK if kind == "pullback" else Phase.PENDING_ONE_CANDLE
        self.update(pending=setup, phase=phase)

    def resolve_pending(self, p: PendingSetup) -> bool:
        """Evaluate a one-bar setup on its expiry bar. Enter, or let it expire."""
        d = p.direction
        if not self.direction_allowed(d):
            return False
        c = self.conds(d)
        self.conditions[f"pending_{p.kind}"] = c
        still = c["c1_state"] and c["baseline_agrees"] and c["c2"] and c["volume"] and c["bridge"]
        if p.kind == "pullback":
            ok = still
            etype: EntryType = "pullback"
        elif p.kind == "one_candle_a":
            # C1 signal read from the setup bar; everything else (incl. the missing one) now.
            ok = still
            etype = "one_candle_a"
        else:
            retraced = (self.h.px("close") - p.setup_close) * d < 0
            ok = still and retraced
            etype = "one_candle_b"
        if ok:
            self.enter(d, etype, origin_entry=True)
        return ok

    def continuation(self, d: int) -> bool:
        if not self.rules.continuation or self.st.trend_dir != d:
            return False
        if self.st.last_exit_time == self.h.time():
            return False
        h = self.h
        sig_name = "cont_signal" if h.has("cont_signal") else "c1_signal"
        c = {
            "continuation_signal": h.iv(sig_name) == d,
            "c1_state": h.iv("c1_state") == d,
            "baseline_agrees": self.side() == d,
        }
        self.conditions["continuation_" + ("long" if d > 0 else "short")] = c
        if all(c.values()) and self.direction_allowed(d):
            self.enter(d, "continuation")
            return True
        return False

    def enter(self, d: int, etype: EntryType, origin_entry: bool = False) -> None:
        h, risk = self.h, self.risk
        sig = h.time()
        atr = h.v("atr")
        stop_d = risk.stop_atr_multiple * atr
        tp_d = risk.tp1_atr_multiple * atr
        legs: list[
            tuple[Leg, float | None, float, float]
        ]  # leg, target distance, target fraction, risk fraction
        if risk.positions_per_entry == 1:
            legs = [("single", None, 1.0, 2 * risk.risk_per_position)]
        elif h.instrument.supports_hedging:
            legs = [
                ("tp1", tp_d, 1.0, risk.risk_per_position),
                ("runner", None, 1.0, risk.risk_per_position),
            ]
        else:
            # FIFO / no-hedging venue: one position, half closed at TP1 (story 63).
            legs = [("combined", tp_d, 0.5, 2 * risk.risk_per_position)]
        for i, (leg, tgt, frac, rf) in enumerate(legs):
            self.intents.append(
                OpenIntent(
                    symbol=h.symbol,
                    direction=d,
                    leg=leg,
                    leg_index=i,
                    entry_type=etype,
                    signal_time=sig,
                    atr=atr,
                    stop_distance=stop_d,
                    target_distance=tgt,
                    target_fraction=frac,
                    risk_fraction=rf,
                    idempotency_key=idempotency_key(h.symbol, sig, i),
                )
            )
        upd: dict[str, Any] = dict(
            phase=Phase.IN_TRADE,
            awaiting_fill=True,
            pending=None,
            entry_type=etype,
            entry_signal_time=sig,
            entry_atr=atr,
            best_close=None,
            tp1_reached=False,
        )
        if etype != "continuation":
            upd.update(trend_dir=d, trend_origin=sig)
        self.update(**upd)
