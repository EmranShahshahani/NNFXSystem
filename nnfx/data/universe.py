"""Point-in-time crypto universe (doc 03 §2b, ticket 06).

At each rebalance date the universe is ranked by trailing quote-volume using
only bars that had closed by that date. Coins that later delist remain in the
schedule while they were tradeable; positions in them are force-closed at the
last valid price by the harness. Selecting on end-of-sample data is the
survivorship bias this module exists to prevent, and ``validate_point_in_time``
rejects any schedule that could not have been built at the time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from nnfx.data.bars import BarFrame


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rebalance: str = "MS"  # pandas offset alias: month start
    window_days: int = Field(90, ge=1)
    top_n: int = Field(15, ge=1)
    min_history_days: int = Field(30, ge=0)


class LookaheadError(RuntimeError):
    pass


@dataclass(frozen=True)
class UniverseSchedule:
    rebalances: tuple[tuple[pd.Timestamp, tuple[str, ...]], ...]

    def members_at(self, ts: pd.Timestamp) -> tuple[str, ...]:
        current: tuple[str, ...] = ()
        for when, members in self.rebalances:
            if when <= ts:
                current = members
            else:
                break
        return current

    def ever(self) -> set[str]:
        return {s for _, m in self.rebalances for s in m}


def trailing_liquidity(
    frame: BarFrame, as_of: pd.Timestamp, window_days: int, min_history_days: int
) -> float:
    idx = frame.index
    if not len(idx) or idx[0] > as_of - pd.Timedelta(days=min_history_days):
        return float("nan")
    if idx[-1] < as_of - pd.Timedelta(days=2):  # no longer trading at as_of
        return float("nan")
    mask = (idx <= as_of) & (idx > as_of - pd.Timedelta(days=window_days))
    if not mask.any():
        return float("nan")
    return float(np.sum(frame.close[mask] * frame.volume[mask]))


def rank_at(
    frames: Mapping[str, BarFrame], as_of: pd.Timestamp, cfg: UniverseConfig
) -> tuple[str, ...]:
    scores = {
        s: trailing_liquidity(f, as_of, cfg.window_days, cfg.min_history_days)
        for s, f in frames.items()
    }
    ranked = sorted(
        ((v, s) for s, v in scores.items() if np.isfinite(v) and v > 0), key=lambda x: (-x[0], x[1])
    )
    return tuple(sorted(s for _, s in ranked[: cfg.top_n]))


def build_universe(
    frames: Mapping[str, BarFrame], start: pd.Timestamp, end: pd.Timestamp, cfg: UniverseConfig
) -> UniverseSchedule:
    dates = pd.date_range(start, end, freq=cfg.rebalance, tz="UTC")
    # A rebalance at date d may only see bars that closed at or before d.
    return UniverseSchedule(
        tuple(
            (d, rank_at({s: f.between(None, d) for s, f in frames.items()}, d, cfg)) for d in dates
        )
    )


def end_of_sample_basket(frames: Mapping[str, BarFrame], cfg: UniverseConfig) -> tuple[str, ...]:
    """The survivorship-biased basket: today's top coins. Exists only to be rejected."""
    end = max(f.index[-1] for f in frames.values())
    return rank_at(frames, end, cfg)


def validate_point_in_time(
    schedule: UniverseSchedule, frames: Mapping[str, BarFrame], cfg: UniverseConfig
) -> None:
    """Raise ``LookaheadError`` unless every rebalance is reproducible from data available then."""
    for when, members in schedule.rebalances:
        expected = rank_at({s: f.between(None, when) for s, f in frames.items()}, when, cfg)
        if tuple(sorted(members)) != expected:
            extra = sorted(set(members) - set(expected))
            missing = sorted(set(expected) - set(members))
            raise LookaheadError(
                f"universe at {when.date()} is not point-in-time: includes {extra}, omits {missing}"
            )


def static_schedule(members: tuple[str, ...], start: pd.Timestamp) -> UniverseSchedule:
    return UniverseSchedule(((start, tuple(sorted(members))),))
