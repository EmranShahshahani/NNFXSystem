"""Paper runs and alerts over HTTP, accounts on (Strategy Builder ticket 22, ADR 10 §26)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from nnfx.ui.auth import Auth
from nnfx.ui.server import App, serve
from tests.test_beta_auth import _call, _client
from tests.test_strategy_engine import DOC, FILL, RISE, SETUP, SYM, TO_TARGET, frame

ROOT = Path(__file__).resolve().parents[1]
ROWS = [*RISE, SETUP, FILL, *TO_TARGET]
F = frame(ROWS)


class Beta:
    def __init__(self, base: str, app: App, auth: Auth) -> None:
        self.base, self.app, self.auth = base, app, auth
        self.bale: list[tuple[str, dict]] = []

    def user(self, name: str):
        self.auth.signup(self.auth.create_invites()[0], name, "password-1")
        c = _client()
        _call(c, self.base + "/api/login", {"username": name, "password": "password-1"})
        return c


@pytest.fixture
def beta(tmp_path: Path) -> Iterator[Beta]:
    auth = Auth(tmp_path / "beta.db")
    posts: list[tuple[str, dict]] = []
    app = App(
        ROOT,
        auth=auth,
        research=str(tmp_path / "r"),
        strategies=str(tmp_path / "s"),
        paper=str(tmp_path / "paper"),
        alerts=str(tmp_path / "alerts"),
        paper_bars=lambda sym, now: F.between(None, now),
        bale_token="TOKEN",
        bale_post=lambda url, body: posts.append((url, body)),
    )
    httpd = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    b = Beta(f"http://127.0.0.1:{httpd.server_address[1]}", app, auth)
    b.bale = posts
    yield b
    httpd.shutdown()


def save(b: Beta, c, name: str = "tracer") -> None:
    raw = {**DOC, "metadata": {"name": name}}
    code, res = _call(c, b.base + "/api/strategy/save", {"document": raw})
    assert code == 200 and res["ok"], res


def play(b: Beta) -> None:
    for t in F.index:
        b.app.paper_tick(t + pd.Timedelta(minutes=1))
    b.app.notifier.flush()


def test_a_user_starts_lists_and_stops_a_paper_run_of_a_saved_strategy(beta: Beta):
    c = beta.user("ali")
    save(beta, c)
    code, res = _call(c, beta.base + "/api/paper/start", {"name": "tracer"})
    assert code == 200 and res["ok"] and res["run"]["status"] == "running"
    assert res["run"]["symbols"] == [SYM]  # the document's universe by default
    code, res2 = _call(c, beta.base + "/api/paper/runs")
    assert [r["id"] for r in res2["runs"]] == [res["run"]["id"]]
    assert "document" not in res2["runs"][0]
    code, _ = _call(c, beta.base + "/api/paper/stop", {"id": res["run"]["id"]})
    assert code == 200
    assert _call(c, beta.base + "/api/paper/runs")[1]["runs"][0]["status"] == "stopped"


def test_runs_and_alerts_belong_to_their_owner(beta: Beta):
    ali, sara = beta.user("ali"), beta.user("sara")
    save(beta, ali)
    rid = _call(ali, beta.base + "/api/paper/start", {"name": "tracer"})[1]["run"]["id"]
    play(beta)
    assert [a["kind"] for a in _call(ali, beta.base + "/api/alerts")[1]["alerts"]] == [
        "candidate",
        "placed",
        "filled",
    ]
    assert _call(sara, beta.base + "/api/alerts")[1]["alerts"] == []
    assert _call(sara, beta.base + "/api/paper/runs")[1]["runs"] == []
    code, res = _call(sara, beta.base + "/api/paper/stop", {"id": rid})
    assert code == 400 and "پیدا نشد" in res["error"]


def test_the_feed_can_be_read_from_a_known_point(beta: Beta):
    c = beta.user("ali")
    save(beta, c)
    _call(c, beta.base + "/api/paper/start", {"name": "tracer"})
    play(beta)
    first = _call(c, beta.base + "/api/alerts")[1]["alerts"]
    later = _call(c, beta.base + f"/api/alerts?after={first[0]['seq']}")[1]["alerts"]
    assert [a["seq"] for a in later] == [a["seq"] for a in first[1:]]


def test_each_channel_is_switchable_per_user(beta: Beta):
    ali, sara = beta.user("ali"), beta.user("sara")
    for c in (ali, sara):
        save(beta, c)
        _call(c, beta.base + "/api/paper/start", {"name": "tracer"})
    s = _call(ali, beta.base + "/api/alerts/settings")[1]
    assert s["in_site"] and not s["bale"] and s["bale_available"]
    code, _ = _call(
        ali, beta.base + "/api/alerts/settings", {"in_site": False, "bale": True, "bale_chat": "42"}
    )
    assert code == 200
    play(beta)
    assert _call(ali, beta.base + "/api/alerts")[1]["alerts"] == []  # in-site off
    assert {b["chat_id"] for _, b in beta.bale} == {"42"} and len(beta.bale) == 3
    assert len(_call(sara, beta.base + "/api/alerts")[1]["alerts"]) == 3  # defaults: in-site only


def test_bad_settings_are_refused_in_persian(beta: Beta):
    c = beta.user("ali")
    code, res = _call(c, beta.base + "/api/alerts/settings", {"bale": True, "bale_chat": "x y"})
    assert code == 400 and "شناسه" in res["error"]
    code, res = _call(c, beta.base + "/api/alerts/settings", {"bale": True, "bale_chat": ""})
    assert code == 400


def test_everything_here_needs_an_account(beta: Beta):
    anon = _client()
    for path in ("/api/paper/runs", "/api/alerts", "/api/alerts/settings"):
        assert _call(anon, beta.base + path)[0] == 401
    for path in ("/api/paper/start", "/api/paper/stop", "/api/alerts/settings"):
        assert _call(anon, beta.base + path, {})[0] == 401


def test_starting_an_unsaved_strategy_is_refused(beta: Beta):
    c = beta.user("ali")
    code, res = _call(c, beta.base + "/api/paper/start", {"name": "nope"})
    assert code == 400 and "پیدا نشد" in res["error"]


def test_a_paper_run_has_its_own_journal_with_statistics_and_review_status(beta: Beta):
    ali, sara = beta.user("ali"), beta.user("sara")
    save(beta, ali)
    rid = _call(ali, beta.base + "/api/paper/start", {"name": "tracer"})[1]["run"]["id"]
    play(beta)
    code, res = _call(ali, beta.base + f"/api/paper/journal?id={rid}")
    assert code == 200
    (row,) = res["journal"]
    assert row["source"] == "paper" and row["setup"] == "candle_setup" and row["asset"] == SYM
    assert res["stats"]["setup"][0]["count"] == 1
    assert res["review"]["forward_trades"] == 1 and res["review"]["rules_locked"] is True
    code, err = _call(sara, beta.base + f"/api/paper/journal?id={rid}")
    assert code == 400 and "پیدا نشد" in err["error"]
    assert _call(_client(), beta.base + f"/api/paper/journal?id={rid}")[0] == 401
