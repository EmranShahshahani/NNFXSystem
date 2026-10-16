"""Indicator protocols, the normalised contract, and the registry (doc 02 §3.2).

The wrapper owns normalisation: whatever an indicator natively produces (a
histogram, a colour change, a band crossing), its wrapper emits only

* volatility   -> ``value``  float, price units
* baseline     -> ``line``   float, price units
* confirmation -> ``signal`` in {-1,0,+1} (fires this bar) and ``state`` in {-1,+1}
* volume       -> ``gate``   bool
* exit         -> ``exit``   +1 exit long, -1 exit short, 0 none

During warmup ``line``/``value`` are NaN, ``state``/``signal``/``exit`` are 0 and
``gate`` is False. The engine never imports a concrete indicator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

import numpy as np

from nnfx.data.bars import BarFrame

SlotKind = Literal["volatility", "baseline", "confirmation", "volume", "exit"]
CONTRACT: dict[SlotKind, tuple[str, ...]] = {
    "volatility": ("value",),
    "baseline": ("line",),
    "confirmation": ("signal", "state"),
    "volume": ("gate",),
    "exit": ("exit",),
}


@runtime_checkable
class VolatilityIndicator(Protocol):
    def value(self, bars: BarFrame) -> np.ndarray: ...


@runtime_checkable
class BaselineIndicator(Protocol):
    def line(self, bars: BarFrame) -> np.ndarray: ...


@runtime_checkable
class ConfirmationIndicator(Protocol):
    def signals(self, bars: BarFrame) -> tuple[np.ndarray, np.ndarray]: ...


@runtime_checkable
class VolumeIndicator(Protocol):
    def gate(self, bars: BarFrame) -> np.ndarray: ...


@runtime_checkable
class ExitIndicator(Protocol):
    def exits(self, bars: BarFrame) -> np.ndarray: ...


class Indicator(ABC):
    kind: ClassVar[SlotKind]
    name: ClassVar[str]
    family: ClassVar[str] = "unspecified"
    defaults: ClassVar[dict[str, Any]] = {}
    # Gate 5: small published-default-centred grids, every point a counted trial.
    grid: ClassVar[dict[str, tuple[Any, ...]]] = {}
    # Families needing extra lookahead scrutiny are tagged (doc 05 §2, Gate 1).
    notes: ClassVar[str] = ""

    def __init__(self, **params: Any) -> None:
        unknown = sorted(set(params) - set(self.defaults))
        if unknown:
            raise ValueError(
                f"{self.kind}/{self.name}: unknown parameter(s) {unknown}; accepts {sorted(self.defaults)}"
            )
        merged = dict(self.defaults)
        for k, v in params.items():
            d = self.defaults[k]
            merged[k] = type(d)(v) if isinstance(d, (int, float)) and not isinstance(d, bool) else v
        self.params: dict[str, Any] = merged

    @property
    def p(self) -> Mapping[str, Any]:
        return self.params

    @abstractmethod
    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        """All contract outputs keyed by contract field name."""

    def __repr__(self) -> str:
        ps = ", ".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        name = getattr(self, "name", type(self).__name__)
        return f"{self.kind}/{name}({ps})"


class Volatility(Indicator):
    kind = "volatility"

    @abstractmethod
    def value(self, bars: BarFrame) -> np.ndarray: ...

    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        return {"value": np.asarray(self.value(bars), dtype="float64")}


class Baseline(Indicator):
    kind = "baseline"

    @abstractmethod
    def line(self, bars: BarFrame) -> np.ndarray: ...

    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        return {"line": np.asarray(self.line(bars), dtype="float64")}


class Confirmation(Indicator):
    kind = "confirmation"

    def signals(self, bars: BarFrame) -> tuple[np.ndarray, np.ndarray]:
        from nnfx.indicators._math import state_to_signal

        st = np.asarray(self.state(bars), dtype="int8")
        return state_to_signal(st), st

    @abstractmethod
    def state(self, bars: BarFrame) -> np.ndarray:
        """Directional stance; the default ``signals`` fires on its flips."""

    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        sig, st = self.signals(bars)
        return {"signal": sig.astype("int8"), "state": st.astype("int8")}


class Volume(Indicator):
    kind = "volume"

    @abstractmethod
    def gate(self, bars: BarFrame) -> np.ndarray: ...

    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        g = np.asarray(self.gate(bars))
        return {"gate": np.where(np.isnan(g.astype("float64")), False, g).astype(bool)}


class Exit(Indicator):
    kind = "exit"

    @abstractmethod
    def exits(self, bars: BarFrame) -> np.ndarray: ...

    def outputs(self, bars: BarFrame) -> dict[str, np.ndarray]:
        return {"exit": np.asarray(self.exits(bars), dtype="int8")}


REGISTRY: dict[tuple[SlotKind, str], type[Indicator]] = {}


def register(kind: SlotKind, name: str) -> Callable[[type[Indicator]], type[Indicator]]:
    def deco(cls: type[Indicator]) -> type[Indicator]:
        key = (kind, name)
        if key in REGISTRY and REGISTRY[key] is not cls:
            raise ValueError(f"indicator {kind}/{name} registered twice")
        if cls.kind != kind:
            raise TypeError(f"{cls.__name__} is a {cls.kind} indicator, cannot register as {kind}")
        cls.name = name
        REGISTRY[key] = cls
        return cls

    return deco


def unregister(kind: SlotKind, name: str) -> None:
    REGISTRY.pop((kind, name), None)


def create(kind: SlotKind, name: str, params: Mapping[str, Any] | None = None) -> Indicator:
    _ensure_loaded()
    try:
        cls = REGISTRY[(kind, name)]
    except KeyError:
        have = sorted(n for k, n in REGISTRY if k == kind)
        raise KeyError(f"no {kind} indicator named {name!r}; registered: {have}") from None
    return cls(**dict(params or {}))


def registered(kind: SlotKind | None = None) -> list[tuple[SlotKind, str]]:
    _ensure_loaded()
    return sorted(k for k in REGISTRY if kind is None or k[0] == kind)


def _ensure_loaded() -> None:
    import nnfx.indicators.library
    import nnfx.indicators.library_ext  # noqa: F401
