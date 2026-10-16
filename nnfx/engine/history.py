"""What the engine is allowed to see: bars and contract values up to bar ``end``.

The backtest passes full precomputed arrays with a moving ``end`` (valid because
Gate 1 proves no indicator reads the future); the live harness passes arrays
computed on truncated history. Access is only by non-negative lag, so the
engine cannot read past ``end`` even when the arrays extend beyond it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame
from nnfx.indicators.slots import SlotOutputs
from nnfx.instruments import InstrumentSpec


@dataclass(frozen=True)
class SymbolHistory:
    symbol: str
    instrument: InstrumentSpec
    index: pd.DatetimeIndex
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    outputs: SlotOutputs
    end: int

    @classmethod
    def from_frame(
        cls,
        bars: BarFrame,
        outputs: SlotOutputs,
        instrument: InstrumentSpec,
        end: int | None = None,
    ) -> SymbolHistory:
        return cls(
            bars.symbol,
            instrument,
            bars.index,
            bars.open,
            bars.high,
            bars.low,
            bars.close,
            bars.volume,
            outputs,
            len(bars) - 1 if end is None else end,
        )

    def at(self, end: int) -> SymbolHistory:
        return SymbolHistory(
            self.symbol,
            self.instrument,
            self.index,
            self.open,
            self.high,
            self.low,
            self.close,
            self.volume,
            self.outputs,
            end,
        )

    def _i(self, lag: int) -> int:
        if lag < 0:
            raise IndexError("lookahead: negative lag is not allowed")
        return self.end - lag

    def ok(self, lag: int = 0) -> bool:
        return self._i(lag) >= 0

    def time(self, lag: int = 0) -> str:
        return self.index[self._i(lag)].isoformat()

    def px(self, name: str, lag: int = 0) -> float:
        return float(getattr(self, name)[self._i(lag)])

    def v(self, name: str, lag: int = 0) -> float:
        arr = getattr(self.outputs, name)
        return float(arr[self._i(lag)])

    def iv(self, name: str, lag: int = 0) -> int:
        arr = getattr(self.outputs, name)
        return int(arr[self._i(lag)])

    def has(self, name: str) -> bool:
        return getattr(self.outputs, name) is not None

    def last_signal_age(
        self, name: str, direction: int, inclusive: bool, max_lookback: int
    ) -> int | None:
        """Bars since the most recent ``name`` signal in ``direction`` (signal bar = 1 if inclusive)."""
        arr = getattr(self.outputs, name)
        for k in range(0, min(max_lookback, self.end) + 1):
            if int(arr[self.end - k]) == direction:
                return k + 1 if inclusive else k
        return None

    def values(self) -> dict[str, float | int | bool | None]:
        return self.outputs.values_at(self.end)

    def inputs(self) -> dict[str, float | str]:
        i = self.end
        return {
            "time": self.index[i].isoformat(),
            "open": float(self.open[i]),
            "high": float(self.high[i]),
            "low": float(self.low[i]),
            "close": float(self.close[i]),
            "volume": float(self.volume[i]),
        }
