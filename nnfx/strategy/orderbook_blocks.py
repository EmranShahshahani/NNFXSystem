"""Order-book Blocks: walls move the trigger, the stop and the targets (ticket 21, ADR 10 §25).

Videos 35-50 (blueprint 05) read the order book around a trade. Live-first: the walls come
from recorded snapshots (``StrategyData.book``), so a backtest uses them only where the
recorder ran. Each Block behaves as its plain counterpart when there is no book at the
candidate's time, and the engine flags the run incomplete (``DocumentRun.incomplete``).

=======================  ======================================================================
Block                    What it does
=======================  ======================================================================
``wall_trigger``         Execution. The stop-market trigger moves just beyond the largest
                         persistent ask wall above the setup's trigger (mirror: bid wall below
                         it for shorts); the breakout is aborted when volume contracts as price
                         nears a heavy wall
``wall_shielded_stop``   Stop. The structural stop moves in behind the nearest persistent bid
                         wall between the stop and the entry (mirror for shorts)
``wall_targets``         Exit. A Profit Chain whose targets sit just in front of the opposing
                         walls (never below the 2R floor)
=======================  ======================================================================

Walls are the order-book module's: large *for this book* (a percentile of its own level sizes),
persistent across N snapshots, and never a spoof (vanished or stepped back as price approached).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import Field

from nnfx.engine.types import ExitPlan
from nnfx.orderbook import Wall, WallParams
from nnfx.strategy.blocks import (
    MIN_FULL_CLOSE_R,
    Block,
    BlockKind,
    BlockParams,
    ExecutionBlock,
    OrderSpec,
    SetupCandidate,
    StopBlock,
    StrategyData,
    register,
)
from nnfx.strategy.book import BookState
from nnfx.strategy.library import (
    ProfitChain,
    ProfitChainParams,
    StopMarket,
    StopMarketParams,
    StructuralStop,
    StructuralStopParams,
)


class BookParams(BlockParams):
    """How walls are found and how fresh the book must be; shared by every order-book Block."""

    percentile: float = Field(
        95.0, gt=0, lt=100, description="دیوار: اندازهٔ خوشه بالاتر از این صدک عمق همین دفتر سفارش"
    )
    min_multiple: float = Field(
        3.0, ge=1, description="دیوار: دست‌کم این چند برابر میانهٔ اندازهٔ سطوح همین دفتر"
    )
    persist: int = Field(
        3, ge=1, description="دیوار: باید در این تعداد اسنپ‌شات پیاپی دیده شود (وگرنه اسپوف است)"
    )
    window_pct: float = Field(
        5.0, gt=0, description="دیوار: فقط خوشه‌های تا این درصد از قیمت میانی دفتر"
    )
    max_age_seconds: int = Field(
        120, ge=1, description="قدیمی‌ترین اسنپ‌شاتی که هنوز «دفتر سفارش در این لحظه» حساب می‌شود"
    )


def wall_params(p: BookParams) -> WallParams:
    return WallParams(
        percentile=p.percentile,
        min_multiple=p.min_multiple,
        persist=p.persist,
        window_pct=p.window_pct,
    )


def near_edge(w: Wall) -> float:
    """The edge of the wall's cluster that price meets first."""
    return w.low if w.side == "ask" else w.high


def far_edge(w: Wall) -> float:
    return w.high if w.side == "ask" else w.low


def opposing_side(direction: int) -> str:
    """Whose walls stand in a trade's way: asks for a long, bids for a short."""
    return "ask" if direction > 0 else "bid"


def own_side(direction: int) -> str:
    """Whose walls protect a trade: bids under a long, asks over a short."""
    return opposing_side(-direction)


class BookBlock[P: BookParams](Block[P]):
    """A Block that reads the order book at its candidate's time."""

    def book_state(self, candidate: SetupCandidate, data: StrategyData) -> BookState | None:
        p = self.p
        return data.book.at(
            candidate.symbol,
            candidate.time,
            wall_params(p),
            pd.Timedelta(seconds=p.max_age_seconds),
        )


