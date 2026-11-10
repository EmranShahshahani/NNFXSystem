"""Paper runs of a Strategy Document (Strategy Builder ticket 22, ADR 10 §26)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nnfx.alerts import AlertSettings, AlertStore, BaleSender, Notifier
from nnfx.data.bars import BarFrame
from nnfx.harness.parity import COMPARED
from nnfx.strategy.paper import PaperError, PaperManager
from tests.test_strategy_engine import BTC, DOC, FILL, RISE, SETUP, SYM, TO_TARGET, frame, run

ROWS = [*RISE, SETUP, FILL, *TO_TARGET]
INST = {SYM: BTC}


def closes(f: BarFrame) -> list[pd.Timestamp]:
    return list(f.index)


class Bars:
    """A bar source over a recorded frame: only bars closed by ``now`` exist."""

    def __init__(self, f: BarFrame) -> None:
        self.f = f
        self.calls = 0

    def __call__(self, symbol: str, now: pd.Timestamp) -> BarFrame:
        self.calls += 1
        return self.f.between(None, now)


def manager(tmp_path: Path, bars: Bars, post=None) -> tuple[PaperManager, Notifier]:
    store = AlertStore(tmp_path / "alerts")
    posts = post or (lambda url, body: None)
    n = Notifier(store, BaleSender("T", post=posts, sleep=lambda s: None))
    return PaperManager(tmp_path / "paper", INST, bars, n), n


def start(m: PaperManager, owner: str = "ali", raw=DOC, symbols=(SYM,)) -> str:
    return m.start(owner, "tracer", 1, raw, list(symbols)).id


def step_through(m: PaperManager, f: BarFrame) -> None:
    for now in closes(f):
        m.tick(now + pd.Timedelta(minutes=1))


def cycles(path: Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        if r["type"] == "cycle":
            out[r["time"]] = {k: r[k] for k in COMPARED}
    return out


def test_a_paper_run_over_recorded_bars_decides_exactly_as_the_backtest(tmp_path: Path):
    f = frame(ROWS)
    _, bt_journal = run(ROWS)
    bt = {r["time"]: {k: r[k] for k in COMPARED} for r in bt_journal.records("cycle")}
    m, _ = manager(tmp_path, Bars(f))
    rid = start(m)
    step_through(m, f)
    paper = cycles(m.run_dir("ali", rid) / "journal.jsonl")
    assert set(paper) == set(bt)
    for t in bt:
        assert json.dumps(paper[t], sort_keys=True) == json.dumps(bt[t], sort_keys=True), t


def test_a_restart_on_every_bar_changes_nothing(tmp_path: Path):
    f = frame(ROWS)
    _, bt_journal = run(ROWS)
    bt = {r["time"]: {k: r[k] for k in COMPARED} for r in bt_journal.records("cycle")}
    bars = Bars(f)
    rid = start(manager(tmp_path, bars)[0])
    for now in closes(f)[1:]:
        m, _ = manager(tmp_path, bars)  # a fresh process image each bar
        m.tick(now + pd.Timedelta(minutes=1))
    m, _ = manager(tmp_path, bars)
    paper = cycles(m.run_dir("ali", rid) / "journal.jsonl")
    for t in paper:
        assert json.dumps(paper[t], sort_keys=True) == json.dumps(bt[t], sort_keys=True), t


def test_alerts_follow_the_candidate_the_trigger_and_the_fill(tmp_path: Path):
    f = frame(ROWS)
    m, n = manager(tmp_path, Bars(f))
    start(m)
    step_through(m, f)
    n.flush()
    kinds = [a["kind"] for a in n.store.feed("ali")]
    assert kinds == ["candidate", "placed", "filled"]


def test_a_second_tick_on_the_same_bars_alerts_nothing_new(tmp_path: Path):
    f = frame(ROWS)
    m, n = manager(tmp_path, Bars(f))
    start(m)
    step_through(m, f)
    before = n.store.feed("ali")
    m.tick(closes(f)[-1] + pd.Timedelta(minutes=2))
    assert n.store.feed("ali") == before


def test_runs_are_per_user_and_can_be_stopped(tmp_path: Path):
    f = frame(ROWS)
    m, _ = manager(tmp_path, Bars(f))
    a, b = start(m, "ali"), start(m, "sara")
    assert [r.id for r in m.runs("ali")] == [a] and [r.id for r in m.runs("sara")] == [b]
    m.stop("ali", a)
    assert m.runs("ali")[0].status == "stopped" and m.runs("sara")[0].status == "running"
    with pytest.raises(PaperError):
        m.stop("sara", a)  # not sara's run
    bars = m.bars
    before = bars.calls  # type: ignore[attr-defined]
    m.tick(closes(f)[3] + pd.Timedelta(minutes=1))
    assert bars.calls == before + 1  # type: ignore[attr-defined]  # only sara's run cycled


def test_a_stopped_run_is_not_resumed_by_a_restart(tmp_path: Path):
    f = frame(ROWS)
    m, _ = manager(tmp_path, Bars(f))
    rid = start(m)
    m.stop("ali", rid)
    m2, _ = manager(tmp_path, Bars(f))
    assert m2.runs("ali")[0].status == "stopped"


def test_an_invalid_document_or_too_many_runs_is_refused(tmp_path: Path):
    m, _ = manager(tmp_path, Bars(frame(ROWS)))
    with pytest.raises(PaperError, match="سند"):
        m.start("ali", "x", 1, {"nonsense": True}, [SYM])
    with pytest.raises(PaperError, match="نماد"):
        m.start("ali", "x", 1, DOC, [])
    for _ in range(3):
        start(m)
    with pytest.raises(PaperError, match="حداکثر"):
        start(m)


def test_a_failing_bar_source_stops_that_run_with_a_reason_and_leaves_others_running(
    tmp_path: Path,
):
    f = frame(ROWS)

    class Flaky(Bars):
        def __call__(self, symbol: str, now: pd.Timestamp) -> BarFrame:
            if len(self.f.between(None, now)) > 3 and self.broken:
                raise OSError("nobitex down")
            return super().__call__(symbol, now)

        broken = True

    bars = Flaky(f)
    m, n = manager(tmp_path, bars)
    rid = start(m)
    step_through(m, f)
    (r,) = m.runs("ali")
    assert r.status == "error" and "nobitex down" in r.error and r.id == rid
    n.flush()
    assert any(a["kind"] == "halt" for a in n.store.feed("ali"))


def test_a_bale_outage_does_not_change_the_decisions(tmp_path: Path):
    f = frame(ROWS)

    def down(url: str, body: dict) -> None:
        raise OSError("bale unreachable")

    m, n = manager(tmp_path, Bars(f), post=down)
    n.store.set_settings("ali", AlertSettings(True, True, "9"))
    rid = start(m)
    step_through(m, f)
    n.flush()
    _, bt_journal = run(ROWS)
    paper = cycles(m.run_dir("ali", rid) / "journal.jsonl")
    assert len(paper) == len(list(bt_journal.records("cycle")))
    assert n.store.failures("ali")


def test_live_bars_fetch_the_window_once_then_only_what_is_new():
    from nnfx.strategy.paper import LiveBars

    f = frame(ROWS)
    asked: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    class Feed:
        def bars(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> BarFrame:
            asked.append((start, end))
            return f.between(start, end)

    live = LiveBars(Feed(), history_bars=8)
    t = closes(f)
    first = live(SYM, t[9] + pd.Timedelta(minutes=1))
    assert list(first.index) == t[2:10]  # the 8-bar window ending now
    assert asked[0][0] == t[9] + pd.Timedelta(minutes=1) - 8 * (t[1] - t[0])
    second = live(SYM, t[11] + pd.Timedelta(minutes=1))
    assert list(second.index) == t[4:12]  # trimmed to the history, no duplicates
    assert asked[1][0] == t[9] - 2 * (t[1] - t[0])  # only the tail was asked for


def test_a_short_outage_of_the_bar_source_is_waited_out(tmp_path: Path):
    f = frame(ROWS)

    class Blip(Bars):
        down = {4, 5}  # two rounds without the source

        def __call__(self, symbol: str, now: pd.Timestamp) -> BarFrame:
            self.calls += 1
            if self.calls in self.down:
                raise OSError("nobitex down")
            return super().__call__(symbol, now)

    m, _ = manager(tmp_path, Blip(f))
    rid = start(m)
    step_through(m, f)
    assert m.runs("ali")[0].status == "running"
    _, bt_journal = run(ROWS)
    paper = cycles(m.run_dir("ali", rid) / "journal.jsonl")
    assert paper[list(paper)[-1]]["equity"] == list(bt_journal.records("cycle"))[-1]["equity"]
