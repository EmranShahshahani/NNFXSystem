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
from nnfx.engine.types import ExitStepView, PositionView
from nnfx.instruments import crypto_spec
from nnfx.strategy import REGISTRY, StrategyData
from nnfx.strategy.blocks import (
    ConfirmationBlock,
    ContextBlock,
    ContextOutput,
    ExecutionBlock,
    ExitBlock,
    SetupBlock,
    SetupCandidate,
    SetupOutput,
    StopBlock,
)
from nnfx.strategy.library import CandleSetup, ProfitChain, ProfitChainParams

ROLES = {"hwc": "D1", "mwc": "H4", "lwc": "M15"}
SCALE = 1000.0


@cache
def data() -> StrategyData:
    bars = intraday_walk(96 * 40, seed=3, symbol="BTC/USDT")
    return StrategyData.build(bars, ROLES, crypto_spec("BTC/USDT"), SessionConfig())


def variants(btype: str) -> list[str]:
    """``type`` plus ``type@role`` for each role a Block's ``timeframe`` parameter can take."""
    field = REGISTRY[btype].Params.model_fields.get("timeframe")
    return [btype] + ([f"{btype}@{r}" for r in ROLES] if field is not None else [])


def block(spec: str):
    """A Block with default parameters, or ``type@role`` on another timeframe role."""
    btype, _, role = spec.partition("@")
    cls = REGISTRY[btype]
    return cls(cls.Params(**({"timeframe": role} if role else {})))


@cache
def candidates() -> list[SetupCandidate]:
    d = data()
    out = CandleSetup().compute(d)
    cands = [SetupCandidate.at(out, d, "candle_setup", 1, i) for i in range(len(d))]
    return [c for c in cands if c is not None]


def arrays(out: ContextOutput | SetupOutput) -> dict[str, np.ndarray]:
    """Every published array of a series Block's output, flags and tags flattened."""
    a = {
        f.name: getattr(out, f.name)
        for f in fields(out)
        if f.name not in ("flags", "tags", "meta") and getattr(out, f.name) is not None
    }
    if isinstance(out, ContextOutput):
        a.update({f"extra:{k}": v for k, v in out.flags.items()})
        for k, (lo, sh) in out.tags.items():
            a.update({f"tag:{k}:long": lo, f"tag:{k}:short": sh})
    else:
        a.update({f"extra:{k}": v for k, v in out.tags.items()})
        a.update({f"meta:{k}": v for k, v in out.meta.items()})
    return a


def same(a: np.ndarray, b: np.ndarray) -> bool:
    return bool(np.array_equal(a, b, equal_nan=a.dtype.kind == "f"))


SERIES = sorted(
    v for t, c in REGISTRY.items() if issubclass(c, (ContextBlock, SetupBlock)) for v in variants(t)
)
PER_CANDIDATE = sorted(
    t
    for t, c in REGISTRY.items()
    if issubclass(c, (ConfirmationBlock, ExecutionBlock, StopBlock, ExitBlock))
)


def test_the_registry_holds_the_tracer_blocks_and_gates_cover_all_of_them():
    assert {
        "three_sma_alignment",
        "candle_setup",
        "stop_market",
        "structural_stop",
        "fixed_r",
    } <= set(REGISTRY)
    assert {v.partition("@")[0] for v in SERIES} | set(PER_CANDIDATE) == set(REGISTRY)
    assert "three_sma_alignment@hwc" in SERIES
    assert {"rsi_momentum", "volume_expansion"} <= set(PER_CANDIDATE)
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


