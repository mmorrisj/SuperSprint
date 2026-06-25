"""MLT governance: Mandate (scope) and Lattice (authorization verdict).

These are the deterministic gates that stand between a planned change and the
sandbox. None of them ask the model anything.

Mandate answers "is this action *allowed at all*?" (scope, tools, forbidden
paths). Lattice renders a per-decision verdict: ALLOW / ESCALATE / BLOCK,
combining categorical always-escalate rules, numeric change-size gates, the
confidence score, and the Mandate scope check.

TRACE (the tool-call broker + evidence chain) lives in ``evidence.py`` plus the
pipeline wiring; here we only decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .policy import Policy
from .scoring import Score
from .tickets.base import Ticket


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    ESCALATE = "ESCALATE"  # human must approve (HITL)
    BLOCK = "BLOCK"  # hard refusal; never executes


@dataclass
class PlannedChange:
    """What Lane 4 intends to do, evaluated before (and again after) execution."""

    paths: list[str]
    tools: list[str]
    lines_changed: int


@dataclass
class Decision:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict == Verdict.ALLOW


def mandate_scope_check(change: PlannedChange, policy: Policy) -> list[str]:
    """Return a list of scope violations (empty == in scope)."""
    violations = []
    for p in change.paths:
        if not policy.path_writable(p):
            violations.append(f"path out of scope: {p}")
    for t in change.tools:
        if not policy.tool_allowed(t):
            violations.append(f"tool not permitted: {t}")
    return violations


def lattice_verdict(
    ticket: Ticket,
    change: PlannedChange,
    score: Score,
    policy: Policy,
) -> Decision:
    reasons: list[str] = []

    # 1. Hard scope/tool violations -> BLOCK (never executes).
    violations = mandate_scope_check(change, policy)
    if violations:
        return Decision(Verdict.BLOCK, reasons=violations)

    # 2. Categorical always-escalate rules: regardless of confidence.
    if policy.category_always_escalates(ticket.category):
        reasons.append(f"category '{ticket.category}' always escalates")
        return Decision(Verdict.ESCALATE, reasons=reasons)

    # 3. Change-size gate.
    tier = policy.change_size_tier(change.lines_changed)
    if tier == "human":
        reasons.append(
            f"change is {change.lines_changed} lines (> extended max "
            f"{policy.change_size.extended_max_lines}) -> human review"
        )
        return Decision(Verdict.ESCALATE, reasons=reasons)
    if tier == "extended":
        reasons.append(f"change {change.lines_changed} lines: extended verification tier")

    # 4. Confidence gate.
    if score.value < policy.confidence.autonomous_min:
        reasons.append(
            f"confidence {score.value:.2f} < autonomous min "
            f"{policy.confidence.autonomous_min:.2f}"
        )
        return Decision(Verdict.ESCALATE, reasons=reasons)

    reasons.append(f"in scope, {tier} tier, confidence {score.value:.2f} -> autonomous")
    return Decision(Verdict.ALLOW, reasons=reasons)
