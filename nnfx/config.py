"""The whole system's behaviour as one validated file (doc 02 §5).

Every model forbids unknown keys: a typo in a slot or rule name fails loudly at
load time rather than silently disabling a filter.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ParamValue = int | float | str | bool


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SlotSpec(Strict):
    name: str
    params: dict[str, ParamValue] = Field(default_factory=dict)


class Slots(Strict):
    atr: SlotSpec
    baseline: SlotSpec
    c1: SlotSpec
    c2: SlotSpec | None = None
    volume: SlotSpec | None = None
    exit: SlotSpec | None = None
    continuation: SlotSpec | None = None


SLOT_NAMES = tuple(Slots.model_fields)
SLOT_KIND = {
    "atr": "volatility",
    "baseline": "baseline",
    "c1": "confirmation",
    "c2": "confirmation",
    "volume": "volume",
    "exit": "exit",
    "continuation": "confirmation",
}


class RulesConfig(Strict):
    # Structural rules: each is a flag so the ablation study can toggle it (D2).
    bridge_too_far: bool = True
    bridge_multiple: float = Field(1.0, gt=0)
    seven_candle_rule: bool = True
    seven_candle_bars: int = Field(7, ge=1)
    # A6: inclusive means the signal bar itself counts as bar 1.
    seven_candle_inclusive: bool = True
    # A7: two irreducible readings, both off by default.
    one_candle_rule: Literal["off", "A", "B"] = "off"
    pullback: bool = True
    baseline_entries: bool = True
    continuation: bool = True
    # A4: C2 must agree (state) by default; firing (signal) is testable.
    c2_required: bool = True
    c2_mode: Literal["state", "signal"] = "state"
    volume_required: bool = True
    # Off only for screening a C1 in isolation (doc 05 §10 stage 1).
    baseline_filter: bool = True
    exit_on_baseline_cross: bool = True
    # Long-only spot benchmark is allow_short=false (doc 04 §6).
    allow_long: bool = True
    allow_short: bool = True

    @field_validator("one_candle_rule", mode="before")
    @classmethod
    def _bool_off(cls, v: Any) -> Any:
        return "off" if v is False or v is None else v


class RiskConfig(Strict):
    risk_per_position: float = Field(0.01, gt=0, lt=0.2)
    positions_per_entry: Literal[1, 2] = 2
    stop_atr_multiple: float = Field(1.5, gt=0)
    tp1_atr_multiple: float = Field(1.0, gt=0)
    trail_atr_multiple: float = Field(1.5, gt=0)
    trail_step_atr: float = Field(0.5, gt=0)
    # A3 / A11, independent toggles.
    atr_frozen_at_entry: bool = True
    # Runner breakeven + ATR trail; ablated jointly with the exit indicator (doc 05 §7).
    trailing: bool = True
    trail_uses_live_atr: bool = True
    # Walking-skeleton mode: a fixed number of units, no risk sizing.
    fixed_units: float | None = None
    sizing_tolerance: float = Field(0.25, ge=0)
    max_positions_per_ccy: int | None = 2
    max_beta_weighted_risk: float | None = None
    min_liquidation_atr: float = 3.0
    leverage: float = Field(1.0, gt=0)
    # Kill switch: a drawdown fraction the operator has explicitly approved.
    kill_switch_drawdown: float | None = None
    kill_switch_approved: bool = False

    @model_validator(mode="after")
    def _kill_switch_needs_approval(self) -> RiskConfig:
        if self.kill_switch_drawdown is not None and not self.kill_switch_approved:
            raise ValueError(
                "kill_switch_drawdown is set but kill_switch_approved is false; the threshold "
                "must be derived from the bootstrap and approved by the operator (story 51)"
            )
        return self


class SessionConfig(Strict):
    close_tz: str = "America/New_York"
    close_hour: int = Field(17, ge=0, le=23)
    # Instruments with has_sessions=False (24/7 crypto) close here instead.
    continuous_close_tz: str = "UTC"
    continuous_close_hour: int = Field(0, ge=0, le=23)


class CostToggles(Strict):
    enabled: bool = True
    stress_multiplier: float = Field(1.0, ge=0)
    funding: bool = True
    swap: bool = True


class AccountConfig(Strict):
    initial_equity: float = Field(10_000.0, gt=0)
    currency: str = "USD"


class SystemConfig(Strict):
    slots: Slots
    rules: RulesConfig = RulesConfig()
    risk: RiskConfig = RiskConfig()
    session: SessionConfig = SessionConfig()
    costs: CostToggles = CostToggles()
    account: AccountConfig = AccountConfig()

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def with_overrides(self, overrides: dict[str, Any]) -> SystemConfig:
        """Apply dotted-path overrides, e.g. {"rules.bridge_too_far": False}."""
        data = self.model_dump(mode="json")
        for path, value in overrides.items():
            node = data
            *parents, leaf = path.split(".")
            for p in parents:
                if node.get(p) is None:
                    node[p] = {}
                node = node[p]
            if leaf not in node and not isinstance(node, dict):
                raise KeyError(path)
            node[leaf] = value
        return SystemConfig.model_validate(data)


def load_system_config(path: Path | str) -> SystemConfig:
    raw = yaml.safe_load(Path(path).read_text())
    return SystemConfig.model_validate(raw)
