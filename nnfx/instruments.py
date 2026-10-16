"""InstrumentSpec - the market-abstraction boundary (doc 01 §3b, doc 02 §3.5).

It declares *capabilities*, not a market name. The engine and broker branch on
``can_short``, ``has_funding``, ``has_sessions``, ``supports_hedging``,
``stop_trigger_price`` and ``size_step`` - never on ``market_class``.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from nnfx.data.bars import VolumeKind

MarketClass = Literal["fx_spot", "crypto_spot", "crypto_perp"]

# Priority order that yields the market-standard names for the 28 crosses.
MAJORS = ("EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY")


def fx_28() -> list[str]:
    """The 28 major and cross pairs from the 8 majors, standard naming."""
    return [a + b for a, b in combinations(MAJORS, 2)]


class InstrumentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    market_class: MarketClass
    base: str
    quote: str
    can_short: bool
    size_step: Decimal
    min_size: Decimal
    value_per_price_unit: Decimal = Decimal(1)
    has_funding: bool = False
    has_swap: bool = False
    has_sessions: bool = True
    supports_hedging: bool = True
    stop_trigger_price: Literal["last", "mark"] = "last"
    volume_kind: VolumeKind = "traded"
    # Crypto-perp margin model, for the 3xATR liquidation-distance constraint.
    max_leverage: float = 1.0
    maintenance_margin_rate: float = 0.0
    # BTC beta, for the beta-weighted exposure cap (doc 02 §7).
    btc_beta: float = 1.0
    # Typical order-book depth in quote currency, for depth-scaled slippage.
    depth: float | None = None
    # Point-in-time universe bookkeeping (ticket 06).
    delisted_at: str | None = None
    tags: tuple[str, ...] = Field(default_factory=tuple)

    def currencies(self) -> tuple[str, str]:
        return self.base, self.quote


def fx_spec(symbol: str, **overrides: Any) -> InstrumentSpec:
    base: dict[str, Any] = dict(
        symbol=symbol,
        market_class="fx_spot",
        base=symbol[:3],
        quote=symbol[3:],
        can_short=True,
        size_step=Decimal("1000"),  # 0.01 lots of 100k units
        min_size=Decimal("1000"),
        has_swap=True,
        has_sessions=True,
        volume_kind="tick",
        btc_beta=0.0,
    )
    base.update(overrides)
    return InstrumentSpec(**base)


def crypto_spec(
    symbol: str, market_class: MarketClass = "crypto_perp", **overrides: Any
) -> InstrumentSpec:
    b, q = symbol.split("/") if "/" in symbol else (symbol[:-4], symbol[-4:])
    q = q.split(":")[0]
    perp = market_class == "crypto_perp"
    base: dict[str, Any] = dict(
        symbol=symbol,
        market_class=market_class,
        base=b,
        quote=q,
        can_short=perp,
        size_step=Decimal("0.00000001"),
        min_size=Decimal("0.00000001"),
        has_funding=perp,
        has_sessions=False,
        supports_hedging=perp,
        stop_trigger_price="mark" if perp else "last",
        volume_kind="traded",
        max_leverage=20.0 if perp else 1.0,
        maintenance_margin_rate=0.005 if perp else 0.0,
    )
    base.update(overrides)
    return InstrumentSpec(**base)


class InstrumentsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baskets: dict[str, list[str]] = Field(default_factory=dict)
    defaults: dict[MarketClass, dict[str, Any]] = Field(default_factory=dict)
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class InstrumentRegistry:
    def __init__(self, cfg: InstrumentsFile) -> None:
        self.cfg = cfg

    @classmethod
    def load(cls, path: Path) -> InstrumentRegistry:
        raw = yaml.safe_load(path.read_text()) or {}
        baskets = raw.get("baskets", {})
        # "fx_28" is expanded from code so the list cannot drift out of standard naming.
        for name, members in list(baskets.items()):
            if members == "fx_28":
                baskets[name] = fx_28()
        return cls(InstrumentsFile.model_validate(raw))

    def basket(self, name: str) -> list[str]:
        try:
            return list(self.cfg.baskets[name])
        except KeyError:
            raise KeyError(f"unknown basket {name!r}; have {sorted(self.cfg.baskets)}") from None

    def spec(self, symbol: str, market_class: MarketClass | None = None) -> InstrumentSpec:
        ov = dict(self.cfg.overrides.get(symbol, {}))
        mc: MarketClass = (
            ov.pop("market_class", None)
            or market_class
            or ("crypto_perp" if "/" in symbol else "fx_spot")
        )
        params = {**self.cfg.defaults.get(mc, {}), **ov}
        if mc == "fx_spot":
            return fx_spec(symbol, **params)
        return crypto_spec(symbol, market_class=mc, **params)
