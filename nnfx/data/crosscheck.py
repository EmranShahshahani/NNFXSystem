"""Second-source cross-checks (doc 03 §2, §2b).

Compares the same symbol from two sources on a seeded sample of common dates
and reports divergences, so feed- or venue-specific artefacts surface before
they become findings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame


@dataclass(frozen=True)
class Divergence:
    time: pd.Timestamp
    field: str
    a: float
    b: float
    rel: float


@dataclass(frozen=True)
class CrossCheckReport:
    symbol: str
    source_a: str
    source_b: str
    sampled: int
    common: int
    divergences: tuple[Divergence, ...]
    tolerance: float

    @property
    def ok(self) -> bool:
        return not self.divergences

    def render(self) -> str:
        head = (
            f"{self.symbol}: {self.source_a} vs {self.source_b}, {self.sampled} of {self.common} "
            f"common bars sampled, tol={self.tolerance:.4%}: {len(self.divergences)} divergence(s)"
        )
        lines = [
            f"  {d.time} {d.field}: {d.a:.6g} vs {d.b:.6g} ({d.rel:.3%})"
            for d in self.divergences[:20]
        ]
        return "\n".join([head, *lines])


def cross_check(
    a: BarFrame,
    b: BarFrame,
    *,
    source_a: str,
    source_b: str,
    sample: int = 50,
    tolerance: float = 0.002,
    fields: tuple[str, ...] = ("close",),
    seed: int = 0,
    match_by_date: bool = True,
) -> CrossCheckReport:
    da, db = a.df, b.df
    if match_by_date:
        da.index = pd.DatetimeIndex(da.index).normalize()
        db.index = pd.DatetimeIndex(db.index).normalize()
    common = da.index.intersection(db.index)
    rng = np.random.default_rng(seed)
    n = min(sample, len(common))
    picks = common[np.sort(rng.choice(len(common), size=n, replace=False))] if n else common
    divs: list[Divergence] = []
    for t in picks:
        for f in fields:
            va, vb = float(da[f].loc[t]), float(db[f].loc[t])
            rel = abs(va - vb) / max(abs(va), 1e-12)
            if rel > tolerance:
                divs.append(Divergence(pd.Timestamp(t), f, va, vb, rel))
    return CrossCheckReport(a.symbol, source_a, source_b, n, len(common), tuple(divs), tolerance)
