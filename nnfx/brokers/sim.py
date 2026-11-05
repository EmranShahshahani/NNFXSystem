"""Simulated execution, shared by BacktestBroker and PaperBroker (doc 02 §3.5).

Per bar, for one symbol:

1. **open** - queued closes and market orders fill at the open (spread +
   slippage, rollover-widened spread on sessioned instruments). Stops and targets
   gapped through at the open fill *at the open*, not at their level.
2. **intrabar** - stops trigger on last or mark price per
   ``InstrumentSpec.stop_trigger_price``; targets on last price. If both are
   touched in one bar the stop is assumed first (conservative).
   Pending stop-market orders (ADR 09 §4) placed at an earlier decision fill
   here: a long at max(level, open), a short at min(level, open), as stop
   orders with stop slippage. A position opened this way is checked against
   its stop and target in the same bar, stop first. Orders in one OCO group
   are tried in placement order; the first fill cancels the rest.
3. **close** - an unfilled pending order is cancelled when the bar closes
   beyond its invalidation price, or when it has rested its
   ``expires_after_bars`` bars. Carry accrues (swap or funding, by capability) and positions are
   marked to market.

Every order carries an idempotency key; resubmitting a key returns the original
result and never creates a second position.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Literal, Protocol

import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.engine.types import (
    AccountState,
    EntryType,
    ExitPlan,
    ExitStepView,
    Leg,
    PendingOrderView,
    PositionView,
    TradeOutcome,
    trigger_price,
)
from nnfx.instruments import InstrumentSpec

# Closed positions the account reports to engines (the governors look back 50 trades,
# a day, and a week).
RECENT_OUTCOMES = 500

ConversionFn = Callable[[str, pd.Timestamp], float]


@dataclass(frozen=True)
class PendingSpec:
    """The resting part of a stop-market order; stop and target are absolute prices."""

    level: float
    buffer: float
    stop: float
    target: float | None
    invalidation: float | None
    expires_after_bars: int
    oco_group: str | None

    def trigger(self, direction: int) -> float:
        return trigger_price(self.level, direction, self.buffer)


@dataclass(frozen=True)
class Order:
    symbol: str
    direction: int
    units: float
    leg: Leg
    entry_type: EntryType
    signal_time: str
    atr: float
    stop_distance: float
    target_distance: float | None
    target_fraction: float
    risk_cash: float
    # Set for a pending stop-market order (a Trigger); None for a market order.
    pending: PendingSpec | None = None
    # Fractional exit steps; None means the single target above (or none).
    exit_plan: ExitPlan | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Order:
        spec, plan = d.get("pending"), d.get("exit_plan")
        return cls(
            **{
                **d,
                "pending": None if spec is None else PendingSpec(**spec),
                "exit_plan": None if plan is None else ExitPlan.model_validate(plan),
            }
        )


@dataclass(frozen=True)
class OrderResult:
    status: Literal["accepted", "duplicate", "rejected"]
    order_id: str
    idempotency_key: str
    reason: str = ""


class Broker(Protocol):
    def account(self) -> AccountState: ...
    def positions(self) -> list[PositionView]: ...
    def instrument(self, symbol: str) -> InstrumentSpec: ...
    def submit(self, order: Order, idempotency_key: str) -> OrderResult: ...
    def modify_stop(
        self, position_id: str, new_stop: float, new_target: float | None = None
    ) -> None: ...
    def close(self, position_id: str, fraction: float = 1.0, reason: str = "") -> None: ...
    def cancel(self, order_key: str, reason: str) -> None: ...


@dataclass
class ExitLevel:
    """One exit step at an absolute price: close ``fraction`` of the original size."""

    price: float
    fraction: float
    # Absolute stop to move to once this step fills (never loosening), if any.
    stop_to: float | None = None
    done: bool = False
    # Close whole size steps only (exit plans). The single NNFX target closes its
    # exact fraction, as it always has: its frozen results depend on it.
    whole_steps: bool = False


@dataclass
class SimPosition:
    id: str
    symbol: str
    direction: int
    units: float
    entry_price: float
    entry_time: str
    stop: float
    initial_stop: float
    leg: Leg
    entry_atr: float
    signal_time: str
    entry_type: EntryType
    risk_cash: float
    order_key: str
    original_units: float
    # The exit plan in prices, in order; units left after all steps are the remainder.
    exits: list[ExitLevel] = field(default_factory=list)
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    carry: float = 0.0
    carry_kind: str = "none"
    bars_held: int = 0
    realized_net: float = 0.0  # net P&L of the exits taken so far
    risk_closed: float = 0.0  # risk assigned to the exits taken so far

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SimPosition:
        d = dict(d)
        if "exits" not in d:
            # A state file from before exit plans: one target, maybe already scaled out.
            target, frac = d.pop("target", None), d.pop("target_fraction", 1.0)
            scaled = d.pop("scaled_out", False)
            d["exits"] = (
                []
                if target is None and not scaled
                else [
                    {
                        "price": target if target is not None else d["entry_price"],
                        "fraction": frac,
                        "done": scaled,
                    }
                ]
            )
            d["original_units"] = d["units"] / (1.0 - frac) if scaled else d["units"]
        return cls(**{**d, "exits": [ExitLevel(**e) for e in d["exits"]]})

    @property
    def next_exit(self) -> ExitLevel | None:
        return next((e for e in self.exits if not e.done), None)

    def view(self) -> PositionView:
        nxt = self.next_exit
        return PositionView(
            id=self.id,
            symbol=self.symbol,
            direction=self.direction,
            units=self.units,
            entry_price=self.entry_price,
            entry_time=self.entry_time,
            stop=self.stop,
            target=None if nxt is None else nxt.price,
            target_fraction=1.0 if nxt is None else nxt.fraction,
            leg=self.leg,
            entry_atr=self.entry_atr,
            signal_time=self.signal_time,
            entry_type=self.entry_type,
            scaled_out=any(e.done for e in self.exits),
            exit_steps=tuple(
                ExitStepView(price=e.price, fraction=e.fraction, done=e.done) for e in self.exits
            ),
            steps_filled=sum(e.done for e in self.exits),
            risk_cash=self.risk_cash,
        )


@dataclass(frozen=True)
class Trade:
    """One closed leg (or the closed part of a leg)."""

    position_id: str
    symbol: str
    leg: Leg
    direction: int
    entry_type: EntryType
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    units: float
    gross_pnl: float
    commission: float
    spread_cost: float
    slippage_cost: float
    carry: float
    carry_kind: str
    net_pnl: float
    risk_cash: float
    r_multiple: float
    exit_reason: str
    bars_held: int


@dataclass
class _Queued:
    key: str
    order_id: str
    order: Order


@dataclass
class _Pending:
    key: str
    order_id: str
    order: Order
    placed_time: str
    bars_active: int = 0

    @property
    def spec(self) -> PendingSpec:
        assert self.order.pending is not None
        return self.order.pending

    @property
    def symbol(self) -> str:
        return self.order.symbol

    @property
    def trigger(self) -> float:
        return self.spec.trigger(self.order.direction)

    def view(self) -> PendingOrderView:
        sp = self.spec
        return PendingOrderView(
            order_id=self.order_id,
            key=self.key,
            symbol=self.order.symbol,
            direction=self.order.direction,
            level=sp.level,
            trigger=self.trigger,
            stop=sp.stop,
            target=sp.target,
            invalidation=sp.invalidation,
            expires_after_bars=sp.expires_after_bars,
            bars_active=self.bars_active,
            oco_group=sp.oco_group,
            placed_time=self.placed_time,
            risk_cash=self.order.risk_cash,
        )


@dataclass
class SimState:
    balance: float
    peak_equity: float
    seq: int = 0
    positions: dict[str, SimPosition] = field(default_factory=dict)
    queued: list[_Queued] = field(default_factory=list)
    pending: list[_Pending] = field(default_factory=list)
    queued_closes: list[tuple[str, float, str]] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)
    last_conv: dict[str, float] = field(default_factory=dict)
    # Broker-side event log: fills and closes, so a harness can reconcile its
    # expected position set against what the venue reports.
    events: list[dict[str, Any]] = field(default_factory=list)
    last_bar: dict[str, str] = field(default_factory=dict)
    exit_bar: dict[str, str] = field(default_factory=dict)
    initial_equity: float = 0.0
    trough_equity: float = 0.0  # lowest equity since the last high
    outcomes: list[dict[str, Any]] = field(default_factory=list)


class SimBroker:
    def __init__(
        self,
        instruments: dict[str, InstrumentSpec],
        costs: CostModel,
        initial_equity: float,
        account_currency: str = "USD",
        conversion: ConversionFn | None = None,
    ) -> None:
        self.instruments = instruments
        self.costs = costs
        self.currency = account_currency
        self.conversion = conversion or (lambda ccy, ts: 1.0)
        self.s = SimState(
            balance=initial_equity,
            peak_equity=initial_equity,
            initial_equity=initial_equity,
            trough_equity=initial_equity,
        )
        self.trades: list[Trade] = []

    # ---------------------------------------------------------------- protocol
    def instrument(self, symbol: str) -> InstrumentSpec:
        return self.instruments[symbol]

    def positions(self) -> list[PositionView]:
        return [p.view() for p in sorted(self.s.positions.values(), key=lambda p: p.id)]

    def equity(self) -> float:
        eq = self.s.balance
        for p in self.s.positions.values():
            px = self.s.last_close.get(p.symbol, p.entry_price)
            conv = self.s.last_conv.get(p.symbol, 1.0)
            eq += (px - p.entry_price) * p.direction * p.units * self._vppu(
                p.symbol
            ) * conv + p.carry
        return eq

    def account(self) -> AccountState:
        eq = self.equity()
        return AccountState(
            equity=eq,
            balance=self.s.balance,
            peak_equity=max(self.s.peak_equity, eq),
            currency=self.currency,
            recent_exits=frozenset(
                sym for sym, t in self.s.exit_bar.items() if t == self.s.last_bar.get(sym)
            ),
            pending_orders=tuple(q.view() for q in self.s.pending),
            initial_equity=self.s.initial_equity or None,
            drawdown_from_peak=(
                1.0 - self.s.trough_equity / self.s.peak_equity if self.s.peak_equity > 0 else 0.0
            ),
            recent_outcomes=tuple(TradeOutcome(**o) for o in self.s.outcomes[-RECENT_OUTCOMES:]),
        )

    def value_per_price_unit(self, symbol: str, ts: pd.Timestamp) -> float:
        inst = self.instruments[symbol]
        return float(inst.value_per_price_unit) * self.conversion(inst.quote, ts)

    def submit(self, order: Order, idempotency_key: str) -> OrderResult:
        if idempotency_key in self.s.keys:
            return OrderResult(
                "duplicate", self.s.keys[idempotency_key], idempotency_key, "key already used"
            )
        if order.direction < 0 and not self.instruments[order.symbol].can_short:
            return OrderResult("rejected", "", idempotency_key, "instrument cannot be shorted")
        self.s.seq += 1
        oid = f"{order.symbol}#{self.s.seq}"
        self.s.keys[idempotency_key] = oid
        if order.pending is None:
            self.s.queued.append(_Queued(idempotency_key, oid, order))
            return OrderResult("accepted", oid, idempotency_key)
        placed = self.s.last_bar.get(order.symbol, "")
        rest = _Pending(idempotency_key, oid, order, placed)
        self.s.pending.append(rest)
        self._event("place", key=idempotency_key, order_id=oid, trigger=rest.trigger, time=placed)
        return OrderResult("accepted", oid, idempotency_key)

    def cancel(self, order_key: str, reason: str) -> None:
        """Cancel a resting pending order; unknown or already-filled keys are a no-op."""
        for r in self.s.pending:
            if r.key == order_key:
                self._drop_pending(r, reason, self.s.last_bar.get(r.symbol, ""))
                return

    def modify_stop(
        self, position_id: str, new_stop: float, new_target: float | None = None
    ) -> None:
        p = self.s.positions.get(position_id)
        if p is None:
            return
        p.stop = new_stop
        nxt = p.next_exit
        if new_target is not None and nxt is not None:
            after = [e for e in p.exits if not e.done][1:2]
            if after and (after[0].price - new_target) * p.direction <= 0:
                raise ValueError(
                    f"{position_id}: target {new_target} would pass the next step at {after[0].price}"
                )
            nxt.price = new_target

    def close(self, position_id: str, fraction: float = 1.0, reason: str = "") -> None:
        if position_id in self.s.positions:
            self.s.queued_closes.append((position_id, fraction, reason))

    # -------------------------------------------------------------- internals
    def _event(self, kind: str, **fields: Any) -> None:
        self.s.events.append({"n": len(self.s.events) + 1, "e": kind, **fields})

    def _drop_pending(self, r: _Pending, reason: str, time: str) -> None:
        self.s.pending.remove(r)
        self._event("cancel", key=r.key, order_id=r.order_id, reason=reason, time=time)

    def _open_position(
        self,
        key: str,
        oid: str,
        od: Order,
        px: float,
        ts: pd.Timestamp,
        conv: float,
        hs: float,
        sl: float,
    ) -> SimPosition:
        inst = self.instruments[od.symbol]
        vp = self._vppu(od.symbol) * conv
        if od.pending is not None:
            stop, target = od.pending.stop, od.pending.target
        else:
            stop = px - od.direction * od.stop_distance
            target = None if od.target_distance is None else px + od.direction * od.target_distance
        if od.exit_plan is not None:
            # Steps sit at R multiples of the planned stop distance from the planned
            # entry: the Trigger for a pending order (like its absolute stop), the
            # fill for a market order (whose stop is placed from the fill too).
            sign, r_unit = od.direction, od.stop_distance
            anchor = px if od.pending is None else od.pending.trigger(sign)
            exits = [
                ExitLevel(
                    price=anchor + sign * st.r * r_unit,
                    fraction=st.fraction,
                    stop_to=None if st.stop_to_r is None else anchor + sign * st.stop_to_r * r_unit,
                    whole_steps=True,
                )
                for st in od.exit_plan.steps
            ]
        else:
            # The single target: one step of target_fraction, the rest a remainder.
            exits = [] if target is None else [ExitLevel(target, od.target_fraction)]
        p = SimPosition(
            id=oid,
            symbol=od.symbol,
            direction=od.direction,
            units=od.units,
            entry_price=px,
            entry_time=ts.isoformat(),
            stop=stop,
            initial_stop=stop,
            leg=od.leg,
            entry_atr=od.atr,
            signal_time=od.signal_time,
            entry_type=od.entry_type,
            risk_cash=od.risk_cash,
            order_key=key,
            original_units=od.units,
            exits=exits,
            commission=self.costs.commission(inst, od.units, px, conv),
            spread_cost=hs * od.units * vp,
            slippage_cost=sl * od.units * vp,
        )
        self.s.balance -= p.commission
        self.s.positions[p.id] = p
        return p

    def _fill_pending(
        self, symbol: str, ts: pd.Timestamp, o: float, h: float, lo: float, conv: float
    ) -> None:
        """Fill resting orders this bar reached: gaps at the open first, then intrabar.

        A bar does not say in which order it reached two intrabar levels, so
        within each group the earlier-placed order is taken to fill first.
        """
        resting = [r for r in self.s.pending if r.symbol == symbol]
        gapped = [r for r in resting if (o - r.trigger) * r.order.direction >= 0]
        touched = [
            r
            for r in resting
            if r not in gapped
            and ((h >= r.trigger) if r.order.direction > 0 else (lo <= r.trigger))
        ]
        for r, ref in [(r, o) for r in gapped] + [(r, r.trigger) for r in touched]:
            if r in self.s.pending:  # an OCO sibling may have cancelled it this bar
                self._fill_one(r, ref, ref == o and r in gapped, ts, conv)

    def _fill_one(
        self, r: _Pending, ref: float, at_open: bool, ts: pd.Timestamp, conv: float
    ) -> None:
        od, inst = r.order, self.instruments[r.symbol]
        hs = self.costs.half_spread(inst, ref, at_open)
        sl = self.costs.slippage(inst, ref, True)
        px = ref + od.direction * (hs + sl)
        p = self._open_position(r.key, r.order_id, od, px, ts, conv, hs, sl)
        self.s.pending.remove(r)
        self._event("fill", pid=p.id, key=r.key, units=p.units, price=px, time=ts.isoformat())
        group = r.spec.oco_group
        if group is not None:
            for other in [x for x in self.s.pending if x.spec.oco_group == group]:
                self._drop_pending(other, "oco", ts.isoformat())

    def _age_pending(self, symbol: str, ts: pd.Timestamp, c: float) -> None:
        for r in [r for r in self.s.pending if r.symbol == symbol]:
            sp = r.spec
            r.bars_active += 1
            if sp.invalidation is not None and (c - sp.invalidation) * r.order.direction < 0:
                self._drop_pending(r, "invalidated", ts.isoformat())
            elif r.bars_active >= sp.expires_after_bars:
                self._drop_pending(r, "expired", ts.isoformat())

    def _vppu(self, symbol: str) -> float:
        return float(self.instruments[symbol].value_per_price_unit)

    def _close_leg(
        self,
        p: SimPosition,
        price: float,
        ts: pd.Timestamp,
        reason: str,
        conv: float,
        fraction: float = 1.0,
        *,
        spread: float = 0.0,
        slip: float = 0.0,
    ) -> None:
        inst = self.instruments[p.symbol]
        units = p.units * fraction
        comm = self.costs.commission(inst, units, price, conv)
        gross = (price - p.entry_price) * p.direction * units * self._vppu(p.symbol) * conv
        share = fraction
        entry_comm, entry_spread, entry_slip, carry = (
            p.commission * share,
            p.spread_cost * share,
            p.slippage_cost * share,
            p.carry * share,
        )
        spread_c = spread * units * self._vppu(p.symbol) * conv
        slip_c = slip * units * self._vppu(p.symbol) * conv
        # gross already embeds the exit spread/slippage via the fill price.
        net = gross - comm - entry_comm + carry
        risk = p.risk_cash * share
        self.trades.append(
            Trade(
                position_id=p.id,
                symbol=p.symbol,
                leg=p.leg,
                direction=p.direction,
                entry_type=p.entry_type,
                signal_time=p.signal_time,
                entry_time=p.entry_time,
                exit_time=ts.isoformat(),
                entry_price=p.entry_price,
                exit_price=price,
                units=units,
                gross_pnl=gross,
                commission=comm + entry_comm,
                spread_cost=entry_spread + spread_c,
                slippage_cost=entry_slip + slip_c,
                carry=carry,
                carry_kind=p.carry_kind,
                net_pnl=net,
                risk_cash=risk,
                r_multiple=net / risk if risk > 0 else 0.0,
                exit_reason=reason,
                bars_held=p.bars_held,
            )
        )
        self.s.balance += gross - comm + carry
        self.s.exit_bar[p.symbol] = ts.isoformat()
        self._event("close", pid=p.id, fraction=fraction, units=units, reason=reason)
        p.realized_net += net
        p.risk_closed += risk
        if fraction >= 1.0 - 1e-12:
            self.s.outcomes.append(
                {
                    "position_id": p.id,
                    "symbol": p.symbol,
                    "exit_time": ts.isoformat(),
                    "net_pnl": p.realized_net,
                    "risk_cash": p.risk_closed,
                }
            )
            del self.s.positions[p.id]
        else:
            p.units -= units
            p.commission -= entry_comm
            p.spread_cost -= entry_spread
            p.slippage_cost -= entry_slip
            p.carry -= carry
            p.risk_cash -= risk

    def _exit_fill(
        self, p: SimPosition, ref: float, stop: bool, at_open: bool
    ) -> tuple[float, float, float]:
        inst = self.instruments[p.symbol]
        hs = self.costs.half_spread(inst, ref, at_open)
        sl = self.costs.slippage(inst, ref, stop) if (stop or at_open) else 0.0
        return ref - p.direction * (hs + sl), hs, sl

    # ------------------------------------------------------------- bar driver
    def process_bar(
        self,
        symbol: str,
        ts: pd.Timestamp,
        o: float,
        h: float,
        lo: float,
        c: float,
        *,
        mark_high: float | None = None,
        mark_low: float | None = None,
        funding: float | None = None,
        bar_hours: float = 24.0,
    ) -> None:
        inst = self.instruments[symbol]
        if self.s.last_bar.get(symbol, "") >= ts.isoformat():
            return  # already processed (restart after a crash): never apply a bar twice
        self.s.last_bar[symbol] = ts.isoformat()
        conv = self.conversion(inst.quote, ts)

        def mine() -> list[SimPosition]:
            return sorted(
                (p for p in self.s.positions.values() if p.symbol == symbol), key=lambda p: p.id
            )

        # 1a. queued closes at the open
        keep: list[tuple[str, float, str]] = []
        for pid, frac, reason in self.s.queued_closes:
            p = self.s.positions.get(pid)
            if p is None:
                continue
            if p.symbol != symbol:
                keep.append((pid, frac, reason))
                continue
            px, hs, sl = self._exit_fill(p, o, stop=False, at_open=True)
            self._close_leg(p, px, ts, reason or "close", conv, frac, spread=hs, slip=sl)
        self.s.queued_closes = keep

        # 1b. gaps through existing stops / targets
        for p in mine():
            if (o - p.stop) * p.direction <= 0:
                px, hs, sl = self._exit_fill(p, o, stop=True, at_open=True)
                self._close_leg(p, px, ts, "stop_gap", conv, spread=hs, slip=sl)
            else:
                # Every step the open gapped through fills at the open, in order.
                self._fill_exit_steps(p, o, o, ts, conv, at_open=True)

        # 1c. market orders at the open
        keepq: list[_Queued] = []
        for q in self.s.queued:
            od = q.order
            if od.symbol != symbol:
                keepq.append(q)
                continue
            hs = self.costs.half_spread(inst, o, True)
            sl = self.costs.slippage(inst, o, False)
            px = o + od.direction * (hs + sl)
            p = self._open_position(q.key, q.order_id, od, px, ts, conv, hs, sl)
            self._event("fill", pid=p.id, key=q.key, units=p.units)
        self.s.queued = keepq

        # 1d. pending stop-market orders: gap at the open, else through the level
        self._fill_pending(symbol, ts, o, h, lo, conv)

        # 2. intrabar stops (last or mark) and targets (last)
        use_mark = inst.stop_trigger_price == "mark"
        if use_mark and (mark_high is None or mark_low is None):
            raise ValueError(
                f"{symbol}: stop_trigger_price='mark' but the bars carry no mark prices"
            )
        trig_lo = mark_low if use_mark and mark_low is not None else lo
        trig_hi = mark_high if use_mark and mark_high is not None else h
        for p in mine():
            if self._stop_hit(p, trig_lo, trig_hi):
                self._stop_out(p, ts, conv)
                continue
            moved = self._fill_exit_steps(p, h, lo, ts, conv, at_open=False)
            # Conservative: a stop the steps just tightened is hit if this bar reached it.
            if moved and p.id in self.s.positions and self._stop_hit(p, trig_lo, trig_hi):
                self._stop_out(p, ts, conv)

        # 3. pending orders still resting: invalidation and expiry at the close
        self._age_pending(symbol, ts, c)

        # carry and mark-to-market at the close
        weekday = int(ts.weekday())
        for p in mine():
            notional = p.units * c * self._vppu(symbol) * conv
            cash, kind = self.costs.carry(inst, p.direction, notional, weekday, funding, bar_hours)
            p.carry += cash
            if kind != "none":
                p.carry_kind = kind
            p.bars_held += 1
        self.s.last_close[symbol] = c
        self.s.last_conv[symbol] = conv
        eq = self.equity()
        if eq >= self.s.peak_equity:
            self.s.peak_equity = self.s.trough_equity = eq
        else:
            self.s.trough_equity = min(self.s.trough_equity or eq, eq)

    @staticmethod
    def _stop_hit(p: SimPosition, trig_lo: float, trig_hi: float) -> bool:
        return (trig_lo <= p.stop) if p.direction > 0 else (trig_hi >= p.stop)

    def _stop_out(self, p: SimPosition, ts: pd.Timestamp, conv: float) -> None:
        px, hs, sl = self._exit_fill(p, p.stop, stop=True, at_open=False)
        reason = "stop" if (p.stop - p.initial_stop) * p.direction <= 1e-12 else "trailing_stop"
        self._close_leg(p, px, ts, reason, conv, spread=hs, slip=sl)

    def _fill_exit_steps(
        self, p: SimPosition, h: float, lo: float, ts: pd.Timestamp, conv: float, *, at_open: bool
    ) -> bool:
        """Fill, in order, every exit step the price range [lo, h] reached.

        At the open (h == lo == open) steps fill at the open; intrabar at their
        own price. True if a filled step tightened the stop.
        """
        moved = False
        while p.id in self.s.positions and (nxt := p.next_exit) is not None:
            if not ((h >= nxt.price) if p.direction > 0 else (lo <= nxt.price)):
                break
            ref = h if at_open else nxt.price
            px, hs, sl = self._exit_fill(p, ref, stop=False, at_open=at_open)
            moved |= self._fill_exit_step(p, nxt, px, ts, conv, hs, sl)
        return moved

    def _fill_exit_step(
        self,
        p: SimPosition,
        ex: ExitLevel,
        px: float,
        ts: pd.Timestamp,
        conv: float,
        hs: float,
        sl: float,
    ) -> bool:
        """Close one exit step at ``px``; True if it tightened the stop."""
        ex.done = True
        units = ex.fraction * p.original_units
        if ex.whole_steps:
            # A venue closes whole size steps only: round the step's share down.
            step = Decimal(str(self.instruments[p.symbol].size_step))
            raw = Decimal(repr(units))
            units = float((raw / step).to_integral_value(ROUND_FLOOR) * step)
        if p.units - units <= 1e-9 * p.original_units:
            self._close_leg(p, px, ts, "target", conv, spread=hs, slip=sl)
            return False
        if units > 0:
            self._close_leg(p, px, ts, "target_partial", conv, units / p.units, spread=hs, slip=sl)
        if ex.stop_to is not None and (ex.stop_to - p.stop) * p.direction > 0:
            p.stop = ex.stop_to
            return True
        return False

    def force_close(self, symbol: str, price: float, ts: pd.Timestamp, reason: str) -> None:
        """Immediate close at ``price`` - delisting (last valid price) or end of data."""
        conv = self.conversion(self.instruments[symbol].quote, ts)
        for p in sorted(
            (p for p in self.s.positions.values() if p.symbol == symbol), key=lambda p: p.id
        ):
            self._close_leg(p, price, ts, reason, conv)
        self.s.queued = [q for q in self.s.queued if q.order.symbol != symbol]
        for r in [r for r in self.s.pending if r.symbol == symbol]:
            self._drop_pending(r, reason, ts.isoformat())

    # ------------------------------------------------------------ persistence
    def dump_state(self) -> str:
        d = asdict(self.s)
        d["trades"] = [asdict(t) for t in self.trades]
        return json.dumps(d, sort_keys=True, default=_jsonable)

    def load_state(self, raw: str) -> None:
        d: dict[str, Any] = json.loads(raw)
        trades = d.pop("trades", [])
        self.s = SimState(
            balance=d["balance"],
            peak_equity=d["peak_equity"],
            seq=d["seq"],
            positions={k: SimPosition.from_dict(v) for k, v in d["positions"].items()},
            queued=[
                _Queued(q["key"], q["order_id"], Order.from_dict(q["order"])) for q in d["queued"]
            ],
            pending=[
                _Pending(
                    r["key"],
                    r["order_id"],
                    Order.from_dict(r["order"]),
                    r["placed_time"],
                    r["bars_active"],
                )
                for r in d.get("pending", [])
            ],
            queued_closes=[(str(a), float(b), str(c)) for a, b, c in d["queued_closes"]],
            keys=d["keys"],
            last_close=d["last_close"],
            last_conv=d["last_conv"],
            events=d.get("events", []),
            last_bar=d.get("last_bar", {}),
            exit_bar=d.get("exit_bar", {}),
            # A state file from before governors: its first balance is unknown; the
            # earliest equity it knew (the peak) is the safest stand-in.
            initial_equity=d.get("initial_equity", d["peak_equity"]),
            trough_equity=d.get("trough_equity", d["peak_equity"]),
            outcomes=d.get("outcomes", []),
        )
        self.trades = [Trade(**t) for t in trades]


def _jsonable(o: object) -> Any:
    """JSON for the pydantic models an Order carries (its exit plan)."""
    dump = getattr(o, "model_dump", None)
    if dump is None:
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")
    return dump(mode="json")


class BacktestBroker(SimBroker):
    """Simulated fills over history."""
