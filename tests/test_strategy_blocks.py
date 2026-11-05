"""The gate suite over every registered Block (Strategy Builder ticket 05, ADR 10).

No-lookahead, determinism and price-scale invariance run automatically for
every Block in the registry: a new Block is gated the moment it is registered.
"""

from __future__ import annotations

from dataclasses import fields
from functools import cache

import numpy as np
import pytest

from nnfx.config import SessionConfig
from nnfx.data.synthetic import intraday_walk
from nnfx.instruments import crypto_spec
from nnfx.strategy import REGISTRY, StrategyData
from nnfx.strategy.blocks import (
    ContextBlock,
    ContextOutput,
    ExecutionBlock,
    ExitBlock,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StopBlock,
)
from nnfx.strategy.library import CandleSetup

ROLES = {"hwc": "D1", "mwc": "H4", "lwc": "M15"}
SCALE = 1000.0


@cache
def data() -> StrategyData:
    bars = intraday_walk(96 * 40, seed=3, symbol="BTC/USDT")
    return StrategyData.build(bars, ROLES, crypto_spec("BTC/USDT"), SessionConfig())


def block(btype: str):  # default parameters, but every timeframe role exercised
    cls = REGISTRY[btype]
    return cls(cls.Params())


@cache
def candidates() -> list[SetupCandidate]:
    d = data()
    out = CandleSetup().compute(d)
    cands = [SetupCandidate.at(out, d, "candle_setup", 1, i) for i in range(len(d))]
    return [c for c in cands if c is not None]


def arrays(out: ContextOutput | SetupOutput) -> dict[str, np.ndarray]:
    a = {f.name: getattr(out, f.name) for f in fields(out) if f.name != "flags"}
    if isinstance(out, ContextOutput):
        a.update({f"flag:{k}": v for k, v in out.flags.items()})
    return a


def same(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(np.array_equal(a, b, equal_nan=a.dtype.kind == "f"))


SERIES = sorted(t for t, c in REGISTRY.items() if issubclass(c, (ContextBlock, SetupBlock)))
PER_CANDIDATE = sorted(
    t for t, c in REGISTRY.items() if issubclass(c, (ExecutionBlock, StopBlock, ExitBlock))
)


def test_the_registry_holds_the_tracer_blocks_and_gates_cover_all_of_them():
    assert {
        "three_sma_alignment",
        "candle_setup",
        "stop_market",
        "structural_stop",
        "fixed_r",
    } <= set(REGISTRY)
    assert set(SERIES) | set(PER_CANDIDATE) == set(REGISTRY)
    assert len(candidates()) >= 10  # the fixture really produces setups to gate


@pytest.mark.parametrize("btype", SERIES)
def test_series_blocks_never_look_ahead(btype: str):
    b, d = block(btype), data()
    full = arrays(b.compute(d))
    for n in (300, 1000, 2001, len(d) - 37):
        part = arrays(b.compute(d.head(n)))
        for name, arr in part.items():
            assert same(arr, full[name][:n]), (
                f"{btype}.{name} changed its past when bar {n} arrived"
            )


@pytest.mark.parametrize("btype", SERIES)
def test_series_blocks_are_deterministic(btype: str):
    d = data()
    rebuilt = StrategyData.build(d.base, ROLES, d.instrument, d.session)
    a, b = arrays(block(btype).compute(d)), arrays(block(btype).compute(rebuilt))
    assert all(same(a[k], b[k]) for k in a)


@pytest.mark.parametrize("btype", SERIES)
def test_series_blocks_are_price_scale_invariant(btype: str):
    d = data()
    a, b = arrays(block(btype).compute(d)), arrays(block(btype).compute(d.scaled(SCALE)))
    for name in a:
        if name in SetupOutput.PRICE_FIELDS:
            assert np.allclose(a[name] * SCALE, b[name], rtol=1e-9, equal_nan=True), name
        else:
            assert same(a[name], b[name]), name


def per_candidate(btype: str, c: SetupCandidate, d: StrategyData) -> tuple[list[float], object]:
    """(price-valued outputs, everything else) of a per-candidate Block."""
    b = block(btype)
    if isinstance(b, ExecutionBlock):
        orders = b.orders(c, d)
        prices = [x for o in orders for x in (o.level, o.buffer, o.invalidation) if x is not None]
        return prices, [(o.expires_after_bars, o.oco_group, o.invalidation is None) for o in orders]
    if isinstance(b, StopBlock):
        return [b.initial_stop(c, d)], None
    assert isinstance(b, ExitBlock)
    return [], b.plan(c)  # exits are in R: scale-free by construction


def scaled(c: SetupCandidate) -> SetupCandidate:
    from dataclasses import replace

    return replace(
        c, trigger=c.trigger * SCALE, invalidation=c.invalidation * SCALE, stop=c.stop * SCALE
    )


@pytest.mark.parametrize("btype", PER_CANDIDATE)
def test_candidate_blocks_never_look_ahead_and_are_deterministic(btype: str):
    d = data()
    for c in candidates()[:15]:
        now = per_candidate(btype, c, d.head(c.bar + 1))
        assert now == per_candidate(btype, c, d) == per_candidate(btype, c, d.head(c.bar + 1))


@pytest.mark.parametrize("btype", PER_CANDIDATE)
def test_candidate_blocks_are_price_scale_invariant(btype: str):
    d, ds = data(), data().scaled(SCALE)
    for c in candidates()[:15]:
        (pa, ra), (pb, rb) = per_candidate(btype, c, d), per_candidate(btype, scaled(c), ds)
        assert np.allclose(np.array(pa) * SCALE, np.array(pb), rtol=1e-9) and ra == rb
