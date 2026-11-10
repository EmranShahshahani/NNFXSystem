"""Volume rules (Strategy Builder ticket 17): fire / no-fire fixtures per metric."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.config import SessionConfig
from nnfx.data.bars import BarFrame
from nnfx.strategy import REGISTRY
from nnfx.strategy.blocks import BlockKind, StrategyData, block_catalogue
from nnfx.strategy.library import ProfitChain, ProfitChainParams
from nnfx.strategy.volume import (
    EffortResult,
    EffortResultParams,
    LowVolumeDip,
    LowVolumeDipParams,
    VolumeClimax,
    VolumeClimaxParams,
    VolumeMatrix,
    VolumeMatrixParams,
    VolumeNode,
    VolumeNodeParams,
    climaxes,
    matrix_state,
    volume_profile,
    volume_ratio,
)
from tests.test_strategy_engine import BTC, SYM
from tests.test_strategy_oscillators import ROLES, cand

NEW = {"volume_matrix", "effort_result", "volume_climax", "low_volume_dip", "volume_node"}

Bar = tuple[float, float, float, float, float]  # open, high, low, close, volume


def quiet(n: int, vol: float = 100.0, level: float = 100.0) -> list[Bar]:
    """Bars with a range of 1 and a tiny body: the baseline every anomaly is judged against."""
    return [
        (level, level + 0.5, level - 0.5, level + (0.05 if k % 2 else -0.05), vol) for k in range(n)
    ]


def moving(vols: list[float], step: float, start: float = 100.0) -> list[Bar]:
    """One bar per volume, each closing ``step`` from the last, with a body and small wicks."""
    out, prev = [], start
    for v in vols:
        c = prev + step
        out.append((prev, max(prev, c) + 0.1, min(prev, c) - 0.1, c, v))
        prev = c
    return out


def data(bars: list[Bar], *, kind: str = "traded") -> StrategyData:
    a = np.asarray(bars)
    idx = pd.date_range(
        pd.Timestamp("2024-03-01", tz="UTC") + pd.Timedelta(minutes=15),
        periods=len(a),
        freq="15min",
    )
    df = pd.DataFrame(
        {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": a[:, 4]},
        index=idx,
    )
    f = BarFrame(df, SYM, timeframe="M15", volume_kind=kind, price_venue="x")  # type: ignore[arg-type]
    return StrategyData.build(f, ROLES, BTC, SessionConfig())


def verdict(block: Any, d: StrategyData, bar: int, direction: int = 1) -> str:
    return block.check(cand(d, bar, direction), d).outcome


# ----------------------------------------------------------- the registry
def test_the_volume_blocks_are_flat_confirmations_with_described_parameters():
    assert set(REGISTRY) >= NEW
    catalogue = {b["type"]: b for b in block_catalogue()}
    for t in NEW:
        assert REGISTRY[t].kind == BlockKind.CONFIRMATION
        schema = catalogue[t]["params"]
        assert "$defs" not in schema
        for name, prop in schema["properties"].items():
            assert prop.get("description"), f"{t}.{name}"


def test_no_volume_means_na_never_a_pass():
    d = data(quiet(60), kind="none")
    for t in NEW:
        assert verdict(REGISTRY[t](), d, 59) == "na", t


# ------------------------------------------------------------ the baseline
def test_volume_is_judged_against_the_bars_before_it_and_not_by_its_size():
    bars = quiet(30) + quiet(1, vol=400.0)
    r = volume_ratio(data(bars), "lwc", 20)
    assert np.isnan(r[10]) and r[30] == pytest.approx(4.0)
    big = [(o, h, lo, c, v * 1e6) for o, h, lo, c, v in bars]
    np.testing.assert_allclose(volume_ratio(data(big), "lwc", 20)[20:], r[20:])


# ------------------------------------------------------------- the matrix
RISING_ON_VOLUME = quiet(30) + moving([100] * 3 + [200] * 3, 1.5, 100.0)
RISING_ON_FADING_VOLUME = quiet(30) + moving([200] * 3 + [100] * 3, 1.5, 100.0)
FALLING_ON_FADING_VOLUME = quiet(30) + moving([200] * 3 + [100] * 3, -1.5, 100.0)
FALLING_ON_VOLUME = quiet(30) + moving([100] * 3 + [200] * 3, -1.5, 100.0)
MATRIX = VolumeMatrix(VolumeMatrixParams(bars=3))


@pytest.mark.parametrize(
    ("bars", "long", "short"),
    [
        (RISING_ON_VOLUME, "pass", "fail"),  # bullish confirmation
        (RISING_ON_FADING_VOLUME, "fail", "pass"),  # bearish divergence
        (FALLING_ON_VOLUME, "fail", "pass"),  # bearish confirmation
        (FALLING_ON_FADING_VOLUME, "pass", "fail"),  # bullish divergence: selling exhausted
    ],
    ids=["bull_confirm", "bear_divergence", "bear_confirm", "bull_divergence"],
)
def test_the_four_states_favour_one_side_and_block_the_other(bars, long, short):
    d = data(bars)
    last = len(d) - 1
    assert verdict(MATRIX, d, last, 1) == long
    assert verdict(MATRIX, d, last, -1) == short


def test_the_matrix_names_its_state_and_is_na_when_price_or_volume_is_flat():
    d = data(RISING_ON_FADING_VOLUME)
    assert "bearish divergence" in MATRIX.check(cand(d, len(d) - 1), d).reason
    flat = data(quiet(40))
    assert verdict(MATRIX, flat, 39) == "na"
    price, vol = matrix_state(flat, "lwc", 3, 0.1, 0.5)
    assert not price.any() and not vol.any()


def test_volume_drying_up_inside_a_box_is_not_weakness():
    d = data(RISING_ON_FADING_VOLUME)
    c = replace(cand(d, len(d) - 1), tags=("box_breakout",))
    assert MATRIX.check(c, d).outcome == "na"


# ---------------------------------------------------- effort against result
ABSORPTION = (100.0, 101.0, 99.0, 100.05, 400.0)  # four times the volume, a doji
VACUUM = (100.0, 102.7, 99.9, 102.5, 40.0)  # a big body on 40% of the volume
NORMAL = (100.0, 101.0, 99.0, 100.6, 100.0)
EFFORT = EffortResult()


def test_heavy_volume_with_a_compressed_body_is_absorption():
    d = data([*quiet(30), ABSORPTION])
    r = EFFORT.check(cand(d, 30), d)
    assert r.outcome == "fail" and "absorption" in r.reason


def test_a_big_body_on_light_volume_is_a_vacuum():
    d = data([*quiet(30), VACUUM])
    r = EFFORT.check(cand(d, 30), d)
    assert r.outcome == "fail" and "vacuum" in r.reason


def test_an_ordinary_bar_and_each_anomaly_filter():
    assert verdict(EFFORT, data([*quiet(30), NORMAL]), 30) == "pass"
    vac, absn = data([*quiet(30), VACUUM]), data([*quiet(30), ABSORPTION])
    only_absorption = EffortResult(EffortResultParams(anomaly="absorption"))
    only_vacuum = EffortResult(EffortResultParams(anomaly="vacuum"))
    assert verdict(only_absorption, vac, 30) == "pass" and verdict(only_vacuum, absn, 30) == "pass"
    assert verdict(only_absorption, absn, 30) == "fail" and verdict(only_vacuum, vac, 30) == "fail"


def test_an_anomaly_ages_out_after_fresh_bars_and_needs_history():
    d = data([*quiet(30), ABSORPTION, *quiet(3)])
    assert verdict(EFFORT, d, 31) == "pass"
    assert verdict(EffortResult(EffortResultParams(fresh_bars=2)), d, 31) == "fail"
    assert verdict(EFFORT, d, 5) == "na"


# ------------------------------------------------------------------ climax
BUYING = (100.0, 104.0, 99.5, 103.5, 400.0)  # 4x volume, 4x range, closes up
SELLING = (100.0, 100.5, 96.0, 96.5, 400.0)
CLIMAX = VolumeClimax()


def test_a_buying_climax_blocks_longs_and_a_selling_climax_blocks_shorts():
    up, down = data([*quiet(30), BUYING]), data([*quiet(30), SELLING])
    assert verdict(CLIMAX, up, 30, 1) == "fail" and verdict(CLIMAX, up, 30, -1) == "pass"
    assert verdict(CLIMAX, down, 30, -1) == "fail" and verdict(CLIMAX, down, 30, 1) == "pass"
    buying, selling = climaxes(up, "lwc", 20, 3.0, 1.8)
    assert buying[30] and not selling[30]


def test_volume_alone_or_range_alone_is_not_a_climax():
    loud = (100.0, 100.6, 99.6, 100.5, 400.0)  # volume without range
    wide = (100.0, 104.0, 99.5, 103.5, 150.0)  # range without volume
    for bar in (loud, wide):
        assert verdict(CLIMAX, data([*quiet(30), bar]), 30) == "pass"


def test_a_climax_ages_out_and_the_threshold_is_a_parameter():
    d = data([*quiet(30), BUYING, *quiet(4)])
    assert verdict(CLIMAX, d, 32) == "fail" and verdict(CLIMAX, d, 33) == "pass"
    mild = (100.0, 102.0, 99.5, 101.8, 250.0)  # 2.5x volume, 2.5x range
    m = data([*quiet(30), mild])
    assert verdict(CLIMAX, m, 30) == "pass"
    assert verdict(VolumeClimax(VolumeClimaxParams(factor=2.0, range_factor=2.0)), m, 30) == "fail"
    assert verdict(CLIMAX, data([*quiet(10), BUYING]), 10) == "na"


def test_the_profit_chain_takes_profit_on_a_climax_only_after_the_first_step():
    from tests.test_strategy_blocks import position

    d = data([*quiet(60), BUYING, *quiet(10)])
    on = ProfitChain(ProfitChainParams(climax_exit=True))
    off = ProfitChain()

    def reasons(block: ProfitChain, filled: int, direction: int = 1) -> set[str]:
        cc = cand(d, 30, direction)
        pv = position(block, cc, d, filled)
        return {getattr(block.manage(pv, d, j), "reason", "") for j in range(35, len(d))}

    assert "climax" in reasons(on, 1)
    assert "climax" not in reasons(on, 0)  # the 2R floor
    assert "climax" not in reasons(off, 1)
    assert "climax" not in reasons(on, 1, -1)  # a short does not sell the top


# ----------------------------------------------------------- low volume dip
DIP = (100.0, 100.4, 99.6, 100.0, 40.0)
LOW = LowVolumeDip(LowVolumeDipParams(bars=3))


def test_volume_sinking_to_a_multi_bar_low_just_before_the_candidate_passes():
    d = data([*quiet(30), DIP, *quiet(2)])
    assert verdict(LOW, d, 32) == "pass" and "low" in LOW.check(cand(d, 32), d).reason
    assert verdict(LOW, d, 31) == "pass"


def test_no_dip_a_stale_dip_or_the_dip_bar_itself_does_not_pass():
    assert verdict(LOW, data(quiet(40)), 39) == "fail"
    d = data([*quiet(30), DIP, *quiet(6)])
    assert verdict(LOW, d, 36) == "fail"  # beyond the three-bar window
    assert verdict(LOW, data([*quiet(30), DIP]), 30) == "fail"  # the dip is the candidate bar
    assert verdict(LOW, data(quiet(10)), 9) == "na"


def test_a_quiet_bar_that_is_not_a_lookback_low_is_no_dip():
    shallow = (100.0, 100.4, 99.6, 100.0, 70.0)  # 70% of the baseline: above the 0.6 limit
    d = data([*quiet(30), shallow, *quiet(2)])
    assert verdict(LOW, d, 32) == "fail"


# ------------------------------------------------------------------ profile
def test_the_profile_spreads_each_bars_volume_over_the_bins_it_touches():
    high, low = np.array([10.0, 20.0]), np.array([0.0, 15.0])
    edges, vol = volume_profile(high, low, np.array([100.0, 60.0]), 4)  # type: ignore[misc]
    np.testing.assert_allclose(edges, [0, 5, 10, 15, 20])
    assert vol.sum() == pytest.approx(160.0)
    # bar 1 covers bins 0-2 (high on an edge falls in the next bin: bins 0-2 of 4), bar 2 bins 3
    assert vol[3] == pytest.approx(60.0)
    assert volume_profile(np.array([5.0]), np.array([5.0]), np.array([1.0]), 4) is None


def node_data() -> StrategyData:
    low_region = [(105.0, 105.5, 104.5, 105.0, 50.0)] * 15
    heavy_region = [(109.0, 109.5, 108.5, 109.0, 500.0)] * 15
    return data(low_region + heavy_region)


def test_a_heavy_node_just_ahead_fails_a_long_and_not_a_short():
    d = node_data()
    block = VolumeNode(VolumeNodeParams(role="lwc", window=30, bins=12, lookback=5))
    long = replace(cand(d, 29, 1), trigger=108.0)
    r = block.check(long, d)
    assert r.outcome == "fail" and "108" in r.reason
    assert block.check(replace(cand(d, 29, -1), trigger=108.0), d).outcome == "pass"  # it is behind


def test_a_node_beyond_the_reach_does_not_block_and_short_history_is_na():
    d = node_data()
    block = VolumeNode(VolumeNodeParams(role="lwc", window=30, bins=12, lookback=5))
    assert block.check(replace(cand(d, 29, 1), trigger=107.0), d).outcome == "pass"
    wide = VolumeNode(VolumeNodeParams(role="lwc", window=30, bins=12, clear_atr=4.0, lookback=5))
    assert wide.check(replace(cand(d, 29, 1), trigger=107.0), d).outcome == "fail"
    assert block.check(cand(d, 10), d).outcome == "na"
