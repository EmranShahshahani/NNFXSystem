"""The Block Library's contracts and registry (Strategy Builder ticket 05, ADR 10).

A Block is one configurable rule. Its class declares its kind, a registry
``type`` name, a Persian title, the blueprint sources it comes from, and a
strict ``Params`` model whose every field has a default. Blocks are causal:
an output at a bar uses only bars closed by then on the Block's timeframe.

Contracts by kind:

- Context: ``compute(data) -> ContextOutput``, per-bar allowed directions.
- Setup: ``compute(data) -> SetupOutput``, per-bar Setup Candidates.
- Confirmation: ``check(candidate, data) -> CheckResult`` (pass / fail / na),
  with a ``weight`` toward the Confluence Score and a ``hard`` flag.
- Execution: ``orders(candidate, data) -> [OrderSpec]``.
- Stop: ``initial_stop(candidate, data) -> price``.
- Exit: ``plan(candidate, data, stop) -> ExitPlan`` when the order is placed,
  then ``manage(position, data, bar) -> StopMove | None`` on every bar the
  position is open (conditional breakeven, trailing; ticket 07). No exit
  rule may close the whole position below ``MIN_FULL_CLOSE_R``.

(Market Filter gets its contract with ticket 20; account-wide risk is the
document's Risk section, ADR 10 §10.)
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame, ns
from nnfx.data.timeframes import TimeframeViews
from nnfx.engine.types import ExitPlan, PositionView
from nnfx.instruments import InstrumentSpec
from nnfx.strategy.levels import BoxTrack, LevelBook, track_boxes
from nnfx.strategy.series import atr, pivots, rsi, sma
from nnfx.strategy.structure import waves

Role = Literal["hwc", "mwc", "lwc"]

# The blueprint's floor: never close a whole position below 2R (Profit Chain rule 1).
MIN_FULL_CLOSE_R = 2.0


def closes_all_below(plan: ExitPlan, r: float = MIN_FULL_CLOSE_R) -> bool:
    """Whether ``plan``'s steps below ``r`` R close the whole position."""
    return sum(s.fraction for s in plan.steps if s.r < r) >= 1.0 - 1e-9


class BlockKind(StrEnum):
    CONTEXT = "context"
    SETUP = "setup"
    CONFIRMATION = "confirmation"
    EXECUTION = "execution"
    STOP = "stop"
    EXIT = "exit"
    RISK = "risk"
    MARKET_FILTER = "market_filter"


KIND_FA = {
    BlockKind.CONTEXT: "زمینه",
    BlockKind.SETUP: "ستاپ",
    BlockKind.CONFIRMATION: "تأیید",
    BlockKind.EXECUTION: "اجرا",
    BlockKind.STOP: "حد ضرر",
    BlockKind.EXIT: "خروج",
    BlockKind.RISK: "ریسک",
    BlockKind.MARKET_FILTER: "فیلتر بازار",
}


