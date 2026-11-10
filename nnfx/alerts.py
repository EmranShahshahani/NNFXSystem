"""Alerts for paper runs (Strategy Builder ticket 22, ADR 10 §26).

A paper cycle's journal record becomes alerts (a Setup Candidate appeared; a Trigger was
placed, filled, cancelled or expired). Each user has an in-site feed and, optionally, a Bale
bot chat, each switchable. Delivery is best effort and off the trading path: the feed write is
local and wrapped, Bale goes through a worker thread with retries, and a failure is logged per
user and never raised to the caller.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BALE_URL = "https://tapi.bale.ai/bot{token}/sendMessage"
FEED_LIMIT = 500  # alerts returned at once
Post = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class Alert:
    id: str
    time: str  # the bar the alert is about
    kind: str  # candidate | placed | filled | cancelled | expired | halt | book_stale | book_back
    symbol: str
    text: str  # Persian, ready to show or send
    run: str = ""

    def record(self) -> dict[str, Any]:
        return asdict(self)


def _id(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def _num(x: Any) -> str:
    return f"{x:.8g}" if isinstance(x, (int, float)) else str(x)


def _side(direction: int) -> str:
    return "خرید" if direction > 0 else "فروش"


def alerts_from_cycle(run: str, rec: Mapping[str, Any], symbols: Mapping[str, str]) -> list[Alert]:
    """The alerts one journaled cycle holds; ``symbols`` maps order keys to symbols.

    Ids depend only on the run and the cycle's contents, so replaying a cycle adds nothing.
    """
    when = str(rec["time"])
    out: list[Alert] = []
    for ev in rec.get("evaluations", []):
        v = ev["values"]
        if "event" in v:
            continue  # a management event (stop move, close), not a Setup Candidate
        sym = ev["symbol"]
        verdict = "سفارش ثبت شد" if v.get("decision") == "placed" else "رد شد"
        why = f" ({'، '.join(v['reasons'])})" if v.get("reasons") else ""
        out.append(
            Alert(
                _id(run, when, "candidate", sym, v.get("setup"), v.get("block")),
                when,
                "candidate",
                sym,
                f"نامزد ستاپ {sym}: {v.get('setup')} ({_side(int(v.get('direction', 1)))}) "
                f"تریگر {_num(v.get('trigger'))} — {verdict}{why}",
                run,
            )
        )
    for e in rec.get("orders", []):
        kind = e["e"]
        sym = symbols.get(e.get("key", ""), "?")
        if kind == "place":
            kind_, text = "placed", f"تریگر {sym} در {_num(e.get('trigger'))} ثبت شد"
        elif kind == "fill":
            kind_, text = "filled", f"سفارش {sym} پر شد (قیمت {_num(e.get('price'))})"
        elif kind == "cancel" and e.get("reason") == "expired":
            kind_, text = "expired", f"سفارش {sym} منقضی شد"
        elif kind == "cancel":
            kind_, text = "cancelled", f"سفارش {sym} لغو شد ({e.get('reason')})"
        else:
            continue
        out.append(Alert(_id(run, when, kind_, e.get("n")), when, kind_, sym, text, run))
    return out


@dataclass(frozen=True)
class AlertSettings:
    in_site: bool = True
    bale: bool = False
    bale_chat: str = ""


def owner_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class AlertStore:
    """Per user: ``settings.json``, ``feed.jsonl`` and ``failures.jsonl`` (names hashed)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._seen: dict[str, set[str]] = {}

    def _dir(self, user: str) -> Path:
        return self.root / owner_hash(user)

    def settings(self, user: str) -> AlertSettings:
        p = self._dir(user) / "settings.json"
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            return AlertSettings(bool(raw["in_site"]), bool(raw["bale"]), str(raw["bale_chat"]))
        except (OSError, ValueError, KeyError):
            return AlertSettings()

    def set_settings(self, user: str, s: AlertSettings) -> None:
        d = self._dir(user)
        with self._lock:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "settings.tmp"
            tmp.write_text(json.dumps(asdict(s)), encoding="utf-8")
            tmp.replace(d / "settings.json")

    def _lines(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line from a crash
        return out

    def first_time(self, user: str, alert_id: str) -> bool:
        """Whether this alert has not been handled before (any channel); remembers it.

        A replayed cycle (a crash between handing alerts over and noting it) is thereby
        neither re-sent to Bale nor re-added to the feed, whatever the user's switches are.
        """
        d = self._dir(user)
        with self._lock:
            if user not in self._seen:
                self._seen[user] = {r["id"] for r in self._lines(d / "seen.jsonl")}
            if alert_id in self._seen[user]:
                return False
            d.mkdir(parents=True, exist_ok=True)
            with (d / "seen.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": alert_id}) + "\n")
            self._seen[user].add(alert_id)
        return True

    def append(self, user: str, alert: Alert) -> bool:
        """Add to the feed unless an alert with that id is already there."""
        d = self._dir(user)
        with self._lock:
            d.mkdir(parents=True, exist_ok=True)
            rows = self._lines(d / "feed.jsonl")
            if any(r["id"] == alert.id for r in rows):
                return False
            seq = max((r["seq"] for r in rows), default=0) + 1
            with (d / "feed.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"seq": seq, **alert.record()}, ensure_ascii=False) + "\n")
        return True

    def feed(self, user: str, after: int = 0) -> list[dict[str, Any]]:
        rows = [r for r in self._lines(self._dir(user) / "feed.jsonl") if r["seq"] > after]
        return rows[-FEED_LIMIT:]

    def log_failure(self, user: str, alert: Alert, channel: str, error: str) -> None:
        d = self._dir(user)
        d.mkdir(parents=True, exist_ok=True)
        row = {"id": alert.id, "channel": channel, "error": error, "at": time.time()}
        with self._lock, (d / "failures.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def failures(self, user: str) -> list[dict[str, Any]]:
        return self._lines(self._dir(user) / "failures.jsonl")


def default_post(url: str, body: dict[str, Any]) -> None:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


class BaleSender:
    """The Bale bot API (Telegram-compatible ``sendMessage``) with retries and growing delays."""

    def __init__(
        self,
        token: str,
        *,
        post: Post = default_post,
        sleep: Callable[[float], None] = time.sleep,
        attempts: int = 3,
        base_delay: float = 2.0,
    ) -> None:
        self.token, self.post, self.sleep = token, post, sleep
        self.attempts, self.base_delay = attempts, base_delay

    def send(self, chat: str, text: str) -> str | None:
        """None when delivered, else the last error."""
        url = BALE_URL.format(token=self.token)
        error = ""
        for k in range(self.attempts):
            if k:
                self.sleep(self.base_delay * 2 ** (k - 1))
            try:
                self.post(url, {"chat_id": chat, "text": text})
                return None
            except Exception as e:  # any transport failure is a failed attempt
                error = f"{type(e).__name__}: {e}"
        return error


class Notifier:
    """Delivers alerts per each user's switches, off the caller's thread, never raising."""

    def __init__(self, store: AlertStore, bale: BaleSender | None = None) -> None:
        self.store, self.bale = store, bale
        self._q: queue.Queue[tuple[str, Alert, str] | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._start = threading.Lock()

    def submit(self, user: str, alerts: list[Alert]) -> None:
        for a in alerts:
            try:
                if not self.store.first_time(user, a.id):
                    continue
                s = self.store.settings(user)
                if s.in_site:
                    self.store.append(user, a)
                if s.bale and s.bale_chat and self.bale is not None:
                    self._ensure_worker()
                    self._q.put((user, a, s.bale_chat))
            except Exception:  # alerts must never reach the trading path
                log.exception("alert for %s not queued", user)

    def _ensure_worker(self) -> None:
        with self._start:
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, daemon=True, name="alerts")
                self._worker.start()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is not None:
                    self._deliver(*item)
            except Exception:
                log.exception("alert delivery crashed")
            finally:
                self._q.task_done()

    def _deliver(self, user: str, alert: Alert, chat: str) -> None:
        assert self.bale is not None
        error = self.bale.send(chat, alert.text)
        if error is not None:
            log.warning("Bale delivery failed for %s: %s", alert.id, error)
            self.store.log_failure(user, alert, "bale", error)

    def flush(self) -> None:
        """Wait until everything queued has been tried (tests, shutdown)."""
        self._q.join()


def halt_alert(run: str, when: str, reason: str) -> Alert:
    """A run stopped itself (reconciliation failed, bars unavailable): the user must look."""
    return Alert(
        _id(run, when, "halt", reason), when, "halt", "", f"اجرای کاغذی متوقف شد: {reason}", run
    )


def book_alert(run: str, when: str, symbol: str, stale: bool) -> Alert:
    """The recorder stopped delivering books for ``symbol`` (or resumed): once per outage."""
    kind = "book_stale" if stale else "book_back"
    text = (
        f"دفتر سفارش {symbol} دیگر تازه نمی‌شود؛ بلوک‌های دفتر مثل همتای ساده‌شان عمل می‌کنند"
        if stale
        else f"دفتر سفارش {symbol} دوباره تازه شد"
    )
    return Alert(_id(run, when, kind, symbol), when, kind, symbol, text, run)
