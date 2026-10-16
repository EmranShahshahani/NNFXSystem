"""Ticket 00: pinned environment and merge-safe research state."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from nnfx.env import EnvironmentFingerprint, fingerprint
from nnfx.research.logs import AppendOnlyLog, reconcile

ROOT = Path(__file__).parent.parent


def test_toolchain_bounded_and_lockfile_committed():
    assert (ROOT / ".python-version").read_text().strip() == "3.13"
    assert 'requires-python = ">=3.13,<3.14"' in (ROOT / "pyproject.toml").read_text()
    assert (ROOT / "uv.lock").exists()


def test_fingerprint_is_stable_and_serialisable():
    fp = fingerprint()
    again = EnvironmentFingerprint.model_validate_json(fp.model_dump_json())
    assert again == fp and again.digest == fp.digest
    assert fp.python.count(".") == 2
    names = dict(fp.packages)
    assert "numpy" in names and "pandas" in names and "pydantic" in names
    other = fp.model_copy(
        update={"packages": tuple((n, "0" if n == "numpy" else v) for n, v in fp.packages)}
    )
    assert any(d.startswith("numpy") for d in other.differs_from(fp))


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.mark.parametrize(
    "path", ["data/cache/x.csv", "runs/a.json", ".env", ".venv/x", "data/raw/a.bi5"]
)
def test_gitignore_excludes(path):
    assert _git("check-ignore", "--no-index", path).strip() == path


@pytest.mark.parametrize(
    "path",
    [
        "research/trials.jsonl",
        "data/manifests/dukascopy/EURUSD.H1.json",
        "research/thresholds.frozen.json",
        "uv.lock",
        ".env.example",
    ],
)
def test_gitignore_keeps_research_state(path):
    out = subprocess.run(
        ["git", "check-ignore", "--no-index", path], cwd=ROOT, capture_output=True, text=True
    )
    assert out.returncode == 1, f"{path} must not be ignored"


def test_gitignore_documents_why():
    text = (ROOT / ".gitignore").read_text()
    assert "Deliberately NOT ignored" in text and "undercount" in text


def test_gitattributes():
    attrs = _git(
        "check-attr",
        "eol",
        "merge",
        "--",
        "research/trials.jsonl",
        "research/thresholds.frozen.json",
        "journal/x.jsonl",
        "nnfx/env.py",
    )
    assert "research/trials.jsonl: merge: union" in attrs
    assert "journal/x.jsonl: merge: union" in attrs
    assert "research/thresholds.frozen.json: merge: unset" in attrs
    assert "nnfx/env.py: eol: lf" in attrs


def test_env_example_documents_keys():
    text = (ROOT / ".env.example").read_text()
    for needle in (
        "NNFX_WORKSTATION_ID",
        "NNFX_CACHE_DIR",
        "API_KEY",
        "WITHDRAWAL MUST BE DISABLED",
    ):
        assert needle in text


def test_two_workstation_union_merge_then_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two machines append divergently; union merge; derived count has no double counting."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*a: str) -> None:
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, env=env)

    git("init", "-q", "-b", "main")
    (repo / ".gitattributes").write_text((ROOT / ".gitattributes").read_text())
    log = AppendOnlyLog(repo / "research" / "trials.jsonl")
    monkeypatch.setenv("NNFX_WORKSTATION_ID", "base")
    log.append({"id": "t1"})
    git("add", ".")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "laptop")
    monkeypatch.setenv("NNFX_WORKSTATION_ID", "laptop")
    log.append({"id": "t2"})
    log.append({"id": "t3"})  # also run on the desktop: same content-hash id
    git("commit", "-qam", "laptop")
    git("checkout", "-q", "main")
    monkeypatch.setenv("NNFX_WORKSTATION_ID", "desktop")
    log.append({"id": "t3"})
    log.append({"id": "t4"})
    git("commit", "-qam", "desktop")
    git("merge", "-q", "--no-edit", "laptop")  # must not conflict
    lines = (repo / "research" / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 5  # t1, t3, t4 from desktop + t2, t3 from laptop (t3 twice)
    rep = reconcile(repo / "research" / "trials.jsonl")
    assert rep.distinct == 4 and rep.duplicates_removed == 1
    assert rep.per_workstation == {"base": 1, "desktop": 2, "laptop": 1}
    assert AppendOnlyLog(repo / "research" / "trials.jsonl").count() == 4
    assert all(
        "env" in json.loads(x)
        for x in (repo / "research" / "trials.jsonl").read_text().splitlines()
    )


def test_reconcile_cli(tmp_path: Path):
    from nnfx.cli import main

    log = AppendOnlyLog(tmp_path / "trials.jsonl")
    log.append({"id": "a"})
    log.append({"id": "a"})
    assert main(["research", "reconcile", "--dir", str(tmp_path)]) == 0
    assert log.count() == 1 and len(list(log.records())) == 1
