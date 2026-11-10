"""The oscillator Blocks (Strategy Builder ticket 15): fire / no-fire fixtures per method.

Each fixture is a close path chosen to put RSI where the method looks; the Blocks
are judged by calling ``check`` on a hand-made candidate at each bar.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.strategy import REGISTRY, StrategyData
from nnfx.strategy.blocks import (
    TRIGGER_KINDS,
    Block,
    BlockKind,
    SetupCandidate,
    block_catalogue,
    register,
)
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from nnfx.strategy.oscillators import (
    CascadeParams,
    DivergenceParams,
    MultiplierParams,
    OscDivergence,
    OscInflection,
    OscInflectionParams,
    OscLevelBreak,
    OscMomentum,
    OscMomentumParams,
    OscMultiplier,
    OscRecalibrated,
    OscSignalCross,
    OscSignalCrossParams,
    RecalibratedParams,
    RsiBollingerParams,
    RsiBollingerReentry,
    RsiCascade,
    cycle_period,
    multiplier_factor,
    oscillator,
)
from tests.test_strategy_engine import BTC, frame

ROLES = {"hwc": "M15", "mwc": "M15", "lwc": "M15", "management": "M15"}
METHODS = {
    "osc_momentum", "osc_inflection", "osc_signal_cross", "osc_level_break", "rsi_bb_reentry",
    "osc_recalibrated", "osc_mf", "osc_divergence", "rsi_cascade",
}  # fmt: skip


def rows_of(closes: list[float]) -> list[tuple[float, float, float, float]]:
    """Bars whose body runs from the previous close; wicks are small and never tie."""
    rng = np.random.default_rng(7)
    out, prev = [], closes[0]
    for c in closes:
        up, down = 0.02 + 0.03 * rng.random(2)
        out.append((prev, max(prev, c) + up, min(prev, c) - down, c))
        prev = c
    return out


def data(closes: list[float], roles: dict[str, str] | None = None) -> StrategyData:
    return StrategyData.build(frame(rows_of(closes)), roles or ROLES, BTC, SessionConfig())


def cand(d: StrategyData, bar: int, direction: int = 1) -> SetupCandidate:
    c = float(d.base.close[bar])
    return SetupCandidate(
        "X", "candle_setup", 0, bar, d.base.index[bar].isoformat(), direction, c, c - direction, c - direction
    )  # fmt: skip


def outcomes(block: Any, d: StrategyData, direction: int = 1, start: int = 0) -> list[str]:
    return [block.check(cand(d, i, direction), d).outcome for i in range(start, len(d))]


def ramp(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + step * k for k in range(n)]


FLAT = [100.0 + (0.3 if k % 2 else -0.3) for k in range(40)]
UP = [FLAT[-1] + 1.5 * (k + 1) for k in range(30)]
DOWN = [FLAT[-1] - 1.5 * (k + 1) for k in range(30)]


# ------------------------------------------------------------ the rule
def test_every_method_is_a_flat_oscillator_confirmation():
    assert set(REGISTRY) >= METHODS
    catalogue = {b["type"]: b for b in block_catalogue()}
    for t in METHODS:
        cls = REGISTRY[t]
        assert cls.kind == BlockKind.CONFIRMATION and cls.oscillator
        assert catalogue[t]["oscillator"] is True
        schema = catalogue[t]["params"]
        assert "$defs" not in schema
        for name, prop in schema["properties"].items():
            assert prop.get("description"), f"{t}.{name}"


@pytest.mark.parametrize("kind", sorted(TRIGGER_KINDS, key=str))
def test_the_registry_refuses_an_oscillator_in_a_trigger_role(kind: BlockKind):
    from nnfx.strategy.blocks import BASES

    class Rogue(BASES[kind]):  # type: ignore[misc]
        pass

    Rogue.kind, Rogue.type, Rogue.title_fa, Rogue.oscillator = kind, "rogue_osc", "x", True
    with pytest.raises(TypeError, match="never triggers"):
        register(Rogue)
    assert "rogue_osc" not in REGISTRY


def test_no_registered_oscillator_is_a_setup_or_execution_block():
    for cls in REGISTRY.values():
        if cls.oscillator:
            assert cls.kind not in TRIGGER_KINDS
    assert not any(
        c.oscillator for c in REGISTRY.values() if issubclass(c, Block) and c.kind in TRIGGER_KINDS
    )


# ------------------------------------------------------------ method 1
def test_momentum_passes_when_rsi_has_just_entered_overbought_for_a_long():
    d = data(FLAT + UP)
    out = outcomes(OscMomentum(OscMomentumParams(fresh_bars=3)), d)
    assert "pass" in out[len(FLAT) :]
    assert set(out[: len(FLAT)]) <= {"fail", "na"}  # flat bars: never
    first = out.index("pass")
    assert first > len(FLAT)  # it takes several up bars to reach 70
    assert out[-1] == "fail"  # long since in the zone: not fresh any more
    assert outcomes(OscMomentum(OscMomentumParams(fresh_bars=0)), d)[-1] == "pass"


def test_momentum_for_a_short_mirrors_it():
    d = data(FLAT + DOWN)
    assert "pass" in outcomes(OscMomentum(), d, direction=-1)
    assert "pass" not in outcomes(OscMomentum(), d, direction=1)


def test_unbounded_oscillators_use_rolling_extremes_of_the_bars_before():
    closes = [100.0 + 0.5 * np.sin(k / 3) for k in range(250)] + [
        101.0 + 4.0 * k for k in range(1, 8)
    ]
    d = data(closes)
    o = oscillator(d, "lwc", "roc", 3, overbought=70, oversold=30, window=200, fraction=0.8)
    v = o.value
    for i in (100, 220, 255):
        prior = v[max(0, i - 200) : i]
        assert o.hi[i] == pytest.approx(0.8 * np.nanmax(prior))
        assert o.lo[i] == pytest.approx(0.8 * np.nanmin(prior))
    block = OscMomentum(OscMomentumParams(osc="roc", period=3, fresh_bars=0))
    out = outcomes(block, d)
    assert out[-1] == "pass"  # the jump is far beyond anything in the last 200 bars


# ------------------------------------------------------------ method 2
def test_inflection_is_the_side_of_50_and_can_demand_a_fresh_cross():
    d = data(
        FLAT + DOWN[:15] + [DOWN[14] + 2.0 * (k + 1) for k in range(30)]
    )  # falls, then rises through 50
    side = outcomes(OscInflection(), d)
    assert side[-1] == "pass" and "fail" in side
    assert outcomes(OscInflection(OscInflectionParams(cross_bars=2)), d)[-1] == "fail"
    shifted = OscInflection(
        OscInflectionParams(offset=-100.0)
    )  # the line moved to -50: always above
    assert set(outcomes(shifted, d)[20:]) == {"pass"}
    o = oscillator(d, "lwc", "cci", 14, overbought=70, oversold=30, window=200, fraction=0.8)
    assert o.mid == 0.0


# ------------------------------------------------------------ method 3
def test_signal_cross_counts_only_in_the_extreme_zone_or_through_the_midline():
    crash = FLAT + DOWN + [DOWN[-1] + 1.0 * (k + 1) for k in range(10)]
    d = data(crash)
    extreme = OscSignalCross(OscSignalCrossParams(zone="extreme", zone_margin=0.5))
    assert "pass" in outcomes(extreme, d)
    chop = data([100.0 + (3.0 if (k // 2) % 2 else -3.0) for k in range(80)])
    assert "pass" not in outcomes(OscSignalCross(OscSignalCrossParams(zone="extreme")), chop)
    assert "pass" not in outcomes(OscSignalCross(OscSignalCrossParams(zone="extreme")), chop, -1)


# ------------------------------------------------------------ method 4
def test_the_oscillator_breaks_its_own_level_before_it_is_stale():
    rally = (
        FLAT
        + UP[:10]
        + [UP[9] - 1.0 * k for k in range(1, 8)]
        + [UP[9] - 7 + 1.4 * k for k in range(1, 20)]
    )
    d = data(rally)
    out = outcomes(OscLevelBreak(), d)
    assert "pass" in out
    assert "pass" not in outcomes(OscLevelBreak(), data(FLAT + DOWN))  # nothing to break upward


# ------------------------------------------------------------ method 5
def reentry_path() -> list[float]:
    wave = FLAT + [FLAT[-1] + 2.0 * (k + 1) for k in range(12)]
    pull = [wave[-1] - 0.8 * (k + 1) for k in range(8)]
    return wave + pull + [pull[-1] + 1.6 * (k + 1) for k in range(8)]


def test_rsi_curling_back_over_its_bollinger_middle_after_an_impulse():
    d = data(reentry_path())
    block = RsiBollingerReentry(RsiBollingerParams(cross_bars=2))
    out = outcomes(block, d)
    assert "pass" in out
    assert "pass" not in outcomes(block, d, direction=-1)
    assert "pass" not in outcomes(RsiBollingerReentry(), data(FLAT))


def test_the_dip_variant_wants_the_lower_band_first():
    path = FLAT + DOWN[:12] + [FLAT[-1] - 18 + 1.8 * (k + 1) for k in range(14)]
    d = data(path)
    dip = RsiBollingerReentry(RsiBollingerParams(mode="dip", cross_bars=3))
    assert "pass" in outcomes(dip, d)
    assert "pass" not in outcomes(
        RsiBollingerReentry(RsiBollingerParams(mode="impulse")), data(DOWN)
    )


# ------------------------------------------------------------ method 6
def sine(period: int, n: int, base: float = 100.0, amp: float = 3.0) -> list[float]:
    return [base + amp * np.sin(2 * np.pi * k / period) for k in range(n)]


def test_the_period_is_the_mean_swing_to_swing_distance():
    p = RecalibratedParams(pivot_bars=2, swings=4, structure_pivot_bars=2)
    d = data(sine(10, 120))
    period, cycles = cycle_period(d, p, 118, 1)
    assert period == 10 and cycles == 4
    short = sine(10, 40) + sine(20, 160)
    d2 = data(short)
    assert cycle_period(d2, p, len(short) - 3, 1)[0] == 20  # the 10-bar cycles are forgotten


def test_the_base_period_stands_without_enough_cycles():
    p = RecalibratedParams()
    d = data(ramp(60))
    assert cycle_period(d, p, 59, 1) == (14, 0)
    out = outcomes(OscRecalibrated(RecalibratedParams(fresh_bars=0)), d)
    assert out[-1] == "pass"  # a pure ramp: RSI 100


def test_recalibrated_check_names_its_period():
    d = data(sine(10, 120) + ramp(30, 100.0, 2.0))
    res = OscRecalibrated(RecalibratedParams(pivot_bars=2, structure_pivot_bars=2)).check(
        cand(d, len(d) - 1), d
    )
    assert "RSI(" in res.reason


# ------------------------------------------------------------ method 7
def test_mf_is_the_ratio_of_the_timeframes_in_minutes():
    d = data(ramp(10), {"hwc": "H4", "mwc": "H4", "lwc": "M15", "management": "H4"})
    assert multiplier_factor(d, "mwc") == 16
    assert multiplier_factor(data(ramp(10)), "mwc") == 1


def test_mf_scales_the_period_and_waits_for_enough_bars():
    d = data(ramp(300), {"hwc": "H1", "mwc": "H1", "lwc": "M15", "management": "H1"})
    block = OscMultiplier(MultiplierParams(base_period=14))  # 14 x 4 = 56 bars
    out = outcomes(block, d)
    assert set(out[:50]) == {"na"} and out[-1] == "pass"
    assert "RSI(14x4=56)" in block.check(cand(d, 299), d).reason
    assert outcomes(block, d, direction=-1)[-1] == "fail"


# ------------------------------------------------------------ method 8
DIV_REGULAR = (
    [100.0 + 0.2 * (k % 2) for k in range(20)]
    + [100.0 - 2.0 * (k + 1) for k in range(10)]  # first low 80 (RSI deep oversold)
    + [80.0 + 2.5 * (k + 1) for k in range(8)]
    + [100.0 - 1.1 * (k + 1) for k in range(16)]  # lower low 82.4? no: 100 - 17.6 = 82.4 (higher)
)


def test_regular_and_hidden_divergence_need_a_pivot_in_the_extreme_zone():
    # Regular bullish: price LL 79, RSI HL (the slower second leg).
    path = (
        FLAT
        + [100.0 - 2.0 * (k + 1) for k in range(10)]
        + [80.0 + 2.5 * (k + 1) for k in range(8)]
        + [100.0 - 1.1 * (k + 1) for k in range(19)]
        + [79.1 + 1.0 * (k + 1) for k in range(8)]
    )
    d = data(path)
    reg = OscDivergence(DivergenceParams(form="regular", pivot_bars=3, fresh_bars=20))
    out = outcomes(reg, d)
    assert "pass" in out
    # Neutral territory is discarded: the same shapes at a gentle slope never reach 30.
    gentle = (
        FLAT
        + [100.0 - 0.3 * (k + 1) for k in range(10)]
        + [97.0 + 0.4 * (k + 1) for k in range(8)]
        + [100.2 - 0.18 * (k + 1) for k in range(19)]
        + [96.8 + 0.2 * (k + 1) for k in range(8)]
    )
    assert "pass" not in outcomes(reg, data(gentle))
    assert "pass" not in outcomes(reg, d, direction=-1)


def hidden_path() -> list[float]:
    """A mild first low (RSI ~42), then a sharp drop to a slightly higher price low (RSI lower)."""
    x, drift = FLAT[-1], []
    for k in range(30):
        x += -1.2 if k % 2 == 0 else 0.8
        drift.append(x)
    bounce = [drift[-1] + 2.5 * (k + 1) for k in range(7)]
    drop = [bounce[-1] - (bounce[-1] - 93.5) / 5 * (k + 1) for k in range(5)]
    return FLAT + drift + bounce + drop + [drop[-1] + 1.5 * (k + 1) for k in range(8)]


def test_hidden_divergence_is_price_higher_low_with_a_deeper_oscillator_low():
    d = data(hidden_path())
    hidden = DivergenceParams(form="hidden", pivot_bars=2, fresh_bars=20, oversold=45.0)
    assert "pass" in outcomes(OscDivergence(hidden), d)
    regular = DivergenceParams(form="regular", pivot_bars=2, fresh_bars=20, oversold=45.0)
    assert "pass" not in outcomes(OscDivergence(regular), d)
    # With the default 30 the pivots are in neutral territory: discarded.
    neutral = DivergenceParams(form="hidden", pivot_bars=2, fresh_bars=20)
    assert "pass" not in outcomes(OscDivergence(neutral), d)


# ------------------------------------------------------------ the cascade
CASCADE_ROLES = {"hwc": "H4", "mwc": "H1", "lwc": "M15", "management": "H1"}
QUIET = [100.0 + (0.3 if k % 2 else -0.3) for k in range(600)]
SURGE = QUIET + [QUIET[-1] + 0.4 * (k + 1) for k in range(500)]


def test_the_cascade_passes_on_the_role_that_has_just_entered_the_zone():
    d = data(SURGE, CASCADE_ROLES)
    block = RsiCascade(CascadeParams(roles=["lwc", "mwc", "hwc"], fresh_bars=3))
    out = [block.check(cand(d, i), d) for i in range(len(d))]
    passes = {r.reason.split()[2] for r in out if r.outcome == "pass"}
    assert "lwc" in passes and passes & {"mwc", "hwc"}
    assert "pass" not in outcomes(block, data(QUIET + QUIET, CASCADE_ROLES))
    assert "pass" not in outcomes(block, d, direction=-1)


def test_a_stretched_higher_role_alone_does_not_pass_when_sequential():
    roles = CASCADE_ROLES
    # Rises for a long time, then the LWC pulls back out of the zone while the H1/H4 stay in it.
    path = ramp(500, 100.0, 0.4) + [300.0 - 0.15 * k for k in range(60)]
    d = data(path, roles)
    seq = RsiCascade(CascadeParams(fresh_bars=1))
    loose = RsiCascade(CascadeParams(fresh_bars=1, sequential=False))
    s = outcomes(seq, d, start=500)
    assert s.count("pass") <= outcomes(loose, d, start=500).count("pass")


# ------------------------------------------------------------ the exit
def rsi_peak_path() -> list[float]:
    """Quiet, a surge that pushes RSI out of its band, then a pullback."""
    surge = [FLAT[-1] + 3.0 * (k + 1) for k in range(5)]
    return FLAT + surge + [surge[-1] - 2.0 * (k + 1) for k in range(10)]


def managed_closes(params: ProfitChainParams, filled: int, direction: int = 1) -> list[int]:
    from tests.test_strategy_blocks import position

    d = data(rsi_peak_path())
    c = cand(d, 30, direction)
    block = ProfitChain(params)
    pv = position(block, c, d, filled)
    out = []
    for j in range(35, len(d)):
        mv = block.manage(pv, d, j)
        if mv is not None and getattr(mv, "reason", "") == "rsi_bb_exhaustion":
            out.append(j)
    return out


def test_the_rsi_exhaustion_exit_closes_after_the_band_rejection_and_never_before_a_step():
    on = ProfitChainParams(rsi_exhaustion_exit=True, rsi_reject_bars=3)
    closes = managed_closes(on, filled=1)
    assert closes and min(closes) >= 45  # only after the surge, on the pullback
    assert managed_closes(on, filled=0) == []  # the 2R floor: nothing before a step has filled
    assert managed_closes(ProfitChainParams(), filled=1) == []  # off by default
    assert managed_closes(on, filled=1, direction=-1) == []  # a long's exhaustion is no short's


def test_the_cascade_hold_keeps_the_position_while_the_higher_role_is_still_stretched():
    on = ProfitChainParams(rsi_exhaustion_exit=True, rsi_reject_bars=3)
    hold = ProfitChainParams(rsi_exhaustion_exit=True, rsi_reject_bars=3, hold_while_rsi_role="lwc")
    free, held = managed_closes(on, filled=1), managed_closes(hold, filled=1)
    d = data(rsi_peak_path())
    rsi14 = d.rsi("lwc", 14)
    assert set(held) <= set(free)
    assert all(rsi14[j] <= 70 for j in held)  # never closed while RSI is beyond 70
    assert len(held) < len(free)  # and the fixture does have bars where the hold mattered


def test_parameter_validation_refuses_inconsistent_forms():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RecalibratedParams(min_period=50, max_period=10)
    for bad in ([], ["lwc", "lwc"]):
        with pytest.raises(ValidationError):
            CascadeParams(roles=bad)
    assert CascadeParams().sequential is False  # a missed entry may have pulled back already


def test_signal_cross_looks_past_a_newer_mid_zone_cross_to_an_older_valid_one():
    crash = FLAT + DOWN + [DOWN[-1] + 1.0 * (k + 1) for k in range(10)]
    d = data(crash)
    wide = OscSignalCross(OscSignalCrossParams(zone="extreme", zone_margin=0.5, cross_bars=12))
    narrow = OscSignalCross(OscSignalCrossParams(zone="extreme", zone_margin=0.5, cross_bars=3))
    assert outcomes(wide, d).count("pass") >= outcomes(narrow, d).count("pass")
