"""Journal rows and statistics (Strategy Builder ticket 23, ADR 10 §27)."""

from __future__ import annotations

import pytest

from nnfx.strategy.analytics import (
    DIMENSIONS,
    REVIEW_EVERY,
    JournalRow,
    journal_rows,
    review_status,
    statistics,
)
from tests.test_strategy_engine import FILL, RISE, SETUP, SYM, TO_STOP, TO_TARGET, frame, run


def rows_of(tail, **kw):
    rows = [*RISE, SETUP, FILL, *tail]
    out, journal = run(rows, costs=kw.get("costs"))
    return journal_rows(
        out.result.trades,
        journal.records("cycle"),
        {SYM: frame(rows)},
        source="backtest",
    )


def test_a_winning_trade_carries_the_blueprint_fields():
    (r,) = rows_of(TO_TARGET)
    assert r.asset == SYM and r.direction == "long" and r.setup == "candle_setup"
    assert r.timestamp.startswith("2024-03-01T03:00")  # the bar the order filled in
    assert r.session == "asia"  # the 02:45-03:00 UTC bar
    assert r.weekday == "friday"
    assert r.risk_tier == pytest.approx(0.005)
    assert r.size > 0 and r.leverage == 1.0
    assert r.stop == 106.0 and r.targets == [pytest.approx(121.9)]
    assert r.outcome == "win" and r.realised_r == pytest.approx(2.0)
    assert r.fees == 0 and r.slippage == 0  # a free run


def test_costs_reach_the_row_as_fees_slippage_and_spread():
    from pathlib import Path

    from nnfx.brokers.costs import CostModel

    venue = Path(__file__).resolve().parents[1] / "config" / "venues" / "backtest.yaml"
    (r,) = rows_of(TO_TARGET, costs=CostModel.from_venue(venue))
    assert r.fees > 0 and r.slippage >= 0 and r.spread >= 0
    assert r.source == "backtest"


def test_a_losing_trade_has_its_adverse_excursion_in_r():
    (r,) = rows_of(TO_STOP)
    assert r.outcome == "loss" and r.realised_r == pytest.approx(-1.0)
    # entry 111.3, the stop bar's low 105.5, stop distance 5.3: 5.8 / 5.3 R
    assert r.mae_r == pytest.approx(5.8 / 5.3, rel=1e-3)


def test_excursion_is_left_out_when_no_bars_are_at_hand():
    rows = [*RISE, SETUP, FILL, *TO_TARGET]
    out, journal = run(rows)
    (r,) = journal_rows(out.result.trades, journal.records("cycle"), None, source="paper")
    assert r.mae_r is None and r.source == "paper"


def row(**kw) -> JournalRow:
    base = dict(
        position_id="p",
        timestamp="2024-03-04T09:00:00+00:00",  # a Monday, London
        exit_time="2024-03-04T10:00:00+00:00",
        session="london",
        weekday="monday",
        asset="BTC/USDT",
        direction="long",
        setup="candle_setup",
        risk_tier=0.005,
        size=1.0,
        leverage=1.0,
        stop=1.0,
        targets=[2.0],
        outcome="win",
        realised_r=2.0,
        mae_r=0.5,
        slippage=0.0,
        fees=0.0,
        spread=0.0,
        justified=True,
        source="backtest",
    )
    base.update(kw)
    return JournalRow(**base)


def test_statistics_count_and_average_r_per_value_of_each_dimension():
    rs = [
        row(setup="a", realised_r=2.0),
        row(setup="a", realised_r=-1.0, outcome="loss"),
        row(setup="b", realised_r=-1.0, outcome="loss", session="asia"),
    ]
    st = statistics(rs)
    assert set(st) == set(DIMENSIONS)
    a = next(g for g in st["setup"] if g["key"] == "a")
    assert a["count"] == 2 and a["wins"] == 1 and a["win_rate"] == 0.5
    assert a["expectancy_r"] == pytest.approx(0.5) and a["total_r"] == pytest.approx(1.0)
    assert [g["key"] for g in st["session"]] == ["asia", "london"]
    assert st["weekday"][0]["count"] == 3 and st["asset"][0]["key"] == "BTC/USDT"
    assert st["risk_tier"][0]["key"] == "0.5%"


def test_statistics_of_nothing_are_empty_groups():
    assert statistics([]) == {d: [] for d in DIMENSIONS}


def test_a_review_is_prompted_at_every_fifty_trades():
    assert REVIEW_EVERY == 50
    assert review_status(49, 0)["review_due"] is None
    s = review_status(50, 0)
    assert s["review_due"] == 50 and s["next_review_at"] == 100
    assert review_status(137, 0)["review_due"] == 100


def test_changing_rules_is_warned_against_before_a_hundred_forward_trades():
    s = review_status(120, 99)
    assert s["rules_locked"] is True and "۱۰۰" in s["warning"] and s["forward_trades"] == 99
    s = review_status(120, 100)
    assert s["rules_locked"] is False and s["warning"] is None


def test_a_losing_streak_up_to_seven_is_called_normal():
    losses = [row(position_id=f"l{i}", outcome="loss", realised_r=-1.0) for i in range(6)]
    s = review_status(6, 0, losses)
    assert s["current_losing_streak"] == 6 and s["streak_is_normal"] is True
    losses += [row(position_id="x", outcome="loss", realised_r=-1.0)] * 2
    assert review_status(8, 0, losses)["streak_is_normal"] is False
