"""Shared fixtures: a throwaway git repo and a loaded policy."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orchestrator.policy import load_policy

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def target_repo(tmp_path) -> Path:
    """A minimal git repo with a src/ module and a passing test."""
    repo = tmp_path / "target"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    # A test that currently passes (so an empty/irrelevant change keeps it green).
    (repo / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    (repo / "pytest.ini").write_text("[pytest]\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


@pytest.fixture
def policy():
    return load_policy(REPO_ROOT / "policy" / "profiles" / "minimal.md")


@pytest.fixture
def strict_policy():
    return load_policy(REPO_ROOT / "policy" / "profiles" / "strict.md")
