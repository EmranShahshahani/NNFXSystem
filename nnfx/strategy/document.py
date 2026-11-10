"""Strategy Documents: a user's strategy as data (Strategy Builder ticket 05, ADR 10).

A document has metadata, timeframe roles, a universe, an ordered list of
Blocks ``{kind, type, enabled, params}`` resolved through the registry, and a
Risk section. ``validate_document`` returns every problem at once, each with a
path and a Persian message for the UI; a valid document has every parameter
resolved (defaults filled in), so its fingerprint, the hash of its content,
does not depend on key order or on whether defaults were written out.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

from nnfx.data.bars import BASE_TIMEFRAMES, TIMEFRAMES
from nnfx.research.logs import canonical_json
from nnfx.strategy import bands as _bands  # noqa: F401
from nnfx.strategy import dominance as _dominance  # noqa: F401
from nnfx.strategy import fibonacci as _fibonacci  # noqa: F401
from nnfx.strategy import health as _health  # noqa: F401
from nnfx.strategy import library as _library  # noqa: F401  (registers the Blocks)
from nnfx.strategy import momentum as _momentum  # noqa: F401
from nnfx.strategy import orderbook_blocks as _orderbook_blocks  # noqa: F401
from nnfx.strategy import oscillators as _oscillators  # noqa: F401
from nnfx.strategy import pivots as _pivots  # noqa: F401
from nnfx.strategy import sessions as _sessions  # noqa: F401
from nnfx.strategy import setups as _setups  # noqa: F401  (registers the remaining setups)
from nnfx.strategy import trendlines as _trendlines  # noqa: F401
from nnfx.strategy import volume as _volume  # noqa: F401
from nnfx.strategy.blocks import KIND_FA, REGISTRY, Block, BlockKind

REQUIRED_KINDS = (BlockKind.SETUP, BlockKind.EXECUTION, BlockKind.STOP, BlockKind.EXIT)
SINGLE_KINDS = (BlockKind.STOP, BlockKind.EXIT)  # one enabled Block each decides


class _Strict(BaseModel):
    """Strict: "4" is not a number (an int is accepted for a float)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Metadata(_Strict):
    name: str = Field(min_length=1)
    version: int = Field(1, ge=1)
    parent: str | None = None
    parent_version: int | None = None
    description: str = ""


class TimeframeRoles(_Strict):
    hwc: str = "D1"
    mwc: str = "H4"
    lwc: str = "M15"
    # Where open positions are managed (the blueprint's 4H closes); unset means the MWC.
    management: str | None = None

    def as_dict(self) -> dict[str, str]:
        out = {"hwc": self.hwc, "mwc": self.mwc, "lwc": self.lwc}
        if self.management is not None:
            out["management"] = self.management
        return out


class BlockSpec(BaseModel):
    # Not strict as a whole: ``kind`` arrives as text and becomes a BlockKind.
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BlockKind
    type: str
    enabled: StrictBool = True
    params: dict[str, Any] = Field(default_factory=dict)


CEILING = 0.01  # the blueprint's hard 1% ceiling on risk per trade


class StreakGovernor(_Strict):
    """Consecutive losses cut risk, more of them halt trading (blueprint: video 75)."""

    enabled: bool = True
    reduce_after: int = Field(3, ge=1)
    reduced_risk: float = Field(0.0025, gt=0, le=CEILING)
    halt_after: int = Field(5, ge=1)
    halt_hours: float = Field(48, gt=0)


class LossLimits(_Strict):
    """Realised loss limits as fractions of the period's starting balance (video 85, 62)."""

    daily: float | None = Field(0.015, gt=0, lt=1)
    daily_halt_hours: float = Field(24, gt=0)
    weekly: float | None = Field(None, gt=0, lt=1)  # the blueprint names it without a number


class PerformanceGovernor(_Strict):
    """Degradation shrinks risk until it recovers."""

    enabled: bool = True
    window: int = Field(50, ge=1, le=500)  # the broker reports the last 500 closed positions
    min_win_rate: float = Field(0.40, ge=0, le=1)
    max_drawdown: float = Field(0.06, gt=0, lt=1)  # until a new equity high
    reduced_risk: float = Field(0.0025, gt=0, le=CEILING)


class LeverageGovernor(_Strict):
    """Leverage only sets margin: it must keep liquidation beyond the stop."""

    leverage: float = Field(1.0, ge=1)
    safety: float = Field(1.5, ge=1)  # max leverage < 1 / (stop% x safety)