class BlockParams(BaseModel):
    """Every field needs a default and a description (the UI renders forms from them).

    Strict: "4" is not a number and true is not 1 (an int is accepted for a float).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# ------------------------------------------------------------------- data
@dataclass(frozen=True)
class StrategyData:
    """One symbol's bars on every timeframe role, aligned to the LWC bars.

    Besides HWC, MWC and LWC there is always a ``management`` role, where open
    positions are managed; it is the MWC unless the document sets it.
    """

    symbol: str
    roles: dict[str, str]  # role -> timeframe, e.g. {"lwc": "M15", "mwc": "H4", ...}
    frames: dict[str, BarFrame]  # role -> bars
    positions: dict[str, np.ndarray]  # role -> index of its latest closed bar per LWC bar
    instrument: InstrumentSpec
    session: SessionConfig
    _cache: dict[Any, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def build(
        cls,
        base: BarFrame,
        roles: dict[str, str],
        instrument: InstrumentSpec,
        session: SessionConfig,
    ) -> StrategyData:
        if base.timeframe != roles["lwc"]:
            raise ValueError(f"LWC is {roles['lwc']} but the bars are {base.timeframe}")
        roles = {**roles, "management": roles.get("management") or roles["mwc"]}
        higher = sorted({tf for tf in roles.values() if tf != base.timeframe})
        views = TimeframeViews(base, instrument=instrument, session=session, timeframes=higher)
        frames = {role: views.frame(tf) for role, tf in roles.items()}
        at = ns(base.index)
        positions = {
            role: np.searchsorted(ns(f.index), at, side="right").astype("int64") - 1
            for role, f in frames.items()
        }
        return cls(base.symbol, dict(roles), frames, positions, instrument, session)

    @property
    def base(self) -> BarFrame:
        return self.frames["lwc"]

    def __len__(self) -> int:
        return len(self.base)

    def aligned(self, role: str, values: np.ndarray, fill: Any) -> np.ndarray:
        """Per-``role``-bar ``values`` read from each LWC bar (its latest closed role bar)."""
        pos = self.positions[role]
        out = np.full(len(pos), fill, dtype=values.dtype)
        ok = pos >= 0
        out[ok] = values[pos[ok]]
        return out

    def pivots(self, role: str, left: int, right: int) -> tuple[np.ndarray, np.ndarray]:
        """Swing-low and swing-high bar indices on ``role`` (see ``series.pivots``).

        A pivot at ``k`` is confirmed at role bar ``k + right``; callers read
        only those confirmed by the role bar they stand on.
        """
        key = ("pivots", role, left, right)
        if key not in self._cache:
            f = self.frames[role]
            self._cache[key] = pivots(f.low, f.high, left, right)
        out: tuple[np.ndarray, np.ndarray] = self._cache[key]
        return out

    def waves(self, role: str, pivot_bars: int) -> tuple[np.ndarray, np.ndarray]:
        """Dow state and wave number of each ``role`` bar (``structure.waves``), cached."""
        key = ("waves", role, pivot_bars)
        if key not in self._cache:
            f = self.frames[role]
            self._cache[key] = waves(f.low, f.high, f.close, pivot_bars)
        out: tuple[np.ndarray, np.ndarray] = self._cache[key]
        return out

    def dow(self, role: str, pivot_bars: int) -> np.ndarray:
        """The Dow trend state of each ``role`` bar (``structure.dow_states``), cached."""
        return self.waves(role, pivot_bars)[0]

    def sma(self, role: str, period: int) -> np.ndarray:
        """The simple moving average of each ``role`` bar's close, cached."""
        key = ("sma", role, period)
        if key not in self._cache:
            self._cache[key] = sma(self.frames[role].close, period)
        out: np.ndarray = self._cache[key]
        return out

    def memo[T](self, key: Any, make: Callable[[], T]) -> T:
        """``make()`` once per ``key`` for this data (the shared cache Blocks may use)."""
        if key not in self._cache:
            self._cache[key] = make()
        out: T = self._cache[key]
        return out

    def rsi(self, role: str, period: int = 14) -> np.ndarray:
        """Wilder's RSI of each ``role`` bar's close, cached."""
        key = ("rsi", role, period)
        if key not in self._cache:
            self._cache[key] = rsi(self.frames[role].close, period)
        out: np.ndarray = self._cache[key]
        return out

    def atr(self, role: str, period: int = 14) -> np.ndarray:
        """Wilder's ATR of each ``role`` bar, cached."""
        key = ("atr", role, period)
        if key not in self._cache:
            f = self.frames[role]
            self._cache[key] = atr(f.high, f.low, f.close, period)
        out: np.ndarray = self._cache[key]
        return out

    def levels(
        self, role: str, *, pivot_bars: int, tolerance_atr: float, half_life: float, max_age: int
    ) -> LevelBook:
        """The horizontal levels of ``role``'s bars (``levels.LevelBook``), cached."""
        key = ("levels", role, pivot_bars, tolerance_atr, half_life, max_age)
        if key not in self._cache:
            f = self.frames[role]
            self._cache[key] = LevelBook(
                f.open, f.high, f.low, f.close, self.atr(role), pivot_bars=pivot_bars,
                tolerance_atr=tolerance_atr, half_life=half_life, max_age=max_age,
            )  # fmt: skip
        out: LevelBook = self._cache[key]
        return out

    def boxes(
        self,
        role: str,
        *,
        pivot_bars: int,
        lookback: int,
        tolerance_atr: float,
        min_top: int,
        min_bottom: int,
        min_height_atr: float,
        max_height_atr: float,
        min_bars: int,
        window: int,
    ) -> BoxTrack:
        """Boxes and their breakouts on ``role``'s bars (``levels.track_boxes``), cached."""
        key = (
            *("boxes", role, pivot_bars, lookback, tolerance_atr, min_top, min_bottom),
            *(min_height_atr, max_height_atr, min_bars, window),
        )
        if key not in self._cache:
            f = self.frames[role]
            self._cache[key] = track_boxes(
                f.open,
                f.high,
                f.low,
                f.close,
                self.atr(role),
                pivot_bars=pivot_bars,
                lookback=lookback,
                tolerance_atr=tolerance_atr,
                min_top=min_top,
                min_bottom=min_bottom,
                min_height_atr=min_height_atr,
                max_height_atr=max_height_atr,
                min_bars=min_bars,
                window=window,
            )
        out: BoxTrack = self._cache[key]
        return out

    def on_close(self, role: str, values: np.ndarray, fill: Any) -> np.ndarray:
        """``role``-bar ``values`` placed on the LWC bar where each ``role`` bar closes.

        Everywhere else ``fill``: a role bar's news arrives once, when it closes.
        """
        pos = self.positions[role]
        mask = (pos >= 0) & (pos != np.r_[-1, pos[:-1]])
        out = np.full(len(pos), fill, dtype=values.dtype)
        out[mask] = values[pos[mask]]
        return out

    def bar_containing(self, role: str, time: str) -> int:
        """The ``role`` bar that the LWC bar labelled ``time`` belongs to.

        Bars are labelled at their close, so it is the first ``role`` bar
        closing at or after ``time``. Refuses a time before the data.
        """
        at = ns(pd.DatetimeIndex([time]))[0]
        if at < ns(self.base.index)[0]:
            raise ValueError(f"{self.symbol}: {time} is before the data starts")
        return int(np.searchsorted(ns(self.frames[role].index), at, "left"))

    def head(self, n: int) -> StrategyData:
        """The data as it stood at the close of LWC bar ``n - 1``."""
        return StrategyData.build(self.base.head(n), self.roles, self.instrument, self.session)

    def scaled(self, factor: float) -> StrategyData:
        return StrategyData.build(
            self.base.scaled(factor), self.roles, self.instrument, self.session
        )