def digest_all() -> str:
    """One hash of every series Block's outputs on the fixture."""
    import hashlib

    h = hashlib.sha256()
    for spec in SERIES:
        for name, arr in sorted(arrays(block(spec).compute(data())).items()):
            h.update(spec.encode() + name.encode() + np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def test_series_blocks_are_deterministic_across_processes():
    import subprocess
    import sys

    code = "from tests.test_strategy_blocks import digest_all; print(digest_all())"
    other = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert other.stdout.strip() == digest_all()


@pytest.mark.parametrize("btype", SERIES)
def test_series_blocks_are_price_scale_invariant(btype: str):
    d = data()
    a, b = arrays(block(btype).compute(d)), arrays(block(btype).compute(d.scaled(SCALE)))
    for name in a:
        if name in SetupOutput.PRICE_FIELDS or name.removeprefix("meta:") in SetupOutput.PRICE_META:
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
    if isinstance(b, ConfirmationBlock):
        res = b.check(c, d)  # verdicts are scale-free: the outcome, never the wording
        return [], res.outcome
    assert isinstance(b, ExitBlock)
    return [], b.plan(c, d, c.stop)  # exits are in R: scale-free by construction


def scaled(c: SetupCandidate) -> SetupCandidate:
    from dataclasses import replace

    return replace(
        c,
        trigger=c.trigger * SCALE,
        invalidation=c.invalidation * SCALE,
        stop=c.stop * SCALE,
        meta=tuple((k, v * SCALE if k in SetupOutput.PRICE_META else v) for k, v in c.meta),
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


# ------------------------------------------------------ position management
EXITS = sorted(t for t, c in REGISTRY.items() if issubclass(c, ExitBlock))


def exit_variants() -> list[ExitBlock]:
    """Every Exit Block with defaults, plus the Profit Chain's data-reading modes."""
    out: list[ExitBlock] = [block(t) for t in EXITS]
    out.append(
        ProfitChain(ProfitChainParams(counter_trend="always", counter_trend_exit="boundary"))
    )
    out.append(ProfitChain(ProfitChainParams(pivot_bars=1)))
    out.append(ProfitChain(ProfitChainParams(sma_flatten_exit=True, sma_period=5)))
    out.append(ProfitChain(ProfitChainParams(rsi_exhaustion_exit=True, rsi_period=5)))
    out.append(ProfitChain(ProfitChainParams(hold_while_rsi_role="lwc", rsi_exhaustion_exit=True)))
    out.append(ProfitChain(ProfitChainParams(macd_decel_exit=True, macd_fast=3, macd_slow=8)))
    out.append(ProfitChain(ProfitChainParams(roc_ceiling_exit=True, roc_period=4, roc_window=30)))
    out.append(ProfitChain(ProfitChainParams(adx_exhaustion="close", adx_level=20.0)))
    out.append(ProfitChain(ProfitChainParams(adx_exhaustion="tighten", adx_level=20.0)))
    out.append(
        ProfitChain(ProfitChainParams(climax_exit=True, climax_factor=1.5, climax_range=1.2))
    )
    out.append(ProfitChain(ProfitChainParams(health_exit="close", health_min_signals=1)))
    out.append(ProfitChain(ProfitChainParams(health_exit="tighten", health_min_signals=1)))
    out.append(ProfitChain(ProfitChainParams(runway_exit=True, runway_period=5, runway_bars=8)))
    out.append(ProfitChain(ProfitChainParams(pivot_exit="both", pivot_period="H4")))
    out.append(ProfitChain(ProfitChainParams(pivot_exit="r3", pivot_period="W1")))
    out.append(ProfitChain(ProfitChainParams(fib_target="1.0", fib_min_impulse_atr=1.0)))
    return out


def position(b: ExitBlock, c: SetupCandidate, d: StrategyData, filled: int):
    """A position entered on the bar after ``c`` at its trigger, ``filled`` steps done."""
    plan = b.plan(c, d, c.stop)
    risk = c.trigger - c.stop
    return PositionView(
        id="p",
        symbol=c.symbol,
        direction=c.direction,
        units=1.0,
        entry_price=c.trigger,
        entry_time=d.base.index[c.bar + 1].isoformat(),
        stop=c.stop,
        leg="single",
        entry_atr=0.0,
        signal_time=c.time,
        entry_type="setup",
        exit_steps=tuple(
            ExitStepView(price=c.trigger + s.r * risk, fraction=s.fraction, done=n < filled)
            for n, s in enumerate(plan.steps)
        ),
        steps_filled=filled,
    )


def spread() -> list[SetupCandidate]:
    """Five candidates spread over the fixture, so swings exist before most of them."""
    cs = candidates()
    return cs[len(cs) // 6 :: max(1, len(cs) // 6)][:5]


def management_closes(d: StrategyData, after: int, n: int = 3) -> list[int]:
    pos = d.positions["management"]
    return [j for j in range(after + 20, len(d)) if pos[j] != pos[j - 1]][:n]


def managed(b: ExitBlock, c: SetupCandidate, d: StrategyData, j: int, filled: int):
    mv = b.manage(position(b, c, d, filled), d, j)
    if mv is None:
        return None
    return (getattr(mv, "stop", None), mv.reason)  # a close move has no stop


@pytest.mark.parametrize("b", exit_variants(), ids=lambda b: repr(b.p))
def test_exit_blocks_manage_without_lookahead(b: ExitBlock):
    d, seen, closes = data(), 0, 0
    for c in spread():
        assert b.plan(c, d.head(c.bar + 1), c.stop) == b.plan(c, d, c.stop)
        for j in management_closes(d, c.bar):
            for filled in (1, 3):
                now = managed(b, c, d.head(j + 1), j, filled)
                assert now == managed(b, c, d, j, filled), (c.bar, j, filled)
                seen += now is not None
                closes += now is not None and now[0] is None
    if isinstance(b, ProfitChain) and b.p.counter_trend != "always":
        assert seen  # the fixture really produces stop moves to gate
    if isinstance(b, ProfitChain) and b.p.sma_flatten_exit:
        assert closes  # and profit-taking closes


@pytest.mark.parametrize("b", exit_variants(), ids=lambda b: repr(b.p))
def test_exit_blocks_manage_scale_free(b: ExitBlock):
    d, ds = data(), data().scaled(SCALE)
    for c in spread():
        assert b.plan(c, d, c.stop) == b.plan(scaled(c), ds, c.stop * SCALE)
        for j in management_closes(d, c.bar):
            for filled in (1, 3):
                a, z = managed(b, c, d, j, filled), managed(b, scaled(c), ds, j, filled)
                assert (a is None) == (z is None)
                if a is not None and z is not None:
                    assert z[1] == a[1]
                    assert (z[0] is None) == (a[0] is None)
                    if a[0] is not None:
                        assert z[0] == pytest.approx(a[0] * SCALE, rel=1e-9)
