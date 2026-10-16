"""Integrity gates, run automatically before any research command (doc 03 §2).

Gates either fail (``severity="error"``) or flag (``severity="flag"``). Flags are
reported, never dropped: a return outlier may be a feed error or a genuine
event, and both need eyes. A tick-volume flag travels into every report that
consumes the frame.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame
from nnfx.instruments import InstrumentSpec

Severity = Literal["error", "flag"]

# Days on which FX venues routinely print no daily bar; not a gap.
FX_HOLIDAYS = ((12, 25), (1, 1))


@dataclass(frozen=True)
class GateResult:
    gate: str
    symbol: str
    passed: bool
    severity: Severity
    timestamps: tuple[pd.Timestamp, ...] = ()
    detail: str = ""

    def render(self) -> str:
        status = "PASS" if self.passed else ("FAIL" if self.severity == "error" else "FLAG")
        ts = ", ".join(str(t) for t in self.timestamps[:5])
        more = f" (+{len(self.timestamps) - 5})" if len(self.timestamps) > 5 else ""
        tail = f" at {ts}{more}" if ts else ""
        return f"{status:4} {self.gate:<18} {self.symbol}: {self.detail}{tail}"


class IntegrityError(RuntimeError):
    def __init__(self, failures: Sequence[GateResult]):
        self.failures = list(failures)
        super().__init__("integrity gates failed:\n" + "\n".join(f.render() for f in failures))


@dataclass
class GateReport:
    symbol: str
    results: list[GateResult] = field(default_factory=list)

    @property
    def failures(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed and r.severity == "error"]

    @property
    def flags(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed and r.severity == "flag"]

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_on_error(self) -> GateReport:
        if self.failures:
            raise IntegrityError(self.failures)
        return self

    def render(self) -> str:
        return "\n".join(r.render() for r in self.results)


def _result(
    gate: str, sym: str, mask: np.ndarray, idx: pd.DatetimeIndex, sev: Severity, detail: str
) -> GateResult:
    bad = tuple(idx[mask])
    return GateResult(gate, sym, passed=not bad, severity=sev, timestamps=bad, detail=detail)


def gate_positive_prices(bars: BarFrame) -> GateResult:
    px = np.column_stack([bars.open, bars.high, bars.low, bars.close])
    mask = np.asarray((px <= 0).any(axis=1))
    return _result(
        "positive_prices", bars.symbol, mask, bars.index, "error", "zero or negative price"
    )


def gate_high_low(bars: BarFrame) -> GateResult:
    o, h, lo, c = bars.open, bars.high, bars.low, bars.close
    mask = (h < lo) | (h < np.maximum(o, c)) | (lo > np.minimum(o, c))
    return _result(
        "high_low", bars.symbol, mask, bars.index, "error", "high below low / OHLC inconsistent"
    )


def expected_calendar(
    start: pd.Timestamp, end: pd.Timestamp, has_sessions: bool, close_tz: str
) -> pd.DatetimeIndex:
    """Expected session dates (local close dates) between two bar close times."""
    days = pd.date_range(
        start.tz_convert(close_tz).normalize(), end.tz_convert(close_tz).normalize(), freq="D"
    )
    if has_sessions:
        days = days[days.weekday < 5]
        days = days[[(d.month, d.day) not in FX_HOLIDAYS for d in days]]
    return days


def gate_calendar(
    bars: BarFrame, instrument: InstrumentSpec, close_tz: str, max_missing: int = 0
) -> GateResult:
    if bars.timeframe != "D1" or len(bars) < 2:
        return GateResult("calendar_gaps", bars.symbol, True, "error", detail="not applicable")
    tz = close_tz if instrument.has_sessions else "UTC"
    # A D1 bar's session date is the local date just before its close instant.
    have = set((bars.index.tz_convert(tz) - pd.Timedelta(seconds=1)).normalize().date)
    exp = expected_calendar(
        bars.index[0] - pd.Timedelta(seconds=1),
        bars.index[-1] - pd.Timedelta(seconds=1),
        instrument.has_sessions,
        tz,
    )
    missing = [d for d in exp if d.date() not in have]
    passed = len(missing) <= max_missing
    stamps = tuple(pd.Timestamp(d).tz_convert("UTC") for d in missing)
    return GateResult(
        "calendar_gaps",
        bars.symbol,
        passed,
        "error",
        stamps if not passed else (),
        f"{len(missing)} expected session(s) missing",
    )


def gate_return_outliers(bars: BarFrame, z: float = 8.0, window: int = 60) -> GateResult:
    """Flag daily returns more than ``z`` robust deviations from the trailing median."""
    c = pd.Series(bars.close, index=bars.index)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = pd.Series(np.log(c.where(c > 0).to_numpy()), index=c.index).diff()
    med = r.rolling(window, min_periods=20).median().shift(1)
    mad = (r - med).abs().rolling(window, min_periods=20).median().shift(1) * 1.4826
    score = ((r - med).abs() / mad.replace(0, np.nan)).fillna(0).to_numpy()
    mask = score > z
    return _result(
        "return_outliers", bars.symbol, mask, bars.index, "flag", f"|return| > {z} robust sd"
    )


def gate_volume(bars: BarFrame) -> list[GateResult]:
    v = bars.volume
    out = [_result("volume_negative", bars.symbol, v < 0, bars.index, "error", "negative volume")]
    if bars.volume_kind == "tick":
        out.append(
            GateResult(
                "volume_kind",
                bars.symbol,
                passed=False,
                severity="flag",
                detail="TICK VOLUME: a count of price updates, not traded size",
            )
        )
    elif bars.volume_kind == "traded":
        out.append(
            _result("volume_zero", bars.symbol, v == 0, bars.index, "flag", "zero traded volume")
        )
    return out


def run_gates(
    bars: BarFrame,
    instrument: InstrumentSpec,
    *,
    close_tz: str = "America/New_York",
    max_missing_sessions: int = 0,
    outlier_z: float = 8.0,
) -> GateReport:
    report = GateReport(bars.symbol)
    report.results += [
        gate_positive_prices(bars),
        gate_high_low(bars),
        gate_calendar(bars, instrument, close_tz, max_missing_sessions),
        gate_return_outliers(bars, z=outlier_z),
        *gate_volume(bars),
    ]
    return report


def ensure_clean(bars: BarFrame, instrument: InstrumentSpec, **kw: object) -> GateReport:
    """Run all gates and raise on any failure. Called by every research entrypoint."""
    return run_gates(bars, instrument, **kw).raise_on_error()  # type: ignore[arg-type]
