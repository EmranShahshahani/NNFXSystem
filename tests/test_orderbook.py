"""Order Book Source, recorder, walls and spoofs (Strategy Builder ticket 04, seam 3)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest

from nnfx.orderbook import (
    FixtureOrderBook,
    NobitexOrderBook,
    OrderBookError,
    OrderBookSnapshot,
    RecordedOrderBook,
    WallParams,
    WallTracker,
    depth_to_move,
    parse_nobitex,
    record,
)

# The example responses in Nobitex's own docs (market data: order book v3, depth v2).
V3_EXAMPLE = {
    "status": "ok",
    "lastUpdate": 1644991756704,
    "lastTradePrice": "35650565900",
    "asks": [["1476091000", "1.016"], ["1479700000", "0.2561"]],
    "bids": [["1470001120", "0.126571"], ["1470000000", "0.818994"]],
}
V2_DEPTH_EXAMPLE = {
    "status": "ok",
    "lastUpdate": "1658565992195",
    "bids": [["7309999000", "2.200274"], ["7310000000", "2.199856"], ["7310025000", "2.102569"]],
    "asks": [["7409894000", "0.054789"], ["7447665000", "0.055276"], ["7450000000", "0.059756"]],
    "lastTradePrice": "7417000000",
}
T0 = pd.Timestamp("2024-01-01 00:00", tz="UTC")


def snap(
    t: int,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    last: float | None = None,
) -> OrderBookSnapshot:
    """A snapshot ``t`` seconds after T0."""
    return OrderBookSnapshot.of("BTC/IRT", T0 + pd.Timedelta(seconds=t), bids, asks, last)


# ---------------------------------------------------------------- parsing
def test_parses_the_documented_v3_order_book():
    s = parse_nobitex(V3_EXAMPLE, "BTC/IRT")
    assert s.time == pd.Timestamp(1644991756704, unit="ms", tz="UTC")
    assert s.best_bid == 1470001120.0 and s.best_ask == 1476091000.0
    assert s.asks[1].tolist() == [1479700000.0, 0.2561]
    assert s.last_trade == 35650565900.0


def test_parses_the_depth_endpoint_and_sorts_its_bids_best_first():
    s = parse_nobitex(V2_DEPTH_EXAMPLE, "BTC/IRT")
    assert s.time == pd.Timestamp(1658565992195, unit="ms", tz="UTC")
    assert s.bids[:, 0].tolist() == [7310025000.0, 7310000000.0, 7309999000.0]
    assert s.best_ask == 7409894000.0


def test_an_error_status_is_an_error():
    with pytest.raises(OrderBookError, match="failed"):
        parse_nobitex({"status": "failed", "message": "Invalid symbol"}, "BTC/IRT")


class FakeNobitex:
    """Serves the documented responses and records the paths asked for."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def __call__(self, url: str) -> bytes:
        path = urlparse(url).path
        self.paths.append(path)
        if path.endswith("/all"):
            body = {
                "status": "ok",
                "BTCIRT": V3_EXAMPLE,
                "USDTIRT": {**V3_EXAMPLE, "lastUpdate": 1},
            }
        else:
            body = V3_EXAMPLE
        return json.dumps(body).encode()


def test_live_provider_reads_one_symbol_or_all_in_one_call():
    http = FakeNobitex()
    live = NobitexOrderBook(http_get=http)
    assert live.snapshot("BTC/IRT").best_ask == 1476091000.0
    both = live.snapshots_now(["BTC/IRT", "USDT/IRT"])
    assert http.paths == ["/v3/orderbook/BTCIRT", "/v3/orderbook/all"]
    assert set(both) == {"BTC/IRT", "USDT/IRT"} and both["USDT/IRT"].symbol == "USDT/IRT"


