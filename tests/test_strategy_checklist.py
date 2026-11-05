"""The Pre-Trade Checklist and the candidate journal (Strategy Builder ticket 08)."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pandas as pd

from nnfx.data.bars import BarFrame
from nnfx.journal.journal import Journal
from nnfx.strategy import validate_document
from nnfx.strategy.run import backtest_document
from tests.test_strategy_engine import BTC, DOC, SYM

Row = tuple[float, float, float, float]


def rise(n: int) -> list[Row]:
    """``n`` quiet rising bars, then a Candle Setup (trigger = high, stop = low)."""
    bars = [(100.0 + k, 101.1 + k, 99.9 + k, 101.0 + k) for k in range(n)]
    c = 100.0 + n
    return [*bars, (c, c + 0.3, c - 5.0, c + 0.2)]


def fill_then(n: int, win: bool) -> list[Row]:
    c = 100.0 + n
    trigger, stop = c + 0.3, c - 5.0
    fill = (c + 0.2, trigger + 1.2, c + 0.1, trigger + 1.1)
    if win:
        target = trigger + 2 * (trigger - stop)
        return [fill, (fill[3], target + 0.5, fill[3] - 0.1, target + 0.2)]
    return [fill, (fill[3], fill[3] + 0.1, stop - 0.5, stop + 0.1)]


def frame(rows: list[Row], volume: list[float] | None = None, kind: str = "traded") -> BarFrame:
    a = np.asarray(rows)
    idx = pd.date_range(pd.Timestamp("2024-03-01 00:15", tz="UTC"), periods=len(a), freq="15min")
    vol = np.ones(len(a)) if volume is None else np.asarray(volume, dtype="float64")
    df = pd.DataFrame(
        {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": vol},
        index=idx,
    )
    return BarFrame(df, SYM, timeframe="M15", volume_kind=kind, price_venue="x")  # type: ignore[arg-type]


def doc(*confirmations: dict[str, Any], **risk: Any) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    raw["blocks"] = [raw["blocks"][0], raw["blocks"][1], *confirmations, *raw["blocks"][2:]]
    raw["risk"] = {"risk_per_trade": 0.005, **risk}
    return raw


RSI = {"kind": "confirmation", "type": "rsi_momentum"}
VOLUME = {"kind": "confirmation", "type": "volume_expansion"}


def run(
    rows: list[Row], raw: dict[str, Any], volume: list[float] | None = None, kind: str = "traded"
):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    journal = Journal()
    out = backtest_document(
        res.document, {SYM: frame(rows, volume, kind)}, {SYM: BTC}, journal=journal
    )
    return out, out.candidates


def checks(cand: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(c["block"], c["kind"], c["outcome"]) for c in cand["checklist"]]


# ---------------------------------------------------------------- record
def test_each_candidate_lists_every_check_with_outcome_weight_and_reason():
    _, cands = run(rise(20) + fill_then(20, win=True), doc(RSI, VOLUME))
    (c,) = cands
    assert checks(c) == [
        ("three_sma_alignment#0", "context", "pass"),
        ("rsi_momentum#2", "confirmation", "pass"),
        ("volume_expansion#3", "confirmation", "pass"),
    ]
    rsi = c["checklist"][1]
    assert rsi["weight"] == 1.0 and rsi["hard"] is False and "RSI" in rsi["reason"]
    assert c["checklist"][0]["hard"] is True  # context checks are gates
    assert (c["score"], c["decision"]) == (2.0, "placed") and c["justified"] is True


def test_not_applicable_checks_are_shown_and_never_counted_as_passes():
    # Ten bars before the setup: RSI 14 and a 20-bar volume average cannot be computed.
    raw = doc(RSI, VOLUME)
    _, cands = run(rise(10) + fill_then(10, win=True), raw)
    (c,) = cands
    assert [x["outcome"] for x in c["checklist"][1:]] == ["na", "na"]
    assert c["score"] == 0.0 and "15" in c["checklist"][1]["reason"]
    assert c["justified"] is True  # not applicable is not a failure
    # A venue that reports no volume cannot vote on volume.
    _, none = run(rise(20) + fill_then(20, win=True), raw, kind="none")
    assert none[0]["checklist"][2]["outcome"] == "na" and none[0]["score"] == 1.0


def test_a_failed_hard_check_refuses_the_candidate_with_its_reason():
    hard_volume = {**VOLUME, "params": {"factor": 1.5, "hard": True}}
    out, cands = run(rise(20) + fill_then(20, win=True), doc(RSI, hard_volume))
    (c,) = cands
    assert c["decision"] == "refused" and c["reasons"] == ["checklist:volume_expansion#3"]
    assert out.result.trades == []


def test_a_failed_soft_check_lowers_the_score_but_not_the_decision():
    soft_volume = {**VOLUME, "params": {"factor": 1.5}}
    out, cands = run(rise(20) + fill_then(20, win=True), doc(RSI, soft_volume))
    (c,) = cands
    assert c["decision"] == "placed" and c["score"] == 1.0 and c["justified"] is False
    assert len(out.result.trades) == 1


def test_the_score_selects_the_risk_tier():
    _, two = run(rise(20) + fill_then(20, win=True), doc(RSI, VOLUME, sizing="tiered"))
    _, one = run(
        rise(20) + fill_then(20, win=True),
        doc(RSI, {**VOLUME, "params": {"factor": 1.5}}, sizing="tiered"),
    )
    assert (two[0]["score"], two[0]["tier"]) == (2.0, 0.0075)
    assert (one[0]["score"], one[0]["tier"]) == (1.0, 0.005)
    heavy = {**RSI, "params": {"weight": 3.0}}
    _, three = run(rise(20) + fill_then(20, win=True), doc(heavy, sizing="tiered"))
    assert (three[0]["score"], three[0]["tier"]) == (3.0, 0.01)


def test_the_decision_path_shows_each_stage_in_order():
    _, cands = run(rise(20) + fill_then(20, win=True), doc(RSI, VOLUME))
    path = cands[0]["decision_path"]
    assert [p["stage"] for p in path] == [
        "context",
        "rsi_momentum#2",
        "volume_expansion#3",
        "risk",
        "stop",
        "order",
    ]
    assert all(p["status"] == "pass" for p in path)
    hard = {**VOLUME, "params": {"factor": 1.5, "hard": True}}
    _, refused = run(rise(20) + fill_then(20, win=True), doc(RSI, hard))
    assert [p["status"] for p in refused[0]["decision_path"]] == [
        "pass",
        "pass",
        "fail",
        "skipped",
        "skipped",
        "skipped",
    ]


# ------------------------------------------------------------ stop labels
def test_losing_trades_are_labelled_justified_or_unjustified():
    full, _ = run(rise(20) + fill_then(20, win=False), doc(RSI, VOLUME))
    (t,) = full.result.trades
    assert t.r_multiple < 0 and full.stop_labels == {t.position_id: "justified"}
    rule_break, _ = run(
        rise(20) + fill_then(20, win=False), doc(RSI, {**VOLUME, "params": {"factor": 1.5}})
    )
    (t2,) = rule_break.result.trades
    assert rule_break.stop_labels == {t2.position_id: "unjustified"}
    winner, _ = run(rise(20) + fill_then(20, win=True), doc(RSI, VOLUME))
    assert winner.stop_labels == {}  # only losing trades are labelled


def test_confirmation_blocks_are_validated_like_any_block():
    bad = doc({**RSI, "params": {"weight": -1}})
    res = validate_document(bad)
    assert res.document is None and res.issues[0].path == "blocks[2].params.weight"
