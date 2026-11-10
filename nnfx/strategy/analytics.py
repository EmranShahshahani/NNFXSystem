"""The trade journal and its statistics (Strategy Builder ticket 23, ADR 10 §27).

One row per closed position, carrying the blueprint's fields (video 71-80: timestamp, session,
asset, direction, setup type, risk tier, size, leverage, stop, targets, outcome, realised R,
MAE, slippage, fees). Backtest and paper trades share this one shape: rows are built from the
broker's trades, the journaled cycles (which hold the candidate and its order) and, when at
hand, the bars (for the adverse excursion).

Statistics group the rows by setup, session, weekday, asset and risk tier. A review is
prompted at every 50 trades; changing rules is warned against until 100 forward (paper)
trades exist; a losing streak of up to 7 is called normal (spec stories 102-105).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from nnfx.brokers.sim import Trade
from nnfx.data.bars import TIMEFRAMES, BarFrame
from nnfx.strategy.sessions import SESSION_HOURS

DIMENSIONS = ("setup", "session", "weekday", "asset", "risk_tier")
REVIEW_EVERY = 50
FORWARD_TRADES_BEFORE_CHANGES = 100
NORMAL_LOSING_STREAK = 7
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class JournalRow:
    position_id: str
    timestamp: str  # the entry bar's close label (UTC)
    exit_time: str
    session: str  # asia | london | new_york | off_hours, by the entry bar's open
    weekday: str
    asset: str
    direction: str  # long | short
    setup: str  # the Setup Block's type; "unknown" when the candidate cannot be traced
    risk_tier: float | None  # the fraction of equity risked
    size: float  # units
    leverage: float | None
    stop: float | None  # the initial stop
    targets: list[float]
    outcome: str  # win | loss | breakeven, on the whole position's net result
    realised_r: float
    mae_r: float | None  # the deepest drawdown from entry, in initial-stop distances
    slippage: float  # cash
    fees: float  # cash: commissions
    spread: float  # cash
    justified: bool | None  # the candidate passed the checklist (ADR 10 §11)
    source: str  # backtest | paper

    def record(self) -> dict[str, Any]:
        return asdict(self)


def session_of(opened: pd.Timestamp) -> str:
    """The session a bar opening at ``opened`` traded in; the latest-opening one on overlap."""
    hour = opened.hour + opened.minute / 60.0
    live = [(lo, name) for name, (lo, hi) in SESSION_HOURS.items() if lo <= hour < hi]
    return max(live)[1] if live else "off_hours"


def _tier_label(tier: float | None) -> str:
    return "?" if tier is None else f"{tier * 100:.4g}%"


def _candidates(cycles: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Each order key -> its evaluation and intent; each position id -> the key it filled."""
    by_key: dict[str, Any] = {}
    key_of: dict[str, str] = {}
    for rec in cycles:
        for ev in rec["evaluations"]:
            if "event" in ev["values"]:
                continue
            for intent in ev["intents"]:
                by_key[intent["idempotency_key"]] = (ev["values"], intent)
        for e in rec.get("orders", []):
            if e.get("e") == "fill":
                key_of[e["pid"]] = e["key"]
    return by_key, key_of


def _mae_r(legs: Sequence[Trade], stop: float | None, frame: BarFrame | None) -> float | None:
    """How far price went against the entry before the exit, in initial-stop distances.

    Bars after the entry bar through the exit bar: the entry bar's own range may precede the
    fill, so it is left out (a small understatement).
    """
    if frame is None or stop is None or not len(frame):
        return None
    first = legs[0]
    dist = abs(first.entry_price - stop)
    if dist <= 0:
        return None
    last = max(legs, key=lambda t: t.exit_time)
    bars = frame.between(
        pd.Timestamp(first.entry_time) + pd.Timedelta(1, "ns"), pd.Timestamp(last.exit_time)
    )
    if not len(bars):
        return 0.0
    if first.direction > 0:
        worst = first.entry_price - float(bars.df["low"].min())
    else:
        worst = float(bars.df["high"].max()) - first.entry_price
    return max(0.0, worst) / dist


