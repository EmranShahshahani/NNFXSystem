"""The pre-registered acceptance verdict (doc 03 §8.2, ticket 26).

Thresholds are read from ``research/thresholds.frozen.json`` and never from
code or arguments. A result that lands just short is a FAIL. A criterion with
no evidence supplied is MISSING, and MISSING fails the verdict: absence of
evidence is not a pass. Market-specific criteria are N/A elsewhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from nnfx.research.partition import Market

Status = Literal["PASS", "FAIL", "N/A", "MISSING"]


@dataclass
class Evidence:
    market: Market
    expectancy_ci_lower: float | None = None
    n_eff: float | None = None
    expectancy: float | None = None
    dsr_probability: float | None = None
    dsr_trial_count: int | None = None
    pbo: float | None = None
    wfe: float | None = None
    mar: float | None = None
    bootstrap_p95_dd: float | None = None
    random_percentile: float | None = None
    stress_ci_lower: float | None = None
    stress_expectancy: float | None = None
    plateau_ratio: float | None = None
    holdout_expectancy: float | None = None
    development_expectancy: float | None = None
    regime_expectancy: dict[str, float] = field(default_factory=dict)
    instrument_breadth: float | None = None
    cross_market_consistent: bool | None = None


@dataclass(frozen=True)
class Row:
    criterion: str
    threshold: str
    measured: str
    status: Status


@dataclass
class Verdict:
    rows: list[Row]

    @property
    def passed(self) -> bool:
        return all(r.status in ("PASS", "N/A") for r in self.rows)

    def render(self) -> str:
        out = ["| # | criterion | threshold | measured | result |", "|---|---|---|---|---|"]
        for r in self.rows:
            num, _, name = r.criterion.partition("_")
            out.append(
                f"| {num} | {name.replace('_', ' ')} | {r.threshold} | {r.measured} | **{r.status}** |"
            )
        out.append("")
        out.append(
            f"**VERDICT: {'PASS' if self.passed else 'FAIL'}** - thresholds frozen; a near miss is a fail (doc 03 §8.3)."
        )
        return "\n".join(out)


def _cmp(op: str, x: float, v: float) -> bool:
    return {">": x > v, ">=": x >= v, "<": x < v, "<=": x <= v}[op]


def _num(name: str, crit: dict[str, Any], x: float | None, fmt: str = "{:.3f}") -> Row:
    thr = f"{crit['op']} {crit['value']}"
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return Row(name, thr, "-", "MISSING")
    return Row(
        name,
        thr,
        fmt.format(x),
        "PASS" if _cmp(crit["op"], float(x), float(crit["value"])) else "FAIL",
    )


def evaluate(
    ev: Evidence, thresholds: dict[str, Any], logged_trial_count: int | None = None
) -> Verdict:
    c = thresholds["criteria"]
    rows: list[Row] = [
        _num(
            "1_expectancy_ci_lower", c["1_expectancy_ci_lower"], ev.expectancy_ci_lower, "{:+.3f}R"
        ),
        _num("2_effective_sample", c["2_effective_sample"], ev.n_eff, "{:.0f}"),
        _num("3_expectancy_point", c["3_expectancy_point"], ev.expectancy, "{:+.3f}R"),
    ]
    dsr = _num("4_deflated_sharpe", c["4_deflated_sharpe"], ev.dsr_probability)
    if (
        dsr.status == "PASS"
        and logged_trial_count is not None
        and ev.dsr_trial_count != logged_trial_count
    ):
        # DSR against anything but the logged count is meaningless (doc 03 §8.2 row 4).
        dsr = Row(
            dsr.criterion,
            dsr.threshold,
            f"{dsr.measured} vs {ev.dsr_trial_count} trials, log has {logged_trial_count}",
            "FAIL",
        )
    rows.append(dsr)
    rows += [
        _num("5_pbo", c["5_pbo"], ev.pbo, "{:.1%}"),
        _num("6_walk_forward_efficiency", c["6_walk_forward_efficiency"], ev.wfe),
        _num("7_mar", c["7_mar"], ev.mar),
        _num(
            "8_bootstrap_p95_drawdown", c["8_bootstrap_p95_drawdown"], ev.bootstrap_p95_dd, "{:.1%}"
        ),
        _num(
            "9_random_control_percentile",
            c["9_random_control_percentile"],
            ev.random_percentile,
            "{:.0%}",
        ),
    ]
    # 10: criteria 1 and 3 still hold with costs x1.5.
    c1, c3 = c["1_expectancy_ci_lower"], c["3_expectancy_point"]
    if ev.stress_ci_lower is None or ev.stress_expectancy is None:
        rows.append(Row("10_cost_stress", "1 and 3 hold at 1.5x costs", "-", "MISSING"))
    else:
        ok = _cmp(c1["op"], ev.stress_ci_lower, c1["value"]) and _cmp(
            c3["op"], ev.stress_expectancy, c3["value"]
        )
        rows.append(
            Row(
                "10_cost_stress",
                "1 and 3 hold at 1.5x costs",
                f"lo {ev.stress_ci_lower:+.3f}R, E {ev.stress_expectancy:+.3f}R",
                "PASS" if ok else "FAIL",
            )
        )
    rows.append(_num("11_parameter_plateau", c["11_parameter_plateau"], ev.plateau_ratio, "{:.0%}"))
    # 12: holdout >= 50% of development expectancy.
    if ev.holdout_expectancy is None or ev.development_expectancy is None:
        rows.append(Row("12_holdout_degradation", ">= 0.5 x development", "-", "MISSING"))
    else:
        ratio = (
            ev.holdout_expectancy / ev.development_expectancy
            if ev.development_expectancy > 0
            else float("-inf")
        )
        rows.append(_num("12_holdout_degradation", c["12_holdout_degradation"], ratio, "{:.0%}"))
    # 13: crypto only - positive expectancy in both bull and bear.
    if ev.market not in c["13_regime_coverage"]["markets"]:
        rows.append(
            Row("13_regime_coverage", "bull > 0 and bear > 0", "n/a for " + ev.market, "N/A")
        )
    else:
        need = c["13_regime_coverage"]["requires"]
        if not all(k in ev.regime_expectancy for k in need):
            rows.append(Row("13_regime_coverage", "bull > 0 and bear > 0", "-", "MISSING"))
        else:
            ok = all(ev.regime_expectancy[k] > 0 for k in need)
            meas = ", ".join(f"{k} {ev.regime_expectancy[k]:+.3f}R" for k in need)
            rows.append(
                Row("13_regime_coverage", "bull > 0 and bear > 0", meas, "PASS" if ok else "FAIL")
            )
    # 14: FX only - share of basket profitable.
    if ev.market not in c["14_instrument_breadth"]["markets"]:
        rows.append(Row("14_instrument_breadth", "> 0.6", "n/a for " + ev.market, "N/A"))
    else:
        rows.append(
            _num(
                "14_instrument_breadth", c["14_instrument_breadth"], ev.instrument_breadth, "{:.0%}"
            )
        )
    if ev.cross_market_consistent is None:
        rows.append(Row("15_cross_market", "directionally consistent", "-", "MISSING"))
    else:
        rows.append(
            Row(
                "15_cross_market",
                "directionally consistent",
                str(ev.cross_market_consistent),
                "PASS" if ev.cross_market_consistent else "FAIL",
            )
        )
    return Verdict(rows)
