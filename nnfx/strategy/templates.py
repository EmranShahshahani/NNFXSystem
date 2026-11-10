"""Templates: read-only Strategy Documents users clone (Strategy Builder ticket 12, ADR 10).

A Template is a validated ``StrategyDocument`` plus where each of its Blocks
comes from: the blueprint video numbers (and a note) behind every Block and
behind the Risk section. Nothing here can be edited in place; ``clone`` hands
out a plain dict (metadata pointing at the Template and its version) that
the user changes freely and validates like any other document.

Every blueprint number is a parameter, never a constant. Where the blueprint
gives two values the Template takes the series-summary one and the other stays
a parameter (spec): the 10R step is 15% (``f3``; the blueprint also says 20%),
and risk is tiered 0.25-1.0% (``risk.sizing = "fixed"`` gives the 0.5% base).

Tickets from 12 on add each new Block here too, enabled or disabled as the
blueprint says.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from nnfx.strategy.document import StrategyDocument, validate_document

TCP_SLUG = "tcp_azizpour"


@dataclass(frozen=True)
class BlockSource:
    """Where one Block (or the Risk section) comes from in the blueprint."""

    videos: tuple[int, ...] = ()
    note: str = ""  # a blueprint document or section, for rules the videos do not number

    def record(self) -> dict[str, Any]:
        return {"videos": list(self.videos), "note": self.note}


@dataclass(frozen=True)
class Template:
    slug: str
    name: str
    version: int
    description: str
    document: StrategyDocument
    sources: tuple[BlockSource, ...]  # one per document Block, in order
    risk_sources: BlockSource

    def clone(self, name: str | None = None) -> dict[str, Any]:
        """A fresh, editable copy of the document: its own name, version 1, this Template as parent."""
        raw: dict[str, Any] = copy.deepcopy(self.document.model_dump(mode="json"))
        raw["metadata"] = {
            "name": name or f"{self.name} (کپی)",
            "version": 1,
            "parent": self.slug,
            "parent_version": self.version,
            "description": "",
        }
        return raw

    def listing(self, *, full: bool = False) -> dict[str, Any]:
        doc = self.document
        out: dict[str, Any] = {
            "slug": self.slug,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "fingerprint": doc.fingerprint(),
            "read_only": True,
            "timeframes": doc.timeframes.as_dict(),
            "blocks": [
                {
                    "kind": str(b.kind),
                    "type": b.type,
                    "enabled": b.enabled,
                    "sources": s.record(),
                }
                for b, s in zip(doc.blocks, self.sources, strict=True)
            ],
            "risk_sources": self.risk_sources.record(),
        }
        if full:
            out["document"] = doc.model_dump(mode="json")
        return out


# (kind, type, enabled, params, source). Order matters: it is the document's Block order.
_Row = tuple[str, str, bool, dict[str, Any], BlockSource]

_CANDLE = {"only_setups": ["candle_setup"]}
_BOX = {"only_setups": ["box_breakout"]}

_TCP_BLOCKS: list[_Row] = [
    # --- Context: the direction the wave cycles and the 3-SMA system allow
    ("context", "wave_cycles", True, {}, BlockSource((26, 63, 64))),
    ("context", "three_sma_alignment", True, {}, BlockSource((34,), "3-SMA system note (10)")),
    ("context", "choppy_regime", True, {}, BlockSource((27,), "3-SMA entanglement filter (10)")),
    ("context", "sma_baseline_filter", True, {}, BlockSource((37,), "the 99 filter")),
    ("context", "dow_trend", False, {}, BlockSource((3, 28))),  # wave_cycles reads Dow states
    ("context", "overextension_guard", False, {}, BlockSource((34,), "99 SMA gravity filter")),
    ("context", "sma_slope_gate", False, {}, BlockSource((34,), "slope degradation governor")),
    # --- Setups: the Candle Setup and the Box Breakout lead
    ("setup", "candle_setup", True, {}, BlockSource((35, 36, 37))),
    ("setup", "box_breakout", True, {}, BlockSource((21,), "blueprint 01 (B)")),
    ("setup", "box_extremes", False, {}, BlockSource((64,), "two-way trading box")),
    # --- Candle Setup confirmations (the Second Wave is "ideally": a score, not a refusal)
    ("confirmation", "second_wave", True, {**_CANDLE, "hard": False}, BlockSource((35,))),
    ("confirmation", "rsi_momentum", True, _CANDLE, BlockSource((13,), "RSI 14 surge (01 A)")),
    ("confirmation", "volume_continuation", True, _CANDLE, BlockSource((33, 35))),
    ("confirmation", "volume_expansion", False, _CANDLE, BlockSource((31, 32))),
    ("confirmation", "sma_crossover", False, _CANDLE, BlockSource((), "crossover dynamics (10)")),
    ("confirmation", "level_location", False, _CANDLE, BlockSource((4, 5, 36))),
    # --- Box Breakout confirmations
    ("confirmation", "touch_count", True, _BOX, BlockSource((21,))),
    ("confirmation", "breakout_body_close", True, {**_BOX, "hard": True}, BlockSource((21,))),
    ("confirmation", "breakout_range", True, _BOX, BlockSource((24,))),
    ("confirmation", "consecutive_closes", True, _BOX, BlockSource((24,))),
    ("confirmation", "box_volume_dryup", True, _BOX, BlockSource((29,), "blueprint 01 (B)")),
    # --- Execution, Stop, Exit
    ("execution", "stop_market", True, {}, BlockSource((35, 41), "Trigger / stop-market (01)")),
    ("stop", "structural_stop", True, {}, BlockSource((6,))),
    ("exit", "profit_chain", True, {}, BlockSource((19, 20), "blueprint 01 (B); 61-70 recycling")),
    ("exit", "fixed_r", False, {"r": 2.0}, BlockSource((), "no exit below 2R (01 B)")),
]


def _raw_tcp() -> dict[str, Any]:
    return {
        "metadata": {
            "name": "TCP Azizpour",
            "version": 1,
            "description": (
                "Trade City Pro (Arshia Azizpour): the blueprint's defaults. HWC daily "
                "(weekly is a one-line change), MWC 4H, LWC 15m, positions managed on 4H closes."
            ),
        },
        "timeframes": {"hwc": "D1", "mwc": "H4", "lwc": "M15", "management": "H4"},
        "universe": [],
        "blocks": [
            {"kind": k, "type": t, "enabled": e, "params": p} for k, t, e, p, _ in _TCP_BLOCKS
        ],
        # Tiers 0.25-1.0% by Confluence Score, the Streak Governor (3 losses -> 0.25%, 5 -> a
        # 48h halt), the -1.5% daily limit and the Leverage Governor: the schema defaults.
        "risk": {"sizing": "tiered"},
    }


def _build() -> dict[str, Template]:
    res = validate_document(_raw_tcp())
    if res.document is None:  # a Template that does not validate is a bug in this file
        raise RuntimeError(f"the TCP Template is invalid:\n{res.render()}")
    doc = res.document
    tcp = Template(
        TCP_SLUG,
        doc.metadata.name,
        doc.metadata.version,
        doc.metadata.description,
        doc,
        tuple(s for *_, s in _TCP_BLOCKS),
        BlockSource((7, 62, 75, 85), "tiers, Streak Governor, loss limits, Leverage Governor"),
    )
    return {tcp.slug: tcp}


TEMPLATES: dict[str, Template] = _build()


def get_template(slug: str) -> Template:
    try:
        return TEMPLATES[slug]
    except KeyError:
        raise KeyError(f"unknown Template «{slug}»; known: {', '.join(TEMPLATES)}") from None


def list_templates() -> list[dict[str, Any]]:
    return [t.listing() for t in TEMPLATES.values()]


__all__ = [
    "TCP_SLUG",
    "TEMPLATES",
    "BlockSource",
    "Template",
    "get_template",
    "list_templates",
]
