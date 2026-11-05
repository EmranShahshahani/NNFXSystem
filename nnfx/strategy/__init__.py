"""Strategy Documents, the Block Library and the engine that runs them (ADR 10)."""

from nnfx.strategy.blocks import REGISTRY, BlockKind, StrategyData, block_catalogue
from nnfx.strategy.document import (
    StrategyDocument,
    ValidationIssue,
    ValidationResult,
    load_document,
    validate_document,
)

__all__ = [
    "REGISTRY",
    "BlockKind",
    "StrategyData",
    "StrategyDocument",
    "ValidationIssue",
    "ValidationResult",
    "block_catalogue",
    "load_document",
    "validate_document",
]