class RiskSection(_Strict):
    # "fixed": risk_per_trade (video 75); "tiered": tiers[Confluence Score] (video 7).
    sizing: Literal["fixed", "tiered"] = "fixed"
    risk_per_trade: float = Field(0.005, gt=0, le=CEILING)
    tiers: list[float] = Field(default_factory=lambda: [0.0025, 0.005, 0.0075, 0.01])
    milestone_pct: float | None = Field(0.10, gt=0, lt=1)  # resize risk only at +/-10% equity
    # Open + resting risk across all symbols (a portfolio cap, not a per-trade risk).
    max_open_risk: float | None = Field(None, gt=0, le=0.2)
    max_positions_per_symbol: int = Field(1, ge=1)
    atr_period: int = Field(14, ge=1)  # the ATR the risk manager's liquidation check uses
    streak: StreakGovernor = StreakGovernor()
    loss_limits: LossLimits = LossLimits()
    performance: PerformanceGovernor = PerformanceGovernor()
    leverage: LeverageGovernor = LeverageGovernor()

    @field_validator("tiers")
    @classmethod
    def _tiers(cls, v: list[float]) -> list[float]:
        if not v or any(not 0 < t <= CEILING for t in v):
            raise ValueError(f"هر سطح ریسک باید بیشتر از صفر و حداکثر {CEILING:.0%} باشد.")
        if any(b < a for a, b in pairwise(v)):
            raise ValueError("سطح‌های ریسک باید با افزایش امتیاز هم‌گرایی افزایش یابند (نه کاهش).")
        return v


class ChecklistSection(_Strict):
    """How the Pre-Trade Checklist judges a setup (ADR 10 §11)."""

    # A stop is "justified" only on a setup that passed every applicable check AND
    # reached this Confluence Score (blueprint: "a valid setup with high confluence").
    justified_min_score: float = Field(1.0, ge=0)


class StrategyDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    metadata: Metadata
    timeframes: TimeframeRoles = TimeframeRoles()
    universe: list[str] = Field(default_factory=list)
    blocks: list[BlockSpec]
    risk: RiskSection = RiskSection()
    checklist: ChecklistSection = ChecklistSection()

    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json")).encode()).hexdigest()[
            :16
        ]

    def instances(self, kind: BlockKind) -> list[tuple[int, Block[Any]]]:
        """The enabled Blocks of ``kind``, with their positions in the document."""
        out = []
        for i, b in enumerate(self.blocks):
            if b.enabled and b.kind == kind:
                cls = REGISTRY[b.type]
                out.append((i, cls(cls.Params(**b.params))))
        return out


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str  # Persian, for the UI


@dataclass
class ValidationResult:
    document: StrategyDocument | None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.document is not None

    def render(self) -> str:
        return "\n".join(f"{i.path}: {i.message} [{i.code}]" for i in self.issues)


def _path(loc: tuple[Any, ...], prefix: str = "") -> str:
    out = prefix
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _fa(err: dict[str, Any]) -> str:
    """A Persian message for one pydantic error."""
    t, ctx = err.get("type", ""), err.get("ctx") or {}
    if t == "missing":
        return "این فیلد لازم است."
    if t.startswith(("float", "int", "decimal")) and ("parsing" in t or "type" in t):
        return "باید عدد باشد." if t.startswith(("float", "decimal")) else "باید عدد صحیح باشد."
    if t.startswith("bool"):
        return "باید درست یا نادرست باشد."
    if t == "greater_than":
        return f"باید بزرگ‌تر از {ctx.get('gt')} باشد."
    if t == "greater_than_equal":
        return f"باید دست‌کم {ctx.get('ge')} باشد."
    if t == "less_than":
        return f"باید کمتر از {ctx.get('lt')} باشد."
    if t == "less_than_equal":
        return f"باید حداکثر {ctx.get('le')} باشد."
    if t in ("literal_error", "enum"):
        return f"باید یکی از این‌ها باشد: {ctx.get('expected')}."
    if t == "string_too_short":
        return "نباید خالی باشد."
    if t == "extra_forbidden":
        return "این فیلد در طرح سند وجود ندارد."
    if t == "value_error" and ctx.get("error") is not None:
        return str(ctx["error"])  # our own validators write Persian
    return f"مقدار نامعتبر است ({err.get('msg', t)})."


def _check_timeframes(raw: Any, issues: list[ValidationIssue]) -> None:
    if not isinstance(raw, dict):
        return
    roles = {
        **TimeframeRoles().as_dict(),
        **{
            k: v
            for k, v in raw.items()
            if k in ("hwc", "mwc", "lwc", "management") and v is not None
        },
    }
    bad = False
    for role, tf in roles.items():
        if not isinstance(tf, str) or tf not in TIMEFRAMES:
            issues.append(
                ValidationIssue(
                    f"timeframes.{role}",
                    "bad_timeframe",
                    f"تایم‌فریم «{tf}» شناخته نشده است؛ یکی از {', '.join(TIMEFRAMES)}.",
                )
            )
            bad = True
    if bad:
        return
    if roles["lwc"] not in BASE_TIMEFRAMES:
        issues.append(
            ValidationIssue(
                "timeframes.lwc",
                "lwc_not_base",
                f"تایم‌فریم اجرا (LWC) باید پایهٔ داده باشد: {' یا '.join(BASE_TIMEFRAMES)}.",
            )
        )
    d = {r: TIMEFRAMES[tf] for r, tf in roles.items()}
    if not d["hwc"] >= d["mwc"] >= d["lwc"]:
        issues.append(
            ValidationIssue("timeframes", "role_order", "ترتیب نقش‌ها باید HWC ≥ MWC ≥ LWC باشد.")
        )
    if "management" in d and d["management"] < d["lwc"]:
        issues.append(
            ValidationIssue(
                "timeframes.management",
                "role_order",
                "تایم‌فریم مدیریت پوزیشن نمی‌تواند کوچک‌تر از تایم‌فریم اجرا (LWC) باشد.",
            )
        )