# ------------------------------------------------- recorder and replays
def test_recorder_stores_snapshots_that_replay_without_lookahead(tmp_path: Path):
    now = {"t": T0}
    sleeps: list[float] = []

    def sleep(sec: float) -> None:
        sleeps.append(sec)
        now["t"] += pd.Timedelta(seconds=sec)

    n = record(
        NobitexOrderBook(http_get=FakeNobitex()),
        ["BTC/IRT", "USDT/IRT"],
        tmp_path,
        interval_s=10.0,
        iterations=3,
        sleep=sleep,
        clock=lambda: now["t"],
    )
    assert n == 6 and sleeps == [10.0, 10.0]
    # Judge staleness by when the books were seen here (the docs' example is from 2022).
    rec = RecordedOrderBook(tmp_path, max_age=None)
    got = rec.snapshots("BTC/IRT", T0, T0 + pd.Timedelta(minutes=1))
    # Recorded at the recorder's clock, not the exchange's lastUpdate.
    assert [s.time for s in got] == [T0 + pd.Timedelta(seconds=s) for s in (0, 10, 20)]
    assert rec.snapshot("BTC/IRT", T0 + pd.Timedelta(seconds=15)).time == T0 + pd.Timedelta(
        seconds=10
    )
    assert rec.snapshot("BTC/IRT", T0 - pd.Timedelta(seconds=1)) is None  # nothing yet
    assert rec.snapshot("ETH/IRT", T0) is None
    assert got[0].bids.tolist() == parse_nobitex(V3_EXAMPLE, "BTC/IRT").bids.tolist()


def test_recorder_keeps_going_when_one_poll_fails(tmp_path: Path):
    calls = {"n": 0}

    def flaky(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("connection reset")
        return json.dumps(V3_EXAMPLE).encode()

    times = iter(T0 + pd.Timedelta(seconds=10 * i) for i in range(100))
    errors: list[str] = []
    n = record(
        NobitexOrderBook(http_get=flaky),
        ["BTC/IRT"],
        tmp_path,
        interval_s=10.0,
        iterations=3,
        sleep=lambda s: None,
        clock=lambda: next(times),
        on_error=errors.append,
    )
    assert n == 2 and len(errors) == 1 and "connection reset" in errors[0]


def test_fixture_provider_answers_like_the_recorded_one():
    book = FixtureOrderBook(
        [snap(0, [(99, 1)], [(101, 1)]), snap(10, [(99.5, 1)], [(100.5, 1)])],
        max_age=pd.Timedelta(seconds=30),
    )
    assert book.snapshot("BTC/IRT", T0 + pd.Timedelta(seconds=9)).best_ask == 101
    assert len(book.snapshots("BTC/IRT", T0, T0 + pd.Timedelta(seconds=10))) == 2


# ------------------------------------------------------------------ depth
def test_depth_needed_to_move_price_by_a_percentage():
    s = snap(0, [(100, 2), (99, 3), (97, 10)], [(101, 1), (102, 4), (104, 20)])
    up = depth_to_move(s, 1.0, side="buy")  # from best ask 101 up to 102.01
    assert (up.base, up.quote) == (5.0, 101 * 1 + 102 * 4)
    down = depth_to_move(s, 1.0, side="sell")  # from best bid 100 down to 99
    assert (down.base, down.quote) == (5.0, 100 * 2 + 99 * 3)
    assert depth_to_move(s, 10.0, side="buy").exhausted


# ------------------------------------------------------------------ walls
def thin(mid: float, t: int, wall: tuple[float, float] | None = None, last: float | None = None):
    """A book of 1-unit levels every 0.5 around ``mid``, plus an optional ask wall."""
    bids = [(mid - 0.5 * k, 1.0) for k in range(1, 21)]
    asks = [(mid + 0.5 * k, 1.0) for k in range(1, 21)]
    if wall is not None:
        asks = [(p, s) for p, s in asks if abs(p - wall[0]) > 1e-9] + [wall]
    return snap(t, bids, asks, last if last is not None else mid)


PARAMS = WallParams(percentile=95.0, persist=3, window_pct=10.0)


def run(snaps: list[OrderBookSnapshot]) -> WallTracker:
    tracker = WallTracker(PARAMS)
    for s in snaps:
        tracker.update(s)
    return tracker


def test_a_large_level_that_persists_becomes_a_wall():
    tracker = run([thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)])
    (w,) = tracker.walls()
    assert (w.side, w.price, w.size, w.seen) == ("ask", 105.0, 40.0, 3)
    assert [e.kind for e in tracker.events] == ["confirmed"]


