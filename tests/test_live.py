"""Tickets 19, 27, 28: journal, idempotency, restart safety, reconciliation, live cycle, parity."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nnfx.brokers.costs import CostModel
from nnfx.brokers.paper import PaperBroker
from nnfx.data.synthetic import regime_walk
from nnfx.env import fingerprint
from nnfx.harness.backtest import BacktestHarness
from nnfx.harness.conversion import Conversion
from nnfx.harness.live import LiveHarness, ReconciliationError
from nnfx.harness.parity import run_parity
from nnfx.instruments import fx_spec
from nnfx.journal.journal import Journal
from tests.helpers import config

CFG = config(**{"slots.c1": {"name": "macd", "params": {}}})
FRAMES = {
    "EURUSD": regime_walk(500, seed=21, symbol="EURUSD"),
    "GBPUSD": regime_walk(500, seed=22, symbol="GBPUSD", start_price=1.5),
}
INST = {s: fx_spec(s) for s in FRAMES}
DAYS = FRAMES["EURUSD"].index


def harness(tmp: Path, day: pd.Timestamp, **kw) -> LiveHarness:
    broker = PaperBroker(
        INST,
        CostModel.zero(),
        10_000,
        "USD",
        Conversion("USD", FRAMES),
        state_path=tmp / "broker.json",
    )
    return LiveHarness(
        CFG,
        INST,
        list(FRAMES),
        lambda s, now: FRAMES[s].between(None, now),
        broker,
        Journal(tmp / "journal.jsonl"),
        clock=lambda: day + pd.Timedelta(minutes=5),
        **kw,
    )


# ---------------------------------------------------------------- journal
def test_every_evaluation_journals_inputs_values_intents_and_fingerprint():
    j = Journal()
    BacktestHarness(CFG, INST, FRAMES, journal=j).run()
    env = j.last("environment")
    assert env and env["fingerprint"]["python"] == fingerprint().python
    cycles = list(j.records("cycle"))
    assert cycles and all(c["env"] == fingerprint().digest for c in cycles)
    ev = cycles[-1]["evaluations"][0]
    assert {"inputs", "values", "intents", "state_before", "state_after"} <= set(ev)
    assert {"open", "high", "low", "close", "volume"} <= set(ev["inputs"]) and "atr" in ev["values"]
    assert any(c["submitted"] for c in cycles)


def test_backtest_journal_is_byte_identical_across_runs():
    a, b = Journal(), Journal()
    BacktestHarness(CFG, INST, FRAMES, journal=a).run()
    BacktestHarness(CFG, INST, FRAMES, journal=b).run()
    assert a.text().encode() == b.text().encode()


# ---------------------------------------------------- restart and idempotency
def _run_days(tmp: Path, days) -> None:
    for d in days:
        harness(tmp, d).run_cycle()


def test_killed_mid_cycle_resumes_without_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clean, crashy = tmp_path / "clean", tmp_path / "crashy"
    days = list(DAYS[200:320])
    _run_days(clean, days)
    # Crash on every day where an order was submitted: after submit, before the journal write.
    real_append = Journal.append
    crashed = 0

    def boom(self, rec):
        nonlocal crashed
        if (
            rec.get("type") == "cycle"
            and rec.get("submitted")
            and not getattr(self, "_retry", False)
        ):
            crashed += 1
            raise SystemExit("killed")
        return real_append(self, rec)

    for d in days:
        monkeypatch.setattr(Journal, "append", boom)
        try:
            harness(crashy, d).run_cycle()
        except SystemExit:
            monkeypatch.setattr(Journal, "append", real_append)
            h = harness(crashy, d)  # restart the process
            h.journal._retry = True  # type: ignore[attr-defined]
            rep = h.run_cycle()
            assert all(o["status"] == "duplicate" for o in rep.orders), (
                "resubmission must be a no-op"
            )
        monkeypatch.setattr(Journal, "append", real_append)
    assert crashed > 0
    a = json.loads((clean / "broker.json").read_text())
    b = json.loads((crashy / "broker.json").read_text())
    assert (
        a["positions"] == b["positions"]
        and a["trades"] == b["trades"]
        and a["balance"] == b["balance"]
    )


def test_bars_are_never_applied_twice(tmp_path: Path):
    _run_days(tmp_path, DAYS[200:230])
    before = (tmp_path / "broker.json").read_text()
    harness(tmp_path, DAYS[229]).run_cycle()  # same day again
    assert (tmp_path / "broker.json").read_text() == before


# ----------------------------------------------------------- reconciliation
def test_divergence_halts_and_alerts(tmp_path: Path):
    days = list(DAYS[200:400])
    for d in days:
        harness(tmp_path, d).run_cycle()
        st = json.loads((tmp_path / "broker.json").read_text())
        if st["positions"]:
            break
    else:
        pytest.fail("no position opened")
    # A manual intervention at the venue: someone closes a position by hand.
    pid = sorted(st["positions"])[0]
    del st["positions"][pid]
    (tmp_path / "broker.json").write_text(json.dumps(st))
    alerts: list[str] = []
    rep = harness(tmp_path, days[days.index(d) + 1], alert=alerts.append).run_cycle()
    assert rep.halted and pid in rep.halted and alerts
    assert Journal(tmp_path / "journal.jsonl").last("halt") is not None
    h = harness(tmp_path, days[days.index(d) + 1])
    with pytest.raises(ReconciliationError):
        h.reconcile(h.journal.last("cycle"))


def test_daily_report_even_on_a_quiet_day(tmp_path: Path):
    reports = tmp_path / "reports"
    harness(tmp_path, DAYS[250], report_dir=reports).run_cycle()
    rep = harness(tmp_path, DAYS[250], report_dir=reports).run_cycle()  # nothing new
    text = rep.render()
    assert "no new bar" in text and "Equity" in text and "Blocked by rules" in text
    assert (reports / f"{rep.run_at[:10]}.md").exists()


def test_live_rejects_a_partial_bar(tmp_path: Path):
    from nnfx.data.bars import BarFrameError

    h = harness(tmp_path, DAYS[250])
    h.clock = lambda: DAYS[250] - pd.Timedelta(hours=1)
    h.bars = lambda s, now: FRAMES[s].between(None, DAYS[250])
    with pytest.raises(BarFrameError, match="partial"):
        h.run_cycle()


# ------------------------------------------------------------------ parity
def test_parity_live_equals_backtest_every_day(tmp_path: Path):
    rep = run_parity(CFG, INST, FRAMES, DAYS[200], DAYS[330], tmp_path)
    assert rep.ok, rep.render()
    assert rep.days == 131
    j = Journal(tmp_path / "live_journal.jsonl")
    assert any(c["submitted"] for c in j.records("cycle")), "parity window must include trading"


def test_parity_detects_a_divergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dataclasses

    import nnfx.harness.live as live

    class Skewed(live.IndicatorSet):  # a live-only data bug: ATR off by 1%
        def compute(self, bars):
            out = super().compute(bars)
            return dataclasses.replace(out, atr=out.atr * 1.01)

    monkeypatch.setattr(live, "IndicatorSet", Skewed)
    rep = run_parity(CFG, INST, FRAMES, DAYS[200], DAYS[260], tmp_path)
    assert not rep.ok and "PARITY FAILURE" in rep.render()
