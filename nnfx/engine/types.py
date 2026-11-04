"""Engine data contracts: state machine, positions as the engine sees them, intents."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class PendingOrderView(Model):
    """A resting stop-market order (a Trigger) as reported by a broker."""

    order_id: str
    key: str
    symbol: str
    direction: int
    level: float
    # level + direction * buffer: the price the order is resting at.
    trigger: float
    stop: float
    target: float | None
    invalidation: float | None
    expires_after_bars: int
    bars_active: int
    oco_group: str | None
    placed_time: str


class AccountState(Model):
    equity: float
    balance: float
    peak_equity: float
    currency: str = "USD"
    # Symbols that had a position closed by the broker during the current bar.
    recent_exits: frozenset[str] = frozenset()
    # Resting pending orders, in placement order.
    pending_orders: tuple[PendingOrderView, ...] = ()


def trigger_price(level: float, direction: int, buffer: float) -> float:
    """Where a stop-market entry rests: just beyond its level, by ``buffer``."""
    return level + direction * buffer


class EntryIntent(Model):
    """What every entry intent carries, market or pending."""

    symbol: str
    direction: int
    leg: Leg
    leg_index: int
    entry_type: EntryType
    signal_time: str
    atr: float
    target_fraction: float = 1.0
    risk_fraction: float
    idempotency_key: str


class OpenIntent(EntryIntent):
    """A market entry at the next bar's open, with stop and target as distances."""

    kind: Literal["open"] = "open"
    stop_distance: float
    target_distance: float | None


class PendingOrderIntent(EntryIntent):
    """A stop-market entry (a Trigger) resting just beyond a level (ADR 09 §4).

    The order rests at ``trigger = level + direction * buffer`` from the bar
    after it is placed. Stop and target are absolute prices: a gap fill beyond
    the trigger keeps them where the setup put them. Sizing uses the distance
    from the trigger to the stop. Before it fills it is cancelled when a bar
    closes beyond ``invalidation`` or after ``expires_after_bars`` bars.
    Orders sharing an ``oco_group`` cancel each other on the first fill.
    """

    kind: Literal["pending"] = "pending"
    level: float
    buffer: float = 0.0
    stop: float
    target: float | None = None
    invalidation: float | None = None
    expires_after_bars: int
    oco_group: str | None = None

    @model_validator(mode="after")
    def _check(self) -> PendingOrderIntent:
        if self.direction not in (1, -1):
            raise ValueError("direction must be 1 or -1")
        if (self.trigger - self.stop) * self.direction <= 0:
            raise ValueError(
                f"stop {self.stop} must be on the losing side of the entry {self.trigger}"
            )
        if self.target is not None and (self.target - self.trigger) * self.direction <= 0:
            raise ValueError(f"target {self.target} must be beyond the entry {self.trigger}")
        if self.expires_after_bars < 1:
            raise ValueError("expires_after_bars must be at least 1")
        return self

    @property
    def trigger(self) -> float:
        return trigger_price(self.level, self.direction, self.buffer)

    @property
    def stop_distance(self) -> float:
        return abs(self.trigger - self.stop)

    @property
    def target_distance(self) -> float | None:
        return None if self.target is None else abs(self.target - self.trigger)


class CancelIntent(Model):
    """Cancel a resting pending order by its idempotency key."""

    kind: Literal["cancel"] = "cancel"
    symbol: str
    order_key: str
    reason: str


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


OrderIntent = Annotated[
    OpenIntent | PendingOrderIntent | CancelIntent | CloseIntent | ModifyIntent,
    Field(discriminator="kind"),
]


def idempotency_key(symbol: str, signal_time: str, leg_index: int) -> str:
    """Deterministic: (symbol, signal-bar timestamp, position index). Never random."""
    return f"{symbol}|{signal_time}|{leg_index}"