def _check_block(i: int, raw: Any, issues: list[ValidationIssue]) -> dict[str, Any] | None:
    """Validate one Block against the registry; returns its resolved params, or None."""
    at = f"blocks[{i}]"
    if not isinstance(raw, dict):
        issues.append(ValidationIssue(at, "bad_value", "هر بلوک باید یک شیء باشد."))
        return None
    try:  # the Block's own fields: kind, type, enabled, params (params checked below)
        BlockSpec.model_validate({**raw, "params": {}, "kind": BlockKind.SETUP, "type": "x"})
    except ValidationError as exc:
        for err in exc.errors():
            issues.append(
                ValidationIssue(_path(tuple(err["loc"]), at), "bad_value", _fa(dict(err)))
            )
        return None
    btype, kind = raw.get("type"), raw.get("kind")
    cls = REGISTRY.get(str(btype))
    if cls is None:
        issues.append(
            ValidationIssue(
                f"{at}.type", "unknown_block_type", f"نوع بلوک «{btype}» شناخته نشده است."
            )
        )
        return None
    if kind != cls.kind:
        try:
            given = KIND_FA[BlockKind(str(kind))]
        except ValueError:
            given = str(kind)
        issues.append(
            ValidationIssue(
                f"{at}.kind",
                "wrong_kind",
                f"بلوک «{btype}» از نوع «{KIND_FA[cls.kind]}» است، نه «{given}».",
            )
        )
        return None
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        issues.append(ValidationIssue(f"{at}.params", "bad_value", "پارامترها باید یک شیء باشند."))
        return None
    try:
        resolved: dict[str, Any] = cls.Params(**params).model_dump(mode="json")
        return resolved
    except ValidationError as exc:
        for err in exc.errors():
            loc = err["loc"]
            name = str(loc[0]) if loc else ""
            path = f"{at}.params.{name}" if name else f"{at}.params"
            if err["type"] == "extra_forbidden":
                msg = f"پارامتر «{name}» برای بلوک «{btype}» وجود ندارد."
                issues.append(ValidationIssue(path, "unknown_param", msg))
            else:
                label = f"پارامتر «{name}»" if name else f"پارامترهای بلوک «{btype}»"
                issues.append(ValidationIssue(path, "bad_param", f"{label}: {_fa(dict(err))}"))
        return None


def validate_document(raw: Any) -> ValidationResult:
    """Every problem in ``raw`` at once; a resolved document when there are none."""
    issues: list[ValidationIssue] = []
    if not isinstance(raw, dict):
        return ValidationResult(
            None, [ValidationIssue("", "bad_value", "سند باید یک شیء JSON باشد.")]
        )
    try:
        StrategyDocument.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors():
            loc = tuple(err["loc"])
            if loc[:1] == ("blocks",) and len(loc) > 2:
                continue  # Block contents are checked against the registry below
            code = "required" if err["type"] == "missing" else "bad_value"
            issues.append(ValidationIssue(_path(loc), code, _fa(dict(err))))
    _check_timeframes(raw.get("timeframes", {}), issues)
    blocks = raw.get("blocks")
    resolved: list[dict[str, Any]] = []
    if isinstance(blocks, list):
        for i, b in enumerate(blocks):
            params = _check_block(i, b, issues)
            if params is not None:
                resolved.append({**b, "params": params})
        # Count what the document declares, valid or not: a broken Setup Block is
        # its own error, not also a missing one.
        present = {
            b.get("kind")
            for b in blocks
            if isinstance(b, dict) and b.get("enabled", True) is not False
        }
        for kind in SINGLE_KINDS:
            n = sum(
                1
                for b in blocks
                if isinstance(b, dict)
                and b.get("kind") == kind
                and b.get("enabled", True) is not False
            )
            if n > 1:
                issues.append(
                    ValidationIssue(
                        "blocks",
                        f"too_many:{kind}",
                        f"فقط یک بلوک فعالِ «{KIND_FA[kind]}» مجاز است؛ {n} بلوک فعال است.",
                    )
                )
        for kind in REQUIRED_KINDS:
            if kind not in present:
                issues.append(
                    ValidationIssue(
                        "blocks",
                        f"missing_kind:{kind}",
                        f"سند باید دست‌کم یک بلوک فعالِ «{KIND_FA[kind]}» داشته باشد.",
                    )
                )
    if issues:
        return ValidationResult(None, issues)
    return ValidationResult(StrategyDocument.model_validate({**raw, "blocks": resolved}))


def load_document(path: Path | str) -> StrategyDocument:
    """Read a document from JSON or YAML; raise ValueError listing every problem."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml

        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    res = validate_document(raw)
    if res.document is None:
        raise ValueError(f"{path}: invalid Strategy Document\n{res.render()}")
    return res.document
