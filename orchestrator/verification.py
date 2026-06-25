"""Independent verification (Lane 6).

The second half of the spine. Verification is *structurally independent* of the
step that wrote the code:

  * it runs in a *fresh* sandbox pinned to the same approved base,
  * it re-applies the candidate edits and re-derives acceptance criteria from
    the ticket itself (not from the harness's claims),
  * it *ignores* ``HarnessResult.claimed_success`` entirely.

"Done" requires this to pass. A harness that edits the test to make it pass is
caught because Lane 6 re-derives criteria from the ticket; a harness that
simply claims success without changing verifiable state fails because the
deterministic test command is what decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .harness.base import FileEdit
from .policy import Policy
from .sandbox import GitWorktreeSandbox
from .tickets.base import Ticket


@dataclass
class VerificationResult:
    passed: bool
    unmet: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(self.unmet) if self.unmet else "all acceptance checks passed"


def _derive_criteria(ticket: Ticket, policy: Policy) -> list[tuple[str, list[str]]]:
    """Re-derive acceptance checks (name, command) from the ticket + policy.

    Independent of whatever Lane 4 did. The base check is the policy's test
    command; tickets may add explicit verification commands in
    ``meta['acceptance_commands']`` (a list of shell argv lists).
    """
    checks: list[tuple[str, list[str]]] = [("policy test command", list(policy.runtime.test_command))]
    for i, cmd in enumerate(ticket.meta.get("acceptance_commands", [])):
        checks.append((f"acceptance[{i}]", list(cmd)))
    return checks


def verify(
    ticket: Ticket,
    edits: list[FileEdit],
    policy: Policy,
    repo_path: str | Path,
    base_ref: str,
    timeout: int = 600,
) -> VerificationResult:
    criteria = _derive_criteria(ticket, policy)
    unmet: list[str] = []
    checks: list[dict] = []
    # Fresh sandbox -> independence from Lane 4's working tree.
    with GitWorktreeSandbox(repo_path, base_ref) as sbx:
        sbx.apply_edits(edits)
        for name, cmd in criteria:
            result = sbx.run(cmd, timeout=timeout)
            checks.append(
                {
                    "name": name,
                    "cmd": cmd,
                    "exit_code": result.exit_code,
                    "passed": result.ok,
                    "tail": (result.stdout + result.stderr)[-500:],
                }
            )
            if not result.ok:
                unmet.append(f"{name} failed (exit {result.exit_code})")
    return VerificationResult(passed=not unmet, unmet=unmet, checks=checks)
