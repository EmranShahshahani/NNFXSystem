"""Hand-built fixtures: drive decide() with exact contract arrays."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from nnfx.config import Slots, SlotSpec, SystemConfig
from nnfx.engine import AccountState, EngineState, PositionView, StrategyEngine, SymbolHistory
from nnfx.indicators.slots import SlotOutputs
from nnfx.instruments import InstrumentSpec, fx_spec

BASE_SLOTS = Slots(
    atr=SlotSpec(name="atr"),
    baseline=SlotSpec(name="kama"),
    c1=SlotSpec(name="supertrend"),
    c2=SlotSpec(name="vortex"),
    volume=SlotSpec(name="adx"),
    exit=None,
)


def config(**overrides: Any) -> SystemConfig:
    return SystemConfig(slots=BASE_SLOTS).with_overrides(overrides)


def hist(
    close: Sequence[float],
    *,
    baseline: Sequence[float] | float = 1.0,
    atr: Sequence[float] | float = 0.01,
    c1_signal: Sequence[int] | None = None,
    c1_state: Sequence[int] | None = None,
    c2_state: Sequence[int] | int | None = 1,
    c2_signal: Sequence[int] | None = None,
    volume: Sequence[bool] | bool | None = True,
    exit: Sequence[int] | None = None,
    cont_signal: Sequence[int] | None = None,
    high: Sequence[float] | None = None,
    low: Sequence[float] | None = None,
    instrument: InstrumentSpec | None = None,
    symbol: str = "EURUSD",
) -> SymbolHistory:
    c = np.asarray(close, dtype="float64")
    n = len(c)

    def arr(x: Any, dtype: str, default: Any) -> np.ndarray:
        if x is None:
            return np.full(n, default, dtype=dtype)
        if np.isscalar(x):
            return np.full(n, x, dtype=dtype)
        a = np.asarray(x, dtype=dtype)
        assert len(a) == n, (len(a), n)
        return a

    c1_sig = arr(c1_signal, "int8", 0)
    if c1_state is not None:
        c1_st = arr(c1_state, "int8", 0)
    else:
        st, cur = np.zeros(n, dtype="int8"), 1
        for i in range(n):
            if c1_sig[i]:
                cur = int(c1_sig[i])
            st[i] = cur
        c1_st = st
    outputs = SlotOutputs(
        atr=arr(atr, "float64", 0.01),
        baseline=arr(baseline, "float64", 1.0),
        c1_signal=c1_sig,
        c1_state=c1_st,
        c2_signal=None if c2_state is None else arr(c2_signal, "int8", 0),
        c2_state=None if c2_state is None else arr(c2_state, "int8", 1),
        volume_gate=None if volume is None else arr(volume, "bool", True),
        exit=None if exit is None else arr(exit, "int8", 0),
        cont_signal=None if cont_signal is None else arr(cont_signal, "int8", 0),
        cont_state=None if cont_signal is None else arr(cont_signal, "int8", 0),
    )
    idx = pd.date_range("2020-01-01 22:00", periods=n, freq="D", tz="UTC")
    hi = np.asarray(high, dtype="float64") if high is not None else c + 0.001
    lo = np.asarray(low, dtype="float64") if low is not None else c - 0.001
    return SymbolHistory(
        symbol,
        instrument or fx_spec(symbol),
        idx,
        c.copy(),
        hi,
        lo,
        c.copy(),
        np.ones(n),
        outputs,
        n - 1,
    )


ACCOUNT = AccountState(equity=10_000, balance=10_000, peak_equity=10_000)


def run(
    h: SymbolHistory,
    cfg: SystemConfig | None = None,
    *,
    positions: Sequence[PositionView] = (),
    state: EngineState | None = None,
    account: AccountState = ACCOUNT,
    start: int | None = None,
) -> tuple[list[Any], EngineState]:
    """Evaluate every bar from ``start`` to the end, threading state; return the last intents."""
    cfg = cfg or config()
    eng = StrategyEngine()
    st = state or EngineState()
    intents: list[Any] = []
    first = h.end if start is None else start
    for i in range(first, h.end + 1):
        d = eng.decide({h.symbol: h.at(i)}, list(positions), account, cfg, st)
        st, intents = d.state, d.intents
    return intents, st


def position(
    direction: int = 1,
    *,
    leg: str = "runner",
    entry: float = 1.0,
    stop: float | None = None,
    target: float | None = None,
    atr: float = 0.01,
    pid: str = "EURUSD#1",
    entry_type: str = "standard",
) -> PositionView:
    return PositionView(
        id=pid,
        symbol="EURUSD",
        direction=direction,
        units=1000,
        entry_price=entry,
        entry_time="2020-01-01T22:00:00+00:00",
        stop=stop if stop is not None else entry - direction * 1.5 * atr,
        target=target,
        leg=leg,  # type: ignore[arg-type]
        entry_atr=atr,
        signal_time="2020-01-01T22:00:00+00:00",
        entry_type=entry_type,  # type: ignore[arg-type]
    )