# ---------------------------------------------------------------- outputs
@dataclass(frozen=True)
class ContextOutput:
    long_ok: np.ndarray  # bool per LWC bar
    short_ok: np.ndarray
    flags: dict[str, np.ndarray] = field(default_factory=dict)  # per-bar states, for the record
    # Candidate tags by direction: tag -> (bool per bar for longs, for shorts).
    tags: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    # Bars where resting breakout orders are cancelled and none are placed (e.g. a
    # Choppy Regime). None: the Block never cancels orders.
    cancels_orders: np.ndarray | None = None

    def allows(self, i: int, direction: int) -> bool:
        return bool(self.long_ok[i] if direction > 0 else self.short_ok[i])

    def tags_for(self, i: int, direction: int) -> set[str]:
        k = 0 if direction > 0 else 1
        return {t for t, sides in self.tags.items() if sides[k][i]}


@dataclass(frozen=True)
class SetupOutput:
    direction: np.ndarray  # int8 per LWC bar: 1, -1, or 0 for no candidate
    trigger: np.ndarray  # prices; NaN where no candidate
    invalidation: np.ndarray
    stop: np.ndarray  # the setup's proposed stop
    tags: dict[str, np.ndarray] = field(default_factory=dict)  # tag -> bool per bar
    # Facts the Confirmation Blocks read (NaN where there is no candidate): e.g. the
    # broken ``level``, the ``anchor`` bar of a breakout (a bar index of the Block's
    # own timeframe), the edge's ``touches``.
    meta: dict[str, np.ndarray] = field(default_factory=dict)

    PRICE_FIELDS: ClassVar[tuple[str, ...]] = ("trigger", "invalidation", "stop")
    PRICE_META: ClassVar[tuple[str, ...]] = ("level",)