# --------------------------------------------------------------- execution
class WallTriggerParams(StopMarketParams, BookParams):
    max_distance_pct: float = Field(
        1.0, gt=0, description="فقط دیوارهایی تا این درصد از تریگر دورتر در مسیر معامله"
    )
    beyond_pct: float = Field(
        0.05, ge=0, description="فاصلهٔ تریگر جدید پشت لبهٔ دور دیوار، درصد قیمت"
    )
    abort_on_contraction: bool = Field(
        True, description="لغو شکست وقتی حجم در نزدیکی یک دیوار سنگین کم می‌شود"
    )
    approach_pct: float = Field(
        0.5, gt=0, description="«نزدیک دیوار»: لبهٔ نزدیک دیوار تا این درصد از قیمت پایانی"
    )
    volume_bars: int = Field(
        3, ge=1, description="مقایسهٔ حجم این تعداد کندل اخیر با همان تعداد قبل‌تر"
    )
    contraction_factor: float = Field(
        0.7, gt=0, lt=1, description="حجم اخیر کمتر از این ضریب حجم قبلی: انقباض"
    )


@register
class WallTrigger(BookBlock[WallTriggerParams], ExecutionBlock[WallTriggerParams]):
    """The stop-market entry, placed beyond the wall that stands in the breakout's way.

    A long's trigger is the setup's resistance; the order-book walls of its book decide the
    entry (video 35-41): the largest persistent ask wall within ``max_distance_pct`` above the
    trigger moves the order to just beyond the wall's far edge, so price enters after the wall
    is cleared. Shorts mirror it with bid walls below. If volume is contracting (the last
    ``volume_bars`` bars average under ``contraction_factor`` of the ones before) as price
    nears a heavy wall (its near edge within ``approach_pct`` of the close), the breakout is
    aborted: no order is placed (the bounce-off-the-wall case). Spoofs never move anything.
    Without a book at the candidate's time this is the plain stop-market order.
    """

    kind = BlockKind.EXECUTION
    type = "wall_trigger"
    title_fa = "تریگر پشت دیوار دفتر سفارش"
    sources = (
        "tcp-blueprint 05: videos 41-50 (order-book walls, ask wall above resistance)",
        "tcp-blueprint 01: do not enter into a heavy wall on falling volume",
    )
    Params = WallTriggerParams

    def orders(self, candidate: SetupCandidate, data: StrategyData) -> list[OrderSpec]:
        p, d = self.p, candidate.direction
        plain = StopMarket(p).orders(candidate, data)
        state = self.book_state(candidate, data)
        if state is None:
            return plain
        walls = state.walls_on(opposing_side(d))
        close = float(data.base.close[candidate.bar])
        if p.abort_on_contraction and self._contracting_into_wall(walls, candidate, data, close):
            return []
        trigger = candidate.trigger
        reach = trigger * p.max_distance_pct / 100.0
        ahead = [w for w in walls if 0 < (w.price - trigger) * d <= reach]
        if not ahead:
            return plain
        wall = max(ahead, key=lambda w: (w.size, -abs(w.price - trigger)))
        level = far_edge(wall) + d * far_edge(wall) * p.beyond_pct / 100.0
        return [
            OrderSpec(
                level=level,
                buffer=level * p.buffer_pct / 100.0,
                invalidation=plain[0].invalidation,
                expires_after_bars=plain[0].expires_after_bars,
                oco_group=plain[0].oco_group,
            )
        ]

    def _contracting_into_wall(
        self, walls: list[Wall], candidate: SetupCandidate, data: StrategyData, close: float
    ) -> bool:
        p, d = self.p, candidate.direction
        reach = close * p.approach_pct / 100.0
        if not any(0 <= (near_edge(w) - close) * d <= reach for w in walls):
            return False
        f, i, k = data.base, candidate.bar, p.volume_bars
        if f.volume_kind == "none" or i + 1 < 2 * k:
            return False  # no volume to judge by: nothing is aborted
        recent, before = f.volume[i - k + 1 : i + 1], f.volume[i - 2 * k + 1 : i - k + 1]
        if not (np.isfinite(recent).all() and np.isfinite(before).all()) or before.mean() <= 0:
            return False
        return bool(recent.mean() < p.contraction_factor * before.mean())


# -------------------------------------------------------------------- stop
class WallStopParams(StructuralStopParams, BookParams):
    shield_buffer_pct: float = Field(
        0.05, ge=0, description="فاصلهٔ حد ضرر پشت لبهٔ دور دیوار، درصد قیمت"
    )
    min_gap_pct: float = Field(
        0.05, ge=0, description="دیوار باید دست‌کم این درصد از تریگر دور باشد (وگرنه نادیده)"
    )


