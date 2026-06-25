"""Harness adapter interface — the "model/harness agnostic" seam.

A harness is anything that, given a prompt and a sandbox working directory,
produces file edits plus a transcript of what it did. Real adapters wrap
Claude Code / Codex / Aider / a self-hosted vLLM endpoint run headless. The
orchestrator only ever sees this interface, so swapping harnesses is a config
change.

The harness reports the edits it made; the orchestrator (not the harness) is
responsible for scope enforcement, testing, and deciding whether the work is
acceptable. The harness is never trusted to grade itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class FileEdit:
    path: str  # repo-relative
    content: str  # full new file content (create or overwrite)


@dataclass
class HarnessResult:
    edits: list[FileEdit] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    # The harness may *claim* success, but the orchestrator independently
    # verifies. This flag is advisory only and never trusted for "Done".
    claimed_success: bool = True

    def lines_changed(self) -> int:
        return sum(len(e.content.splitlines()) for e in self.edits)

    def paths(self) -> list[str]:
        return [e.path for e in self.edits]


class Harness(Protocol):
    name: str

    def run(self, prompt: str, workdir: str | Path, *, budget_tokens: int) -> HarnessResult:
        """Run the harness inside ``workdir`` and return what it changed."""
        ...
