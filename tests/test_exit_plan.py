"""Fractional exit steps (Strategy Builder ticket 03, ADR 09 §5)."""

from __future__ import annotations

import pytest

from nnfx.brokers.sim import Order
from nnfx.engine.types import ExitPlan, ExitStep, ModifyIntent
from tests.scripted import SYM, bars, broker, drive, market, pending

# A Profit Chain shaped plan: 35% at 2R (then breakeven), 40% at 5R, 15% at 10R, 10% runner.
CHAIN = ExitPlan(
    steps=(
        ExitStep(r=2.0, fraction=0.35, stop_to_r=0.0),
        ExitStep(r=5.0, fraction=0.40),
        ExitStep(r=10.0, fraction=0.15),
    ),
    remainder=0.10,
)


def exits(b) -> list[tuple[str, float, float]]:
    """(reason, exit price, share of the original size) for each closed piece."""
    total = sum(t.units for t in b.trades) + sum(p.units for p in b.s.positions.values())
    return [(t.exit_reason, t.exit_price, round(t.units / total, 6)) for t in b.trades]


# ------------------------------------------------------------- validation
def test_fractions_and_remainder_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        ExitPlan(steps=(ExitStep(r=2.0, fraction=0.5),), remainder=0.4)
    with pytest.raises(ValueError, match="increasing"):
        ExitPlan(steps=(ExitStep(r=5.0, fraction=0.5), ExitStep(r=2.0, fraction=0.5)))
    with pytest.raises(ValueError, match="greater than 0"):
        ExitStep(r=2.0, fraction=0.0)
    with pytest.raises(ValueError, match="greater than 0"):
        ExitStep(r=0.0, fraction=0.5)
    with pytest.raises(ValueError, match="exit plan or a target"):
        market(target_distance=5.0, exit_plan=CHAIN)
    assert ExitPlan(steps=(ExitStep(r=1.0, fraction=1.0),)).remainder == 0.0


# ------------------------------------------------------------------ steps
def test_each_step_closes_its_share_of_the_original_size_at_its_r_level():
    # Entry 100, stop distance 5 -> R = 5: steps at 110, 125, 150.
    h = bars(
        [
            (100, 101, 99, 100),
            (100, 104, 99, 103),
            (103, 111, 102, 108),
            (108, 126, 107, 120),
            (120, 151, 119, 140),
        ]
    )
    b, _, _ = drive(h, {0: [market(exit_plan=CHAIN)]})
    assert exits(b) == [
        ("target_partial", 110.0, 0.35),
        ("target_partial", 125.0, 0.40),
        ("target_partial", 150.0, 0.15),
    ]
    (p,) = b.s.positions.values()
    assert p.stop == 100.0  # moved to breakeven by the first step
    # Total initial risk is the approved risk, split across the pieces.
    approved = b.trades[0].risk_cash / 0.35
    assert sum(t.risk_cash for t in b.trades) + p.risk_cash == pytest.approx(approved)


def test_a_breakeven_step_then_a_fall_closes_the_rest_at_entry():
    h = bars([(100, 101, 99, 100), (100, 104, 99, 103), (103, 111, 102, 108), (108, 109, 98, 99)])
    b, _, _ = drive(h, {0: [market(exit_plan=CHAIN)]})
    assert exits(b) == [("target_partial", 110.0, 0.35), ("trailing_stop", 100.0, 0.65)]
    assert not b.s.positions


def test_a_bar_reaching_a_step_and_its_breakeven_stop_closes_the_rest_at_entry():
    # Conservative: once the step fills, the same bar trading back to entry stops the rest.
    h = bars([(100, 101, 99, 100), (100, 104, 99, 103), (103, 111, 99, 104)])
    b, _, _ = drive(h, {0: [market(exit_plan=CHAIN)]})
    assert exits(b) == [("target_partial", 110.0, 0.35), ("trailing_stop", 100.0, 0.65)]


def test_several_steps_in_one_bar_fill_in_order_and_a_gap_fills_them_at_the_open():
    h = bars([(100, 101, 99, 100), (100, 126, 101, 120), (152, 153, 151, 152)])
    b, _, _ = drive(h, {0: [market(exit_plan=CHAIN)]})
    assert exits(b) == [
        ("target_partial", 110.0, 0.35),
        ("target_partial", 125.0, 0.40),
        ("target_partial", 152.0, 0.15),
    ]


def test_a_stop_and_a_step_in_one_bar_assume_the_stop():
    h = bars([(100, 101, 99, 100), (100, 111, 94, 100)])
    b, _, _ = drive(h, {0: [market(exit_plan=CHAIN)]})
    assert exits(b) == [("stop", 95.0, 1.0)]


