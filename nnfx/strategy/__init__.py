"""Strategy Documents, the Block Library and the engine that runs them (ADR 10)."""

from nnfx.strategy.blocks import REGISTRY, BlockKind, StrategyData, block_catalogue
from nnfx.strategy.document import (
    StrategyDocument,
    ValidationIssue,
    ValidationResult,
    load_document,
    validate_document,
)
from nnfx.strategy.templates import TEMPLATES, Template, get_template, list_templates

__all__ = [
    "REGISTRY",
    "TEMPLATES",
    "BlockKind",
    "StrategyData",
    "StrategyDocument",
    "Template",
    "ValidationIssue",
    "ValidationResult",
    "block_catalogue",
    "get_template",
    "list_templates",
    "load_document",
    "validate_document",
]
