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


def setup_after(rise: int, dip: int = 4, back: int = 3) -> tuple[list[Row], float]:
    """A steady rise, a pullback, a resumption, then a long Candle Setup at close ``c``.

    With the defaults RSI 14 runs 65.9, 68.1, 70.1, 72.1, 72.4: it *enters* the
    zone above 70 two bars before the setup, as the blueprint asks.
    """
    out, c = [], 100.0
    for _ in range(rise):
        out.append((c, c + 1.1, c - 0.1, c + 1.0))
        c += 1.0
    for _ in range(dip):
        out.append((c, c + 0.1, c - 1.6, c - 1.5))
        c -= 1.5
    for _ in range(back):
        out.append((c, c + 1.1, c - 0.1, c + 1.0))
        c += 1.0
    out.append((c, c + 0.3, c - 5.0, c + 0.2))  # trigger c + 0.3, stop c - 5
    return out, c


def then(c: float, win: bool) -> list[Row]:
    trigger, stop = c + 0.3, c - 5.0
    fill = (c + 0.2, trigger + 1.2, c + 0.1, trigger + 1.1)
    if win:
        target = trigger + 2 * (trigger - stop)
        return [fill, (fill[3], target + 0.5, fill[3] - 0.1, target + 0.2)]
    return [fill, (fill[3], fill[3] + 0.1, stop - 0.5, stop + 0.1)]


def scenario(win: bool = True, **kw: int) -> tuple[list[Row], int]:
    rows, c = setup_after(kw.pop("rise", 20), **kw)
    return [*rows, *then(c, win)], len(rows) - 1


