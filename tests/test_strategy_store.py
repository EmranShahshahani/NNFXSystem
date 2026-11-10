"""The per-user, versioned store of Strategy Documents (Strategy Builder ticket 13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nnfx.strategy import get_template, validate_document
from nnfx.strategy.store import MAX_STRATEGIES, MAX_VERSIONS, StrategyStore

TCP = get_template("tcp_azizpour")


def doc(name="mine", **risk):
    raw = TCP.clone(name)
    raw["risk"].update(risk)
    res = validate_document(raw)
    assert res.document is not None, res.render()
    return res.document


def test_the_first_save_is_version_one_and_a_change_makes_the_next_version(tmp_path: Path):
    s = StrategyStore(tmp_path)
    a = s.save("ali", doc())
    assert (a.name, a.version, a.unchanged) == ("mine", 1, False)
    b = s.save("ali", doc(risk_per_trade=0.004))
    assert (b.version, b.unchanged) == (2, False) and b.fingerprint != a.fingerprint
    assert s.load("ali", "mine").metadata.version == 2  # the latest, with its own number
    assert s.load("ali", "mine", 1).fingerprint() == a.fingerprint  # an old version is intact
    assert [v["version"] for v in s.versions("ali", "mine")] == [1, 2]


def test_saving_an_identical_document_adds_no_version(tmp_path: Path):
    s = StrategyStore(tmp_path)
    s.save("ali", doc())
    again = s.save("ali", doc())
    assert (again.version, again.unchanged) == (1, True)
    assert len(s.versions("ali", "mine")) == 1


def test_the_version_a_client_claims_is_ignored(tmp_path: Path):
    raw = TCP.clone("mine")
    raw["metadata"]["version"] = 99
    d = validate_document(raw).document
    assert d is not None
    assert StrategyStore(tmp_path).save("ali", d).version == 1


def test_each_user_has_their_own_strategies(tmp_path: Path):
    s = StrategyStore(tmp_path)
    s.save("ali", doc("x"))
    assert s.list("sara") == []
    with pytest.raises(KeyError, match="x"):
        s.load("sara", "x")
    s.save("sara", doc("x", risk_per_trade=0.003))
    assert s.load("ali", "x").risk.risk_per_trade != s.load("sara", "x").risk.risk_per_trade


def test_the_listing_names_the_latest_version_and_the_parent(tmp_path: Path):
    s = StrategyStore(tmp_path)
    s.save("ali", doc("b"))
    s.save("ali", doc("a"))
    s.save("ali", doc("a", risk_per_trade=0.004))
    rows = s.list("ali")
    assert [(r["name"], r["version"], r["versions"]) for r in rows] == [("a", 2, 2), ("b", 1, 1)]
    assert rows[0]["parent"] == "tcp_azizpour" and rows[0]["fingerprint"]


def test_names_with_path_characters_and_persian_are_safe(tmp_path: Path):
    s = StrategyStore(tmp_path)
    for n in ["../../etc/passwd", "استراتژی من", "a/b", " spaced "]:
        s.save("../ali", doc(n))
    assert {r["name"] for r in s.list("../ali")} == {
        "../../etc/passwd", "استراتژی من", "a/b", "spaced",
    }  # fmt: skip
    assert all(p.is_relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert s.load("../ali", " spaced ").metadata.name == "spaced"


def test_delete_removes_every_version(tmp_path: Path):
    s = StrategyStore(tmp_path)
    s.save("ali", doc())
    s.save("ali", doc(risk_per_trade=0.004))
    s.delete("ali", "mine")
    assert s.list("ali") == []
    with pytest.raises(KeyError):
        s.delete("ali", "mine")


def test_the_missing_things_are_persian_errors(tmp_path: Path):
    s = StrategyStore(tmp_path)
    s.save("ali", doc())
    with pytest.raises(KeyError, match="استراتژی"):
        s.load("ali", "nope")
    with pytest.raises(KeyError, match="نسخهٔ 7"):
        s.load("ali", "mine", 7)


def test_the_caps_protect_the_disk(tmp_path: Path):
    s = StrategyStore(tmp_path)
    for i in range(MAX_STRATEGIES):
        s.save("ali", doc(f"s{i}"))
    with pytest.raises(ValueError, match="حداکثر"):
        s.save("ali", doc("one too many"))
    s.save("ali", doc("s0", risk_per_trade=0.004))  # a new version of an old one is fine
    for i in range(MAX_VERSIONS - 2):
        s.save("ali", doc("s0", risk_per_trade=0.001 + i * 1e-5))
    with pytest.raises(ValueError, match="نسخه"):
        s.save("ali", doc("s0", risk_per_trade=0.0099))


def test_a_blank_name_and_a_damaged_file_do_not_break_the_store(tmp_path: Path):
    s = StrategyStore(tmp_path)
    raw = TCP.clone("   ")
    d = validate_document(raw).document
    assert d is not None
    with pytest.raises(ValueError, match="خالی"):
        s.save("ali", d)
    s.save("ali", doc("good"))
    s.save("ali", doc("bad"))
    for f in tmp_path.rglob("v0001.json"):
        if '"bad"' in f.read_text(encoding="utf-8"):
            f.write_text("{broken", encoding="utf-8")
    assert [r["name"] for r in s.list("ali")] == ["good"]  # the damaged one is skipped
    assert s.save("ali", doc("bad")).version == 2  # and saving repairs its line
    s.delete("ali", "bad")  # a stray temp file does not stop a delete
    assert [r["name"] for r in s.list("ali")] == ["good"]
