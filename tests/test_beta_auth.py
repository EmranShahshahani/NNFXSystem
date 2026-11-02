"""Beta B1: invite-only accounts, sessions, access control and feedback."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.cookiejar import CookieJar
from pathlib import Path

import pytest

from nnfx.ui.auth import Auth, AuthError
from nnfx.ui.server import App, serve

ROOT = Path(__file__).resolve().parents[1]


def test_invites_are_single_use_and_passwords_hashed(tmp_path: Path):
    a = Auth(tmp_path / "b.db")
    code = a.create_invites(1, "ali")[0]
    u = a.signup(code, "ali", "s3cret-pass")
    with pytest.raises(AuthError):
        a.signup(code, "reza", "s3cret-pass")
    with pytest.raises(AuthError):
        a.signup("nope", "reza", "s3cret-pass")
    with pytest.raises(AuthError):
        a.signup(a.create_invites()[0], "x", "s3cret-pass")  # username too short
    with pytest.raises(AuthError):
        a.signup(a.create_invites()[0], "reza", "short")
    assert b"s3cret-pass" not in (tmp_path / "b.db").read_bytes()
    tok = a.login("ali", "s3cret-pass")
    assert a.user_for(tok) == u and a.user_for("forged") is None
    a.logout(tok)
    assert a.user_for(tok) is None


def test_login_throttle_and_session_expiry(tmp_path: Path):
    now = [1000.0]
    a = Auth(tmp_path / "b.db", clock=lambda: now[0])
    a.signup(a.create_invites()[0], "sara", "good-password")
    for _ in range(10):
        with pytest.raises(AuthError):
            a.login("sara", "wrong", "1.2.3.4")
    with pytest.raises(AuthError, match="ناموفق"):
        a.login("sara", "good-password", "1.2.3.4")
    now[0] += 601
    tok = a.login("sara", "good-password", "1.2.3.4")
    now[0] += 31 * 86400
    assert a.user_for(tok) is None


@pytest.fixture()
def beta(tmp_path: Path) -> Iterator[tuple[str, Auth]]:
    auth = Auth(tmp_path / "beta.db")
    httpd = serve(App(ROOT, auth=auth), port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", auth
    httpd.shutdown()


def _client() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _call(
    op: urllib.request.OpenerDirector, url: str, body: object | None = None
) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    try:
        with op.open(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_everything_but_login_requires_a_session(beta):
    base, auth = beta
    anon = _client()
    assert _call(anon, base + "/api/me")[1] == {"user": None, "admin": False, "auth": True}
    for path in ("/api/datasets", "/api/rules", "/api/research", "/api/live", "/api/catalogue"):
        assert _call(anon, base + path)[0] == 401
    assert _call(anon, base + "/api/backtest", {"datasets": []})[0] == 401
    assert _call(anon, base + "/api/feedback", {"text": "hi"})[0] == 401

    me = _client()
    code, r = _call(
        me,
        base + "/api/signup",
        {"invite": auth.create_invites()[0], "username": "neda", "password": "long-enough"},
    )
    assert code == 200 and r["ok"]
    assert _call(me, base + "/api/me")[1]["user"] == "neda"
    code, rules = _call(me, base + "/api/rules")
    assert code == 200 and len(rules["rules"]) == 42
    assert (
        _call(me, base + "/api/feedback", {"text": "نمودار روی گوشی کوچک است", "page": "backtest"})[
            0
        ]
        == 200
    )
    # Not an admin: no invites, no feedback list.
    assert _call(me, base + "/api/admin/invites", {"n": 1})[0] == 403
    assert _call(me, base + "/api/admin/feedback")[0] == 403
    assert _call(me, base + "/api/logout", {})[0] == 200
    assert _call(me, base + "/api/datasets")[0] == 401


def test_admin_creates_invites_and_reads_feedback(beta):
    base, auth = beta
    auth.signup(auth.create_invites()[0], "admin", "admin-password", admin=True)
    adm = _client()
    assert (
        _call(adm, base + "/api/login", {"username": "admin", "password": "admin-password"})[0]
        == 200
    )
    code, r = _call(adm, base + "/api/admin/invites", {"n": 2, "note": "friends"})
    assert code == 200 and len(r["codes"]) == 2
    friend = _client()
    assert (
        _call(
            friend,
            base + "/api/signup",
            {"invite": r["codes"][0], "username": "omid", "password": "password-1"},
        )[0]
        == 200
    )
    _call(friend, base + "/api/feedback", {"text": "great"})
    fb = _call(adm, base + "/api/admin/feedback")[1]
    assert fb[0]["user"] == "omid" and fb[0]["text"] == "great"
    inv = _call(adm, base + "/api/admin/invites")[1]
    assert any(x["used_by"] == "omid" for x in inv)


def test_beta_never_leaks_tracebacks(beta, monkeypatch):
    base, auth = beta
    auth.signup(auth.create_invites()[0], "user1", "password-1")
    c = _client()
    _call(c, base + "/api/login", {"username": "user1", "password": "password-1"})
    monkeypatch.setattr(App, "backtest", lambda self, req: 1 / 0)
    code, r = _call(c, base + "/api/backtest", {"datasets": []})
    assert code == 500 and "trace" not in r


def test_cli_refuses_public_bind_without_accounts():
    from nnfx.cli import main

    with pytest.raises(SystemExit, match="auth-db"):
        main(["ui", "--host", "0.0.0.0", "--port", "0"])
