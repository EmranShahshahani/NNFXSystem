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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nnfx.data.bars import BASE_TIMEFRAMES, TIMEFRAMES
from nnfx.strategy import library as _library  # noqa: F401  (registers the Blocks)
from nnfx.strategy.blocks import KIND_FA, REGISTRY, Block, BlockKind

REQUIRED_KINDS = (BlockKind.SETUP, BlockKind.EXECUTION, BlockKind.STOP, BlockKind.EXIT)


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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

    def as_dict(self) -> dict[str, str]:
        return {"hwc": self.hwc, "mwc": self.mwc, "lwc": self.lwc}


class BlockSpec(_Strict):
    kind: BlockKind
    type: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class RiskSection(_Strict):
    risk_per_trade: float = Field(0.005, gt=0, le=0.01)  # the blueprint's 1% ceiling
    max_positions_per_symbol: int = Field(1, ge=1)


class StrategyDocument(_Strict):
    schema_version: Literal[1] = 1
    metadata: Metadata
    timeframes: TimeframeRoles = TimeframeRoles()
    universe: list[str] = Field(default_factory=list)
    blocks: list[BlockSpec]
    risk: RiskSection = RiskSection()

    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def instances(self, kind: BlockKind) -> list[tuple[int, Block]]:
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
    return f"مقدار نامعتبر است ({err.get('msg', t)})."


def _check_timeframes(raw: Any, issues: list[ValidationIssue]) -> None:
    if not isinstance(raw, dict):
        return
    roles = {
        **TimeframeRoles().as_dict(),
        **{k: v for k, v in raw.items() if k in ("hwc", "mwc", "lwc")},
    }
    bad = False
    for role, tf in roles.items():
        if tf not in TIMEFRAMES:
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


def _check_block(i: int, raw: Any, issues: list[ValidationIssue]) -> dict[str, Any] | None:
    """Validate one Block against the registry; returns its resolved params, or None."""
    at = f"blocks[{i}]"
    if not isinstance(raw, dict):
        issues.append(ValidationIssue(at, "bad_value", "هر بلوک باید یک شیء باشد."))
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
