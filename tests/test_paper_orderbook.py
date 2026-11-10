"""Recorded order books reach the paper-run server (Strategy Builder ticket 24, ADR 10 §28)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nnfx.cli import main
from nnfx.instruments import InstrumentRegistry
from nnfx.orderbook import OrderBookSnapshot, RecordedOrderBook, record
from nnfx.strategy.paper import paper_symbols
from nnfx.ui.server import App

ROOT = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2024-03-01T10:00:00Z")


def registry() -> InstrumentRegistry:
    return InstrumentRegistry.load(ROOT / "config" / "instruments.yaml")


class Feed:
    """A live source answering for every symbol asked."""

    def snapshots_now(self, symbols: Sequence[str]) -> dict[str, OrderBookSnapshot]:
        return {
            s: OrderBookSnapshot.of(s, T0, [[99, 1]], [[101, 1]], 100.0, exchange_time=T0)
            for s in symbols
        }


def test_paper_symbols_are_the_nobitex_usdt_pairs():
    syms = paper_symbols(registry())
    assert "BTC/USDT" in syms and all(s.endswith("/USDT") for s in syms)
    assert not any("IRT" in s for s in syms)


def test_a_recording_of_a_paper_symbol_is_read_back_under_the_same_name(tmp_path: Path):
    syms = list(paper_symbols(registry()))
    clock = iter([T0 + pd.Timedelta(seconds=10 * k) for k in range(10)])
    record(Feed(), syms, tmp_path, iterations=1, clock=lambda: next(clock), sleep=lambda s: None)
    book = RecordedOrderBook(tmp_path)
    for sym in syms:
        snap = book.snapshot(sym, T0 + pd.Timedelta(seconds=30))
        assert snap is not None and snap.symbol == sym


@pytest.mark.parametrize("path", ["deploy/docker-compose.yml", "deploy/.env.example"])
def test_the_deployment_records_every_paper_symbol(path: str):
    text = (ROOT / path).read_text()
    line = next(ln for ln in text.splitlines() if "NNFX_ORDERBOOK_SYMBOLS" in ln)
    recorded = set(re.findall(r"[A-Z]+/[A-Z]+", line))
    assert set(paper_symbols(registry())) <= recorded, line


def test_the_server_keeps_the_recordings_directory_only_when_given(tmp_path: Path):
    assert App(ROOT, paper=str(tmp_path / "p"), alerts=str(tmp_path / "a")).orderbook_root is None
    app = App(ROOT, paper=str(tmp_path / "p"), alerts=str(tmp_path / "a"), orderbook="rec")
    assert app.orderbook_root == ROOT / "rec"


def test_the_ui_command_passes_the_flag_or_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    seen: list[Any] = []

    class FakeApp:
        def __init__(self, root: Path, **kw: Any) -> None:
            seen.append(kw.get("orderbook"))

    class FakeHttpd:
        server_address = ("127.0.0.1", 0)

        def serve_forever(self) -> None:
            return None

    monkeypatch.setattr("nnfx.ui.server.App", FakeApp)
    monkeypatch.setattr("nnfx.ui.server.serve", lambda *a, **k: FakeHttpd())
    monkeypatch.delenv("NNFX_ORDERBOOK", raising=False)
    base = ["ui", "--paper-interval", "0"]
    assert main(base) == 0
    assert main([*base, "--orderbook", str(tmp_path)]) == 0
    monkeypatch.setenv("NNFX_ORDERBOOK", "/from/env")
    assert main(base) == 0
    assert main([*base, "--orderbook", str(tmp_path)]) == 0  # the flag wins
    assert seen == [None, str(tmp_path), "/from/env", str(tmp_path)]