def test_a_large_level_seen_fewer_than_n_times_is_not_a_wall():
    tracker = run(
        [thin(100, 0, wall=(105.0, 40.0)), thin(100, 10, wall=(105.0, 40.0)), thin(100, 20)]
    )
    assert tracker.walls() == [] and "confirmed" not in [e.kind for e in tracker.events]


def test_wall_size_is_judged_against_the_books_own_depth():
    # 40 units is a wall in a 1-unit book but not in a 50-unit book.
    deep = [
        snap(
            t,
            [(100 - 0.5 * k, 50.0) for k in range(1, 21)],
            [(100 + 0.5 * k, 50.0) for k in range(1, 21)],
        )
        for t in (0, 10, 20)
    ]
    assert run(deep).walls() == []


def test_a_wall_that_vanishes_as_price_approaches_is_a_spoof():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(102, 30, wall=(105.0, 40.0)), thin(103.5, 40)]  # gone before price got there
    tracker = run(snaps)
    assert tracker.walls() == []
    spoof = tracker.events[-1]
    assert (spoof.kind, spoof.reason, spoof.wall.price) == ("spoof", "vanished", 105.0)


def test_a_wall_that_steps_back_as_price_approaches_is_a_spoof():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(102, 30, wall=(105.0, 40.0)), thin(103, 40, wall=(106.5, 40.0))]
    tracker = run(snaps)
    spoof = tracker.events[-1]
    assert (spoof.kind, spoof.reason) == ("spoof", "stepped_back")
    assert tracker.walls() == []


def test_a_wall_eaten_by_trading_is_consumed_not_a_spoof():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(104, 30, wall=(105.0, 40.0)), thin(105.5, 40, last=105.2)]
    tracker = run(snaps)
    assert [e.kind for e in tracker.events] == ["confirmed", "consumed"]


def test_a_wall_pulled_while_price_moves_away_just_fades():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(98, 30)]
    tracker = run(snaps)
    assert [e.kind for e in tracker.events] == ["confirmed", "faded"]


def test_bid_walls_mirror_ask_walls():
    def bid_book(mid: float, t: int, wall: bool) -> OrderBookSnapshot:
        bids = [
            (mid - 0.5 * k, 40.0 if wall and abs(mid - 0.5 * k - 95.0) < 1e-9 else 1.0)
            for k in range(1, 21)
        ]
        asks = [(mid + 0.5 * k, 1.0) for k in range(1, 21)]
        return snap(t, bids, asks, mid)

    tracker = run([bid_book(100, t, True) for t in (0, 10, 20)] + [bid_book(97.5, 30, False)])
    assert [(e.kind, e.wall.side) for e in tracker.events] == [
        ("confirmed", "bid"),
        ("spoof", "bid"),
    ]


# -------------------------------------------------------------------- cli
def test_cli_records_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import nnfx.orderbook.sources as sources
    from nnfx.cli import main

    monkeypatch.setattr(sources, "default_http_get", FakeNobitex())
    rc = main(
        [
            "orderbook", "record", "--symbols", "BTC/IRT", "USDT/IRT", "--interval", "0",
            "--iterations", "2", "--root", str(tmp_path),
        ]
    )  # fmt: skip
    assert rc == 0
    rec = RecordedOrderBook(tmp_path, max_age=None)
    assert (
        len(rec.snapshots("USDT/IRT", T0 - pd.Timedelta(days=36500), pd.Timestamp.now(tz="UTC")))
        == 2
    )


