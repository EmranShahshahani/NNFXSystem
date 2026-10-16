"""Rule flags and the ablation runner (doc 03 §6, ticket 20).

Each structural rule is toggled independently on the development segment and
its marginal contribution measured. The exit indicator and the trailing stop
compete to close the same position, so they are ablated as a pair (doc 05 §7).
Session-close variants need a data provider that re-resamples H1 bars, since
resampling happens only in the data layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from nnfx.config import SystemConfig
from nnfx.research.evaluate import Evaluator, TrialResult

Variant = tuple[str, dict[str, Any]]

ABLATIONS: dict[str, list[Variant]] = {
    "bridge_too_far": [
        ("on", {"rules.bridge_too_far": True}),
        ("off", {"rules.bridge_too_far": False}),
    ],
    "bridge_multiple": [(f"{m}xATR", {"rules.bridge_multiple": m}) for m in (0.5, 1.0, 1.5)],
    "seven_candle_rule": [
        ("on", {"rules.seven_candle_rule": True}),
        ("off", {"rules.seven_candle_rule": False}),
    ],
    "seven_candle_inclusive": [
        ("inclusive", {"rules.seven_candle_inclusive": True}),
        ("exclusive", {"rules.seven_candle_inclusive": False}),
    ],
    "one_candle_rule": [(v, {"rules.one_candle_rule": v}) for v in ("off", "A", "B")],
    "continuation": [("on", {"rules.continuation": True}), ("off", {"rules.continuation": False})],
    "c2_requirement": [
        ("required", {"rules.c2_required": True}),
        ("not_required", {"rules.c2_required": False}),
    ],
    "c2_mode": [("state", {"rules.c2_mode": "state"}), ("signal", {"rules.c2_mode": "signal"})],
    "position_split": [
        ("two_x_1pct", {"risk.positions_per_entry": 2}),
        ("single_2pct", {"risk.positions_per_entry": 1}),
    ],
    "atr_freeze": [
        ("frozen", {"risk.atr_frozen_at_entry": True}),
        ("live", {"risk.atr_frozen_at_entry": False}),
    ],
    "trail_atr": [
        ("live", {"risk.trail_uses_live_atr": True}),
        ("frozen", {"risk.trail_uses_live_atr": False}),
    ],
    "session_close": [
        ("17:00_NY", {"session.close_tz": "America/New_York", "session.close_hour": 17}),
        ("00:00_UTC", {"session.close_tz": "UTC", "session.close_hour": 0}),
    ],
    "direction": [
        ("symmetric", {"rules.allow_short": True}),
        ("long_only", {"rules.allow_short": False}),
    ],
    "funding": [("on", {"costs.funding": True}), ("off", {"costs.funding": False})],
}


def exit_trailing_pairs(base: SystemConfig) -> list[Variant]:
    exit_spec = base.slots.exit.model_dump() if base.slots.exit else None
    out: list[Variant] = []
    for ex_label, ex in (("exit_on", exit_spec), ("exit_off", None)):
        if ex_label == "exit_on" and ex is None:
            continue
        for tr in (True, False):
            out.append(
                (
                    f"{ex_label}+trail_{'on' if tr else 'off'}",
                    {"slots.exit": ex, "risk.trailing": tr},
                )
            )
    return out


@dataclass
class AblationRow:
    rule: str
    variant: str
    is_base: bool
    trial: TrialResult


@dataclass
class AblationReport:
    base: TrialResult
    rows: list[AblationRow] = field(default_factory=list)

    def render(self) -> str:
        b = self.base.metrics
        out = [
            f"Base: {b.summary()}",
            "",
            "| rule | variant | entries | E[R] | 95% BCa | win% | dE[R] vs base | dEntries |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in self.rows:
            m = r.trial.metrics
            lo, hi = m.expectancy_ci
            out.append(
                f"| {r.rule} | {r.variant}{' (base)' if r.is_base else ''} | {m.n_entries} | {m.expectancy_r:+.3f} | "
                f"[{lo:+.3f}, {hi:+.3f}] | {m.win_rate:.1%} | {m.expectancy_r - b.expectancy_r:+.3f} | "
                f"{m.n_entries - b.n_entries:+d} |"
            )
        return "\n".join(out)


def _matches(base: SystemConfig, overrides: dict[str, Any]) -> bool:
    data = base.model_dump(mode="json")
    for path, v in overrides.items():
        node: Any = data
        for p in path.split("."):
            node = node.get(p) if isinstance(node, dict) else None
        if node != v:
            return False
    return True


def run_ablation(
    base: SystemConfig,
    evaluator: Evaluator,
    rules: Sequence[str] | None = None,
    *,
    include_exit_trailing: bool = True,
) -> AblationReport:
    if evaluator.segment_name != "development":
        raise ValueError("rule ablation runs on the development segment only (doc 03 §6)")
    base_trial = evaluator.evaluate(base, stage="ablation", label="base")
    report = AblationReport(base_trial)
    plan = {k: v for k, v in ABLATIONS.items() if rules is None or k in rules}
    if include_exit_trailing and (rules is None or "exit_x_trailing" in rules):
        plan["exit_x_trailing"] = exit_trailing_pairs(base)
    for rule, variants in plan.items():
        for label, ov in variants:
            cfg = base.with_overrides(ov)
            is_base = _matches(base, ov)
            trial = (
                base_trial
                if is_base
                else evaluator.evaluate(cfg, stage="ablation", label=f"{rule}={label}")
            )
            report.rows.append(AblationRow(rule, label, is_base, trial))
    return report