def test_a_plan_without_remainder_closes_everything_on_the_last_step():
    plan = ExitPlan(steps=(ExitStep(r=1.0, fraction=0.5), ExitStep(r=2.0, fraction=0.5)))
    h = bars([(100, 101, 99, 100), (100, 106, 99, 105), (105, 111, 104, 110)])
    b, _, _ = drive(h, {0: [market(exit_plan=plan)]})
    assert exits(b) == [("target_partial", 105.0, 0.5), ("target", 110.0, 0.5)]
    assert not b.s.positions


def test_pending_fills_measure_steps_in_planned_r_from_the_actual_entry():
    # Trigger 105, stop 95: planned R = 10. A gap fill at 108 puts 2R at 128.
    plan = ExitPlan(steps=(ExitStep(r=2.0, fraction=0.5),), remainder=0.5)
    h = bars([(100, 101, 99, 100), (108, 110, 107, 109), (109, 129, 108, 125)])
    b, _, _ = drive(h, {0: [pending("k", level=105.0, stop=95.0, exit_plan=plan)]})
    assert exits(b) == [("target_partial", 128.0, 0.5)]


# ------------------------------------------------------------------ hooks
def test_the_engine_sees_step_progress_and_can_trail_the_remainder():
    def trail(positions):
        (p,) = positions
        if p.steps_filled == 3 and p.stop < 140.0:
            return [ModifyIntent(symbol=SYM, position_id=p.id, stop=140.0, reason="trail")]
        return []

    h = bars(
        [
            (100, 101, 99, 100),
            (100, 126, 101, 120),
            (120, 151, 119, 150),
            (150, 152, 145, 149),
            (149, 150, 139, 141),
        ]
    )
    b, eng, _ = drive(h, {0: [market(exit_plan=CHAIN)], 2: trail, 3: trail})
    seen = [ps[0].steps_filled if ps else None for ps in eng.positions]
    assert seen == [None, 2, 3, 3, None]
    assert eng.positions[2][0].exit_steps[2].price == 150.0
    assert exits(b)[-1] == ("trailing_stop", 140.0, 0.1)


def test_paper_broker_restarted_every_bar_runs_the_plan_like_the_backtest(tmp_path):
    from nnfx.brokers.costs import CostModel
    from nnfx.brokers.paper import PaperBroker
    from nnfx.harness.loop import TradingLoop
    from nnfx.journal.journal import Journal
    from tests.scripted import BTC, CFG, Scripted

    rows = [
        (100, 101, 99, 100),
        (100, 104, 99, 103),
        (103, 111, 102, 108),
        (108, 126, 107, 120),
        (120, 121, 99, 100),
    ]
    h = bars(rows)
    script = {0: [market(exit_plan=CHAIN)]}
    bt, _, _ = drive(h, script)
    eng = Scripted(script)
    for i in range(len(rows)):
        paper = PaperBroker({SYM: BTC}, CostModel.zero(), 10_000.0, state_path=tmp_path / "p.json")
        loop = TradingLoop(CFG, {SYM: BTC}, paper, Journal(), engine=eng)
        loop.feed_bar(h.at(i), {})
        loop.decide(h.index[i], {SYM: h.at(i)})
    assert [t.__dict__ for t in paper.trades] == [t.__dict__ for t in bt.trades]
    assert exits(paper)[-1] == ("trailing_stop", 100.0, 0.25)


# ------------------------------------------------------- NNFX equivalence
def test_the_legacy_half_at_target_order_is_the_same_as_its_exit_plan():
    rows = [(1.0, 1.001, 0.999, 1.0), (1.0, 1.011, 0.999, 1.01), (1.01, 1.02, 1.0, 1.015)]
    h = bars(rows)
    base = dict(
        symbol=SYM,
        direction=1,
        units=20_000.0,
        leg="combined",
        entry_type="standard",
        signal_time="s",
        atr=0.01,
        stop_distance=0.015,
        risk_cash=300.0,
    )
    legacy = Order(**base, target_distance=0.01, target_fraction=0.5)
    plan = ExitPlan(steps=(ExitStep(r=0.01 / 0.015, fraction=0.5),), remainder=0.5)
    explicit = Order(**base, target_distance=None, target_fraction=1.0, exit_plan=plan)
    results = []
    for order in (legacy, explicit):
        b = broker()
        b.submit(order, "k")
        for i in range(len(rows)):
            o, hi, lo, c = rows[i]
            b.process_bar(SYM, h.index[i], o, hi, lo, c)
        results.append(([t.__dict__ for t in b.trades], b.positions()))
    assert results[0] == results[1]
    assert results[0][0][0]["exit_reason"] == "target_partial"
