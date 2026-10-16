"""Ticket 01: the config schema fails loudly."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from nnfx.config import SystemConfig, load_system_config
from nnfx.indicators.slots import IndicatorSet

ROOT = Path(__file__).parent.parent


def _raw():
    return yaml.safe_load((ROOT / "config/system.yaml").read_text())


def test_shipped_config_loads():
    cfg = load_system_config(ROOT / "config/system.yaml")
    assert cfg.rules.one_candle_rule == "off" and cfg.risk.positions_per_entry == 2
    IndicatorSet(cfg.slots)


def test_unknown_slot_name_fails():
    raw = _raw()
    raw["slots"]["c3"] = {"name": "macd"}
    with pytest.raises(ValidationError, match="c3"):
        SystemConfig.model_validate(raw)


def test_typo_in_rule_fails():
    raw = _raw()
    raw["rules"]["bridge_to_far"] = False
    with pytest.raises(ValidationError, match="bridge_to_far"):
        SystemConfig.model_validate(raw)


def test_unknown_indicator_and_param_fail():
    raw = _raw()
    raw["slots"]["c1"] = {"name": "nope"}
    with pytest.raises(KeyError, match="nope"):
        IndicatorSet(SystemConfig.model_validate(raw).slots)
    raw["slots"]["c1"] = {"name": "macd", "params": {"fats": 3}}
    with pytest.raises(ValueError, match="fats"):
        IndicatorSet(SystemConfig.model_validate(raw).slots)


def test_kill_switch_requires_approval():
    raw = _raw()
    raw["risk"]["kill_switch_drawdown"] = 0.2
    with pytest.raises(ValidationError, match="approved"):
        SystemConfig.model_validate(raw)
    raw["risk"]["kill_switch_approved"] = True
    assert SystemConfig.model_validate(raw).risk.kill_switch_drawdown == 0.2


def test_one_candle_rule_accepts_yaml_false():
    raw = _raw()
    raw["rules"]["one_candle_rule"] = False
    assert SystemConfig.model_validate(raw).rules.one_candle_rule == "off"


def test_overrides_and_digest():
    cfg = load_system_config(ROOT / "config/system.yaml")
    other = cfg.with_overrides({"rules.bridge_too_far": False})
    assert other.rules.bridge_too_far is False and other.digest() != cfg.digest()
    assert cfg.with_overrides({}).digest() == cfg.digest()
