"""The remaining Setup Blocks and the chase guard (Strategy Builder ticket 14).

Each Setup has hand-built bars where it fires and bars where it must not, the
candidate's trigger, invalidation and stop, and the causal/scale-free guarantees.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.journal.journal import Journal
from nnfx.strategy import REGISTRY, StrategyData
from nnfx.strategy.setups import (
    AbsorptionWick,
    AbsorptionWickParams,
    BinaryScenario,
    BinaryScenarioParams,
    ChaseGuard,
    ChaseGuardParams,
    DowContinuation,
    DowContinuationParams,
    Engulfing,
    EngulfingParams,
    GiantIndecisionParams,
    GiantIndecisionReversal,
    LayeredParams,
    LayeredSetup,
    MomentumContinuation,
    MomentumContinuationParams,
)
from tests.test_strategy_engine import BTC, DOC, RISE, SETUP, frame
from tests.test_strategy_engine import run as run_engine
from tests.test_strategy_levels import PERP, Row, box, leg, run, with_volume

ROLES = {"hwc": "M15", "mwc": "M15", "lwc": "M15", "management": "M15"}


def data(rows: list[Row], volume: list[float] | None = None, kind: str = "traded") -> StrategyData:
    f = frame(rows)
    if volume is not None:
        f = with_volume(f, np.asarray(volume, float), kind)
    return StrategyData.build(f, ROLES, BTC, SessionConfig())


def fired(out: Any) -> list[int]:
    return [int(i) for i in np.flatnonzero(out.direction)]


def test_every_new_block_is_registered_with_a_flat_form():
    new = {
        "engulfing", "giant_indecision", "absorption_wick", "layered_setup", "dow_continuation",
        "binary_scenario", "momentum_continuation", "chase_guard",
    }  # fmt: skip
    assert new <= set(REGISTRY)
    for t in new:
        schema = REGISTRY[t].Params.model_json_schema()
        assert "$defs" not in schema, t


# ------------------------------------------------------------------ engulfing
FLAT = [(100.0, 100.6, 99.4, 100.0)] * 20


def fading_leg() -> list[Row]:
    c, rows = 100.0, []
    for b in [3, 3, 3, 2.5, 2, 1.2, 1.0, 0.8]:  # a down leg whose pushes fade
        rows.append((c, c + 0.2, c - b - 0.2, c - b))
        c -= b
    return rows


def bullish_engulf(prev: Row) -> Row:
    return (prev[2] - 0.1, prev[1] + 0.5, prev[2] - 0.3, prev[1] + 0.4)  # body covers prev range


def test_a_bullish_engulfing_after_a_fading_down_leg_triggers_above_its_high():
    rows = [*FLAT, *fading_leg()]
    rows.append(bullish_engulf(rows[-1]))
    out = Engulfing().compute(data(rows))
    i = len(rows) - 1
    assert fired(out) == [i] and out.direction[i] == 1
    assert (out.trigger[i], out.invalidation[i], out.stop[i]) == (
        rows[i][1],
        rows[i][2],
        rows[i][2],
    )
    assert out.tags["engulfing"][i]


def test_a_bearish_engulfing_after_a_fading_up_leg_mirrors_it():
    mirror = [
        (200.0 - o, 200.0 - lo, 200.0 - h, 200.0 - c) for o, h, lo, c in [*FLAT, *fading_leg()]
    ]
    prev = mirror[-1]
    mirror.append((prev[1] + 0.1, prev[1] + 0.3, prev[2] - 0.5, prev[2] - 0.4))
    out = Engulfing().compute(data(mirror))
    i = len(mirror) - 1
    assert fired(out) == [i] and out.direction[i] == -1
    assert (out.trigger[i], out.stop[i]) == (mirror[i][2], mirror[i][1])


def test_an_engulfing_without_prior_weakness_or_a_prior_leg_is_ignored():
    strong = []
    c = 100.0
    for b in [1, 1, 1, 2, 3, 3, 3, 3]:  # the pushes are growing, not fading
        strong.append((c, c + 0.2, c - b - 0.2, c - b))
        c -= b
    rows = [*FLAT, *strong]
    rows.append(bullish_engulf(rows[-1]))
    assert fired(Engulfing().compute(data(rows))) == []
    alone = [*FLAT, (100.0, 100.4, 99.6, 99.8)]  # no leg before it
    alone.append(bullish_engulf(alone[-1]))
    assert fired(Engulfing().compute(data(alone))) == []


def test_a_candle_that_covers_only_the_body_not_the_wicks_is_not_an_engulfing():
    rows = [*FLAT, *fading_leg()]
    prev = rows[-1]
    rows.append((prev[3] - 0.1, prev[1] - 0.1, prev[2], prev[1] - 0.2))  # misses the upper wick
    assert fired(Engulfing().compute(data(rows))) == []


def test_engulfing_volume_contraction_is_checked_only_where_the_venue_has_volume():
    rows = [*FLAT, *fading_leg()]
    rows.append(bullish_engulf(rows[-1]))
    p = EngulfingParams(volume_contraction=True)
    rising_volume = [1.0] * len(FLAT) + [1, 1, 1, 2, 3, 4, 5, 6] + [9.0]
    assert fired(Engulfing(p).compute(data(rows, rising_volume))) == []
    shrinking = [1.0] * len(FLAT) + [9, 8, 7, 6, 4, 3, 2, 1] + [9.0]
    assert len(fired(Engulfing(p).compute(data(rows, shrinking)))) == 1
    flat = [1.0] * len(rows)  # flat volume is not shrinking volume
    assert fired(Engulfing(p).compute(data(rows, flat))) == []
    assert len(fired(Engulfing(p).compute(data(rows, flat, "none")))) == 1  # no volume: ignored


# ------------------------------------------------------ giant indecision reversal
RISING = [(100 + 0.1 * k, 100.6 + 0.1 * k, 99.5 + 0.1 * k, 100.1 + 0.1 * k) for k in range(25)]
LAST = RISING[-1][3]
GIANT = (LAST, LAST + 5.0, LAST - 0.7, LAST - 0.6)  # a giant upper wick, a small body


def test_a_giant_upper_wick_bar_after_an_up_move_triggers_a_short_below_its_low():
    rows = [*RISING, GIANT]
    vol = [1.0] * 25 + [5.0]
    out = GiantIndecisionReversal(GiantIndecisionParams(htf="lwc")).compute(data(rows, vol))
    assert fired(out) == [25] and out.direction[25] == -1
    assert out.trigger[25] == GIANT[2]  # beyond the opposite side of the candle
    assert out.invalidation[25] == out.stop[25] == GIANT[1]  # the extreme wick tip


def test_a_giant_lower_wick_bar_after_a_down_move_makes_a_long():
    mirror = [(200.0 - o, 200.0 - lo, 200.0 - h, 200.0 - c) for o, h, lo, c in [*RISING, GIANT]]
    out = GiantIndecisionReversal(GiantIndecisionParams(htf="lwc")).compute(
        data(mirror, [1.0] * 25 + [5.0])
    )
    assert fired(out) == [25] and out.direction[25] == 1
    assert out.trigger[25] == mirror[25][1] and out.stop[25] == mirror[25][2]


@pytest.mark.parametrize("what", ["volume", "range", "body", "trend", "htf"])
def test_giant_indecision_needs_range_volume_a_small_body_a_trend_and_htf_weakness(what: str):
    rows, vol, p = [*RISING, GIANT], [1.0] * 25 + [5.0], {"htf": "lwc"}
    if what == "volume":
        vol = [1.0] * 24 + [9.0, 5.0]  # an earlier bar had more volume
    if what == "range":
        bigger = (LAST, LAST + 8.0, LAST - 0.7, LAST - 0.6)  # the previous bar was bigger
        rows = [*RISING[:-1], bigger, GIANT]
    if what == "body":
        rows = [*RISING, (LAST, LAST + 5.0, LAST - 0.1, LAST + 3.0)]  # a big body
    if what == "trend":
        rows = [(100.0, 100.6, 99.4, 100.0)] * 25 + [(100.0, 105.0, 99.3, 99.4)]  # no move before
    if what == "htf":
        rows = [*RISING, (LAST, LAST + 5.0, LAST - 0.7, LAST + 0.3)]  # the close stays above SMA 7
    assert fired(GiantIndecisionReversal(GiantIndecisionParams(**p)).compute(data(rows, vol))) == []
    off = GiantIndecisionParams(htf="lwc", require_htf_weakness=False)
    if what == "htf":
        assert fired(GiantIndecisionReversal(off).compute(data(rows, vol))) == [25]


# ------------------------------------------------------------- absorption wick
QUIET = [(100.0, 100.8, 99.2, 100.1)] * 25


def test_a_wick_through_support_that_closes_back_inside_triggers_above_its_high():
    wick = (100.2, 100.6, 98.5, 100.4)
    out = AbsorptionWick().compute(data([*QUIET, wick]))
    assert fired(out) == [25] and out.direction[25] == 1
    assert (out.trigger[25], out.stop[25]) == (100.6, 98.5)
    assert out.meta["level"][25] == 99.2  # the pierced support


def test_a_wick_through_resistance_that_closes_back_inside_shorts():
    wick = (100.0, 101.9, 99.8, 99.7)
    out = AbsorptionWick().compute(data([*QUIET, wick]))
    assert fired(out) == [25] and out.direction[25] == -1
    assert (out.trigger[25], out.stop[25]) == (99.8, 101.9)


def test_a_close_below_support_or_no_pierce_is_not_absorption():
    assert fired(AbsorptionWick().compute(data([*QUIET, (100.2, 100.6, 98.5, 98.9)]))) == []
    assert fired(AbsorptionWick().compute(data([*QUIET, (100.2, 100.6, 99.4, 100.4)]))) == []
    deep = AbsorptionWickParams(min_pierce_atr=5.0)
    assert fired(AbsorptionWick(deep).compute(data([*QUIET, (100.2, 100.6, 98.5, 100.4)]))) == []


# --------------------------------------------------------------------- the LA
IMPULSE = leg(80, 100, 8)
LA_ROWS = (
    IMPULSE + leg(100, 110, 3) + leg(110, 100, 5) + leg(100, 110, 3) + leg(110, 103, 5)
    + leg(103, 110, 3) + leg(110, 103, 5) + leg(103, 110, 3) + leg(110, 104, 5)
)  # fmt: skip
LA = LayeredParams(
    timeframe="lwc", min_bars=4, min_touches=2, min_bottom_touches=2, refresh_bars=1,
    tolerance_atr=2.0,
)  # fmt: skip


def test_the_la_waits_above_the_ceiling_with_its_stop_under_the_inner_higher_low():
    out = LayeredSetup(LA).compute(data(LA_ROWS))
    first = fired(out)[0]
    assert out.direction[first] == 1
    assert out.trigger[first] == 110.0  # the ceiling (the execution adds the buffer)
    assert out.invalidation[first] == pytest.approx(100.0, abs=2.0)  # the box bottom
    assert out.stop[first] == pytest.approx(102.8)  # under the higher low at 103
    assert out.stop[first] > out.invalidation[first]


def test_the_la_needs_an_impulse_a_higher_low_and_faster_pushes_up():
    weak = LA.model_copy(update={"impulse_atr": 50.0})  # the move into the box is not an impulse
    assert fired(LayeredSetup(weak).compute(data(LA_ROWS))) == []
    equal = (
        IMPULSE + leg(100, 110, 5) + leg(110, 100, 5) + leg(100, 110, 5) + leg(110, 103, 5)
        + leg(103, 110, 5) + leg(110, 103, 5) + leg(103, 110, 5) + leg(110, 104, 5)
    )  # fmt: skip
    assert fired(LayeredSetup(LA).compute(data(equal))) == []  # the pushes up are not faster
    lowers = IMPULSE + box(4)[2:]  # a box whose bottom never lifts
    assert fired(LayeredSetup(LA).compute(data(lowers))) == []


def test_the_la_short_mirrors_the_long():
    mirror = [(200.0 - o, 200.0 - lo, 200.0 - h, 200.0 - c) for o, h, lo, c in LA_ROWS]
    p = LA.model_copy(update={"side": "short"})
    out = LayeredSetup(p).compute(data(mirror))
    first = fired(out)[0]
    assert out.direction[first] == -1 and out.trigger[first] == 90.0
    assert out.stop[first] == pytest.approx(200.0 - 102.8)


# ---------------------------------------------------------------- Dow continuation
UP = (
    leg(90, 100, 4) + leg(100, 95, 3) + leg(95, 110, 4) + leg(110, 104, 3) + leg(104, 120, 5)
    + leg(120, 114, 3) + leg(114, 130, 5) + leg(130, 126, 3) + leg(126, 140, 5)
)  # fmt: skip
DOW = DowContinuationParams(timeframe="lwc")


def test_a_break_of_the_last_swing_in_an_uptrend_stops_beyond_the_previous_swing():
    out = DowContinuation(DOW).compute(data(UP))
    idx = fired(out)
    assert idx and set(out.direction[idx]) == {1}
    first = idx[0]
    assert out.invalidation[first] < out.trigger[first]  # the broken swing high is below the break
    assert out.stop[first] < out.invalidation[first]  # and the previous swing low below that
    assert out.trigger[first] == UP[first][1]  # the break bar's high
    # the window ends once the closes come back, never before the break itself
    assert all(out.direction[i] == 1 for i in range(idx[0], idx[0] + 1))


def test_a_down_trend_makes_shorts_and_a_range_makes_nothing():
    mirror = [(300.0 - o, 300.0 - lo, 300.0 - h, 300.0 - c) for o, h, lo, c in UP]
    out = DowContinuation(DOW).compute(data(mirror))
    assert fired(out) and set(out.direction[fired(out)]) == {-1}
    assert fired(DowContinuation(DOW).compute(data(box(4)))) == []


def test_the_first_break_of_a_new_trend_is_not_a_continuation():
    rows = leg(100, 90, 4) + leg(90, 95, 3) + leg(95, 85, 4) + leg(85, 100, 6)  # a reversal break
    out = DowContinuation(DOW).compute(data(rows))
    assert all(out.direction[i] != 1 for i in range(len(rows) - 6))


# --------------------------------------------------------- the binary scenario
def binary_doc() -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["timeframes"] = {"hwc": "M15", "mwc": "M15", "lwc": "M15"}
    side = lambda s: {  # noqa: E731
        "kind": "setup",
        "type": "binary_scenario",
        "params": {"timeframe": "lwc", "side": s, "min_bars": 4},
    }
    raw["blocks"] = [
        {"kind": "context", "type": "wave_cycles", "params": {"two_way_box": True}},
        side("long"),
        side("short"),
        {
            "kind": "execution",
            "type": "stop_market",
            "params": {"buffer_pct": 0.05, "expiry_bars": 8, "oco": True},
        },
        {"kind": "stop", "type": "structural_stop", "params": {"buffer_pct": 0.05}},
        {"kind": "exit", "type": "profit_chain"},
    ]
    raw["risk"] = {"risk_per_trade": 0.005, "max_positions_per_symbol": 2}
    return raw


def test_the_binary_scenario_arms_both_sides_of_a_box_once():
    d = data(box(5))
    long_ = BinaryScenario(BinaryScenarioParams(timeframe="lwc", min_bars=4)).compute(d)
    short = BinaryScenario(BinaryScenarioParams(timeframe="lwc", min_bars=4, side="short")).compute(
        d
    )
    assert len(fired(long_)) == 1 and fired(long_) == fired(short)  # one pair per box
    i = fired(long_)[0]
    assert (long_.direction[i], short.direction[i]) == (1, -1)
    assert (long_.trigger[i], long_.stop[i]) == (110.0, 100.0)
    assert (short.trigger[i], short.stop[i]) == (100.0, 110.0)
    again = BinaryScenario(BinaryScenarioParams(timeframe="lwc", min_bars=4, refresh_bars=4))
    assert len(fired(again.compute(d))) > 1  # a refresh interval re-arms it


def test_the_binary_scenario_pair_is_oco_through_the_harness():
    journal = Journal()
    out = run(box(5), binary_doc(), PERP, journal)
    placed = [c for c in out.candidates if c["decision"] == "placed"]
    assert {c["direction"] for c in placed} == {1, -1}
    events = [e for r in journal.records("cycle") for e in r["orders"]]
    assert [e for e in events if e["e"] == "cancel" and e.get("reason") == "oco"]
    assert len([e for e in events if e["e"] == "fill"]) < len(
        [e for e in events if e["e"] == "place"]
    )


# ----------------------------------------------------------- momentum continuation
def surge() -> list[Row]:
    return [(100.0 + k, 101.2 + k, 99.9 + k, 101.0 + k) for k in range(30)]


def test_a_pullback_to_the_short_sma_in_strong_momentum_triggers():
    rows = surge()
    c = rows[-1][3]
    rows.append((c, c + 0.3, c - 3.0, c + 0.1))  # dips to the 7 SMA and closes back above
    out = MomentumContinuation().compute(data(rows))
    i = len(rows) - 1
    assert i in fired(out) and out.direction[i] == 1
    assert (out.trigger[i], out.stop[i]) == (rows[i][1], rows[i][2])


def test_without_strong_momentum_on_every_listed_timeframe_nothing_fires():
    rows = [(100.0, 100.6, 99.4, 100.0), (100.0, 100.5, 99.5, 100.3)] * 20  # a quiet chop
    assert fired(MomentumContinuation().compute(data(rows))) == []
    one_fails = MomentumContinuationParams(rsi_long=99.9)
    assert fired(MomentumContinuation(one_fails).compute(data(surge()))) == []


def test_prior_high_mode_takes_each_bar_breaking_the_prior_extreme_and_shorts_mirror():
    p = MomentumContinuationParams(micro="prior_high")
    out = MomentumContinuation(p).compute(data(surge()))
    assert len(fired(out)) > 5 and set(out.direction[fired(out)]) == {1}
    mirror = [(200.0 - o, 200.0 - lo, 200.0 - h, 200.0 - c) for o, h, lo, c in surge()]
    down = MomentumContinuation(p).compute(data(mirror))
    assert len(fired(down)) > 5 and set(down.direction[fired(down)]) == {-1}


def test_momentum_roles_are_validated():
    with pytest.raises(ValueError):
        MomentumContinuationParams(roles=["h4"])


# ------------------------------------------------------------------ chase guard
def with_big(rows: list[Row], up: bool = True) -> list[Row]:
    c = rows[-1][3]
    big = (c, c + 6.0, c - 0.2, c + 5.8) if up else (c, c + 0.2, c - 6.0, c - 5.8)
    return [*rows, big]


QUIET_RISE = [(100 + 0.1 * k, 100.6 + 0.1 * k, 99.9 + 0.1 * k, 100.5 + 0.1 * k) for k in range(30)]


def test_an_outsized_up_bar_refuses_new_longs_but_not_shorts():
    rows = with_big(QUIET_RISE)
    out = ChaseGuard(ChaseGuardParams(timeframe="lwc")).compute(data(rows))
    i = len(rows) - 1
    assert not out.long_ok[i] and out.short_ok[i] and out.long_ok[i - 1]
    assert out.flags["outsized"][i] and not out.flags["outsized"][i - 1]
    assert out.cancels_orders is None  # resting orders anchored before the bar are kept


def test_both_directions_or_a_longer_cooldown_widen_the_refusal():
    rows = [*with_big(QUIET_RISE), *QUIET_RISE[:3]]
    i = len(rows) - 4
    both = ChaseGuard(ChaseGuardParams(timeframe="lwc", same_direction_only=False))
    out = both.compute(data(rows))
    assert not out.long_ok[i] and not out.short_ok[i]
    cool = ChaseGuard(ChaseGuardParams(timeframe="lwc", cooldown_bars=3)).compute(data(rows))
    assert [bool(x) for x in cool.long_ok[i : i + 4]] == [False, False, False, True]
    short_cool = ChaseGuard(ChaseGuardParams(timeframe="lwc")).compute(data(rows))
    assert short_cool.long_ok[i + 1]  # the default cooldown is the bar itself


def test_a_normal_bar_never_trips_the_guard_and_the_multiple_is_a_parameter():
    out = ChaseGuard(ChaseGuardParams(timeframe="lwc")).compute(data(QUIET_RISE))
    assert out.long_ok.all() and out.short_ok.all()
    rows = with_big(QUIET_RISE)
    loose = ChaseGuardParams(timeframe="lwc", multiple=50.0)
    assert ChaseGuard(loose).compute(data(rows)).long_ok.all()


def test_the_guard_refuses_a_candle_setup_on_an_outsized_bar_through_the_harness():
    guarded = copy.deepcopy(DOC)
    guarded["blocks"].insert(
        1,
        {
            "kind": "context",
            "type": "chase_guard",
            "params": {"timeframe": "lwc", "multiple": 3.0, "lookback": 5},
        },
    )
    rows = [*RISE, SETUP]  # the setup bar's 5.3 range is far above the 1.2 of the quiet bars
    plain = [c for c in run_engine(rows)[0].candidates if c["decision"] == "placed"]
    assert plain  # without the guard the candidate is placed
    out = run_engine(rows, guarded)[0]
    assert not [c for c in out.candidates if c["decision"] == "placed"]
    assert any("chase_guard" in str(c.get("refused", c)) for c in out.candidates)


# ------------------------------------------------- causality, determinism, scale
def rich_rows() -> list[Row]:
    """Every setup's pattern twice, each after its own quiet lead-in."""
    engulf = [*FLAT, *fading_leg()]
    engulf.append(bullish_engulf(engulf[-1]))
    segments = [
        engulf, [*QUIET, (100.2, 100.6, 98.5, 100.4)], [*RISING, GIANT], UP, LA_ROWS, surge(),
        with_big(QUIET_RISE), box(5),
    ]  # fmt: skip
    return [row for seg in segments * 2 for row in seg]


