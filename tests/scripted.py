"""A scripted engine and hand-built intraday bars, driven through the shared loop.

Strategy Builder harness tests (seam 1) use these: the scripted engine stands
in for a Strategy Document so broker and loop behaviour can be pinned bar by bar.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from nnfx.brokers.costs import CostModel
from nnfx.brokers.sim import BacktestBroker, SimBroker
from nnfx.engine.core import Decision
from nnfx.engine.history import SymbolHistory
from nnfx.engine.types import (
    AccountState,
    EngineState,
    OpenIntent,
    PendingOrderIntent,
    PositionView,
)
from nnfx.harness.loop import TradingLoop
from nnfx.instruments import crypto_spec
from nnfx.journal.journal import Journal
from tests.helpers import config, hist

SYM = "BTC/USDT"
# Spot pricing (last-price stops) with shorting allowed, so both directions are testable.
BTC = crypto_spec(SYM, "crypto_spot").model_copy(update={"can_short": True})
CFG = config(**{"risk.risk_per_position": 0.01})


def bars(rows: Sequence[tuple[float, float, float, float]]) -> SymbolHistory:
    """15-minute bars from (open, high, low, close) rows."""
    a = np.asarray(rows, dtype="float64")
    n = len(a)
    idx = pd.date_range("2024-01-01 00:15", periods=n, freq="15min", tz="UTC")
    outputs = hist([100.0] * n, instrument=BTC, symbol=SYM).outputs
    return SymbolHistory(
        SYM, BTC, idx, a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.ones(n), outputs, n - 1
    )


def pending(
    key: str,
    *,
    direction: int = 1,
    level: float = 105.0,
    buffer: float = 0.0,
    stop: float = 95.0,
    target: float | None = None,
    invalidation: float | None = None,
    expires: int = 10,
    oco: str | None = None,
    **kw: Any,
) -> PendingOrderIntent:
    return PendingOrderIntent(
        symbol=SYM,
        direction=direction,
        leg="single",
        leg_index=0,
        entry_type="standard",
        signal_time=key,
        atr=1.0,
        risk_fraction=0.01,
        idempotency_key=key,
        level=level,
        buffer=buffer,
        stop=stop,
        target=target,
        invalidation=invalidation,
        expires_after_bars=expires,
        oco_group=oco,
        **kw,
    )


# A script step is a list of intents, or a function of the open positions returning one.
Step = Sequence[Any] | Callable[[Sequence[PositionView]], Sequence[Any]]


class Scripted:
    """An engine that emits fixed intents after given bars and records what it saw."""

    def __init__(self, script: Mapping[int, Step]) -> None:
        self.script = script
        self.seen: list[AccountState] = []
        self.positions: list[list[PositionView]] = []

    def decide(
        self,
        history: Mapping[str, SymbolHistory],
        open_positions: Sequence[PositionView],
        account_state: AccountState,
        config: Any,
        state: EngineState | None = None,
    ) -> Decision:
        self.seen.append(account_state)
        self.positions.append(list(open_positions))
        step = self.script.get(history[SYM].end, [])
        intents = step(open_positions) if callable(step) else step
        return Decision(list(intents), state or EngineState(), [])


def broker() -> BacktestBroker:
    return BacktestBroker({SYM: BTC}, CostModel.zero(), 10_000.0)


def drive(h: SymbolHistory, script: Mapping[int, Step], b: SimBroker | None = None):
    b = b or broker()
    eng = Scripted(script)
    journal = Journal()
    loop = TradingLoop(CFG, {SYM: BTC}, b, journal, engine=eng)
    for i in range(h.end + 1):
        loop.feed_bar(h.at(i), {})
        loop.decide(h.index[i], {SYM: h.at(i)})
    return b, eng, journal


def kinds(b: SimBroker) -> list[tuple[str, str]]:
    return [(e["e"], e.get("reason", "")) for e in b.s.events]


def market(
    key: str = "m", *, direction: int = 1, stop_distance: float = 5.0, **kw: Any
) -> OpenIntent:
    """A market entry for the next open."""
    return OpenIntent(
        symbol=SYM,
        direction=direction,
        leg="single",
        leg_index=0,
        entry_type="standard",
        signal_time=key,
        atr=1.0,
        stop_distance=stop_distance,
        target_distance=kw.pop("target_distance", None),
        risk_fraction=0.01,
        idempotency_key=key,
        **kw,
    )
