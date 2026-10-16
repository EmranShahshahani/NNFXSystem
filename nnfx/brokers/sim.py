"""Simulated execution, shared by BacktestBroker and PaperBroker (doc 02 §3.5).

Per bar, for one symbol:

1. **open** - queued closes and market orders fill at the open (spread +
   slippage, rollover-widened spread on sessioned instruments). Stops and targets
   gapped through at the open fill *at the open*, not at their level.
2. **intrabar** - stops trigger on last or mark price per
   ``InstrumentSpec.stop_trigger_price``; targets on last price. If both are
   touched in one bar the stop is assumed first (conservative).
3. **close** - carry accrues (swap or funding, by capability) and positions are
   marked to market.

Every order carries an idempotency key; resubmitting a key returns the original
result and never creates a second position.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.engine.types import AccountState, EntryType, Leg, PositionView
from nnfx.instruments import InstrumentSpec

ConversionFn = Callable[[str, pd.Timestamp], float]


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
    target: float | None
    target_fraction: float
    leg: Leg
    entry_atr: float
    signal_time: str
    entry_type: EntryType
    risk_cash: float
    order_key: str
    scaled_out: bool = False
    commission: float = 0.0
    spread_cost: float = 0.0
    slippage_cost: float = 0.0
    carry: float = 0.0
    carry_kind: str = "none"
    bars_held: int = 0

    def view(self) -> PositionView:
        return PositionView(
            id=self.id,
            symbol=self.symbol,
            direction=self.direction,
            units=self.units,
            entry_price=self.entry_price,
            entry_time=self.entry_time,
            stop=self.stop,
            target=self.target,
            target_fraction=self.target_fraction,
            leg=self.leg,
            entry_atr=self.entry_atr,
            signal_time=self.signal_time,
            entry_type=self.entry_type,
            scaled_out=self.scaled_out,
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
class SimState:
    balance: float
    peak_equity: float
    seq: int = 0
    positions: dict[str, SimPosition] = field(default_factory=dict)
    queued: list[_Queued] = field(default_factory=list)
    queued_closes: list[tuple[str, float, str]] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)
    last_conv: dict[str, float] = field(default_factory=dict)
    # Broker-side event log: fills and closes, so a harness can reconcile its
    # expected position set against what the venue reports.
    events: list[dict[str, Any]] = field(default_factory=list)
    last_bar: dict[str, str] = field(default_factory=dict)
    exit_bar: dict[str, str] = field(default_factory=dict)


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
        self.s = SimState(balance=initial_equity, peak_equity=initial_equity)
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
        self.s.queued.append(_Queued(idempotency_key, oid, order))
        return OrderResult("accepted", oid, idempotency_key)

    def modify_stop(
        self, position_id: str, new_stop: float, new_target: float | None = None
    ) -> None:
        p = self.s.positions.get(position_id)
        if p is None:
            return
        p.stop = new_stop
        if new_target is not None and p.target is not None:
            p.target = new_target

    def close(self, position_id: str, fraction: float = 1.0, reason: str = "") -> None:
        if position_id in self.s.positions:
            self.s.queued_closes.append((position_id, fraction, reason))

    # -------------------------------------------------------------- internals
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
        self.s.events.append(
            {
                "n": len(self.s.events) + 1,
                "e": "close",
                "pid": p.id,
                "fraction": fraction,
                "units": units,
                "reason": reason,
            }
        )
        if fraction >= 1.0 - 1e-12:
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
            elif p.target is not None and (o - p.target) * p.direction >= 0:
                px, hs, sl = self._exit_fill(p, o, stop=False, at_open=True)
                self._target(p, px, ts, conv, hs, sl)

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
            vp = self._vppu(symbol) * conv
            p = SimPosition(
                id=q.order_id,
                symbol=symbol,
                direction=od.direction,
                units=od.units,
                entry_price=px,
                entry_time=ts.isoformat(),
                stop=px - od.direction * od.stop_distance,
                initial_stop=px - od.direction * od.stop_distance,
                target=None
                if od.target_distance is None
                else px + od.direction * od.target_distance,
                target_fraction=od.target_fraction,
                leg=od.leg,
                entry_atr=od.atr,
                signal_time=od.signal_time,
                entry_type=od.entry_type,
                risk_cash=od.risk_cash,
                order_key=q.key,
                commission=self.costs.commission(inst, od.units, px, conv),
                spread_cost=hs * od.units * vp,
                slippage_cost=sl * od.units * vp,
            )
            self.s.balance -= p.commission
            self.s.positions[p.id] = p
            self.s.events.append(
                {
                    "n": len(self.s.events) + 1,
                    "e": "fill",
                    "pid": p.id,
                    "key": q.key,
                    "units": p.units,
                }
            )
        self.s.queued = keepq

        # 2. intrabar stops (last or mark) and targets (last)
        use_mark = inst.stop_trigger_price == "mark"
        if use_mark and (mark_high is None or mark_low is None):
            raise ValueError(
                f"{symbol}: stop_trigger_price='mark' but the bars carry no mark prices"
            )
        trig_lo = mark_low if use_mark and mark_low is not None else lo
        trig_hi = mark_high if use_mark and mark_high is not None else h
        for p in mine():
            stop_hit = (trig_lo <= p.stop) if p.direction > 0 else (trig_hi >= p.stop)
            tgt_hit = p.target is not None and (
                (h >= p.target) if p.direction > 0 else (lo <= p.target)
            )
            if stop_hit:
                px, hs, sl = self._exit_fill(p, p.stop, stop=True, at_open=False)
                reason = (
                    "stop" if (p.stop - p.initial_stop) * p.direction <= 1e-12 else "trailing_stop"
                )
                self._close_leg(p, px, ts, reason, conv, spread=hs, slip=sl)
            elif tgt_hit and p.target is not None:
                px, hs, sl = self._exit_fill(p, p.target, stop=False, at_open=False)
                self._target(p, px, ts, conv, hs, sl)

        # 3. carry and mark-to-market at the close
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
        self.s.peak_equity = max(self.s.peak_equity, self.equity())

    def _target(
        self, p: SimPosition, px: float, ts: pd.Timestamp, conv: float, hs: float, sl: float
    ) -> None:
        if p.target_fraction < 1.0 and not p.scaled_out:
            self._close_leg(
                p, px, ts, "target_partial", conv, p.target_fraction, spread=hs, slip=sl
            )
            p.scaled_out = True
            p.target = None
        else:
            self._close_leg(p, px, ts, "target", conv, spread=hs, slip=sl)

    def force_close(self, symbol: str, price: float, ts: pd.Timestamp, reason: str) -> None:
        """Immediate close at ``price`` - delisting (last valid price) or end of data."""
        conv = self.conversion(self.instruments[symbol].quote, ts)
        for p in sorted(
            (p for p in self.s.positions.values() if p.symbol == symbol), key=lambda p: p.id
        ):
            self._close_leg(p, price, ts, reason, conv)
        self.s.queued = [q for q in self.s.queued if q.order.symbol != symbol]

    # ------------------------------------------------------------ persistence
    def dump_state(self) -> str:
        d = asdict(self.s)
        d["trades"] = [asdict(t) for t in self.trades]
        return json.dumps(d, sort_keys=True)

    def load_state(self, raw: str) -> None:
        d: dict[str, Any] = json.loads(raw)
        trades = d.pop("trades", [])
        self.s = SimState(
            balance=d["balance"],
            peak_equity=d["peak_equity"],
            seq=d["seq"],
            positions={k: SimPosition(**v) for k, v in d["positions"].items()},
            queued=[_Queued(q["key"], q["order_id"], Order(**q["order"])) for q in d["queued"]],
            queued_closes=[(str(a), float(b), str(c)) for a, b, c in d["queued_closes"]],
            keys=d["keys"],
            last_close=d["last_close"],
            last_conv=d["last_conv"],
            events=d.get("events", []),
            last_bar=d.get("last_bar", {}),
            exit_bar=d.get("exit_bar", {}),
        )
        self.trades = [Trade(**t) for t in trades]


class BacktestBroker(SimBroker):
    """Simulated fills over history."""
