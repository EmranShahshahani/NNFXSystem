"""Explicit cost model (doc 03 §2, §2b; ticket 17).

Spread, commission, carry (swap *or* funding, chosen by capability flags) and
slippage are in the result from the first run. Slippage applies to stop fills
too, and gapped stops fill at the open rather than at the stop. Crypto slippage
scales with instrument depth. ``stress_multiplier`` inflates every component
(criterion 10 runs at 1.5x).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from nnfx.config import CostToggles
from nnfx.instruments import InstrumentSpec


class CostSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Full spread, as a fraction of price (bps/1e4) - scale-free across markets.
    spread_bps: float = 0.0
    # Spread multiplier for fills at the session open just after rollover.
    rollover_spread_mult: float = 1.0
    # Commission as a fraction of notional per side, plus a fixed cash amount per lot.
    commission_rate: float = 0.0
    commission_per_lot: float = 0.0
    lot_size: float = 100_000.0
    # Swap: annualised carry as a fraction of notional, by direction (negative = paid).
    swap_long_annual: float = 0.0
    swap_short_annual: float = 0.0
    swap_triple_weekday: int = Field(2, ge=0, le=6)  # Wednesday rollover carries the weekend
    # Funding: rate per 8h settlement used when the bars carry no funding column.
    funding_rate_8h: float = 0.0
    # Slippage in bps for market orders; stops get ``stop_slippage_mult`` times that.
    slippage_bps: float = 0.0
    stop_slippage_mult: float = 2.0
    # Depth scaling: slippage *= sqrt(reference_depth / instrument.depth).
    reference_depth: float | None = None


class CostModel:
    def __init__(
        self,
        specs: dict[str, CostSpec],
        default: CostSpec | None = None,
        toggles: CostToggles | None = None,
        by_class: dict[str, CostSpec] | None = None,
    ):
        self.specs = specs
        self.default = default or CostSpec()
        self.toggles = toggles or CostToggles()
        self.by_class = by_class or {}

    @classmethod
    def zero(cls) -> CostModel:
        return cls({}, CostSpec(), CostToggles(enabled=False))

    @classmethod
    def from_venue(cls, path: Path | str, toggles: CostToggles | None = None) -> CostModel:
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text()) or {}
        by_class = {k: CostSpec(**v) for k, v in (raw.get("market_classes") or {}).items()}
        symbols = {}
        for sym, ov in (raw.get("symbols") or {}).items():
            mc = ov.pop("market_class", None)
            base = by_class.get(mc, CostSpec()) if mc else CostSpec()
            symbols[sym] = base.model_copy(update=ov)
        return cls(symbols, CostSpec(**(raw.get("default") or {})), toggles, by_class)

    def with_toggles(self, toggles: CostToggles) -> CostModel:
        return CostModel(self.specs, self.default, toggles, self.by_class)

    def spec(self, inst: InstrumentSpec) -> CostSpec:
        return self.specs.get(inst.symbol) or self.by_class.get(inst.market_class) or self.default

    @property
    def k(self) -> float:
        return self.toggles.stress_multiplier if self.toggles.enabled else 0.0

    def half_spread(self, inst: InstrumentSpec, price: float, at_session_open: bool) -> float:
        s = self.spec(inst)
        mult = s.rollover_spread_mult if (at_session_open and inst.has_sessions) else 1.0
        return 0.5 * s.spread_bps * 1e-4 * price * mult * self.k

    def slippage(self, inst: InstrumentSpec, price: float, stop: bool) -> float:
        s = self.spec(inst)
        bps = s.slippage_bps * (s.stop_slippage_mult if stop else 1.0)
        if s.reference_depth and inst.depth:
            bps *= math.sqrt(s.reference_depth / inst.depth)
        return bps * 1e-4 * price * self.k

    def commission(
        self, inst: InstrumentSpec, units: float, price: float, quote_to_account: float
    ) -> float:
        s = self.spec(inst)
        notional = units * price * float(inst.value_per_price_unit) * quote_to_account
        return (s.commission_rate * notional + s.commission_per_lot * units / s.lot_size) * self.k

    def carry(
        self,
        inst: InstrumentSpec,
        direction: int,
        notional_account: float,
        weekday: int,
        bar_funding: float | None,
        bar_hours: float,
    ) -> tuple[float, str]:
        """Cash credited (+) or debited (-) for holding through one bar."""
        if not self.toggles.enabled:
            return 0.0, "none"
        s = self.spec(inst)
        if inst.has_funding:
            if not self.toggles.funding:
                return 0.0, "funding"
            rate = bar_funding if bar_funding is not None else s.funding_rate_8h * bar_hours / 8.0
            # Positive funding: longs pay shorts. Asymmetric by construction.
            return -direction * rate * notional_account * self.k, "funding"
        if inst.has_swap:
            if not self.toggles.swap:
                return 0.0, "swap"
            annual = s.swap_long_annual if direction > 0 else s.swap_short_annual
            nights = 3 if weekday == s.swap_triple_weekday else 1
            return annual / 365.0 * nights * notional_account * self.k, "swap"
        return 0.0, "none"
