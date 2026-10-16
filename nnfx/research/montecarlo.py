"""Monte Carlo, kill-switch derivation, regime and stress reporting (doc 03 §3b, §7)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame, ns
from nnfx.instruments import InstrumentSpec
from nnfx.research.metrics import Entry, utc

UNRECOVERABLE_DD = 0.35  # criterion 8: beyond ~35% the account is hard to rescue


@dataclass(frozen=True)
class BootstrapResult:
    max_dd: np.ndarray
    streaks: np.ndarray

    def quantile(self, q: float) -> float:
        return float(np.quantile(self.max_dd, q))

    @property
    def p95_drawdown(self) -> float:
        return self.quantile(0.95)

    @property
    def p95_streak(self) -> float:
        return float(np.quantile(self.streaks, 0.95))


def trade_returns(entries: Sequence[Entry], risk_per_position: float = 0.01) -> np.ndarray:
    """Per-entry fractional equity return: R x (risk per position)."""
    return np.array([e.r * risk_per_position for e in entries], dtype="float64")


def bootstrap(
    returns: Sequence[float] | np.ndarray,
    *,
    n_sims: int = 5000,
    rng: np.random.Generator | None = None,
) -> BootstrapResult:
    """Resample the trade sequence with replacement; record max drawdown and losing streak."""
    r = np.asarray(returns, dtype="float64")
    rng = rng or np.random.default_rng(0)
    if len(r) == 0:
        return BootstrapResult(np.zeros(1), np.zeros(1))
    draws = r[rng.integers(0, len(r), size=(n_sims, len(r)))]
    eq = np.cumprod(1 + draws, axis=1)
    peak = np.maximum.accumulate(np.concatenate([np.ones((n_sims, 1)), eq], axis=1), axis=1)[:, 1:]
    dd = (1 - eq / peak).max(axis=1)
    streaks = np.zeros(n_sims)
    for i in range(n_sims):
        best = cur = 0
        for x in draws[i]:
            cur = cur + 1 if x < 0 else 0
            best = max(best, cur)
        streaks[i] = best
    return BootstrapResult(dd, streaks)


@dataclass(frozen=True)
class KillSwitchProposal:
    threshold: float | None
    p95: float
    ceiling: float
    note: str


def propose_kill_switch(
    bs: BootstrapResult, margin: float = 1.10, ceiling: float = UNRECOVERABLE_DD
) -> KillSwitchProposal:
    """Above the 95th percentile (normal bad luck), below unrecoverable. The operator approves it."""
    p95 = bs.p95_drawdown
    cand = p95 * margin
    if cand >= ceiling:
        return KillSwitchProposal(
            None,
            p95,
            ceiling,
            "no valid threshold: p95 drawdown x margin reaches the unrecoverable ceiling",
        )
    return KillSwitchProposal(
        round(cand, 4),
        p95,
        ceiling,
        "set risk.kill_switch_drawdown to this and kill_switch_approved: true",
    )


# ------------------------------------------------------------------- regimes
def classify_regimes(
    frame: BarFrame, sma: int = 200, slope_bars: int = 20, band: float = 0.0
) -> pd.Series:
    """Independent regime rule: bull if close > SMA and SMA rising, bear if below and falling, else chop."""
    c = pd.Series(frame.close, index=frame.index)
    m = c.rolling(sma, min_periods=sma).mean()
    slope = m - m.shift(slope_bars)
    reg = pd.Series("chop", index=frame.index)
    reg[(c > m * (1 + band)) & (slope > 0)] = "bull"
    reg[(c < m * (1 - band)) & (slope < 0)] = "bear"
    reg[m.isna()] = "unknown"
    return reg


def regime_report(entries: Sequence[Entry], regimes: pd.Series) -> dict[str, dict[str, float]]:
    """Expectancy per regime at entry time; a bull-only trend system is a leveraged long."""
    buckets: dict[str, list[float]] = {}
    idx = ns(regimes.index)
    for e in entries:
        k = int(np.searchsorted(idx, utc(e.entry_time).value, side="right")) - 1
        name = str(regimes.iloc[max(k, 0)]) if len(regimes) else "unknown"
        buckets.setdefault(name, []).append(e.r)
    return {
        k: {"entries": float(len(v)), "expectancy_r": float(np.mean(v))}
        for k, v in sorted(buckets.items())
    }


STRESS_WINDOWS: dict[str, tuple[str, str]] = {
    "2008_gfc": ("2008-01-01", "2009-06-30"),
    "2015_chf": ("2015-01-01", "2015-03-31"),
    "2020_covid": ("2020-02-01", "2020-06-30"),
    "2022_rates": ("2022-01-01", "2022-12-31"),
}


def stress_report(
    entries: Sequence[Entry], windows: Mapping[str, tuple[str, str]] = STRESS_WINDOWS
) -> dict[str, dict[str, float]]:
    out = {}
    for name, (a, b) in windows.items():
        t0, t1 = pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC")
        rs = [e.r for e in entries if t0 <= utc(e.entry_time) <= t1]
        out[name] = {
            "entries": float(len(rs)),
            "expectancy_r": float(np.mean(rs)) if rs else float("nan"),
            "sum_r": float(np.sum(rs)),
        }
    return out


@dataclass(frozen=True)
class CorrelationStress:
    currency: str
    pairs: int
    uncapped_risk: float
    capped_risk: float
    detail: dict[str, float] = field(default_factory=dict)


def correlation_stress(
    instruments: Sequence[InstrumentSpec],
    risk_per_entry: float = 0.02,
    cap: int | None = 2,
    gap_multiple: float = 1.0,
) -> list[CorrelationStress]:
    """Worst case: every pair containing a currency open in the same direction on it, all stopped together."""
    out = []
    ccys = sorted({c for i in instruments for c in (i.base, i.quote)})
    for c in ccys:
        n = sum(1 for i in instruments if c in (i.base, i.quote))
        unc = n * risk_per_entry * gap_multiple
        capped = (min(n, cap) if cap is not None else n) * risk_per_entry * gap_multiple
        out.append(CorrelationStress(c, n, unc, capped))
    return sorted(out, key=lambda s: -s.uncapped_risk)
