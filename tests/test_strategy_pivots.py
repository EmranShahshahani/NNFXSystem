"""Floor-trader pivots (Strategy Builder ticket 18): closed periods only, R1/S1 and R3/R4."""

from __future__ import annotations

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, StrategyData
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from nnfx.strategy.pivots import PivotBreach, PivotBreachParams, period_frame, pivot_levels
from tests.test_strategy_blocks import position
from tests.test_strategy_engine import BTC, frame
from tests.test_strategy_oscillators import ROLES, cand

Row = tuple[float, float, float, float]
H4_BARS = 16  # 15-minute bars in a 4H period
# Period 0: H 110, L 90, C 100 -> P 100, R1 110, R2 120, R3 140, R4 160, S1 90, S3 60, S4 40.
PERIOD0: Row = (100.0, 110.0, 90.0, 100.0)
QUIET: Row = (100.0, 101.0, 99.0, 100.0)


def build(rows: list[Row], start: str = "2024-03-01", roles: dict[str, str] | None = None):
    return StrategyData.build(frame(rows, start), roles or ROLES, BTC, SessionConfig())


LAST = 2 * H4_BARS - 2  # the last bar of ``tail`` in ``two_periods``


def two_periods(*tail: Row) -> StrategyData:
    """A first 4H period with a known high, low and close, then quiet bars, ``tail``, and the
    bar that closes the second period (so ``tail`` trades against the first period's pivots)."""
    return build([*[PERIOD0] * H4_BARS, *[QUIET] * (H4_BARS - 1 - len(tail)), *tail, QUIET])


def test_the_new_block_is_a_confirmation():
    assert REGISTRY["pivot_breach"].kind == BlockKind.CONFIRMATION


# ----------------------------------------------------------- the levels
def test_the_levels_are_the_floor_trader_formulas_of_the_closed_period():
    d = two_periods()
    lv = pivot_levels(d, "H4")
    last = H4_BARS - 1  # the bar that closes the first 4H period
    want = dict(p=100, r1=110, r2=120, r3=140, r4=160, s1=90, s2=80, s3=60, s4=40)
    assert {k: round(float(v[last]), 6) for k, v in lv.items()} == want


def test_no_pivots_before_a_period_has_closed_and_none_from_the_period_in_progress():
    row = (50.0, 200.0, 20.0, 80.0)  # period 1 is wild: it must not leak into its own pivots
    d = build([*[PERIOD0] * H4_BARS, *[row] * H4_BARS])
    lv = pivot_levels(d, "H4")
    assert np.isnan(lv["r1"][: H4_BARS - 1]).all()
    assert (lv["r1"][H4_BARS - 1 : 2 * H4_BARS - 1] == 110.0).all()
    assert lv["r1"][2 * H4_BARS - 1] != 110.0  # period 1 closed: its pivots take over


def test_a_role_with_the_period_timeframe_shares_its_frame():
    d = build([PERIOD0] * (2 * H4_BARS), roles={**ROLES, "mwc": "H4", "management": "H4"})
    assert period_frame(d, "H4") is d.frames["mwc"]


def test_weekly_pivots_come_from_a_closed_week_only():
    week = 7 * 96
    rows = [(200.0, 210.0, 190.0, 200.0)] * week + [(300.0, 310.0, 290.0, 300.0)] * week
    d = build(rows, start="2024-03-04")  # a Monday: weeks close on the next Monday 00:00 UTC
    r1 = pivot_levels(d, "W1")["r1"]
    assert np.isnan(r1[: week - 1]).all()
    assert r1[week - 1] == 210.0 and r1[week + 5] == 210.0  # the second week is still open


# ---------------------------------------------------------- the confirmation
def test_a_close_beyond_r1_confirms_a_long_and_beyond_s1_a_short():
    block = PivotBreach(PivotBreachParams(period="H4"))
    up = two_periods((100.0, 113.0, 99.0, 112.0))
    assert block.check(cand(up, LAST, 1), up).outcome == "pass"
    assert block.check(cand(up, LAST, -1), up).outcome == "fail"
    down = two_periods((100.0, 101.0, 86.0, 88.0))
    assert block.check(cand(down, LAST, -1), down).outcome == "pass"
    inside = two_periods((100.0, 109.0, 99.0, 108.0))
    assert block.check(cand(inside, LAST, 1), inside).outcome == "fail"


def test_before_any_period_has_closed_the_check_is_not_applicable():
    d = two_periods()
    block = PivotBreach(PivotBreachParams(period="H4"))
    assert block.check(cand(d, 3, 1), d).outcome == "na"


def test_the_centre_pivot_alone_is_never_a_signal():
    d = two_periods((100.0, 106.0, 99.0, 105.0))  # beyond P (100), under R1 (110)
    block = PivotBreach(PivotBreachParams(period="H4"))
    assert block.check(cand(d, LAST, 1), d).outcome == "fail"


# ---------------------------------------------------------------- the exit
def reasons(block: ProfitChain, d: StrategyData, filled: int, direction: int = 1) -> set[str]:
    pv = position(block, cand(d, 20, direction), d, filled)
    return {getattr(block.manage(pv, d, j), "reason", "") for j in range(21, len(d))}


def spike(high: float = 145.0, low: float = 99.0) -> Row:
    return (100.0, high, low, 100.0)


def test_r3_closes_what_remains_after_the_first_step():
    d = two_periods(spike(145.0))  # reaches R3 (140), not R4 (160)
    on = ProfitChain(ProfitChainParams(pivot_exit="r3", pivot_period="H4"))
    assert "pivot_r3" in reasons(on, d, 1)
    assert "pivot_r3" not in reasons(on, d, 0)  # the 2R floor
    assert "pivot_r3" not in reasons(ProfitChain(), d, 1)
    assert "pivot_r3" not in reasons(on, d, 1, -1)  # a short looks at S3 (60)


def test_r4_is_the_extreme_and_both_mode_waits_for_it():
    d3 = two_periods(spike(145.0))
    d4 = two_periods(spike(165.0))
    both = ProfitChain(ProfitChainParams(pivot_exit="both", pivot_period="H4"))
    r4 = ProfitChain(ProfitChainParams(pivot_exit="r4", pivot_period="H4"))
    assert not {"pivot_r3", "pivot_r4"} & reasons(both, d3, 1)  # R3 only tightens the stop
    assert "pivot_r4" in reasons(both, d4, 1) and "pivot_r4" in reasons(r4, d4, 1)
    assert "pivot_r4" not in reasons(r4, d3, 1)


def test_a_short_targets_s3_and_s4():
    d = two_periods(spike(101.0, 55.0))  # S3 is 60
    on = ProfitChain(ProfitChainParams(pivot_exit="r3", pivot_period="H4"))
    assert "pivot_r3" in reasons(on, d, 1, -1)
    assert "pivot_r3" not in reasons(on, d, 1, 1)


def test_the_new_period_pivots_do_not_judge_the_candle_that_closes_the_period():
    # The bar that closes period 0 reaches 145, but it was traded against no closed pivots.
    d = build([*[PERIOD0] * (H4_BARS - 1), spike(145.0), *[QUIET] * 8])
    on = ProfitChain(ProfitChainParams(pivot_exit="r3", pivot_period="H4"))
    pv = position(on, cand(d, 3, 1), d, 1)
    assert getattr(on.manage(pv, d, H4_BARS - 1), "reason", "") != "pivot_r3"


def test_the_pivot_period_must_be_h4_or_weekly():
    with pytest.raises(ValueError):
        ProfitChainParams.model_validate({"pivot_period": "M15"})
