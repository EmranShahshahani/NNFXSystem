"""Order-book snapshots and the depth a move needs (Strategy Builder ticket 04).

A snapshot is one moment of one market's resting orders: bids best (highest)
first, asks best (lowest) first, each row ``(price, size)`` in the market's
own units (IRT markets in rials). It is immutable once built.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


class OrderBookError(RuntimeError):
    """A provider could not produce a snapshot (bad response, unknown symbol)."""


def _levels(rows: Sequence[Sequence[float]], descending: bool) -> np.ndarray:
    a = np.asarray([(float(p), float(s)) for p, s in rows], dtype="float64").reshape(-1, 2)
    a = a[a[:, 1] > 0]
    order = np.argsort(-a[:, 0] if descending else a[:, 0], kind="stable")
    out = a[order]
    out.setflags(write=False)
    return out


@dataclass(frozen=True)
class OrderBookSnapshot:
    symbol: str
    time: pd.Timestamp
    bids: np.ndarray  # (n, 2): price, size; highest price first
    asks: np.ndarray  # (n, 2): price, size; lowest price first
    last_trade: float | None = None

    @classmethod
    def of(
        cls,
        symbol: str,
        time: pd.Timestamp,
        bids: Sequence[Sequence[float]],
        asks: Sequence[Sequence[float]],
        last_trade: float | None = None,
    ) -> OrderBookSnapshot:
        """Build from rows in any order; levels with no size are dropped."""
        return cls(
            symbol, pd.Timestamp(time), _levels(bids, True), _levels(asks, False), last_trade
        )

    @property
    def best_bid(self) -> float:
        return float(self.bids[0, 0]) if len(self.bids) else float("nan")

    @property
    def best_ask(self) -> float:
        return float(self.asks[0, 0]) if len(self.asks) else float("nan")

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    def at(self, time: pd.Timestamp) -> OrderBookSnapshot:
        """The same book stamped with another time (the recorder's clock)."""
        return OrderBookSnapshot(
            self.symbol, pd.Timestamp(time), self.bids, self.asks, self.last_trade
        )

    def to_json(self) -> dict[str, object]:
        return {
            "t": self.time.isoformat(),
            "symbol": self.symbol,
            "bids": self.bids.tolist(),
            "asks": self.asks.tolist(),
            "last": self.last_trade,
        }

    @classmethod
    def from_json(cls, d: dict[str, object]) -> OrderBookSnapshot:
        last = d.get("last")
        return cls.of(
            str(d["symbol"]),
            pd.Timestamp(str(d["t"])),
            d["bids"],  # type: ignore[arg-type]
            d["asks"],  # type: ignore[arg-type]
            None if last is None else float(last),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class Depth:
    base: float  # size that must trade to move the price by the asked percentage
    quote: float  # its value in the quote currency
    exhausted: bool  # the book ran out before reaching that price


def depth_to_move(snapshot: OrderBookSnapshot, pct: float, side: Literal["buy", "sell"]) -> Depth:
    """Size a market ``side`` order must take to push price ``pct`` % from the best level.

    Buying eats asks from the best ask up to best ask x (1 + pct/100); selling
    eats bids down to best bid x (1 - pct/100). Levels at the limit count.
    """
    if side == "buy":
        levels, limit = snapshot.asks, snapshot.best_ask * (1 + pct / 100.0)
        reached = levels[:, 0] <= limit * (1 + 1e-12)
    else:
        levels, limit = snapshot.bids, snapshot.best_bid * (1 - pct / 100.0)
        reached = levels[:, 0] >= limit * (1 - 1e-12)
    taken = levels[reached]
    return Depth(
        base=float(taken[:, 1].sum()),
        quote=float((taken[:, 0] * taken[:, 1]).sum()),
        exhausted=bool(reached.all()),
    )
