"""PaperBroker: live data, simulated fills (doc 02 §3.5, build step 7).

It simulates a venue, so it persists its own state after every mutation - as
a real venue would - independently of the harness journal. That independence
is what makes reconciliation meaningful.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from nnfx.brokers.sim import Order, OrderResult, SimBroker


class PaperBroker(SimBroker):
    def __init__(self, *args: Any, state_path: Path | str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.state_path = Path(state_path) if state_path is not None else None
        if self.state_path is not None and self.state_path.exists():
            self.load_state(self.state_path.read_text())

    def _persist(self) -> None:
        if self.state_path is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(self.dump_state())
            tmp.replace(self.state_path)

    def submit(self, order: Order, idempotency_key: str) -> OrderResult:
        res = super().submit(order, idempotency_key)
        self._persist()
        return res

    def modify_stop(
        self, position_id: str, new_stop: float, new_target: float | None = None
    ) -> None:
        super().modify_stop(position_id, new_stop, new_target)
        self._persist()

    def close(self, position_id: str, fraction: float = 1.0, reason: str = "") -> None:
        super().close(position_id, fraction, reason)
        self._persist()

    def process_bar(
        self, symbol: str, ts: pd.Timestamp, o: float, h: float, lo: float, c: float, **kw: Any
    ) -> None:
        super().process_bar(symbol, ts, o, h, lo, c, **kw)
        self._persist()

    def force_close(self, symbol: str, price: float, ts: pd.Timestamp, reason: str) -> None:
        super().force_close(symbol, price, ts, reason)
        self._persist()