@dataclass(frozen=True)
class SetupCandidate:
    symbol: str
    setup: str  # the Setup Block's type
    block_index: int  # its position in the document
    bar: int  # LWC bar it completed on
    time: str
    direction: int
    trigger: float
    invalidation: float
    stop: float
    tags: tuple[str, ...] = ()
    meta: tuple[tuple[str, float], ...] = ()  # see SetupOutput.meta

    def fact(self, name: str) -> float | None:
        return next((v for k, v in self.meta if k == name), None)

    @classmethod
    def at(
        cls, out: SetupOutput, data: StrategyData, setup: str, block_index: int, i: int
    ) -> SetupCandidate | None:
        d = int(out.direction[i])
        if d == 0:
            return None
        return cls(
            data.symbol,
            setup,
            block_index,
            i,
            data.base.index[i].isoformat(),
            d,
            float(out.trigger[i]),
            float(out.invalidation[i]),
            float(out.stop[i]),
            tuple(sorted(t for t, on in out.tags.items() if on[i])),
            tuple(sorted((k, float(v[i])) for k, v in out.meta.items() if np.isfinite(v[i]))),
        )

    def record(self) -> dict[str, Any]:
        return {
            "setup": self.setup,
            "block": self.block_index,
            "direction": self.direction,
            "trigger": self.trigger,
            "invalidation": self.invalidation,
            "stop": self.stop,
            "tags": list(self.tags),
            "meta": dict(self.meta),
        }


Outcome = Literal["pass", "fail", "na"]
# A decision-path stage also shows "skipped" once something earlier refused the candidate.
StageStatus = Literal["pass", "fail", "na", "skipped"]


@dataclass(frozen=True)
class CheckResult:
    """A Confirmation Block's verdict on one candidate."""

    outcome: Outcome  # "na": not applicable here (e.g. missing data); never a pass
    reason: str


