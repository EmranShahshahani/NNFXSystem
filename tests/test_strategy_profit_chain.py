"""The Profit Chain and position management (Strategy Builder ticket 07).

Harness-level: hand-built 15m bars run through the shared backtest harness,
broker and journal, as every other Strategy Document test.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.engine.types import ExitPlan, ExitStep
from nnfx.journal.journal import Journal
from nnfx.strategy import validate_document
from nnfx.strategy.blocks import SetupCandidate, StrategyData, closes_all_below
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from nnfx.strategy.run import backtest_document
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, SYM, TO_STOP, TO_TARGET, frame

Row = tuple[float, float, float, float]
TRIGGER, STOP = 111.3, 106.0
R = TRIGGER - STOP  # 5.3


def leg(start: float, step: float, bars: int) -> list[Row]:
    """``bars`` bars moving ``step`` each, wicks so that every turn is a strict pivot."""
    out, c = [], start
    for _ in range(bars):
        o, c = c, c + step
        if step > 0:
            out.append((o, c + 0.1, o - 0.05, c))
        else:
            out.append((o, o + 0.05, c - 0.1, c))
    return out


def zigzag(start: float, until: float, up: int = 4, down: int = 2) -> tuple[list[Row], float]:
    """Up ``up`` bars of +2, down ``down`` bars of -1.5, until the close passes ``until``."""
    rows, c = [], start
    while c < until:
        rows += leg(c, 2.0, up)
        c = rows[-1][3]
        if c >= until:
            break
        rows += leg(c, -1.5, down)
        c = rows[-1][3]
    return rows, c


def chain(**params: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["blocks"][-1] = {"kind": "exit", "type": "profit_chain", "params": params}
    raw["timeframes"]["management"] = "M15"
    return raw


def run(rows: list[Row], raw: dict[str, Any]):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    journal = Journal()
    out = backtest_document(res.document, {SYM: frame(rows)}, {SYM: BTC}, journal=journal)
    return out, journal


def moves(journal: Journal) -> list[dict[str, Any]]:
    return [
        {"time": r["time"], **ev["values"]}
        for r in journal.records("cycle")
        for ev in r["evaluations"]
        if ev["values"].get("event") == "stop_move"
    ]


def ladder_rows() -> list[Row]:
    up, c = zigzag(FILL[3], TRIGGER + 10.5 * R)  # beyond the 10R step
    return [*RISE, SETUP, FILL, *up, *leg(c, -3.0, 6)]  # then a fall onto the Runner's stop


# ---------------------------------------------------------------- ladder
def test_a_full_ladder_out_then_a_trailing_runner_exit():
    out, journal = run(ladder_rows(), chain())
    trades = out.result.trades
    assert len({t.position_id for t in trades}) == 1
    units = sum(t.units for t in trades)
    shares = [round(t.units / units, 6) for t in trades]
    assert shares == [0.35, 0.40, 0.15, 0.10]
    exits = [t.exit_price for t in trades[:3]]
    assert exits == pytest.approx([TRIGGER + 2 * R, TRIGGER + 5 * R, TRIGGER + 10 * R])
    runner = trades[3]
    # The Runner left at its trailed stop: far above entry, below the 10R step.
    assert TRIGGER + 5 * R < runner.exit_price < TRIGGER + 10 * R and runner.r_multiple > 5
    reasons = [m["reason"] for m in moves(journal)]
    assert reasons[0] == "breakeven_after_pivot" and "runner_trail" in reasons
    stops = [m["to"] for m in moves(journal)]
    assert stops == sorted(stops)  # only ever tighter


def test_the_ladder_steps_and_runner_are_parameters():
    out, _ = run(ladder_rows(), chain(f3=0.20, runner=0.05))
    units = sum(t.units for t in out.result.trades)
    assert [round(t.units / units, 6) for t in out.result.trades] == [0.35, 0.40, 0.20, 0.05]
    out, _ = run(ladder_rows(), chain(f1=0.5, f2=0.5, f3=0, runner=0))
    assert [round(t.exit_price, 6) for t in out.result.trades] == pytest.approx(
        [TRIGGER + 2 * R, TRIGGER + 5 * R]
    )


def test_breakeven_needs_a_new_pivot_after_the_entry():
    # A straight run to 2R (no swing since the entry), then a fall to the stop.
    rows = [*RISE, SETUP, FILL, *TO_TARGET, *TO_STOP]
    out, journal = run(rows, chain())
    assert moves(journal) == []
    first, rest = out.result.trades
    assert first.exit_price == pytest.approx(TRIGGER + 2 * R)
    assert rest.exit_price == pytest.approx(STOP, abs=0.6)  # the original stop, not breakeven
    # Unconditional breakeven, if a user wants it: the step itself moves the stop.
    out, _ = run(rows, chain(breakeven="always"))
    assert out.result.trades[1].exit_price == pytest.approx(TRIGGER, abs=0.6)


def test_breakeven_moves_the_stop_to_entry_once_a_swing_forms():
    rows = [*RISE, SETUP, FILL, *TO_TARGET]
    c = rows[-1][3]
    rows += [*leg(c, -1.0, 2), *leg(c - 2.0, 1.0, 3), *leg(c + 1.0, -4.0, 4)]
    out, journal = run(rows, chain())
    (be,) = [m for m in moves(journal) if m["reason"] == "breakeven_after_pivot"]
    entry = out.result.trades[0].entry_price
    assert be["to"] == pytest.approx(entry) and be["steps_filled"] == 1
    assert out.result.trades[1].exit_price == pytest.approx(entry, abs=0.6)


def test_management_acts_on_the_management_timeframes_closes():
    up, c = zigzag(FILL[3], TRIGGER + 10.5 * R, up=12, down=8)
    rows = [*RISE, SETUP, FILL, *up, *leg(c, -3.0, 12)]
    raw = chain(pivot_bars=1)
    raw["timeframes"]["management"] = "H1"
    _, journal = run(rows, raw)
    ms = moves(journal)
    assert ms and all(pd.Timestamp(m["time"]).minute == 0 for m in ms)


def test_the_management_timeframe_defaults_to_the_mwc():
    res = validate_document(DOC)
    assert res.document is not None
    data = StrategyData.build(
        frame([*RISE, SETUP]), res.document.timeframes.as_dict(), BTC, _session()
    )
    assert data.roles["management"] == "H4"


# --------------------------------------------------------- counter-trend
def test_counter_trend_mode_closes_everything_at_2r_with_no_runner():
    rows = [*RISE, SETUP, FILL, *TO_TARGET, *TO_STOP]
    out, _ = run(rows, chain(counter_trend="always"))
    (t,) = out.result.trades
    assert t.exit_price == pytest.approx(TRIGGER + 2 * R) and t.r_multiple == pytest.approx(2.0)


def _session():
    from nnfx.config import SessionConfig

    return SessionConfig()


def _cand(rows: list[Row]) -> tuple[SetupCandidate, StrategyData]:
    roles = {"hwc": "D1", "mwc": "H4", "lwc": "M15", "management": "M15"}
    data = StrategyData.build(frame(rows), roles, BTC, _session())
    i = len(rows) - 1
    return SetupCandidate(SYM, "candle_setup", 1, i, "", 1, TRIGGER, STOP, STOP), data


@pytest.mark.parametrize(
    ("peak", "r"),
    [(TRIGGER + 2.6 * R, 2.6), (TRIGGER + 1.2 * R, 2.0), (TRIGGER + 6 * R, 3.0), (None, 2.0)],
)
def test_counter_trend_can_close_at_the_first_structural_boundary(peak: float | None, r: float):
    # A swing high at ``peak`` (confirmed by two lower bars each side), then the setup.
    base = 100.0
    rows: list[Row] = [(base, base + 0.5, base - 0.5, base)] * 3
    if peak is not None:
        rows += [(base, base + 1, base - 0.5, base), (base, peak, base - 0.5, base)]
        rows += [(base, base + 1, base - 0.5, base), (base, base + 0.5, base - 0.5, base)]
    rows += [(base, base + 0.5, base - 0.5, base)] * 2
    cand, data = _cand(rows)
    block = ProfitChain(ProfitChainParams(counter_trend="always", counter_trend_exit="boundary"))
    plan = block.plan(cand, data, STOP)
    assert plan == ExitPlan(steps=(ExitStep(r=r, fraction=1.0),))


def test_tagged_counter_trend_applies_only_to_tagged_candidates():
    rows: list[Row] = [(100.0, 100.5, 99.5, 100.0)] * 5
    cand, data = _cand(rows)
    block = ProfitChain(ProfitChainParams(counter_trend="tagged"))
    assert block.plan(cand, data, STOP).runner == pytest.approx(0.10)
    from dataclasses import replace

    tagged = replace(cand, tags=("counter_trend",))
    assert block.plan(tagged, data, STOP).runner == 0.0


# ------------------------------------------------------------ the 2R floor
def test_no_exit_rule_closes_the_whole_position_below_2r():
    def issue(raw: dict[str, Any]) -> list[tuple[str, str]]:
        return [(i.path, i.code) for i in validate_document(raw).issues]

    assert ("blocks[4].params.r1", "bad_param") in issue(chain(r1=1.5))
    fixed = copy.deepcopy(DOC)
    fixed["blocks"][-1]["params"]["r"] = 1.5
    assert ("blocks[4].params.r", "bad_param") in issue(fixed)
    assert issue(chain(counter_trend_max_r=1.5))
    # The engine refuses any plan that would, whatever Exit Block made it.
    assert closes_all_below(ExitPlan(steps=(ExitStep(r=1.5, fraction=1.0),)))
    assert not closes_all_below(
        ExitPlan(steps=(ExitStep(r=1.0, fraction=0.5), ExitStep(r=3.0, fraction=0.5)))
    )


def test_ladder_fractions_must_sum_to_one_with_a_persian_message():
    res = validate_document(chain(f3=0.20))  # runner still 0.10: 1.05
    assert res.document is None
    (i,) = res.issues
    assert i.path == "blocks[4].params" and "جمع" in i.message
    assert validate_document(chain(r2=12.0)).document is None  # R must increase


# -------------------------------------------------------------- recycling
def test_recycling_records_big_winners_as_moved_to_spot():
    out, _ = run(ladder_rows(), chain(recycle_to_spot=True))
    (t,) = out.spot_transfers
    trades = out.result.trades
    assert t.amount == pytest.approx(sum(x.net_pnl for x in trades)) and t.r >= 5
    split = out.split_equity()
    assert split["spot"].iloc[-1] == pytest.approx(t.amount)
    assert np.allclose(split["trading"] + split["spot"], out.result.equity)
    assert out.spot_balance() == pytest.approx(t.amount)
    # Off by default; and a 2R close is not recycled.
    assert run(ladder_rows(), chain())[0].spot_transfers == []
    small = [*RISE, SETUP, FILL, *TO_TARGET, *TO_STOP]
    assert run(small, chain(recycle_to_spot=True))[0].spot_transfers == []
