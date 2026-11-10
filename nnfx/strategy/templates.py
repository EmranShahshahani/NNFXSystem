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
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
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
    ("context", "chase_guard", False, {}, BlockSource((64,), "no chasing after an outsized bar")),
    ("context", "roc_ceiling", False, {}, BlockSource((55,), "4H ROC at its 200-bar ceiling")),
    ("context", "trend_health", False, {}, BlockSource((22, 23, 27, 67), "trend health flags")),
    # --- Sessions (ticket 18): UTC windows, off by default
    ("context", "session_filter", False, {}, BlockSource((58,), "no entries 21:00-00:00 UTC")),
    ("context", "session_regime", False, {}, BlockSource((58,), "session correlation regimes")),
    # --- Market filters (ticket 20): need the dominance / pair series, off by default
    ("market_filter", "dominance_regime", False, {}, BlockSource((12, 66), "regime matrix")),
    ("market_filter", "relative_strength", False, {}, BlockSource((12, 59, 83), "ALT/BTC sieve")),
    # --- Setups: the Candle Setup and the Box Breakout lead
    ("setup", "candle_setup", True, {}, BlockSource((35, 36, 37))),
    ("setup", "box_breakout", True, {}, BlockSource((20, 21), "blueprint 01 (B)")),
    ("setup", "box_extremes", False, {}, BlockSource((64,), "two-way trading box")),
    # --- Trendlines and Fibonacci (ticket 19), off by default
    ("setup", "trendline_bounce", False, {}, BlockSource((25,), "third-touch trendline")),
    ("setup", "trendline_break", False, {}, BlockSource((25,), "close through a trendline")),
    ("setup", "fib_reclaim", False, {}, BlockSource((81,), "0.382 sweep and reclaim")),
    # --- The other setups, present but disabled (ticket 14): a clone switches on what it trades
    ("setup", "engulfing", False, {}, BlockSource((38,), "engulfing without gaps (04)")),
    ("setup", "giant_indecision", False, {}, BlockSource((26,), "giant indecision reversal (03)")),
    ("setup", "absorption_wick", False, {}, BlockSource((68,), "absorption wick at support (07)")),
    ("setup", "layered_setup", False, {}, BlockSource((69,), "the LA layers setup (07)")),
    ("setup", "dow_continuation", False, {}, BlockSource((62,), "Dow wave continuation (07)")),
    (
        "setup",
        "binary_scenario",
        False,
        {"side": "long"},
        BlockSource((87,), "binary scenario (09)"),
    ),
    (
        "setup",
        "binary_scenario",
        False,
        {"side": "short"},
        BlockSource((87,), "binary scenario (09)"),
    ),
    ("setup", "momentum_continuation", False, {}, BlockSource((66,), "continuation mode (07)")),
    # --- Bollinger setups (ticket 18)
    ("setup", "bb_htf_touch", False, {}, BlockSource((14,), "HTF-directed touches and crosses")),
    ("setup", "bb_squeeze", False, {}, BlockSource((14,), "squeeze and expansion")),
    # --- Candle Setup confirmations (the Second Wave is "ideally": a score, not a refusal)
    ("confirmation", "second_wave", True, {**_CANDLE, "hard": False}, BlockSource((35,))),
    ("confirmation", "rsi_momentum", True, _CANDLE, BlockSource((13,), "RSI 14 surge (01 A)")),
    ("confirmation", "volume_continuation", True, _CANDLE, BlockSource((33, 35))),
    ("confirmation", "volume_expansion", False, _CANDLE, BlockSource((31, 32))),
    ("confirmation", "sma_crossover", False, _CANDLE, BlockSource((), "crossover dynamics (10)")),
    ("confirmation", "level_location", False, _CANDLE, BlockSource((4, 5, 36))),
    # --- The oscillator methods (ticket 15): filters and alerts, never triggers; off by default
    ("confirmation", "osc_momentum", False, {}, BlockSource((46,), "method 1: OB/OS as momentum")),
    ("confirmation", "osc_inflection", False, {}, BlockSource((47,), "method 2: 50/0 line")),
    ("confirmation", "osc_signal_cross", False, {}, BlockSource((48,), "method 3: signal line")),
    ("confirmation", "osc_level_break", False, {}, BlockSource((49, 54), "method 4: levels")),
    ("confirmation", "rsi_bb_reentry", False, {}, BlockSource((15, 50), "method 5: BB on RSI")),
    ("confirmation", "osc_recalibrated", False, {}, BlockSource((51,), "method 6: cycle length")),
    ("confirmation", "osc_mf", False, {}, BlockSource((52,), "method 7: multiplier factor")),
    ("confirmation", "osc_divergence", False, {}, BlockSource((53,), "method 8: divergences")),
    ("confirmation", "rsi_cascade", False, {}, BlockSource((27, 46, 54), "RSI cascade")),
    ("confirmation", "macd_cross", False, {}, BlockSource((54,), "MACD cross, not near zero")),
    ("confirmation", "roc_box_breakout", False, {}, BlockSource((55,), "ROC leaves its box")),
    # --- Volume rules (ticket 17): relative to the baseline, off by default
    ("confirmation", "volume_matrix", False, {}, BlockSource((29,), "four-state volume matrix")),
    ("confirmation", "effort_result", False, {}, BlockSource((33,), "absorption and vacuum")),
    ("confirmation", "volume_climax", False, {}, BlockSource((30, 31), "no buying the climax")),
    ("confirmation", "low_volume_dip", False, {}, BlockSource((30, 31), "low-volume reversal")),
    ("confirmation", "volume_node", False, {}, BlockSource((32,), "200-bar volume profile")),
    # --- Bollinger runway and floor pivots (ticket 18)
    ("confirmation", "bb_runway", False, {}, BlockSource((14,), "double band momentum runway")),
    ("confirmation", "pivot_breach", False, {}, BlockSource((57,), "beyond R1/S1 on 4H or weekly")),
    ("confirmation", "fib_confluence", False, {}, BlockSource((80,), "fib with two other factors")),
    # --- Box Breakout confirmations
    ("confirmation", "touch_count", True, _BOX, BlockSource((21,))),
    ("confirmation", "breakout_body_close", True, {**_BOX, "hard": True}, BlockSource((21,))),
    ("confirmation", "breakout_range", True, _BOX, BlockSource((24,))),
    ("confirmation", "consecutive_closes", True, _BOX, BlockSource((24,))),
    ("confirmation", "box_volume_dryup", True, _BOX, BlockSource((29,), "blueprint 01 (B)")),
    # --- Execution, Stop, Exit
    ("execution", "stop_market", True, {}, BlockSource((35, 41), "Trigger / stop-market (01)")),
    ("execution", "adx_order_type", False, {}, BlockSource((56,), "stop order or body close")),
    (
        "execution",
        "wall_trigger",
        False,
        {},
        BlockSource((41, 50), "order-book walls (live-first)"),
    ),
    ("stop", "structural_stop", True, {}, BlockSource((6,))),
    (
        "stop",
        "wall_shielded_stop",
        False,
        {},
        BlockSource((41, 50), "order-book walls (live-first)"),
    ),
    ("exit", "profit_chain", True, {}, BlockSource((19,), "blueprint 01 (B); 61-70 recycling")),
    ("exit", "wall_targets", False, {}, BlockSource((41, 50), "targets in front of walls")),
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


TEMPLATES: Mapping[str, Template] = MappingProxyType(_build())  # read-only, like each Template


def get_template(slug: str) -> Template:
    try:
        return TEMPLATES[slug]
    except KeyError:
        raise KeyError(f"قالب «{slug}» شناخته نشده است؛ قالب‌ها: {', '.join(TEMPLATES)}") from None


def list_templates(*, full: bool = False) -> list[dict[str, Any]]:
    return [t.listing(full=full) for t in TEMPLATES.values()]


__all__ = [
    "TCP_SLUG",
    "TEMPLATES",
    "BlockSource",
    "Template",
    "get_template",
    "list_templates",
]
