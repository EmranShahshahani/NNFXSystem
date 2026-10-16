"""The candidate pool per slot (doc 05 §3-§8) as data, not code branches."""

from __future__ import annotations

from dataclasses import dataclass

from nnfx.config import SlotSpec
from nnfx.indicators.base import REGISTRY, SlotKind, registered

# Doc 05 candidates not yet wrapped. Kept here so the pool's gaps are visible.
PLANNED: dict[SlotKind, tuple[str, ...]] = {
    "baseline": ("t3", "vidya", "ssl_channel_baseline", "range_filter", "ehlers_supersmoother"),
    "confirmation": (
        "schaff_trend_cycle",
        "coral_trend",
        "half_trend",
        "qqe",
        "wave_trend",
        "tdfi",
        "kase_permission",
        "ergodic_tvi",
        "trend_trigger_factor",
        "smi",
        "ttm_trend",
    ),
    "volume": (
        "vpci",
        "damiani_volatmeter",
        "volume_zone_oscillator",
        "chaikin_money_flow",
        "mfi",
        "klinger",
        "obv_slope",
        "vhf",
    ),
    "exit": ("rex", "qqe_exit", "braid_filter", "aroon_exit", "waddah_dead_zone"),
    "volatility": ("keltner_width", "garman_klass", "yang_zhang"),
}


@dataclass(frozen=True)
class CatalogueEntry:
    kind: SlotKind
    name: str
    family: str
    defaults: dict[str, object]
    grid: dict[str, tuple[object, ...]]
    implemented: bool


def catalogue() -> list[CatalogueEntry]:
    out = []
    for kind, name in registered():
        cls = REGISTRY[(kind, name)]
        out.append(CatalogueEntry(kind, name, cls.family, dict(cls.defaults), dict(cls.grid), True))
    for kind, names in PLANNED.items():
        out += [CatalogueEntry(kind, n, "planned", {}, {}, False) for n in names]
    return out


def default_pool(kind: SlotKind) -> list[SlotSpec]:
    """Published defaults only - they carry no in-sample fitting from this project."""
    return [SlotSpec(name=n, params={}) for k, n in registered(kind)]


def render_catalogue() -> str:
    lines = ["| slot | name | family | defaults | grid | status |", "|---|---|---|---|---|---|"]
    for e in catalogue():
        lines.append(
            f"| {e.kind} | {e.name} | {e.family} | {e.defaults} | {e.grid} | {'implemented' if e.implemented else 'planned'} |"
        )
    return "\n".join(lines)
