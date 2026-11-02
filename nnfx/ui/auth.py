"""Invite-only accounts for the beta (B1). Standard library only.

SQLite holds users, single-use invite codes, sessions and feedback. Passwords
are hashed with scrypt and a per-user salt; session tokens are random and only
their SHA-256 is stored, so a leaked database does not leak live sessions.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SESSION_DAYS = 30
USERNAME = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")
MIN_PASSWORD = 8
LOGIN_WINDOW_S = 600
LOGIN_MAX_FAILS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_salt BLOB NOT NULL,
    pw_hash BLOB NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
    code TEXT PRIMARY KEY, created REAL NOT NULL, note TEXT,
    used_by INTEGER REFERENCES users(id), used_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), created REAL NOT NULL,
    page TEXT, text TEXT NOT NULL
);
"""


class AuthError(ValueError):
    pass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    is_admin: bool


def _hash_pw(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, db_path: Path | str, clock: object = time.time) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        with self._db() as db:
            db.executescript(SCHEMA)

    def _now(self) -> float:
        now: float = self._clock()  # type: ignore[operator]
        return now

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # -------------------------------------------------------------- invites
    def create_invites(self, n: int = 1, note: str = "") -> list[str]:
        codes = [secrets.token_urlsafe(9) for _ in range(n)]
        with self._lock, self._db() as db:
            db.executemany(
                "INSERT INTO invites(code, created, note) VALUES (?, ?, ?)",
                [(c, self._now(), note) for c in codes],
            )
        return codes

    def invites(self) -> list[tuple[str, str, str | None]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT i.code, i.note, u.username FROM invites i LEFT JOIN users u ON u.id = i.used_by"
                " ORDER BY i.created"
            ).fetchall()
        return [(str(c), str(n or ""), u) for c, n, u in rows]

    # ---------------------------------------------------------------- users
    def signup(self, invite: str, username: str, password: str, *, admin: bool = False) -> User:
        if not USERNAME.match(username):
            raise AuthError("نام کاربری باید ۳ تا ۳۲ حرف لاتین، عدد یا _ . - باشد")
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"رمز عبور دست‌کم {MIN_PASSWORD} نویسه باشد")
        salt = secrets.token_bytes(16)
        with self._lock, self._db() as db:
            row = db.execute("SELECT used_by FROM invites WHERE code = ?", (invite,)).fetchone()
            if row is None or row[0] is not None:
                raise AuthError("کد دعوت نامعتبر است یا قبلاً استفاده شده")
            try:
                cur = db.execute(
                    "INSERT INTO users(username, pw_salt, pw_hash, is_admin, created) VALUES (?, ?, ?, ?, ?)",
                    (username, salt, _hash_pw(password, salt), int(admin), self._now()),
                )
            except sqlite3.IntegrityError:
                raise AuthError("این نام کاربری گرفته شده است") from None
            uid = int(cur.lastrowid or 0)
            db.execute(
                "UPDATE invites SET used_by = ?, used_at = ? WHERE code = ?",
                (uid, self._now(), invite),
            )
        return User(uid, username, admin)

    def users(self) -> list[User]:
        with self._db() as db:
            rows = db.execute("SELECT id, username, is_admin FROM users ORDER BY id").fetchall()
        return [User(int(i), str(u), bool(a)) for i, u, a in rows]

    def _throttled(self, key: str) -> bool:
        now = self._now()
        recent = [t for t in self._fails.get(key, []) if now - t < LOGIN_WINDOW_S]
        self._fails[key] = recent
        return len(recent) >= LOGIN_MAX_FAILS

    def login(self, username: str, password: str, client: str = "") -> str:
        """Returns a new session token."""
        key = f"{client}|{username}"
        if self._throttled(key):
            raise AuthError("تلاش‌های ناموفق زیاد بود؛ چند دقیقه بعد دوباره امتحان کنید")
        with self._db() as db:
            row = db.execute(
                "SELECT id, pw_salt, pw_hash FROM users WHERE username = ?", (username,)
            ).fetchone()
        ok = row is not None and hmac.compare_digest(_hash_pw(password, row[1]), row[2])
        if not ok:
            self._fails.setdefault(key, []).append(self._now())
            raise AuthError("نام کاربری یا رمز عبور اشتباه است")
        token = secrets.token_urlsafe(32)
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO sessions(token_hash, user_id, expires) VALUES (?, ?, ?)",
                (_token_hash(token), int(row[0]), self._now() + SESSION_DAYS * 86400),
            )
            db.execute("DELETE FROM sessions WHERE expires < ?", (self._now(),))
        return token

    def user_for(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._db() as db:
            row = db.execute(
                "SELECT u.id, u.username, u.is_admin, s.expires FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash = ?",
                (_token_hash(token),),
            ).fetchone()
        if row is None or row[3] < self._now():
            return None
        return User(int(row[0]), str(row[1]), bool(row[2]))

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock, self._db() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

    # ------------------------------------------------------------- feedback
    def add_feedback(self, user: User, text: str, page: str = "") -> None:
        text = text.strip()
        if not text:
            raise AuthError("متن بازخورد خالی است")
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO feedback(user_id, created, page, text) VALUES (?, ?, ?, ?)",
                (user.id, self._now(), page[:64], text[:4000]),
            )

    def feedback(self) -> list[dict[str, object]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT f.created, u.username, f.page, f.text FROM feedback f LEFT JOIN users u ON u.id = f.user_id"
                " ORDER BY f.created DESC"
            ).fetchall()
        return [{"created": c, "user": u, "page": p, "text": t} for c, u, p, t in rows]
