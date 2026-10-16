"""Risk manager (doc 02 §3.4, §7; tickets 15, 16, 18).

* sizing from risk cash, stop distance and a broker-supplied value per price unit
* the quantization guard: realised risk after rounding to the size step must be
  within tolerance of target, or the trade is rejected
* per-currency exposure cap, and the crypto analogue in BTC-beta-weighted terms
* leverage constraint: liquidation must sit beyond 3xATR - a violation is a
  sizing bug and blocks the order
* kill switch, evaluated before every order: blocks new entries on a drawdown
  breach, never dumps existing positions
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from nnfx.config import RiskConfig
from nnfx.engine.types import AccountState, OpenIntent, PositionView
from nnfx.instruments import InstrumentSpec

# Stablecoin legs are not a directional currency bet for the per-currency cap.
EXPOSURE_EXEMPT = frozenset({"USDT", "USDC", "BUSD", "FDUSD", "DAI"})


@dataclass(frozen=True)
class SizedOrder:
    intent: OpenIntent
    units: float
    risk_cash: float
    realized_risk: float


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str = ""
    order: SizedOrder | None = None


@dataclass(frozen=True)
class _Exposure:
    symbol: str
    direction: int
    risk_fraction: float
    instrument: InstrumentSpec


class RiskManager:
    def __init__(self, cfg: RiskConfig) -> None:
        self.cfg = cfg

    # ----------------------------------------------------------------- sizing
    def size(
        self,
        intent: OpenIntent,
        account: AccountState,
        inst: InstrumentSpec,
        value_per_price_unit: float,
    ) -> RiskDecision:
        if self.cfg.fixed_units is not None:
            u = float(self.cfg.fixed_units)
            risk = u * intent.stop_distance * value_per_price_unit
            return RiskDecision(True, order=SizedOrder(intent, u, risk, risk))
        risk_cash = intent.risk_fraction * account.equity
        per_unit = intent.stop_distance * value_per_price_unit
        if per_unit <= 0:
            return RiskDecision(False, "non_positive_stop_distance")
        raw = Decimal(repr(risk_cash / per_unit))
        step = inst.size_step
        units_d = (raw / step).to_integral_value(rounding=ROUND_FLOOR) * step
        if units_d < inst.min_size:
            return RiskDecision(False, f"below_min_size ({float(raw):.6g} < {inst.min_size})")
        units = float(units_d)
        realized = units * per_unit
        dev = abs(realized - risk_cash) / risk_cash
        if dev > self.cfg.sizing_tolerance:
            return RiskDecision(False, f"quantization: realised risk off target by {dev:.0%}")
        return RiskDecision(True, order=SizedOrder(intent, units, risk_cash, realized))

    # --------------------------------------------------------------- approval
    def approve(
        self,
        sized: SizedOrder,
        inst: InstrumentSpec,
        account: AccountState,
        open_positions: Sequence[PositionView],
        instruments: dict[str, InstrumentSpec],
        approved_this_cycle: Iterable[SizedOrder] = (),
        entry_price: float | None = None,
    ) -> RiskDecision:
        intent = sized.intent
        cfg = self.cfg
        # Kill switch - before every order.
        if cfg.kill_switch_drawdown is not None and account.peak_equity > 0:
            dd = 1.0 - account.equity / account.peak_equity
            if dd >= cfg.kill_switch_drawdown:
                return RiskDecision(
                    False, f"kill_switch: drawdown {dd:.1%} >= {cfg.kill_switch_drawdown:.1%}"
                )
        # Leverage constraint on margined instruments.
        if inst.max_leverage > 1.0 and entry_price is not None:
            lev = cfg.leverage
            if lev > inst.max_leverage:
                return RiskDecision(False, f"leverage {lev} exceeds venue max {inst.max_leverage}")
            liq_distance = entry_price * (1.0 / lev - inst.maintenance_margin_rate)
            need = cfg.min_liquidation_atr * intent.atr
            if liq_distance <= need:
                return RiskDecision(
                    False,
                    f"liquidation_inside_{cfg.min_liquidation_atr:g}xATR: sizing bug "
                    f"(liq distance {liq_distance:.6g} <= {need:.6g})",
                )
        exposures = self._exposures(open_positions, instruments, approved_this_cycle)
        new = _Exposure(intent.symbol, intent.direction, intent.risk_fraction, inst)
        # The legs of one entry share a signal; count entries, not legs.
        if cfg.max_positions_per_ccy is not None:
            for ccy, sign in self._ccy_legs(new):
                entries = {
                    e.symbol
                    for e in exposures
                    for c, s in self._ccy_legs(e)
                    if c == ccy and s == sign and e.symbol != intent.symbol
                }
                if len(entries) >= cfg.max_positions_per_ccy:
                    side = "long" if sign > 0 else "short"
                    return RiskDecision(
                        False, f"exposure_cap: already {len(entries)} entries {side} {ccy}"
                    )
        if cfg.max_beta_weighted_risk is not None and inst.btc_beta:
            total = sum(
                e.direction * e.instrument.btc_beta * e.risk_fraction
                for e in exposures
                if e.symbol != intent.symbol
            )
            mine = sum(
                e.direction * e.instrument.btc_beta * e.risk_fraction
                for e in exposures
                if e.symbol == intent.symbol
            )
            after = total + mine + new.direction * inst.btc_beta * new.risk_fraction
            if abs(after) > cfg.max_beta_weighted_risk + 1e-12:
                return RiskDecision(
                    False,
                    f"beta_cap: BTC-beta-weighted risk {after:.2%} > {cfg.max_beta_weighted_risk:.2%}",
                )
        return RiskDecision(True, order=sized)

    @staticmethod
    def _ccy_legs(e: _Exposure) -> list[tuple[str, int]]:
        legs = [(e.instrument.base, e.direction), (e.instrument.quote, -e.direction)]
        return [(c, s) for c, s in legs if c not in EXPOSURE_EXEMPT]

    def _exposures(
        self,
        positions: Sequence[PositionView],
        instruments: dict[str, InstrumentSpec],
        approved: Iterable[SizedOrder],
    ) -> list[_Exposure]:
        out = [
            _Exposure(p.symbol, p.direction, self.cfg.risk_per_position, instruments[p.symbol])
            for p in positions
            if p.symbol in instruments
        ]
        out += [
            _Exposure(
                o.intent.symbol,
                o.intent.direction,
                o.intent.risk_fraction,
                instruments[o.intent.symbol],
            )
            for o in approved
        ]
        return out
