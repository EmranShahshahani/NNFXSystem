"""Overfitting controls (doc 03 §5): DSR, PBO via CSCV, walk-forward, plateaus."""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

import numpy as np

_N = NormalDist()
EULER = 0.5772156649015329


# ------------------------------------------------------------ deflated sharpe
def expected_max_sharpe(n_trials: int, trial_sharpe_var: float) -> float:
    """E[max SR] of ``n_trials`` unskilled trials (Bailey & Lopez de Prado 2014)."""
    if n_trials <= 1:
        return 0.0
    sd = math.sqrt(max(trial_sharpe_var, 0.0))
    return sd * (
        (1 - EULER) * _N.inv_cdf(1 - 1.0 / n_trials)
        + EULER * _N.inv_cdf(1 - 1.0 / (n_trials * math.e))
    )


@dataclass(frozen=True)
class DSRResult:
    probability: float
    sr: float
    sr0: float
    n_trials: int
    n_obs: int


def deflated_sharpe(
    returns: Sequence[float] | np.ndarray,
    n_trials: int,
    trial_sharpe_var: float | None = None,
    trial_sharpes: Sequence[float] | None = None,
) -> DSRResult:
    """Probability the true (per-period) Sharpe exceeds the best an unskilled search would find.

    ``n_trials`` must be the *logged* trial count; an undercount makes this
    optimistic and nothing in the output would look wrong (ADR 08 §2).
    """
    r = np.asarray(returns, dtype="float64")
    t = len(r)
    if t < 3 or r.std(ddof=1) == 0:
        return DSRResult(0.0, 0.0, 0.0, n_trials, t)
    sr = float(r.mean() / r.std(ddof=1))
    if trial_sharpe_var is None:
        trial_sharpe_var = (
            float(np.var(trial_sharpes, ddof=1))
            if trial_sharpes is not None and len(trial_sharpes) > 1
            else 1.0 / t
        )
    sr0 = expected_max_sharpe(n_trials, trial_sharpe_var)
    z = r - r.mean()
    sd = r.std(ddof=0)
    skew = float(np.mean(z**3) / sd**3)
    kurt = float(np.mean(z**4) / sd**4)
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    prob = _N.cdf((sr - sr0) * math.sqrt(t - 1) / denom)
    return DSRResult(prob, sr, sr0, n_trials, t)


# ------------------------------------------------------------------- PBO/CSCV
@dataclass(frozen=True)
class PBOResult:
    pbo: float
    logits: tuple[float, ...]
    n_splits: int


def _sharpe_cols(m: np.ndarray) -> np.ndarray:
    sd = m.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, m.mean(axis=0) / sd, 0.0)


def pbo_cscv(returns: np.ndarray, n_blocks: int = 16) -> PBOResult:
    """Combinatorially symmetric cross-validation (Bailey et al. 2015).

    ``returns`` is T x N: per-period returns of N configurations on a common
    calendar. For every split of the blocks into halves, the in-sample best is
    ranked out-of-sample; PBO is the share of splits where it ranks at or
    below the median.
    """
    m = np.asarray(returns, dtype="float64")
    t, n = m.shape
    if n < 2:
        raise ValueError("PBO needs at least two configurations")
    n_blocks -= n_blocks % 2
    blocks = np.array_split(np.arange(t), n_blocks)
    logits: list[float] = []
    for combo in itertools.combinations(range(n_blocks), n_blocks // 2):
        ins = np.concatenate([blocks[i] for i in combo])
        oos = np.concatenate([blocks[i] for i in range(n_blocks) if i not in combo])
        best = int(np.argmax(_sharpe_cols(m[ins])))
        oos_sr = _sharpe_cols(m[oos])
        rank = (np.argsort(np.argsort(oos_sr))[best] + 1) / (n + 1)
        logits.append(math.log(rank / (1 - rank)))
    lg = np.array(logits)
    return PBOResult(float(np.mean(lg <= 0)), tuple(float(x) for x in lg), len(logits))


# --------------------------------------------------------------- walk-forward
@dataclass(frozen=True)
class WalkForwardResult:
    efficiency: float
    folds: tuple[dict[str, Any], ...]


def walk_forward(
    candidates: Sequence[Hashable],
    evaluate: Callable[[Hashable, int, int], float],
    years: Sequence[int],
    train_years: int = 4,
    test_years: int = 1,
) -> WalkForwardResult:
    """Select on ``train_years``, trade the next ``test_years``, roll forward.

    ``evaluate(candidate, first_year, last_year)`` returns an *annualised* return
    (or expectancy) on that window. Efficiency = mean OOS / mean IS of the chosen.
    """
    ys = sorted(years)
    folds = []
    for k in range(0, len(ys) - train_years - test_years + 1, test_years):
        tr = ys[k : k + train_years]
        te = ys[k + train_years : k + train_years + test_years]
        scores = {c: evaluate(c, tr[0], tr[-1]) for c in candidates}
        best = max(sorted(scores, key=repr), key=lambda c: scores[c])
        folds.append(
            {
                "train": (tr[0], tr[-1]),
                "test": (te[0], te[-1]),
                "chosen": best,
                "is": scores[best],
                "oos": evaluate(best, te[0], te[-1]),
            }
        )
    if not folds:
        return WalkForwardResult(float("nan"), ())
    is_mean = float(np.mean([f["is"] for f in folds]))
    oos_mean = float(np.mean([f["oos"] for f in folds]))
    eff = oos_mean / is_mean if is_mean > 0 else float("nan")
    return WalkForwardResult(eff, tuple(folds))


# ------------------------------------------------------------------- plateau
@dataclass(frozen=True)
class PlateauResult:
    peak: tuple[Any, ...]
    peak_value: float
    worst_neighbour_ratio: float
    neighbours: dict[tuple[Any, ...], float]

    def passes(self, threshold: float = 0.60) -> bool:
        return bool(self.neighbours) and self.worst_neighbour_ratio >= threshold


def plateau(
    results: Mapping[tuple[Any, ...], float],
    grid: Sequence[Sequence[Any]],
    peak: tuple[Any, ...] | None = None,
) -> PlateauResult:
    """Ratio of each +/-1-step neighbour (one parameter at a time) to the peak expectancy."""
    if peak is None:
        peak = max(results, key=lambda k: results[k])
    pv = results[peak]
    neigh: dict[tuple[Any, ...], float] = {}
    for d, axis in enumerate(grid):
        i = list(axis).index(peak[d])
        for j in (i - 1, i + 1):
            if 0 <= j < len(axis):
                key = tuple(axis[j] if q == d else peak[q] for q in range(len(peak)))
                if key in results:
                    neigh[key] = results[key] / pv if pv > 0 else float("nan")
    worst = min(neigh.values()) if neigh else float("nan")
    return PlateauResult(peak, pv, worst, neigh)
