"""Quote-to-account currency conversion from the bars themselves."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame, ns

USD_LIKE = frozenset({"USD", "USDT", "USDC", "BUSD", "FDUSD"})


class Conversion:
    """``rate(ccy, ts)`` = account currency per unit of ``ccy``, from the latest close <= ts."""

    def __init__(self, account: str, frames: Mapping[str, BarFrame]) -> None:
        self.account = account
        self.series: dict[str, tuple[np.ndarray, np.ndarray, bool]] = {}
        for sym, f in frames.items():
            s = sym.replace("/", "")
            if len(s) == 6:
                self.series[s] = (ns(f.index), f.close, True)

    def __call__(self, ccy: str, ts: pd.Timestamp) -> float:
        acc = self.account
        if ccy == acc or (ccy in USD_LIKE and acc in USD_LIKE):
            return 1.0
        for pair, invert in ((f"{ccy}{acc}", False), (f"{acc}{ccy}", True)):
            if pair in self.series:
                t, c, _ = self.series[pair]
                k = int(np.searchsorted(t, ts.value, side="right")) - 1
                if k < 0:
                    k = 0
                px = float(c[k])
                return 1.0 / px if invert else px
        raise KeyError(f"no conversion path from {ccy} to {acc}: add {ccy}{acc} or {acc}{ccy} bars")