BLOCKS: list[Any] = [
    Engulfing(),
    GiantIndecisionReversal(
        GiantIndecisionParams(
            htf="lwc", require_htf_weakness=False, range_factor=0.5, volume_factor=0.2
        )
    ),
    AbsorptionWick(),
    LayeredSetup(LA),
    DowContinuation(DOW),
    BinaryScenario(BinaryScenarioParams(timeframe="lwc", min_bars=4, refresh_bars=3)),
    MomentumContinuation(MomentumContinuationParams(micro="either")),
]


@pytest.mark.parametrize("block", BLOCKS, ids=lambda b: b.type)
def test_setups_never_look_ahead_are_deterministic_and_scale_free(block: Any):
    rows = rich_rows()
    d = data(rows)
    full = block.compute(d)
    assert len(fired(full)) >= 2, "the fixture must produce candidates to gate"
    for n in (60, 100, len(rows) - 7):
        part = block.compute(d.head(n))
        assert np.array_equal(part.direction, full.direction[:n])
        for name in ("trigger", "invalidation", "stop"):
            assert np.array_equal(getattr(part, name), getattr(full, name)[:n], equal_nan=True), (
                name
            )
    assert np.array_equal(block.compute(data(rows)).direction, full.direction)
    big = block.compute(d.scaled(1000.0))
    assert np.array_equal(big.direction, full.direction)
    assert np.allclose(big.trigger, full.trigger * 1000.0, equal_nan=True)
    assert np.allclose(big.stop, full.stop * 1000.0, equal_nan=True)