# ------------------------------------------------------------ review fixes
def test_a_truncated_last_line_does_not_lose_the_recording(tmp_path: Path):
    from nnfx.orderbook import append_snapshot

    for t in (0, 10):
        append_snapshot(tmp_path, snap(t, [(99, 1)], [(101, 1)]))
    f = next((tmp_path / "BTC_IRT").glob("*.jsonl"))
    f.write_text(f.read_text() + '{"t": "2024-01-01T00:00:20+00:00", "symb')  # killed mid-write
    rec = RecordedOrderBook(tmp_path, max_age=None)
    assert len(rec.snapshots("BTC/IRT", T0, T0 + pd.Timedelta(minutes=1))) == 2


def test_one_missing_symbol_does_not_stop_the_others(tmp_path: Path):
    def only_btc(url: str) -> bytes:
        return json.dumps({"status": "ok", "BTCIRT": V3_EXAMPLE}).encode()

    times = iter(T0 + pd.Timedelta(seconds=10 * i) for i in range(100))
    errors: list[str] = []
    n = record(
        NobitexOrderBook(http_get=only_btc),
        ["BTC/IRT", "DOGE/IRT"],
        tmp_path,
        iterations=2,
        sleep=lambda s: None,
        clock=lambda: next(times),
        on_error=errors.append,
    )
    assert n == 2 and len(errors) == 2 and all("DOGE/IRT" in e for e in errors)


def test_the_exchange_book_time_is_kept_and_judges_staleness(tmp_path: Path):
    # Recorded at 10:00 but Nobitex's book is from 2022: too old to be the book "at" 10:00.
    clock = T0 + pd.Timedelta(hours=10)
    record(
        NobitexOrderBook(http_get=FakeNobitex()),
        ["BTC/IRT"],
        tmp_path,
        iterations=1,
        clock=lambda: clock,
    )
    rec = RecordedOrderBook(tmp_path, max_age=pd.Timedelta(minutes=2))
    (s,) = rec.snapshots("BTC/IRT", clock, clock)
    assert s.time == clock and s.exchange_time == pd.Timestamp(1644991756704, unit="ms", tz="UTC")
    assert rec.snapshot("BTC/IRT", clock) is None


def test_polls_keep_their_rhythm_whatever_a_poll_costs(tmp_path: Path):
    now = {"t": T0}
    sleeps: list[float] = []

    def slow_get(url: str) -> bytes:
        now["t"] += pd.Timedelta(seconds=3)  # each poll takes 3 s
        return json.dumps(V3_EXAMPLE).encode()

    def sleep(s: float) -> None:
        sleeps.append(s)
        now["t"] += pd.Timedelta(seconds=s)

    record(
        NobitexOrderBook(http_get=slow_get),
        ["BTC/IRT"],
        tmp_path,
        interval_s=10.0,
        iterations=3,
        sleep=sleep,
        clock=lambda: now["t"],
    )
    assert sleeps == [7.0, 7.0]


def test_replays_need_a_time_and_report_their_gaps():
    book = FixtureOrderBook([snap(t, [(99, 1)], [(101, 1)]) for t in (0, 10, 20, 300, 310)])
    with pytest.raises(TypeError):
        book.snapshot("BTC/IRT")  # type: ignore[call-arg]
    gaps = book.gaps(
        "BTC/IRT", T0, T0 + pd.Timedelta(seconds=400), max_gap=pd.Timedelta(seconds=30)
    )
    assert gaps == [
        (T0 + pd.Timedelta(seconds=20), T0 + pd.Timedelta(seconds=300)),
        (T0 + pd.Timedelta(seconds=310), T0 + pd.Timedelta(seconds=400)),
    ]