@register
class WallShieldedStop(BookBlock[WallStopParams], StopBlock[WallStopParams]):
    """The stop tucked behind the nearest persistent wall that protects the entry (video 41-50).

    Among the persistent walls of the entry's own side (bids below a long, asks above a short)
    that stand strictly between the structural stop and the trigger, the one nearest the trigger
    is chosen and the stop goes just behind its far edge: sellers must eat the wall before the
    trade is stopped. The stop only ever tightens and stays on the losing side of the trigger.
    Without such a wall, or without a book, this is the structural stop.
    """

    kind = BlockKind.STOP
    type = "wall_shielded_stop"
    title_fa = "حد ضرر پشت دیوار دفتر سفارش"
    sources = ("tcp-blueprint 05: videos 41-50 (stop behind the bid wall)",)
    Params = WallStopParams

    def initial_stop(self, candidate: SetupCandidate, data: StrategyData) -> float:
        p, d = self.p, candidate.direction
        base = StructuralStop(p).initial_stop(candidate, data)
        state = self.book_state(candidate, data)
        if state is None:
            return base
        side = own_side(d)
        gap = candidate.trigger * p.min_gap_pct / 100.0
        between = [
            w
            for w in state.walls_on(side)
            if (near_edge(w) - base) * d > 0 and (candidate.trigger - near_edge(w)) * d >= gap
        ]
        if not between:
            return base
        wall = max(between, key=lambda w: near_edge(w) * d)  # the one closest to the entry
        edge = far_edge(wall)
        shield = edge - d * edge * p.shield_buffer_pct / 100.0
        tighter = (shield - base) * d > 0 and (candidate.trigger - shield) * d > 0
        return shield if tighter else base


# -------------------------------------------------------------------- exit
class WallTargetsParams(ProfitChainParams, BookParams):
    front_pct: float = Field(
        0.05, ge=0, description="فاصلهٔ هدف جلوی لبهٔ نزدیک دیوار مقابل، درصد قیمت"
    )


@register
class WallTargets(BookBlock[WallTargetsParams], ProfitChain):
    """The Profit Chain with each target placed just in front of the wall that would stop it.

    Walls on the other side of the book (asks above a long, bids below a short) that lie
    between the previous target and a step's target pull that step in, to just in front of
    the wall's near edge, so the step fills before the wall stops price. The first wall the
    steps meet is the nearest; a step never moves below ``MIN_FULL_CLOSE_R`` and the steps
    stay in increasing order. Everything else (the Runner trail, breakeven, exhaustion exits)
    is the Profit Chain's. Without a book this is the plain Profit Chain.
    """

    kind = BlockKind.EXIT
    type = "wall_targets"
    title_fa = "زنجیرهٔ سود با هدف جلوی دیوار"
    sources = (  # type: ignore[assignment]
        "tcp-blueprint 05: videos 41-50 (take profit in front of the wall)",
        "tcp-blueprint 01 (B): Profit Chain",
    )
    Params = WallTargetsParams

    def plan(self, candidate: SetupCandidate, data: StrategyData, stop: float) -> ExitPlan:
        plan = super().plan(candidate, data, stop)
        state = self.book_state(candidate, data)
        risk = abs(candidate.trigger - stop)
        if state is None or risk <= 0 or not plan.steps:
            return plan
        p, d, trigger = self.p, candidate.direction, candidate.trigger
        walls = sorted(
            (w for w in state.walls_on(opposing_side(d)) if (near_edge(w) - trigger) * d > 0),
            key=lambda w: abs(near_edge(w) - trigger),
        )
        steps: list[Any] = []
        prev_r = 0.0
        for s in plan.steps:
            r = s.r
            for w in walls:
                edge = near_edge(w)
                front = edge - d * edge * p.front_pct / 100.0
                new = round((front - trigger) * d / risk, 6)
                if max(MIN_FULL_CLOSE_R, prev_r + 1e-6) <= new < s.r and (
                    (edge - (trigger + d * s.r * risk)) * d <= 0
                ):
                    r = new
                    break
            steps.append(s.model_copy(update={"r": r}))
            prev_r = r
        return ExitPlan(steps=tuple(steps), runner=plan.runner)
