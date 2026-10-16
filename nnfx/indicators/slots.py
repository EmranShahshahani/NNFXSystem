"""Bind a config's ``slots`` block to indicator instances and compute contract arrays."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

import numpy as np

from nnfx.config import SLOT_KIND, Slots
from nnfx.data.bars import BarFrame
from nnfx.indicators.base import Indicator, SlotKind, create


@dataclass(frozen=True)
class SlotOutputs:
    """Contract arrays for one symbol, aligned with the bars. Missing slot -> None."""

    atr: np.ndarray
    baseline: np.ndarray
    c1_signal: np.ndarray
    c1_state: np.ndarray
    c2_signal: np.ndarray | None = None
    c2_state: np.ndarray | None = None
    volume_gate: np.ndarray | None = None
    exit: np.ndarray | None = None
    cont_signal: np.ndarray | None = None
    cont_state: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.atr)

    def head(self, n: int) -> SlotOutputs:
        kw: dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            kw[f.name] = None if v is None else v[:n]
        return SlotOutputs(**kw)

    def values_at(self, i: int) -> dict[str, float | int | bool | None]:
        """Indicator values at bar ``i``, for the journal."""
        out: dict[str, float | int | bool | None] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if v is None:
                continue
            x = v[i]
            if v.dtype == bool:
                out[f.name] = bool(x)
            elif np.issubdtype(v.dtype, np.integer):
                out[f.name] = int(x)
            else:
                out[f.name] = None if np.isnan(x) else float(x)
        return out

    def equals(self, other: SlotOutputs) -> bool:
        for f in fields(self):
            a, b = getattr(self, f.name), getattr(other, f.name)
            if (a is None) != (b is None):
                return False
            if a is not None and not np.array_equal(a, b, equal_nan=a.dtype.kind == "f"):
                return False
        return True


class IndicatorSet:
    """One instance per configured slot. The engine never sees these, only ``SlotOutputs``."""

    def __init__(self, slots: Slots) -> None:
        self.slots = slots
        self.instances: dict[str, Indicator] = {}
        for slot in Slots.model_fields:
            spec = getattr(slots, slot)
            if spec is None:
                continue
            kind: SlotKind = SLOT_KIND[slot]  # type: ignore[assignment]
            self.instances[slot] = create(kind, spec.name, spec.params)

    def compute(self, bars: BarFrame) -> SlotOutputs:
        out = {slot: ind.outputs(bars) for slot, ind in self.instances.items()}

        def get(slot: str, key: str) -> np.ndarray | None:
            return out[slot][key] if slot in out else None

        atr, base, c1s, c1st = (
            get("atr", "value"),
            get("baseline", "line"),
            get("c1", "signal"),
            get("c1", "state"),
        )
        assert atr is not None and base is not None and c1s is not None and c1st is not None
        return SlotOutputs(
            atr=atr,
            baseline=base,
            c1_signal=c1s,
            c1_state=c1st,
            c2_signal=get("c2", "signal"),
            c2_state=get("c2", "state"),
            volume_gate=get("volume", "gate"),
            exit=get("exit", "exit"),
            cont_signal=get("continuation", "signal"),
            cont_state=get("continuation", "state"),
        )
