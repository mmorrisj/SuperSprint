"""Git worktree sandbox.

Lane 4 / Lane 6 execution happens here. The sandbox is a throwaway git
worktree pinned to an approved revision: the harness writes there, tests run
there, and the main branch never contains unverified code. On context exit the
worktree is removed.

This is the lowest isolation tier. Higher tiers (container, microVM) implement
the same ``apply_edits`` / ``run`` / context-manager interface and are selected
by risk in a real deployment; the orchestrator is agnostic to which tier it got.

Honesty note: a worktree shares the host filesystem and network. It protects
the *main branch*, not the *host*. For untrusted code, swap in the container /
microVM tier.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .harness.base import FileEdit


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class GitWorktreeSandbox:
    def __init__(self, repo_path: str | Path, base_ref: str = "HEAD"):
        self.repo_path = Path(repo_path).resolve()
        self.base_ref = base_ref
        self._dir: Path | None = None
        self._branch: str | None = None

    @property
    def path(self) -> Path:
        if self._dir is None:
            raise RuntimeError("sandbox not entered")
        return self._dir

    def _git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or self.repo_path),
            capture_output=True,
            text=True,
            check=True,
        )

    def __enter__(self) -> "GitWorktreeSandbox":
        tmp = Path(tempfile.mkdtemp(prefix="supersprint-sbx-"))
        self._dir = tmp / "wt"
        # Resolve base_ref to a concrete commit so the sandbox is pinned even
        # if the branch moves underneath us.
        sha = self._git("rev-parse", self.base_ref).stdout.strip()
        self._branch = f"supersprint/sbx-{sha[:8]}-{tmp.name[-6:]}"
        self._git("worktree", "add", "--detach", str(self._dir), sha)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._dir is not None:
            try:
                self._git("worktree", "remove", "--force", str(self._dir))
            except subprocess.CalledProcessError:
                pass
            parent = self._dir.parent
            if parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
        self._dir = None

    # ----- operations ----------------------------------------------------
    def apply_edits(self, edits: Iterable[FileEdit]) -> list[str]:
        written = []
        for edit in edits:
            target = self.path / edit.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(edit.content)
            written.append(edit.path)
        return written

    def run(self, cmd: list[str], timeout: int = 600) -> RunResult:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return RunResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as e:
            return RunResult(124, e.stdout or "", (e.stderr or "") + "\n[timeout]")

    def diff(self) -> str:
        """Unified diff of the sandbox working tree vs the pinned base."""
        proc = subprocess.run(
            ["git", "diff"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        )
        # also include new untracked files
        add = subprocess.run(
            ["git", "add", "-A", "--intent-to-add"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        )
        del add
        proc2 = subprocess.run(
            ["git", "diff"],
            cwd=str(self.path),
            capture_output=True,
            text=True,
        )
        return proc2.stdout or proc.stdout
