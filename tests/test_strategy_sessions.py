"""Sessions in UTC (Strategy Builder ticket 18): the filter, DST-proofing and the regimes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, StrategyData
from nnfx.strategy.sessions import (
    SESSION_HOURS,
    SessionFilter,
    SessionFilterParams,
    SessionRegime,
    SessionRegimeParams,
    in_hours,
    session_trends,
)
from tests.test_strategy_engine import BTC, frame
from tests.test_strategy_oscillators import ROLES, rows_of

PER_DAY = 96  # 15-minute bars


def price_path(points: list[tuple[float, float]], days: int) -> list[float]:
    """Closes at every 15-minute label from 00:15 of day 0, joining ``(hour, price)`` points
    (hours count from midnight of day 0)."""
    hours = (np.arange(days * PER_DAY) + 1) * 0.25
    xs, ys = zip(*points, strict=True)
    return [float(v) for v in np.interp(hours, xs, ys)]


def build(closes: list[float], start: str) -> StrategyData:
    return StrategyData.build(frame(rows_of(closes), start), ROLES, BTC, SessionConfig())


def labels(d: StrategyData) -> pd.DatetimeIndex:
    return d.base.index


def label_set(d: StrategyData, mask: np.ndarray) -> set[str]:
    return {t.strftime("%H:%M") for t in labels(d)[mask]}


def flat_days(days: int, start: str = "2024-03-01") -> StrategyData:
    return build([100.0 + 0.01 * k for k in range(days * PER_DAY)], start)


def test_the_new_blocks_are_context_blocks():
    for t in ("session_filter", "session_regime"):
        assert REGISTRY[t].kind == BlockKind.CONTEXT


def test_the_blueprints_session_windows_are_in_utc():
    assert SESSION_HOURS == {"asia": (0, 8), "london": (7, 16), "new_york": (12, 21)}


def test_in_hours_wraps_past_midnight():
    h = np.array([0.0, 2.0, 5.0, 22.0, 23.75])
    assert list(in_hours(h, 21.0, 3.0)) == [True, True, False, True, True]
    assert list(in_hours(h, 1.0, 1.0)) == [False] * 5


# ----------------------------------------------------------------- filter
def test_no_entries_between_21_and_midnight_utc_by_default():
    d = flat_days(2)
    out = SessionFilter().compute(d)
    blocked = label_set(d, ~out.long_ok)
    assert blocked == {f"{h:02d}:{m:02d}" for h in (21, 22, 23) for m in (0, 15, 30, 45)}
    assert out.long_ok[0] and out.short_ok.tolist() == out.long_ok.tolist()
    assert out.flags["blackout"].sum() == 2 * 12


def test_a_bar_closing_at_21_places_nothing_but_the_midnight_close_does():
    d = flat_days(2)
    ok = dict(zip(labels(d).strftime("%H:%M"), SessionFilter().compute(d).long_ok, strict=True))
    assert ok["20:45"] and not ok["21:00"] and not ok["23:45"] and ok["00:15"]


def test_only_the_chosen_sessions_may_enter():
    d = flat_days(2)
    out = SessionFilter(SessionFilterParams(sessions=["london", "new_york"])).compute(d)
    allowed = label_set(d, out.long_ok)
    assert {"07:00", "12:00", "20:45"} <= allowed
    assert not {"00:00", "06:45", "21:00"} & allowed
    asia = SessionFilter(SessionFilterParams(sessions=["asia"])).compute(d).long_ok
    assert label_set(d, asia) == {f"{h:02d}:{m:02d}" for h in range(8) for m in (0, 15, 30, 45)}


def test_the_blackout_can_be_moved_or_switched_off():
    d = flat_days(1)
    moved = SessionFilter(SessionFilterParams(blackout_from=3.0, blackout_to=5.0)).compute(d)
    assert {"03:00", "04:45"} <= label_set(d, ~moved.long_ok)
    assert "05:00" not in label_set(d, ~moved.long_ok)
    # The three sessions already end at 21:00: without the blackout 21-24 is still outside them.
    off = SessionFilter(SessionFilterParams(blackout=False)).compute(d)
    assert "22:00" in label_set(d, ~off.long_ok)


@pytest.mark.parametrize(
    "start",
    ["2024-03-09", "2024-03-30", "2024-10-26", "2024-11-02"],  # US and EU clock changes
)
def test_the_windows_do_not_move_across_daylight_saving_changes(start):
    d = flat_days(4, start)
    out = SessionFilter().compute(d)
    hours = {t.strftime("%H:%M") for t in labels(d)[out.flags["blackout"]]}
    # Every UTC day blocks the same twelve labels, 21:00 up to 23:45, whatever the local clocks do.
    assert hours == {f"{h:02d}:{m:02d}" for h in (21, 22, 23) for m in (0, 15, 30, 45)}
    assert out.long_ok[labels(d).hour == 20].all()
    assert out.flags["blackout"].sum() == 4 * 12
    assert str(labels(d).tz) == "UTC"


# ----------------------------------------------------------------- regimes
def at(d: StrategyData, day: int, hh: str) -> int:
    t = pd.Timestamp(d.base.index[0].normalize() + pd.Timedelta(days=day)).tz_localize(None)
    return int(d.base.index.get_loc(pd.Timestamp(f"{t.date()} {hh}", tz="UTC")))


def trending_two_days() -> StrategyData:
    # Day 0: flat until 07:00, up 100 -> 130 by 21:00 (London and New York both rise), then flat.
    pts = [(0, 100), (7, 100), (21, 130), (48, 130)]
    return build(price_path(pts, 2), "2024-03-01")


def test_a_session_trends_when_its_net_move_covers_enough_of_its_range():
    d = trending_two_days()
    known, trend = session_trends(d, 7.0, 16.0, 0.5)
    assert list(trend) == [1, 0] and pd.Timestamp(known[0], tz="UTC").hour == 16  # day 0, day 1
    flat = build(price_path([(0, 100), (48, 100)], 2), "2024-03-01")
    assert list(session_trends(flat, 7.0, 16.0, 0.5)[1]) == [0, 0]


def test_a_session_still_in_progress_is_not_judged():
    d = trending_two_days().head(PER_DAY - 16)  # data up to 20:00: New York has an hour to run
    assert len(session_trends(d, 12.0, 21.0, 0.5)[1]) == 0
    assert list(session_trends(d, 7.0, 16.0, 0.5)[1]) == [1]


def test_london_and_new_york_trending_together_set_a_bias_until_the_next_london_close():
    d = trending_two_days()
    out = SessionRegime().compute(d)
    bias = out.flags["bias"]
    assert bias[at(d, 0, "20:45")] == 0 and bias[at(d, 0, "21:00")] == 1
    assert bias[at(d, 1, "15:45")] == 1 and bias[at(d, 1, "16:00")] == 0
    i = at(d, 1, "03:00")
    assert out.allows(i, 1) and not out.allows(i, -1)  # counter-bias entries are refused
    assert out.tags_for(i, 1) == {"continuation"} and out.tags_for(i, -1) == set()
    free = SessionRegime(SessionRegimeParams(follow_continuation=False)).compute(d)
    assert free.allows(i, -1)


def test_disagreeing_sessions_set_no_bias():
    # London rises 07 -> 16, then everything falls back by 21: New York is a down session.
    pts = [(0, 100), (7, 100), (16, 125), (21, 95), (48, 95)]
    d = build(price_path(pts, 2), "2024-03-01")
    assert not SessionRegime().compute(d).flags["bias"].any()


def test_a_london_that_fails_to_trend_moves_momentum_to_the_us_open():
    # Day 0: London chops between 97 and 103 until 13:30; day 1 trends from 07:00 on.
    chop = [(h, 100 + (3 if h % 2 else -3)) for h in range(7, 14)]
    pts = [(0, 100), *chop, (13.5, 100), (24, 100), (31, 100), (45, 140), (48, 140)]
    d = build(price_path(pts, 2), "2024-03-01")
    out = SessionRegime().compute(d)
    failed, window = out.flags["london_failed"], out.flags["us_open_window"]
    assert not failed[at(d, 0, "13:15")] and failed[at(d, 0, "13:30")]
    assert window[at(d, 0, "13:30")] and window[at(d, 0, "14:15")] and not window[at(d, 0, "14:30")]
    assert out.tags_for(at(d, 0, "14:00"), 1) == {"us_open_shift"}
    assert not failed[at(d, 1, "20:00")]  # the next day's London trended


def test_us_open_only_refuses_later_entries_on_a_failure_day():
    chop = [(h, 100 + (3 if h % 2 else -3)) for h in range(7, 14)]
    pts = [(0, 100), *chop, (13.5, 100), (48, 100)]
    d = build(price_path(pts, 2), "2024-03-01")
    only = SessionRegime(SessionRegimeParams(us_open_only=True)).compute(d)
    assert only.allows(at(d, 0, "14:00"), 1) and not only.allows(at(d, 0, "14:30"), 1)
    assert only.allows(at(d, 0, "10:00"), 1)  # judged only once London is in
    assert SessionRegime().compute(d).allows(at(d, 0, "14:30"), 1)


def test_nothing_is_known_before_the_first_session_finishes():
    d = build(price_path([(0, 100), (48, 130)], 2), "2024-03-01")
    out = SessionRegime().compute(d.head(30))
    assert not out.flags["bias"].any() and not out.flags["london_failed"].any()