def test_the_chase_guard_never_looks_ahead():
    rows = rich_rows()
    d = data(rows)
    block = ChaseGuard(ChaseGuardParams(timeframe="lwc", cooldown_bars=2))
    full = block.compute(d)
    assert not full.long_ok.all()
    for n in (60, 100, len(rows) - 7):
        part = block.compute(d.head(n))
        assert np.array_equal(part.long_ok, full.long_ok[:n])
        assert np.array_equal(part.short_ok, full.short_ok[:n])


# ------------------------------------------------------------------ the Template
NEW = [
    "engulfing", "giant_indecision", "absorption_wick", "layered_setup", "dow_continuation",
    "binary_scenario", "momentum_continuation", "chase_guard",
]  # fmt: skip


def test_the_template_carries_every_new_block_disabled_with_its_blueprint_source():
    from nnfx.strategy import get_template

    tcp = get_template("tcp_azizpour")
    rows = {b.type: (b, s) for b, s in zip(tcp.document.blocks, tcp.sources, strict=True)}
    for t in NEW:
        block, source = rows[t]
        assert not block.enabled and source.videos, t
    sides = [b.params["side"] for b in tcp.document.blocks if b.type == "binary_scenario"]
    assert sides == ["long", "short"]


@pytest.mark.parametrize("which", NEW)
def test_a_clone_with_a_new_block_switched_on_still_validates_and_runs(which: str):
    from nnfx.strategy import get_template, validate_document
    from nnfx.strategy.run import backtest_document

    raw = get_template("tcp_azizpour").clone("on")
    for b in raw["blocks"]:
        if b["type"] == which:
            b["enabled"] = True
    raw["universe"] = [BTC.symbol]
    res = validate_document(raw)
    assert res.document is not None, res.render()
    rows = [
        (100.0 + 0.01 * k, 100.5 + 0.01 * k, 99.5 + 0.01 * k, 100.1 + 0.01 * k) for k in range(300)
    ]
    out = backtest_document(res.document, {BTC.symbol: frame(rows)}, {BTC.symbol: BTC})
    assert out.result.trades is not None
