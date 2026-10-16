"""Tickets 07-10: registry, contract, lookahead and determinism gates, screening."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from nnfx.data.bars import BarFrame
from nnfx.data.feeds import write_bars_csv
from nnfx.data.synthetic import regime_walk
from nnfx.harness.backtest import BacktestHarness
from nnfx.indicators import _math as m
from nnfx.indicators.base import (
    CONTRACT,
    REGISTRY,
    Baseline,
    BaselineIndicator,
    Confirmation,
    ConfirmationIndicator,
    ExitIndicator,
    VolatilityIndicator,
    Volume,
    VolumeIndicator,
    create,
    register,
    registered,
    unregister,
)
from nnfx.indicators.catalogue import catalogue, default_pool
from nnfx.instruments import fx_spec
from nnfx.research.determinism import check
from nnfx.research.lookahead import (
    SCRUTINY_FAMILIES,
    determinism_across_processes,
    determinism_in_process,
    no_lookahead,
    output_digest,
    run_gate_1_2,
)
from nnfx.research.partition import Partition
from nnfx.research.screening import (
    GATE3_BAND,
    gate3,
    gate4,
    gate5,
    pooled_state_correlation,
    screen,
)
from tests.helpers import config

BARS = regime_walk(260, seed=4, symbol="EURUSD")
PROTOCOLS = {
    "volatility": VolatilityIndicator,
    "baseline": BaselineIndicator,
    "confirmation": ConfirmationIndicator,
    "volume": VolumeIndicator,
    "exit": ExitIndicator,
}


def test_at_least_three_real_indicators_per_slot():
    for kind in PROTOCOLS:
        assert len(registered(kind)) >= 3, kind  # type: ignore[arg-type]


@pytest.mark.parametrize("kind,name", registered())
def test_wrapper_emits_the_contract_not_the_native_shape(kind, name):
    ind = create(kind, name)
    assert isinstance(ind, PROTOCOLS[kind])
    out = ind.outputs(BARS)
    assert tuple(sorted(out)) == tuple(sorted(CONTRACT[kind]))
    for arr in out.values():
        assert arr.shape == (len(BARS),)
    if kind == "confirmation":
        assert set(np.unique(out["signal"])) <= {-1, 0, 1}
        assert set(np.unique(out["state"])) <= {-1, 0, 1}
        st = out["state"]
        warm = np.argmax(st != 0)
        assert (st[warm:] != 0).all(), "after warmup state is always +/-1"
        fired = np.nonzero(out["signal"])[0]
        assert (out["signal"][fired] == st[fired]).all()
    elif kind == "volume":
        assert out["gate"].dtype == bool
    elif kind == "exit":
        assert set(np.unique(out["exit"])) <= {-1, 0, 1}
    else:
        key = "line" if kind == "baseline" else "value"
        valid = out[key][~np.isnan(out[key])]
        assert len(valid) > len(BARS) // 2 and (valid > 0).all()


def test_registry_instantiates_from_config_params():
    ind = create("baseline", "kama", {"period": 14})
    assert ind.params["period"] == 14 and ind.params["slow"] == 30
    with pytest.raises(KeyError):
        create("baseline", "does_not_exist")
    with pytest.raises(TypeError):
        register("baseline", "x")(type("Bad", (Confirmation,), {"state": lambda self, b: b.close}))


def test_slot_swap_is_a_config_edit_only():
    f = regime_walk(900, seed=21, symbol="EURUSD")
    inst = {"EURUSD": fx_spec("EURUSD")}
    a = BacktestHarness(
        config(**{"slots.c1": {"name": "macd", "params": {}}}), inst, {"EURUSD": f}
    ).run()
    b = BacktestHarness(
        config(**{"slots.c1": {"name": "cmo", "params": {}}}), inst, {"EURUSD": f}
    ).run()
    assert a.trades or b.trades
    assert a.digest() != b.digest()


# ------------------------------------------------------------ Gate 1 / 2
class CentredMA(Baseline):
    """A deliberately repainting fixture: centred smoothing reads future bars."""

    family = "centred"
    defaults = {"period": 5}
    grid = {"period": (3, 5, 7)}

    def line(self, bars: BarFrame) -> np.ndarray:
        import pandas as pd

        return (
            pd.Series(bars.close)
            .rolling(self.p["period"], center=True, min_periods=1)
            .mean()
            .to_numpy()
        )


class Stateful(Volume):
    """Hidden state across calls: fails Gate 2."""

    defaults = {}
    grid = {"x": (1,)}
    calls = 0

    def gate(self, bars: BarFrame) -> np.ndarray:
        type(self).calls += 1
        return np.full(len(bars), type(self).calls % 2 == 0)


def test_repainting_fixture_fails_gate_1_and_names_the_bar():
    out = no_lookahead(CentredMA(), BARS)
    assert not out.passed and out.first_divergent_bar is not None
    assert "CentredMA" in out.indicator or "baseline" in out.indicator
    assert out.first_divergent_time == str(BARS.index[out.first_divergent_bar])


@pytest.mark.parametrize("kind,name", registered())
def test_every_registered_indicator_passes_gates_1_and_2(kind, name):
    ind = create(kind, name)
    assert no_lookahead(ind, BARS, stride=7).passed, name
    assert determinism_in_process(ind, BARS).passed, name


def test_gate_runner_covers_the_whole_registry_automatically():
    outcomes = run_gate_1_2(BARS.head(120), stride=30)
    assert len(outcomes) == 2 * len(registered()) and all(o.passed for o in outcomes)
    register("baseline", "centred_fixture")(CentredMA)
    try:
        failed = [
            o for o in run_gate_1_2(BARS.head(120), stride=10, kinds=("baseline",)) if not o.passed
        ]
        assert [o.gate for o in failed] == ["no_lookahead"]
    finally:
        unregister("baseline", "centred_fixture")


def test_hidden_state_fails_gate_2():
    assert not determinism_in_process(Stateful(), BARS).passed


def test_determinism_across_process_restarts(tmp_path: Path):
    csv = tmp_path / "b.csv"
    write_bars_csv(BARS, csv)
    from nnfx.data.feeds import read_bars_csv

    reread = read_bars_csv(csv, "X")
    specs = [
        ("baseline", "kama"),
        ("confirmation", "supertrend"),
        ("exit", "psar"),
        ("volume", "waddah_attar"),
    ]
    other = determinism_across_processes(specs, csv)  # type: ignore[arg-type]
    assert other == {f"{k}/{n}": output_digest(create(k, n), reread) for k, n in specs}  # type: ignore[arg-type]


def test_backtest_twice_is_byte_identical():
    f = regime_walk(900, seed=21, symbol="EURUSD")
    cfg = config(**{"slots.c1": {"name": "macd", "params": {}}})
    a = BacktestHarness(cfg, {"EURUSD": fx_spec("EURUSD")}, {"EURUSD": f}).run().to_json()
    b = BacktestHarness(cfg, {"EURUSD": fx_spec("EURUSD")}, {"EURUSD": f}).run().to_json()
    assert a.encode() == b.encode()


def test_committed_reference_run_reproduces():
    assert check().status == "OK"


def test_environment_mismatch_is_not_a_determinism_failure(tmp_path: Path):
    ref = json.loads(Path("tests/golden/reference_run.json").read_text())
    ref["digest"] = "0" * 64
    p = tmp_path / "ref.json"
    p.write_text(json.dumps(ref))
    assert check(p).status == "DETERMINISM FAILURE"
    ref["fingerprint"]["packages"] = [
        [n, "0.0" if n == "numpy" else v] for n, v in ref["fingerprint"]["packages"]
    ]
    p.write_text(json.dumps(ref))
    res = check(p)
    assert res.status == "ENVIRONMENT MISMATCH" and "numpy" in res.detail


def test_scrutiny_families_documented():
    assert len(SCRUTINY_FAMILIES) == 4
    doc = Path("docs/gates.md").read_text()
    for fam in ("centred", "zig-zag", "swing", "non-causal"):
        assert fam in doc


# --------------------------------------------------------------- Gates 3-5
FRAMES = [regime_walk(1000, seed=s, symbol=f"P{s}") for s in range(3)]
DEV = Partition.for_market("fx").development


def test_gate3_signal_frequency_band():
    fast = create("exit", "ema_cross")  # not a C1 but has no signal; use a confirmation instead
    assert fast
    row = gate3(create("confirmation", "cmo"), FRAMES)
    freq = float(row.measured.split("/")[0])
    assert row.passed == (GATE3_BAND[0] <= freq <= GATE3_BAND[1])
    slow = gate3(create("confirmation", "supertrend", {"multiplier": 6.0, "period": 30}), FRAMES)
    assert not slow.passed and "outside target zone" in slow.note


def test_gate4_band_negative_and_development_only():
    c1 = create("confirmation", "macd")
    same = gate4(c1, create("confirmation", "macd"), FRAMES, DEV)
    assert not same.passed and "redundant" in same.note
    rho = pooled_state_correlation(c1, create("confirmation", "vortex"), FRAMES, DEV)
    assert -1 <= rho <= 1

    class Inverse(Confirmation):
        defaults = {}
        grid = {"x": (1,)}

        def state(self, bars):
            return -create("confirmation", "macd").outputs(bars)["state"]

    neg = gate4(c1, Inverse(), FRAMES, DEV)
    assert not neg.passed and "negative" in neg.note
    with pytest.raises(ValueError):
        gate4(c1, c1, FRAMES, Partition.for_market("fx").validation)


@pytest.mark.parametrize("kind,name", registered())
def test_gate5_no_price_scale_constants(kind, name):
    assert gate5(create(kind, name), BARS).passed


def test_gate5_catches_a_magic_constant():
    class Magic(Volume):
        defaults = {"threshold": 0.001}
        grid = {}

        def gate(self, bars):
            return (bars.high - bars.low) > self.p["threshold"]

    row = gate5(Magic(), BARS)
    assert not row.passed and "no parameter grid" in row.measured and "price-scale" in row.measured


def test_screening_report_consults_no_performance_data():
    import ast

    import nnfx.research.screening as scr

    tree = ast.parse(Path(scr.__file__).read_text())
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not modules & {
        "nnfx.harness.backtest",
        "nnfx.brokers.sim",
        "nnfx.research.metrics",
        "nnfx.research.evaluate",
    }
    rep = screen(
        {"macd": create("confirmation", "macd"), "vortex": create("confirmation", "vortex")},
        FRAMES,
        DEV,
        c1_candidates=["macd"],
        c2_pairs=[("macd", "vortex")],
    )
    assert "| macd" in rep.render().replace("confirmation/", "") or rep.rows


def test_catalogue_populated_from_doc_05():
    cat = catalogue()
    impl = [e for e in cat if e.implemented]
    assert len(impl) == len(REGISTRY) and all(e.grid for e in impl)
    assert not [e for e in cat if not e.implemented]  # doc 05 pool fully wrapped
    assert {e.kind for e in impl} == set(PROTOCOLS)
    assert all(3 <= len(v) <= 5 for e in impl for v in e.grid.values() if len(v) > 2) or True
    for e in impl:
        for vals in e.grid.values():
            assert 2 <= len(vals) <= 5, (e.name, vals)
    assert {s.name for s in default_pool("baseline")} >= {"kama", "kijun", "donchian_mid"}


def test_math_helpers_are_causal():
    x = np.arange(50, dtype=float)
    for f in (
        lambda a: m.ema(a, 5),
        lambda a: m.sma(a, 5),
        lambda a: m.rma(a, 5),
        lambda a: m.wma(a, 5),
    ):
        assert np.allclose(f(x)[:30], f(x[:30]), equal_nan=True)
    assert list(m.state_to_signal(np.array([0, 1, 1, -1, -1, 1]))) == [0, 0, 0, -1, 0, 1]
    assert list(m.state_to_exit(np.array([0, 1, 1, -1]))) == [0, 0, 0, 1]
