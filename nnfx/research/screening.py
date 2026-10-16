"""Screening Gates 3-5 and the screening report (doc 05 §2, ticket 09).

These gates consult **no performance data**: every function here takes bars and
indicators only, never a trade list or an equity curve. Screening must not
become a covert first round of selection.

Gate 4 agreement mapping: for two +/-1 state series, rho = 2 x agreement - 1, so
rho = 0.60 <-> 80% agreement (C2 is decoration above this) and rho = 0.15 <->
57.5% agreement (C2 is a near-random filter below this). Negative rho rejects
immediately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from nnfx.data.bars import BarFrame
from nnfx.indicators.base import Indicator
from nnfx.research.partition import Segment

GATE3_BAND = (6.0, 50.0)
GATE3_TARGET = (12.0, 35.0)
GATE4_BAND = (0.15, 0.60)


@dataclass(frozen=True)
class ScreenRow:
    candidate: str
    gate: str
    passed: bool
    measured: str
    note: str = ""


@dataclass
class ScreeningReport:
    rows: list[ScreenRow] = field(default_factory=list)

    def eligible(self, candidate: str) -> bool:
        mine = [r for r in self.rows if r.candidate == candidate]
        return bool(mine) and all(r.passed for r in mine)

    def render(self) -> str:
        lines = ["| candidate | gate | result | measured | note |", "|---|---|---|---|---|"]
        for r in self.rows:
            lines.append(
                f"| {r.candidate} | {r.gate} | {'PASS' if r.passed else 'FAIL'} | {r.measured} | {r.note} |"
            )
        return "\n".join(lines)


def _years(frame: BarFrame) -> float:
    if len(frame) < 2:
        return 0.0
    return (frame.index[-1] - frame.index[0]).total_seconds() / (365.25 * 86400)


def signal_frequency(c1: Indicator, frames: Sequence[BarFrame]) -> float:
    """Mean C1 signals per instrument-year."""
    signals, years = 0, 0.0
    for f in frames:
        sig = c1.outputs(f)["signal"]
        signals += int(np.count_nonzero(sig))
        years += _years(f)
    return signals / years if years else 0.0


def gate3(c1: Indicator, frames: Sequence[BarFrame]) -> ScreenRow:
    freq = signal_frequency(c1, frames)
    lo, hi = GATE3_BAND
    tlo, thi = GATE3_TARGET
    zone = "in target zone" if tlo <= freq <= thi else "outside target zone 12-35"
    return ScreenRow(
        repr(c1), "3 signal frequency", lo <= freq <= hi, f"{freq:.1f}/instrument-year", zone
    )


def pooled_state_correlation(
    c1: Indicator, c2: Indicator, frames: Sequence[BarFrame], segment: Segment
) -> float:
    a_all, b_all = [], []
    for f in frames:
        a, b = c1.outputs(f)["state"], c2.outputs(f)["state"]
        inseg = (f.index >= segment.start) & (f.index <= segment.end)
        mask = inseg & (a != 0) & (b != 0)
        a_all.append(a[mask].astype("float64"))
        b_all.append(b[mask].astype("float64"))
    a_cat, b_cat = np.concatenate(a_all), np.concatenate(b_all)
    if len(a_cat) < 2 or a_cat.std() == 0 or b_cat.std() == 0:
        return float("nan")
    return float(np.corrcoef(a_cat, b_cat)[0, 1])


def gate4(
    c1: Indicator, c2: Indicator, frames: Sequence[BarFrame], development: Segment
) -> ScreenRow:
    if development.name != "development":
        raise ValueError("Gate 4 is computed on the development segment only")
    rho = pooled_state_correlation(c1, c2, frames, development)
    lo, hi = GATE4_BAND
    agreement = (rho + 1) / 2 if np.isfinite(rho) else float("nan")
    if not np.isfinite(rho):
        return ScreenRow(f"{c1!r} x {c2!r}", "4 C1/C2 independence", False, "rho undefined")
    if rho < 0:
        note = "negative rho: rejected immediately"
        ok = False
    else:
        ok = lo <= rho <= hi
        note = "" if ok else ("redundant C2" if rho > hi else "near-random C2")
    return ScreenRow(
        f"{c1!r} x {c2!r}",
        "4 C1/C2 independence",
        ok,
        f"rho={rho:.3f} (agreement {agreement:.1%})",
        note,
    )


def gate5(
    ind: Indicator, bars: BarFrame, factors: tuple[float, ...] = (1000.0, 0.001)
) -> ScreenRow:
    """Parameters exposed for the grid, and no price-scale magic constants.

    The scale test multiplies every price by each factor (up and down, so both
    large and tiny constants are caught): discrete contract outputs (signal,
    state, gate, exit) must be unchanged, and price-unit outputs (line, value)
    must scale exactly by the factor.
    """
    problems: list[str] = []
    numeric = [
        k
        for k, v in ind.defaults.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    ungridded = [k for k in numeric if k not in ind.grid]
    if not ind.grid:
        problems.append("no parameter grid exposed")
    a = ind.outputs(bars)
    for factor in factors:
        b = ind.outputs(bars.scaled(factor))
        for key in a:
            x, y = a[key], b[key]
            if key in ("line", "value"):
                ok = np.allclose(x * factor, y, rtol=1e-6, equal_nan=True)
            else:
                ok = bool(np.array_equal(x, y))
            msg = f"'{key}' is not price-scale invariant"
            if not ok and msg not in problems:
                problems.append(msg)
    note = f"ungridded: {ungridded}" if ungridded else ""
    return ScreenRow(
        repr(ind),
        "5 parameterisation",
        not problems,
        "; ".join(problems) or "scale-invariant",
        note,
    )


def screen(
    candidates: Mapping[str, Indicator],
    frames: Sequence[BarFrame],
    development: Segment,
    *,
    c1_candidates: Sequence[str] = (),
    c2_pairs: Sequence[tuple[str, str]] = (),
) -> ScreeningReport:
    report = ScreeningReport()
    for name in c1_candidates:
        report.rows.append(gate3(candidates[name], frames))
    for c1, c2 in c2_pairs:
        report.rows.append(gate4(candidates[c1], candidates[c2], frames, development))
    for ind in candidates.values():
        report.rows.append(gate5(ind, frames[0]))
    return report
