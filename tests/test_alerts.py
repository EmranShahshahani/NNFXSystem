"""Alerts for paper runs (Strategy Builder ticket 22, ADR 10 §26): derivation, feed, Bale."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from nnfx.alerts import AlertSettings, AlertStore, BaleSender, Notifier, alerts_from_cycle

CYCLE = {
    "type": "cycle",
    "time": "2024-03-01T02:45:00+00:00",
    "evaluations": [
        {
            "symbol": "BTC/USDT",
            "time": "2024-03-01T02:45:00+00:00",
            "values": {
                "setup": "candle_setup",
                "direction": 1,
                "trigger": 111.3,
                "decision": "placed",
                "reasons": [],
            },
        },
        {  # a management event is not a Setup Candidate
            "symbol": "BTC/USDT",
            "time": "2024-03-01T02:45:00+00:00",
            "values": {"event": "stop_move", "from": 1, "to": 2},
        },
    ],
    "orders": [
        {"n": 1, "e": "place", "key": "k1", "order_id": "o1", "trigger": 111.3},
        {"n": 2, "e": "fill", "pid": "p1", "key": "k1", "units": 1.0, "price": 111.3},
        {"n": 3, "e": "cancel", "key": "k2", "order_id": "o2", "reason": "invalidated"},
        {"n": 4, "e": "cancel", "key": "k3", "order_id": "o3", "reason": "expired"},
        {"n": 5, "e": "close", "pid": "p1", "fraction": 1.0, "units": 1.0, "reason": "target"},
    ],
}
SYMBOLS = {"k1": "BTC/USDT", "k2": "ETH/USDT", "k3": "SOL/USDT"}


def kinds(alerts) -> list[tuple[str, str]]:
    return [(a.kind, a.symbol) for a in alerts]


def test_a_cycle_yields_candidate_placed_filled_cancelled_and_expired():
    out = alerts_from_cycle("run1", CYCLE, SYMBOLS)
    assert kinds(out) == [
        ("candidate", "BTC/USDT"),
        ("placed", "BTC/USDT"),
        ("filled", "BTC/USDT"),
        ("cancelled", "ETH/USDT"),
        ("expired", "SOL/USDT"),
    ]
    assert "111.3" in out[1].text and out[0].time == CYCLE["time"]


def test_alert_ids_are_stable_so_a_replayed_cycle_adds_nothing():
    a = alerts_from_cycle("run1", CYCLE, SYMBOLS)
    b = alerts_from_cycle("run1", CYCLE, SYMBOLS)
    assert [x.id for x in a] == [x.id for x in b] and len({x.id for x in a}) == len(a)
    assert {x.id for x in alerts_from_cycle("run2", CYCLE, SYMBOLS)}.isdisjoint({x.id for x in a})


def test_the_feed_keeps_each_alert_once_in_order(tmp_path: Path):
    store = AlertStore(tmp_path)
    alerts = alerts_from_cycle("run1", CYCLE, SYMBOLS)
    assert [store.append("ali", a) for a in alerts] == [True] * 5
    assert store.append("ali", alerts[0]) is False  # a replay
    feed = store.feed("ali")
    assert [f["kind"] for f in feed] == ["candidate", "placed", "filled", "cancelled", "expired"]
    assert [f["kind"] for f in store.feed("ali", after=feed[2]["seq"])] == ["cancelled", "expired"]
    assert store.feed("someone-else") == []


def test_settings_default_to_the_site_only_and_survive_a_reload(tmp_path: Path):
    store = AlertStore(tmp_path)
    assert store.settings("ali") == AlertSettings(in_site=True, bale=False, bale_chat="")
    store.set_settings("ali", AlertSettings(in_site=False, bale=True, bale_chat="123"))
    assert AlertStore(tmp_path).settings("ali") == AlertSettings(False, True, "123")


class FakeBale:
    """A scripted Bale API: the first ``fail`` posts fail, the rest succeed."""

    def __init__(self, fail: int = 0) -> None:
        self.fail, self.calls = fail, []

    def __call__(self, url: str, body: dict) -> None:
        self.calls.append((url, body))
        if len(self.calls) <= self.fail:
            raise OSError("bale unreachable")


def sender(post: FakeBale, sleeps: list[float] | None = None, **kw) -> BaleSender:
    return BaleSender("TOKEN", post=post, sleep=(sleeps if sleeps is not None else []).append, **kw)


def test_bale_posts_to_the_bot_api():
    post = FakeBale()
    assert sender(post).send("123", "سلام") is None
    ((url, body),) = post.calls
    assert url == "https://tapi.bale.ai/botTOKEN/sendMessage"
    assert body == {"chat_id": "123", "text": "سلام"}


def test_bale_retries_with_growing_delays_then_succeeds():
    post, sleeps = FakeBale(fail=2), []
    assert sender(post, sleeps).send("1", "x") is None
    assert len(post.calls) == 3 and sleeps == [2.0, 4.0]


def test_bale_reports_the_last_error_after_all_attempts():
    post = FakeBale(fail=99)
    err = sender(post, attempts=3).send("1", "x")
    assert err is not None and "unreachable" in err and len(post.calls) == 3


def notifier(tmp_path: Path, post: FakeBale) -> Notifier:
    return Notifier(AlertStore(tmp_path), sender(post))


def test_delivery_follows_each_users_switches(tmp_path: Path):
    post = FakeBale()
    n = notifier(tmp_path, post)
    n.store.set_settings(
        "ali", AlertSettings(in_site=True, bale=True, bale_chat="9", bale_verified=True)
    )
    n.store.set_settings("sara", AlertSettings(in_site=False, bale=False, bale_chat="9"))
    (alert, *_) = alerts_from_cycle("r", CYCLE, SYMBOLS)
    n.submit("ali", [alert])
    n.submit("sara", [alert])
    n.flush()
    assert len(n.store.feed("ali")) == 1 and n.store.feed("sara") == []
    assert [b["chat_id"] for _, b in post.calls] == ["9"]


def test_bale_needs_a_chat_id(tmp_path: Path):
    post = FakeBale()
    n = notifier(tmp_path, post)
    n.store.set_settings(
        "ali", AlertSettings(in_site=True, bale=True, bale_chat="", bale_verified=True)
    )
    n.submit("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[:1])
    n.flush()
    assert post.calls == []


def test_a_bale_failure_is_logged_and_the_feed_still_has_the_alert(tmp_path: Path):
    n = Notifier(AlertStore(tmp_path), sender(FakeBale(fail=99)))
    n.store.set_settings(
        "ali", AlertSettings(in_site=True, bale=True, bale_chat="9", bale_verified=True)
    )
    n.submit("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[:1])
    n.flush()
    assert len(n.store.feed("ali")) == 1
    (fail,) = n.store.failures("ali")
    assert fail["channel"] == "bale" and "unreachable" in fail["error"]


def test_submit_returns_at_once_while_delivery_is_stuck(tmp_path: Path):
    gate, entered = threading.Event(), threading.Event()

    def stuck(url: str, body: dict) -> None:
        entered.set()
        gate.wait(5)

    n = Notifier(AlertStore(tmp_path), sender(stuck))  # type: ignore[arg-type]
    n.store.set_settings(
        "ali", AlertSettings(in_site=True, bale=True, bale_chat="9", bale_verified=True)
    )
    done = threading.Event()

    def go() -> None:
        n.submit("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[:1])
        done.set()

    threading.Thread(target=go).start()
    assert done.wait(2), "submit blocked on a stuck Bale call"
    assert entered.wait(2)
    gate.set()
    n.flush()


def test_a_broken_store_never_raises_into_the_caller(tmp_path: Path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    n = Notifier(AlertStore(blocker / "sub"), sender(FakeBale()))  # root is not a directory
    n.submit("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[:1])
    n.flush()  # no exception


def test_the_feed_is_one_json_object_per_line(tmp_path: Path):
    store = AlertStore(tmp_path)
    store.append("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[0])
    (path,) = [p for p in tmp_path.rglob("feed.jsonl")]
    assert json.loads(path.read_text().splitlines()[0])["kind"] == "candidate"


def test_a_replayed_alert_is_neither_resent_nor_re_added_whatever_the_switches(tmp_path: Path):
    post = FakeBale()
    n = notifier(tmp_path, post)
    n.store.set_settings(
        "ali", AlertSettings(in_site=False, bale=True, bale_chat="9", bale_verified=True)
    )
    alerts = alerts_from_cycle("r", CYCLE, SYMBOLS)[:2]
    n.submit("ali", alerts)
    n.submit("ali", alerts)  # a crash replayed the cycle
    n.flush()
    assert len(post.calls) == 2
    again = notifier(tmp_path, post)  # and a restarted process remembers too
    again.submit("ali", alerts)
    again.flush()
    assert len(post.calls) == 2