def test_the_live_provider_can_read_the_depth_endpoint():
    paths: list[str] = []

    def get(url: str) -> bytes:
        paths.append(urlparse(url).path)
        return json.dumps(V2_DEPTH_EXAMPLE).encode()

    s = NobitexOrderBook(http_get=get, endpoint="depth").snapshot("BTC/IRT")
    assert paths == ["/v2/depth/BTCIRT"] and s is not None and s.best_ask == 7409894000.0


def test_depth_reaching_the_limit_exactly_is_not_exhausted():
    s = snap(0, [(100, 1)], [(100, 1), (101, 1)])
    assert not depth_to_move(s, 1.0, side="buy").exhausted


def test_two_walls_can_stand_in_one_book():
    def two(t: int) -> OrderBookSnapshot:
        s = thin(100, t, wall=(105.0, 50.0))
        asks = [(p, 60.0 if abs(p - 103.0) < 1e-9 else z) for p, z in s.asks.tolist()]
        return snap(t, s.bids.tolist(), asks, 100)

    tracker = run([two(t) for t in (0, 10, 20)])
    assert sorted(w.price for w in tracker.walls()) == [103.0, 105.0]


def test_a_wall_reports_its_cluster_edges():
    def clustered(t: int) -> OrderBookSnapshot:
        s = thin(100, t)
        asks = [(p, z) for p, z in s.asks.tolist() if not 104.9 < p < 105.2] + [
            (105.0, 30.0),
            (105.05, 15.0),
            (105.1, 10.0),
        ]
        return snap(t, s.bids.tolist(), asks, 100)

    tracker = WallTracker(WallParams(percentile=95.0, persist=3, window_pct=10.0, cluster_pct=0.06))
    for t in (0, 10, 20):
        tracker.update(clustered(t))
    (w,) = tracker.walls()
    assert (w.price, w.low, w.high, w.size) == (105.0, 105.0, 105.1, 55.0)


def test_a_gap_through_a_wall_is_consumed_even_near_a_new_cluster():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(105.8, 30, wall=(106.5, 40.0))]  # jumped over 105 to just under a new wall
    tracker = run(snaps)
    assert [e.kind for e in tracker.events] == ["confirmed", "consumed"]


def test_a_neighbour_never_inherits_a_vanished_walls_status():
    def book(mid: float, t: int, walls: list[tuple[float, float]]) -> OrderBookSnapshot:
        s = thin(mid, t)
        asks = [
            (p, z) for p, z in s.asks.tolist() if all(abs(p - w) > 1e-9 for w, _ in walls)
        ] + walls
        return snap(t, s.bids.tolist(), asks, mid)

    snaps = [book(100, t, [(101.5, 40.0)]) for t in (0, 10, 20)]  # 101.5 confirmed
    snaps += [book(100.2, 30, [(101.5, 40.0), (101.0, 40.0)])]  # 101.0 appears, unconfirmed
    snaps += [book(100.4, 40, [(101.0, 40.0)])]  # 101.5 pulled as price approaches
    tracker = run(snaps)
    assert [(e.kind, e.wall.price) for e in tracker.events] == [
        ("confirmed", 101.5),
        ("spoof", 101.5),
    ]
    assert tracker.walls() == []  # 101.0 has two sightings, not three


def test_a_level_that_spoofed_is_remembered_when_it_returns():
    snaps = [thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)]
    snaps += [thin(102, 30, wall=(105.0, 40.0)), thin(103.5, 40)]  # spoof
    snaps += [thin(103.5, t, wall=(105.0, 40.0)) for t in (50, 60, 70)]  # back again
    tracker = run(snaps)
    assert tracker.walls() == []
    (w,) = tracker.walls(include_suspect=True)
    assert w.suspect


def test_one_sided_and_crossed_books_are_skipped_without_losing_walls():
    tracker = run([thin(100, t, wall=(105.0, 40.0)) for t in (0, 10, 20)])
    assert tracker.update(snap(30, [], [(101, 1)])) == []
    assert tracker.update(snap(40, [(102, 1)], [(101, 1)])) == []
    assert [w.price for w in tracker.walls()] == [105.0]
