"""Proving a Bale chat id belongs to the user (Strategy Builder ticket 27, ADR 10 §29)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from nnfx.alerts import AlertSettings, AlertStore, VerificationError
from nnfx.ui.auth import Auth
from nnfx.ui.server import App, serve
from tests.test_beta_auth import _call, _client


def store_with_chat(tmp_path: Path, chat: str = "42") -> AlertStore:
    s = AlertStore(tmp_path)
    s.set_settings("ali", AlertSettings(True, False, chat))
    return s


def test_the_right_code_verifies_the_saved_chat(tmp_path: Path):
    s = store_with_chat(tmp_path)
    code = s.issue_code("ali", now=1000.0)
    assert len(code) == 6 and code.isdigit()
    assert s.settings("ali").bale_verified is False
    assert s.check_code("ali", code, now=1100.0) is True
    assert s.settings("ali").bale_verified is True
    assert s.check_code("ali", code, now=1101.0) is False  # one use only


def test_a_wrong_or_expired_code_does_not_verify(tmp_path: Path):
    s = store_with_chat(tmp_path)
    code = s.issue_code("ali", now=1000.0)
    wrong = "000000" if code != "000000" else "111111"
    assert s.check_code("ali", wrong, now=1010.0) is False
    assert s.check_code("ali", code, now=1000.0 + 601) is False  # ten minutes
    assert s.settings("ali").bale_verified is False


def test_five_wrong_tries_burn_the_code(tmp_path: Path):
    s = store_with_chat(tmp_path)
    code = s.issue_code("ali", now=1000.0)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert s.check_code("ali", wrong, now=1010.0) is False
    assert s.check_code("ali", code, now=1011.0) is False  # even the right one, now


def test_codes_are_rate_limited_per_user(tmp_path: Path):
    s = store_with_chat(tmp_path)
    s.issue_code("ali", now=1000.0)
    with pytest.raises(VerificationError, match="کد"):
        s.issue_code("ali", now=1030.0)
    s.issue_code("ali", now=1061.0)  # a minute later is fine


def test_a_code_needs_a_saved_chat_and_belongs_to_that_chat(tmp_path: Path):
    s = AlertStore(tmp_path)
    with pytest.raises(VerificationError, match="شناسه"):
        s.issue_code("ali", now=1.0)
    s = store_with_chat(tmp_path, "42")
    code = s.issue_code("ali", now=1.0)
    s.set_settings("ali", AlertSettings(True, False, "43"))  # the chat changed since
    assert s.check_code("ali", code, now=2.0) is False
    assert s.settings("ali").bale_verified is False


@pytest.fixture
def beta(tmp_path: Path) -> Iterator[tuple[str, App, Auth, list[dict]]]:
    auth = Auth(tmp_path / "beta.db")
    sent: list[dict] = []
    app = App(
        Path(__file__).resolve().parents[1],
        auth=auth,
        research=str(tmp_path / "r"),
        strategies=str(tmp_path / "s"),
        paper=str(tmp_path / "paper"),
        alerts=str(tmp_path / "alerts"),
        bale_token="TOKEN",
        bale_post=lambda url, body: sent.append(body),
    )
    httpd = serve(app, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app, auth, sent
    httpd.shutdown()


def login(base: str, auth: Auth, name: str):
    auth.signup(auth.create_invites()[0], name, "password-1")
    c = _client()
    _call(c, base + "/api/login", {"username": name, "password": "password-1"})
    return c


def test_the_whole_handshake_over_http(beta):
    base, _app, auth, sent = beta
    c = login(base, auth, "ali")
    _call(c, base + "/api/alerts/settings", {"bale_chat": "42"})
    code, res = _call(c, base + "/api/alerts/settings", {"bale": True})
    assert code == 400 and "تأیید" in res["error"]  # unverified: refused
    assert _call(c, base + "/api/alerts/settings")[1]["bale_verified"] is False
    code, res = _call(c, base + "/api/alerts/bale/code", {})
    assert code == 200 and res["ok"] and len(sent) == 1 and sent[0]["chat_id"] == "42"
    digits = "".join(ch for ch in sent[0]["text"] if ch.isdigit())
    assert len(digits) == 6  # the message carries the code
    assert _call(c, base + "/api/alerts/bale/verify", {"code": "x"})[0] == 400
    code, res = _call(c, base + "/api/alerts/bale/verify", {"code": digits})
    assert code == 200 and res["bale_verified"] is True
    assert _call(c, base + "/api/alerts/settings", {"bale": True})[0] == 200


def test_changing_the_chat_takes_the_verification_away(beta):
    base, _app, auth, sent = beta
    c = login(base, auth, "ali")
    _call(c, base + "/api/alerts/settings", {"bale_chat": "42"})
    _call(c, base + "/api/alerts/bale/code", {})
    digits = "".join(ch for ch in sent[0]["text"] if ch.isdigit())
    _call(c, base + "/api/alerts/bale/verify", {"code": digits})
    _call(c, base + "/api/alerts/settings", {"bale": True})
    code, res = _call(c, base + "/api/alerts/settings", {"bale_chat": "99"})
    assert code == 200 and res["bale_verified"] is False and res["bale"] is False


def test_a_code_cannot_be_asked_for_without_a_chat_or_an_account_or_a_bot(beta, tmp_path):
    base, _app, auth, sent = beta
    c = login(base, auth, "ali")
    code, res = _call(c, base + "/api/alerts/bale/code", {})
    assert code == 400 and "شناسه" in res["error"] and sent == []
    assert _call(_client(), base + "/api/alerts/bale/code", {})[0] == 401
    assert _call(_client(), base + "/api/alerts/bale/verify", {"code": "1"})[0] == 401


def test_an_unverified_chat_never_receives_alerts(tmp_path: Path):
    from nnfx.alerts import BaleSender, Notifier, alerts_from_cycle
    from tests.test_alerts import CYCLE, SYMBOLS

    posts: list = []
    n = Notifier(AlertStore(tmp_path), BaleSender("T", post=lambda u, b: posts.append(b)))
    n.store.set_settings("ali", AlertSettings(True, True, "9"))  # not verified
    n.submit("ali", alerts_from_cycle("r", CYCLE, SYMBOLS)[:1])
    n.flush()
    assert posts == [] and len(n.store.feed("ali")) == 1  # the feed still works