def frame(rows: list[Row], setup_i: int, kind: str = "traded") -> BarFrame:
    a = np.asarray(rows)
    idx = pd.date_range(pd.Timestamp("2024-03-01 00:15", tz="UTC"), periods=len(a), freq="15min")
    vol = np.ones(len(a))
    vol[setup_i] = 2.0  # the setup candle expands volume
    df = pd.DataFrame(
        {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": vol},
        index=idx,
    )
    return BarFrame(df, SYM, timeframe="M15", volume_kind=kind, price_venue="x")  # type: ignore[arg-type]


def doc(
    *confirmations: dict[str, Any], checklist: dict[str, Any] | None = None, **risk: Any
) -> dict[str, Any]:
    raw = copy.deepcopy(DOC)
    # The pullback scenarios have a still-falling SMA 7 at the setup: slope is tested elsewhere.
    setup = {"kind": "setup", "type": "candle_setup", "params": {"sma_slope": False}}
    raw["blocks"] = [raw["blocks"][0], setup, *confirmations, *raw["blocks"][2:]]
    raw["risk"] = {"risk_per_trade": 0.005, **risk}
    if checklist is not None:
        raw["checklist"] = checklist
    return raw


RSI = {"kind": "confirmation", "type": "rsi_momentum"}
VOLUME = {"kind": "confirmation", "type": "volume_expansion"}
QUIET = {**VOLUME, "params": {"factor": 2.5}}  # the setup's 2x volume fails this


def run(raw: dict[str, Any], win: bool = True, kind: str = "traded", **kw: int):
    rows, setup_i = scenario(win, **kw)
    res = validate_document(raw)
    assert res.document is not None, res.render()
    out = backtest_document(
        res.document, {SYM: frame(rows, setup_i, kind)}, {SYM: BTC}, journal=Journal()
    )
    return out, out.candidates


def checks(cand: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(c["block"], c["kind"], c["outcome"]) for c in cand["checklist"]]


# ---------------------------------------------------------------- record
def test_each_candidate_lists_every_check_with_outcome_weight_and_reason():
    _, (c,) = run(doc(RSI, VOLUME))
    assert checks(c) == [
        ("three_sma_alignment#0", "context", "pass"),
        ("rsi_momentum#2", "confirmation", "pass"),
        ("volume_expansion#3", "confirmation", "pass"),
    ]
    rsi = c["checklist"][1]
    assert rsi["weight"] == 1.0 and rsi["hard"] is False and "entered" in rsi["reason"]
    assert c["checklist"][0]["hard"] is True  # context checks are gates
    assert (c["score"], c["decision"], c["justified"]) == (2.0, "placed", True)


def test_rsi_must_enter_the_zone_not_just_sit_in_it():
    # A rise with no pullback keeps RSI pinned above 70 for many bars.
    _, (c,) = run(doc(RSI), dip=0, back=0)
    assert c["checklist"][1]["outcome"] == "fail" and "already" in c["checklist"][1]["reason"]
    _, (lvl,) = run(doc({**RSI, "params": {"fresh_bars": 0}}), dip=0, back=0)
    assert lvl["checklist"][1]["outcome"] == "pass"  # level-only mode, if a user wants it


def test_not_applicable_checks_are_shown_and_never_counted_as_passes():
    # Too little history for RSI 14 or a 20-bar volume average.
    _, (c,) = run(doc(RSI, VOLUME), rise=10, dip=0, back=0)
    assert [x["outcome"] for x in c["checklist"][1:]] == ["na", "na"]
    assert c["score"] == 0.0 and "15" in c["checklist"][1]["reason"]
    # A venue that reports no volume cannot vote on volume.
    _, (none,) = run(doc(RSI, VOLUME), kind="none")
    assert none["checklist"][2]["outcome"] == "na" and none["score"] == 1.0


def test_a_failed_hard_check_refuses_the_candidate_with_its_reason():
    out, (c,) = run(doc(RSI, {**QUIET, "params": {"factor": 2.5, "hard": True}}))
    assert c["decision"] == "refused" and c["reasons"] == ["confirmation:volume_expansion#3"]
    assert out.result.trades == []


def test_a_failed_soft_check_lowers_the_score_but_not_the_decision():
    out, (c,) = run(doc(RSI, QUIET))
    assert c["decision"] == "placed" and c["score"] == 1.0 and c["justified"] is False
    assert len(out.result.trades) == 1


def test_the_score_selects_the_risk_tier():
    _, (two,) = run(doc(RSI, VOLUME, sizing="tiered"))
    _, (one,) = run(doc(RSI, QUIET, sizing="tiered"))
    _, (three,) = run(doc({**RSI, "params": {"weight": 3.0}}, sizing="tiered"))
    assert [(x["score"], x["risk_tier"]) for x in (two, one, three)] == [
        (2.0, 0.0075),
        (1.0, 0.005),
        (3.0, 0.01),
    ]


def test_fractional_weights_reach_their_tier_whatever_the_order():
    w = [
        {**RSI, "params": {"weight": 0.6}},
        {**VOLUME, "params": {"weight": 0.3}},
        {**VOLUME, "params": {"weight": 0.1, "lookback": 10}},
    ]
    _, (c,) = run(doc(*w, sizing="tiered"))  # 0.6 + 0.3 + 0.1 = 0.9999999999999999 in floats
    assert c["score"] == 1.0 and c["risk_tier"] == 0.005


def test_the_decision_path_shows_each_stage_in_order():
    _, (c,) = run(doc(RSI, VOLUME))
    path = c["decision_path"]
    assert [p["stage"] for p in path] == [
        "context", "rsi_momentum#2", "volume_expansion#3", "risk", "stop", "order",
    ]  # fmt: skip
    assert all(p["status"] == "pass" for p in path)
    _, (hard,) = run(doc(RSI, {**QUIET, "params": {"factor": 2.5, "hard": True}}))
    assert [p["status"] for p in hard["decision_path"]] == [
        "pass",
        "pass",
        "fail",
        "skipped",
        "skipped",
        "skipped",
    ]


def test_after_a_context_refusal_every_later_stage_is_skipped_but_still_listed():
    raw = doc(RSI, VOLUME)
    raw["blocks"][0]["params"]["timeframe"] = "mwc"  # no 4H history yet: context refuses
    _, (c,) = run(raw)
    assert [p["status"] for p in c["decision_path"]] == ["fail"] + ["skipped"] * 5
    assert [x["outcome"] for x in c["checklist"][1:]] == ["pass", "pass"]  # still evaluated


def test_every_refusal_reason_is_journaled_even_after_a_context_refusal():
    # A short on a spot market that the context also refuses: both reasons are kept.
    fall = [(200.0 - k, 200.1 - k, 198.9 - k, 199.0 - k) for k in range(10)]
    rows = [*fall, (190.0, 195.0, 189.7, 189.8), (189.8, 189.9, 188.0, 188.1)]
    raw = doc()
    raw["blocks"][0]["params"]["timeframe"] = "mwc"
    res = validate_document(raw)
    assert res.document is not None
    out = backtest_document(res.document, {SYM: frame(rows, 10)}, {SYM: BTC})
    (c,) = out.candidates
    assert c["direction"] == -1 and c["reasons"] == [
        "context:three_sma_alignment#0",
        "cannot_short",
    ]


# ------------------------------------------------------------ stop labels
def test_losing_trades_are_labelled_justified_or_unjustified():
    full, _ = run(doc(RSI, VOLUME), win=False)
    (t,) = full.result.trades
    assert t.r_multiple < 0 and full.stop_labels == {t.position_id: "justified"}
    broke, _ = run(doc(RSI, QUIET), win=False)
    (t2,) = broke.result.trades
    assert broke.stop_labels == {t2.position_id: "unjustified"}
    winner, _ = run(doc(RSI, VOLUME))
    assert winner.stop_labels == {}  # only losing trades are labelled


def test_a_loss_without_confluence_is_never_justified():
    # Nothing checked (no Confirmations): the minimum score of 1 is not met.
    bare, (c,) = run(doc(), win=False)
    assert c["justified"] is False and list(bare.stop_labels.values()) == ["unjustified"]
    lenient, _ = run(doc(checklist={"justified_min_score": 0}), win=False)
    assert list(lenient.stop_labels.values()) == ["justified"]


def test_confirmation_blocks_are_validated_like_any_block():
    res = validate_document(doc({**RSI, "params": {"weight": -1}}))
    assert res.document is None and res.issues[0].path == "blocks[2].params.weight"
