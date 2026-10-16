"""Engine data contracts: state machine, positions as the engine sees them, intents."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Phase(StrEnum):
    FLAT = "FLAT"
    PENDING_PULLBACK = "PENDING_PULLBACK"
    # Not in doc 02's diagram: the 1-Candle Rule variants also hold a one-bar setup.
    PENDING_ONE_CANDLE = "PENDING_ONE_CANDLE"
    IN_TRADE = "IN_TRADE"
    RUNNER_BE = "RUNNER_BE"
    TRAILING = "TRAILING"


TRADE_PHASES = frozenset({Phase.IN_TRADE, Phase.RUNNER_BE, Phase.TRAILING})
EntryType = Literal[
    "standard", "baseline", "pullback", "one_candle_a", "one_candle_b", "continuation"
]
Leg = Literal["tp1", "runner", "single", "combined"]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PendingSetup(Model):
    kind: Literal["pullback", "one_candle_a", "one_candle_b"]
    direction: int
    origin: Literal["standard", "baseline"]
    setup_time: str
    # Explicit expiry: evaluated on exactly the next bar after ``setup_time``, then gone.
    expires_after_bars: int = 1
    missing: Literal["volume", "c2"] | None = None
    setup_close: float


class SymbolState(Model):
    phase: Phase = Phase.FLAT
    pending: PendingSetup | None = None
    # Entry submitted at the last decision, fill not yet observed.
    awaiting_fill: bool = False
    entry_type: EntryType | None = None
    entry_signal_time: str | None = None
    entry_atr: float | None = None
    best_close: float | None = None
    tp1_reached: bool = False
    # Continuation bookkeeping: direction and signal bar of the original entry.
    trend_dir: int = 0
    trend_origin: str | None = None
    last_exit_time: str | None = None


class EngineState(Model):
    symbols: dict[str, SymbolState] = Field(default_factory=dict)

    def get(self, symbol: str) -> SymbolState:
        return self.symbols.get(symbol, SymbolState())


class PositionView(Model):
    """An open position as reported by a broker."""

    id: str
    symbol: str
    direction: int
    units: float
    entry_price: float
    entry_time: str
    stop: float
    target: float | None = None
    target_fraction: float = 1.0
    leg: Leg
    entry_atr: float
    signal_time: str
    entry_type: EntryType
    scaled_out: bool = False


class AccountState(Model):
    equity: float
    balance: float
    peak_equity: float
    currency: str = "USD"
    # Symbols that had a position closed by the broker during the current bar.
    recent_exits: frozenset[str] = frozenset()


class OpenIntent(Model):
    kind: Literal["open"] = "open"
    symbol: str
    direction: int
    leg: Leg
    leg_index: int
    entry_type: EntryType
    signal_time: str
    atr: float
    stop_distance: float
    target_distance: float | None
    target_fraction: float = 1.0
    risk_fraction: float
    idempotency_key: str


class CloseIntent(Model):
    kind: Literal["close"] = "close"
    symbol: str
    position_id: str
    reason: str


class ModifyIntent(Model):
    kind: Literal["modify"] = "modify"
    symbol: str
    position_id: str
    stop: float
    target: float | None = None
    reason: str


OrderIntent = Annotated[OpenIntent | CloseIntent | ModifyIntent, Field(discriminator="kind")]


def idempotency_key(symbol: str, signal_time: str, leg_index: int) -> str:
    """Deterministic: (symbol, signal-bar timestamp, position index). Never random."""
    return f"{symbol}|{signal_time}|{leg_index}"
