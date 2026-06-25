"""Deterministic mock harness.

Lets the entire spine run and be tested with no LLM. The "fix" is read from
``ticket.meta['fix_spec']``: a mapping of repo-relative path -> file content
the harness will write into the sandbox. This makes it trivial to construct
scenarios:

  * a *good* fix whose edits make the test command pass,
  * a *bad* fix that claims success but fails independent verification
    (exercising the "never fakes success" path),
  * an *out-of-scope* fix that touches forbidden paths (exercising Mandate),
  * a *huge* fix that trips the change-size gate.

Because it is deterministic, tests are reproducible.
"""

from __future__ import annotations

from pathlib import Path

from ..tickets.base import Ticket
from .base import Harness, HarnessResult, FileEdit


class MockHarness(Harness):
    name = "mock"

    def __init__(self, ticket: Ticket):
        self._ticket = ticket

    def run(self, prompt: str, workdir: str | Path, *, budget_tokens: int) -> HarnessResult:
        spec = self._ticket.meta.get("fix_spec", {})
        edits = [FileEdit(path=p, content=c) for p, c in spec.items()]
        claimed = bool(self._ticket.meta.get("claimed_success", True))
        transcript = [
            f"received prompt ({len(prompt)} chars)",
            f"writing {len(edits)} file(s): {', '.join(e.path for e in edits) or '(none)'}",
            "claiming success" if claimed else "reporting failure",
        ]
        # A real harness would also emit tool_calls; we record the writes so
        # the TRACE gateway / evidence chain has something to broker.
        tool_calls = [{"tool": "write", "path": e.path} for e in edits]
        return HarnessResult(
            edits=edits,
            transcript=transcript,
            tool_calls=tool_calls,
            tokens_in=len(prompt) // 4,
            tokens_out=sum(len(e.content) for e in edits) // 4,
            claimed_success=claimed,
        )
