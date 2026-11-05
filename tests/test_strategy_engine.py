"""The Strategy Engine on hand-built 15m bars (Strategy Builder ticket 05, seam 1)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nnfx.data.bars import BarFrame
from nnfx.instruments import crypto_spec
from nnfx.journal.journal import Journal
from nnfx.research.partition import HoldoutAccessError
from nnfx.research.trials import ResearchState
from nnfx.strategy import validate_document
from nnfx.strategy.run import backtest_document

SYM = "BTC/USDT"
BTC = crypto_spec(SYM, "crypto_spot")

DOC: dict[str, Any] = {
    "metadata": {"name": "tracer"},
    "timeframes": {"hwc": "D1", "mwc": "H4", "lwc": "M15"},
    "universe": [SYM],
    "blocks": [
        {
            "kind": "context",
            "type": "three_sma_alignment",
            "params": {"fast": 2, "mid": 3, "slow": 4, "timeframe": "lwc"},
        },
        {"kind": "setup", "type": "candle_setup"},
        {"kind": "execution", "type": "stop_market", "params": {"buffer_pct": 0, "expiry_bars": 4}},
        {"kind": "stop", "type": "structural_stop", "params": {"buffer_pct": 0}},
        {"kind": "exit", "type": "fixed_r", "params": {"r": 2.0}},
    ],
    "risk": {"risk_per_trade": 0.005},
}

# Ten quiet rising bars (open = previous close, small wicks), then a Candle Setup:
# a long lower wick to 106 with the SMA 7 (108.03) inside it and a tiny upper wick.
RISE = [(100.0 + k, 101.1 + k, 99.9 + k, 101.0 + k) for k in range(10)]
SETUP = (111.0, 111.3, 106.0, 111.2)  # trigger 111.3, invalidation and stop 106 -> R = 5.3
FILL = (111.2, 112.5, 111.1, 112.4)  # trades through 111.3
TO_TARGET = [(112.4 + 2 * k, 114.5 + 2 * k, 112.3 + 2 * k, 114.4 + 2 * k) for k in range(4)] + [
    (120.4, 122.0, 120.3, 121.8)  # 2R = 111.3 + 10.6 = 121.9
]
TO_STOP = [(112.4, 112.5, 105.5, 106.0)]


def frame(rows: list[tuple[float, float, float, float]], start: str = "2024-03-01") -> BarFrame:
    a = np.asarray(rows)
    idx = pd.date_range(
        pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=15), periods=len(a), freq="15min"
    )
    df = pd.DataFrame(
        {"open": a[:, 0], "high": a[:, 1], "low": a[:, 2], "close": a[:, 3], "volume": 1.0},
        index=idx,
    )
    return BarFrame(df, SYM, timeframe="M15", volume_kind="traded", price_venue="x")


def doc(raw: dict[str, Any] = DOC):
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return res.document


def run(rows, raw: dict[str, Any] = DOC, **kw: Any):
    journal = Journal()
    out = backtest_document(doc(raw), {SYM: frame(rows)}, {SYM: BTC}, journal=journal, **kw)
    return out, journal


def orders(journal: Journal) -> list[tuple[Any, ...]]:
    evs = [e for r in journal.records("cycle") for e in r["orders"]]
    return [(e["e"], e.get("trigger") or e.get("price"), e.get("reason", "")) for e in evs]


def test_a_candle_setup_places_fills_and_exits_at_two_r():
    out, journal = run([*RISE, SETUP, FILL, *TO_TARGET])
    assert orders(journal) == [("place", 111.3, ""), ("fill", 111.3, ""), ("close", None, "target")]
    (t,) = out.result.trades
    assert (t.entry_price, t.exit_price, t.exit_reason) == (111.3, pytest.approx(121.9), "target")
    assert t.r_multiple == pytest.approx(2.0)
    assert t.risk_cash == pytest.approx(0.005 * out.result.initial_equity, rel=0.01)


def test_the_same_setup_stopped_out_loses_one_r():
    out, journal = run([*RISE, SETUP, FILL, *TO_STOP])
    assert orders(journal) == [("place", 111.3, ""), ("fill", 111.3, ""), ("close", None, "stop")]
    (t,) = out.result.trades
    assert (t.exit_price, t.exit_reason) == (106.0, "stop") and t.r_multiple == pytest.approx(-1.0)


def test_one_journal_record_per_setup_candidate_with_its_checks():
    _, journal = run([*RISE, SETUP, FILL, *TO_TARGET])
    evaluated = [ev for r in journal.records("cycle") for ev in r["evaluations"]]
    assert len(evaluated) == 1
    (ev,) = evaluated
    assert ev["values"]["setup"] == "candle_setup" and ev["values"]["trigger"] == 111.3
    assert ev["conditions"]["context"] == {"three_sma_alignment#0": True}
    assert ev["blocked"] == [] and len(ev["intents"]) == 1
    assert ev["intents"][0]["kind"] == "pending" and ev["intents"][0]["stop"] == 106.0


def test_a_candidate_the_context_refuses_is_journaled_but_not_traded():
    raw = copy.deepcopy(DOC)
    raw["blocks"][0]["params"]["timeframe"] = "mwc"  # no closed 4H history yet: nothing allowed
    out, journal = run([*RISE, SETUP, FILL, *TO_TARGET], raw)
    (ev,) = [ev for r in journal.records("cycle") for ev in r["evaluations"]]
    assert ev["blocked"] == ["context:three_sma_alignment#0"] and ev["intents"] == []
    assert out.result.trades == [] and orders(journal) == []


def test_each_run_records_a_trial_with_the_fingerprint_in_its_own_log(tmp_path: Path):
    research = ResearchState(tmp_path)
    out, _ = run([*RISE, SETUP, FILL, *TO_TARGET], research=research)
    rows = [json.loads(ln) for ln in (tmp_path / "strategy_trials.jsonl").read_text().splitlines()]
    assert [r["document"] for r in rows] == [doc().fingerprint()] and rows[0]["id"] == out.trial_id
    assert rows[0]["segment"] == "validation" and rows[0]["metrics"]["trades"] == 1
    assert research.trial_count() == 0  # NNFX's trial count (and its DSR) is untouched
    out2, _ = run([*RISE, SETUP, FILL, *TO_TARGET], research=research)
    assert (
        out2.trial_id == out.trial_id
        and len((tmp_path / "strategy_trials.jsonl").read_text().splitlines()) == 1
    )


def test_a_run_reaching_into_the_holdout_is_refused(tmp_path: Path):
    research = ResearchState(tmp_path)
    late = frame([*RISE, SETUP, FILL, *TO_TARGET], start="2025-02-01")
    with pytest.raises(HoldoutAccessError):
        backtest_document(doc(), {SYM: late}, {SYM: BTC}, research=research)


def test_the_result_carries_the_document_fingerprint():
    out, _ = run([*RISE, SETUP, FILL, *TO_TARGET])
    assert out.fingerprint == doc().fingerprint() == out.result.config_digest