def journal_rows(
    trades: Sequence[Trade],
    cycles: Iterable[Mapping[str, Any]],
    frames: Mapping[str, BarFrame] | None,
    *,
    source: str,
) -> list[JournalRow]:
    """One row per position, oldest entry first."""
    by_key, key_of = _candidates(cycles)
    legs: dict[str, list[Trade]] = {}
    for t in trades:
        legs.setdefault(t.position_id, []).append(t)
    rows = []
    for pid, ts in legs.items():
        ts = sorted(ts, key=lambda t: t.exit_time)
        first = min(ts, key=lambda t: t.entry_time)
        values, intent = by_key.get(key_of.get(pid, ""), ({}, {}))
        frame = None if frames is None else frames.get(first.symbol)
        lwc = frame.timeframe if frame is not None else None
        entry = pd.Timestamp(first.entry_time)
        opened = entry - TIMEFRAMES[lwc] if lwc in TIMEFRAMES else entry
        net = sum(t.net_pnl for t in ts)
        risk = sum(t.risk_cash for t in ts)
        r = net / risk if risk > 0 else 0.0
        stop = intent.get("stop")
        rows.append(
            JournalRow(
                position_id=pid,
                timestamp=first.entry_time,
                exit_time=max(t.exit_time for t in ts),
                session=session_of(opened),
                weekday=WEEKDAYS[opened.weekday()],
                asset=first.symbol,
                direction="long" if first.direction > 0 else "short",
                setup=values.get("setup", "unknown"),
                risk_tier=values.get("risk_tier"),
                size=sum(t.units for t in ts),
                leverage=(values.get("risk") or {}).get("leverage"),
                stop=stop,
                targets=[float(x) for x in values.get("targets", [])],
                outcome="win" if net > 0 else ("loss" if net < 0 else "breakeven"),
                realised_r=r,
                mae_r=_mae_r(ts, stop, frame),
                slippage=sum(t.slippage_cost for t in ts),
                fees=sum(t.commission for t in ts),
                spread=sum(t.spread_cost for t in ts),
                justified=values.get("justified"),
                source=source,
            )
        )
    return sorted(rows, key=lambda x: (x.timestamp, x.position_id))


def _key(row: JournalRow, dim: str) -> str:
    return _tier_label(row.risk_tier) if dim == "risk_tier" else str(getattr(row, dim))


def statistics(rows: Sequence[JournalRow]) -> dict[str, list[dict[str, Any]]]:
    """Per dimension and value: count, wins, win rate, expectancy and total R, mean MAE."""
    out: dict[str, list[dict[str, Any]]] = {}
    for dim in DIMENSIONS:
        groups: dict[str, list[JournalRow]] = {}
        for r in rows:
            groups.setdefault(_key(r, dim), []).append(r)
        order = WEEKDAYS if dim == "weekday" else sorted(groups)
        out[dim] = [_group(k, groups[k]) for k in order if k in groups]
    return out


def _group(key: str, rs: list[JournalRow]) -> dict[str, Any]:
    n = len(rs)
    wins = sum(r.outcome == "win" for r in rs)
    maes = [r.mae_r for r in rs if r.mae_r is not None]
    return {
        "key": key,
        "count": n,
        "wins": wins,
        "win_rate": wins / n,
        "expectancy_r": sum(r.realised_r for r in rs) / n,
        "total_r": sum(r.realised_r for r in rs),
        "mean_mae_r": sum(maes) / len(maes) if maes else None,
    }


def _streaks(rows: Sequence[JournalRow]) -> tuple[int, int]:
    """(current, longest) run of losses, in the order the positions closed."""
    cur = longest = 0
    for r in sorted(rows, key=lambda x: (x.exit_time, x.position_id)):
        cur = cur + 1 if r.outcome == "loss" else 0
        longest = max(longest, cur)
    return cur, longest


def review_status(trades: int, forward: int, rows: Sequence[JournalRow] = ()) -> dict[str, Any]:
    """The review prompt, the rule-change warning and the losing-streak note."""
    done = (trades // REVIEW_EVERY) * REVIEW_EVERY
    locked = forward < FORWARD_TRADES_BEFORE_CHANGES
    cur, longest = _streaks(rows)
    return {
        "trades": trades,
        "forward_trades": forward,
        "review_due": done or None,
        "next_review_at": done + REVIEW_EVERY,
        "rules_locked": locked,
        "warning": (
            f"قوانین را پیش از ۱۰۰ معامله رو‌به‌جلو تغییر ندهید ({forward} از ۱۰۰ انجام شده)"
            if locked
            else None
        ),
        "current_losing_streak": cur,
        "longest_losing_streak": longest,
        "streak_is_normal": cur <= NORMAL_LOSING_STREAK,
    }