@dataclass(frozen=True)
class ChecklistItem:
    """One line of a candidate's Pre-Trade Checklist."""

    block: str  # the Block's label, e.g. "rsi_momentum#2"
    kind: Literal["context", "confirmation"]
    outcome: Outcome
    weight: float  # toward the Confluence Score (0 for context gates)
    hard: bool  # a failure refuses the candidate
    reason: str

    @property
    def refusal(self) -> str | None:
        return f"{self.kind}:{self.block}" if self.hard and self.outcome == "fail" else None

    def record(self) -> dict[str, Any]:
        return {
            "block": self.block,
            "kind": self.kind,
            "outcome": self.outcome,
            "weight": self.weight,
            "hard": self.hard,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StopMove:
    """An Exit Block's request to move an open position's stop (only ever tighter)."""

    stop: float
    reason: str  # e.g. "breakeven_after_pivot", "runner_trail"


@dataclass(frozen=True)
class CloseMove:
    """An Exit Block's request to close what remains of an open position (profit-taking)."""

    reason: str  # e.g. "sma25_flatten"


@dataclass(frozen=True)
class OrderSpec:
    """A stop-market entry an Execution Block asks for (sized and stopped later)."""

    level: float
    buffer: float
    invalidation: float | None
    expires_after_bars: int
    oco_group: str | None = None
    # True: not a resting stop order but a market entry at the next bar's open (``level`` is
    # the price it is judged at); used when a candle close, not a touch, must confirm.
    market: bool = False


# ----------------------------------------------------------------- blocks
class Block[P: BlockParams]:
    kind: ClassVar[BlockKind]
    type: ClassVar[str]
    title_fa: ClassVar[str]
    sources: ClassVar[tuple[str, ...]] = ()
    # An oscillator Block only filters and alerts; it never triggers (video 44, 53).
    oscillator: ClassVar[bool] = False
    # builtins.type: the class attribute ``type`` (the registry name) shadows the builtin here.
    Params: ClassVar[builtins.type[BlockParams]] = BlockParams

    def __init__(self, params: P | None = None) -> None:
        self.p: P = params if params is not None else self.Params()  # type: ignore[assignment]


class ContextBlock[P: BlockParams](Block[P]):
    def compute(self, data: StrategyData) -> ContextOutput:
        raise NotImplementedError


class SetupBlock[P: BlockParams](Block[P]):
    def compute(self, data: StrategyData) -> SetupOutput:
        raise NotImplementedError


class ConfirmationParams(BlockParams):
    """Every Confirmation Block has a weight toward the Confluence Score and a hard-fail flag."""

    weight: float = Field(1.0, ge=0, description="وزن در امتیاز هم‌گرایی")
    hard: bool = Field(False, description="رد شدن این بررسی، ستاپ را کامل رد می‌کند")
    only_setups: list[str] = Field(
        default_factory=list,
        description="فقط برای ستاپ‌های این نوع‌ها بررسی شود (خالی: برای همهٔ ستاپ‌ها)",
    )

    @field_validator("only_setups")
    @classmethod
    def _known_setups(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in REGISTRY or REGISTRY[t].kind != BlockKind.SETUP]
        if bad:
            raise ValueError(f"نوع ستاپ شناخته نشده است: {', '.join(bad)}")
        return v


class ConfirmationBlock[P: ConfirmationParams](Block[P]):
    def applies_to(self, setup: str) -> bool:
        """Whether this check is part of the checklist of a candidate from ``setup``."""
        return not self.p.only_setups or setup in self.p.only_setups

    def check(self, candidate: SetupCandidate, data: StrategyData) -> CheckResult:
        raise NotImplementedError


class ExecutionBlock[P: BlockParams](Block[P]):
    def orders(self, candidate: SetupCandidate, data: StrategyData) -> list[OrderSpec]:
        raise NotImplementedError


class StopBlock[P: BlockParams](Block[P]):
    def initial_stop(self, candidate: SetupCandidate, data: StrategyData) -> float:
        raise NotImplementedError


class ExitBlock[P: BlockParams](Block[P]):
    def plan(self, candidate: SetupCandidate, data: StrategyData, stop: float) -> ExitPlan:
        """The exit steps in R, R being the distance from the trigger to ``stop``."""
        raise NotImplementedError

    def manage(
        self, position: PositionView, data: StrategyData, bar: int
    ) -> StopMove | CloseMove | None:
        """At the close of LWC ``bar``: a stop move or a profit-taking close, if any.

        Causal like every Block: it reads only what was known at that close.
        The engine applies a stop move only when it tightens the stop and
        leaves it on the right side of the close. A close may follow only
        profit already taken (``steps_filled`` >= 1): the 2R floor stands.
        """
        return None


BASES: dict[BlockKind, type[Block[Any]]] = {
    BlockKind.CONTEXT: ContextBlock,
    BlockKind.SETUP: SetupBlock,
    BlockKind.CONFIRMATION: ConfirmationBlock,
    BlockKind.EXECUTION: ExecutionBlock,
    BlockKind.STOP: StopBlock,
    BlockKind.EXIT: ExitBlock,
}
REGISTRY: dict[str, type[Block[Any]]] = {}
# The kinds that create or place entries; a Block flagged ``oscillator`` may be none of them.
TRIGGER_KINDS = frozenset({BlockKind.SETUP, BlockKind.EXECUTION})


def register[B: type[Block[Any]]](cls: B) -> B:
    if cls.type in REGISTRY:
        raise ValueError(f"block type {cls.type!r} registered twice")
    if not issubclass(cls, BASES[cls.kind]):
        raise TypeError(
            f"{cls.__name__} is a {cls.kind} Block but not a {BASES[cls.kind].__name__}"
        )
    if cls.oscillator and cls.kind in TRIGGER_KINDS:
        raise TypeError(
            f"{cls.__name__}: an oscillator never triggers, so it cannot be a {cls.kind} Block"
        )
    for name, f in cls.Params.model_fields.items():
        if f.is_required() or not f.description:
            raise TypeError(f"{cls.type}.{name}: every parameter needs a default and a description")
    REGISTRY[cls.type] = cls
    return cls


def block_catalogue(kinds: Iterable[BlockKind] | None = None) -> list[dict[str, Any]]:
    """Every registered Block with its parameter schema (for the API and the UI forms)."""
    want = set(kinds) if kinds is not None else set(BlockKind)
    return [
        {
            "type": c.type,
            "kind": str(c.kind),
            "kind_fa": KIND_FA[c.kind],
            "title_fa": c.title_fa,
            "sources": list(c.sources),
            "oscillator": c.oscillator,
            "params": c.Params.model_json_schema(),
        }
        for c in sorted(REGISTRY.values(), key=lambda c: (list(BlockKind).index(c.kind), c.type))
        if c.kind in want
    ]
