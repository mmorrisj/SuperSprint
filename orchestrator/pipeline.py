"""The core spine: process a ticket end to end.

Wires together the solid-core pieces in the order that enforces the
architectural principle:

  claim (lock)               TODO -> IN_PROGRESS, atomic
    -> Lane 3 score          confidence computed OUTSIDE the model
    -> Lane 4 write          harness runs in a sandbox (main branch is safe)
    -> Lattice verdict       deterministic ALLOW / ESCALATE / BLOCK on the diff
    -> Lane 4 self-test      writer's own tests (recorded, NOT trusted)
    -> Lane 6 verify         INDEPENDENT re-verification in a fresh sandbox
    -> Lane 7 seal + done    DONE only with a sealed evidence chain

Failure at any gate rolls back the sandbox (main never contained the change),
records why in the hash-chained evidence log, and either bounces the ticket
back or escalates to a human. "Done" is refused unless the evidence chain
contains an independent ``verify_passed`` entry — evidence outranks any status
or harness claim.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .control import Control, Paused
from .escalation import escalate
from .evidence import EvidenceChain, default_seal_key
from .governance import PlannedChange, Verdict, lattice_verdict
from .harness.base import Harness, HarnessResult
from .harness.mock import MockHarness
from .policy import Policy
from .sandbox import GitWorktreeSandbox
from .scoring import score_ticket
from .tickets.base import Ticket, TicketStore, Status
from .verification import verify

HarnessFactory = Callable[[Ticket], Harness]


@dataclass
class PipelineResult:
    ticket_id: str
    outcome: str  # done | escalated | reopened | reingest | blocked | halted | skipped
    detail: str = ""
    evidence_sealed: bool = False
    diff: str = ""


@dataclass
class Pipeline:
    store: TicketStore
    policy: Policy
    repo_path: str | Path
    evidence_dir: str | Path
    control: Control
    base_ref: str = "HEAD"
    worker: str = "harness-1"
    harness_factory: HarnessFactory = field(default=lambda t: MockHarness(t))
    resolved_corpus: list[str] = field(default_factory=list)

    def _chain(self, ticket_id: str) -> EvidenceChain:
        return EvidenceChain(Path(self.evidence_dir) / f"{ticket_id}.jsonl")

    # ------------------------------------------------------------------
    def process(self, ticket_id: str) -> PipelineResult:
        chain = self._chain(ticket_id)
        try:
            self.control.check()  # global stop/pause
        except Paused as p:
            return PipelineResult(ticket_id, "halted", p.scope)

        # ---- claim (the lock) ----
        if not self.store.claim(ticket_id, self.worker):
            return PipelineResult(ticket_id, "skipped", "already claimed or not in TODO")
        ticket = self.store.get(ticket_id)
        chain.append("lane1", "claimed", {"worker": self.worker, "title": ticket.title})

        # ---- Lane 3: deterministic confidence, outside the model ----
        score = score_ticket(ticket, self.policy, self.resolved_corpus)
        chain.append("lane3", "score", {"value": score.value, "route": score.route,
                                         "rationale": score.rationale})
        if score.route == "reingest":
            self.store.transition(ticket_id, Status.TODO, reason=f"re-ingest: {score.rationale}")
            chain.append("lane3", "reingest", {"rationale": score.rationale})
            return PipelineResult(ticket_id, "reingest", score.rationale)
        if score.route == "human":
            escalate(self.store, chain, ticket, lane="lane3",
                     reason=f"low confidence: {score.rationale}")
            return PipelineResult(ticket_id, "escalated", score.rationale)

        # ---- Lane 4: write the fix in a sandbox ----
        try:
            self.control.check("lane4")
        except Paused as p:
            self.store.transition(ticket_id, Status.TODO, reason=p.scope)
            chain.append("lane4", "halted", {"scope": p.scope})
            return PipelineResult(ticket_id, "halted", p.scope)

        harness = self.harness_factory(ticket)
        with GitWorktreeSandbox(self.repo_path, self.base_ref) as sbx:
            prompt = self._build_prompt(ticket)
            result: HarnessResult = harness.run(
                prompt, sbx.path, budget_tokens=self.policy.runtime.max_tokens_per_ticket
            )
            sbx.apply_edits(result.edits)
            diff = sbx.diff()
            chain.append("lane4", "harness_run", {
                "harness": harness.name,
                "paths": result.paths(),
                "lines_changed": result.lines_changed(),
                "tokens": result.tokens_in + result.tokens_out,
                "claimed_success": result.claimed_success,  # recorded, NOT trusted
            })

            # ---- Lattice verdict on the actual change ----
            change = PlannedChange(
                paths=result.paths(),
                tools=sorted({tc.get("tool", "write") for tc in result.tool_calls} | {"run_tests"}),
                lines_changed=result.lines_changed(),
            )
            decision = lattice_verdict(ticket, change, score, self.policy)
            chain.append("lattice", "verdict", {"verdict": decision.verdict.value,
                                                "reasons": decision.reasons})
            if decision.verdict == Verdict.BLOCK:
                # sandbox discarded on exit; main branch never touched
                self.store.transition(ticket_id, Status.REJECTED,
                                      reason="; ".join(decision.reasons))
                chain.append("lane4", "rollback", {"why": "blocked", "reasons": decision.reasons})
                return PipelineResult(ticket_id, "blocked", "; ".join(decision.reasons), diff=diff)
            if decision.verdict == Verdict.ESCALATE:
                escalate(self.store, chain, ticket, lane="lattice",
                         reason="; ".join(decision.reasons))
                return PipelineResult(ticket_id, "escalated", "; ".join(decision.reasons), diff=diff)

            # ---- Lane 4 self-test (writer's own check; recorded, not trusted) ----
            self_test = sbx.run(self.policy.runtime.test_command)
            chain.append("lane4", "self_test", {"exit_code": self_test.exit_code,
                                                "passed": self_test.ok})
            if not self_test.ok:
                self.store.transition(ticket_id, Status.TODO,
                                      reason="lane4 tests failed; bounced back")
                chain.append("lane4", "rollback", {"why": "self_test_failed"})
                return PipelineResult(ticket_id, "reopened", "lane4 tests failed", diff=diff)

            edits = list(result.edits)

        # ---- Lane 6: INDEPENDENT verification in a fresh sandbox ----
        vres = verify(ticket, edits, self.policy, self.repo_path, self.base_ref)
        chain.append("lane6", "verify", {"passed": vres.passed, "checks": vres.checks})
        if not vres.passed:
            # bounce back with the specific unmet criterion (new info for retry)
            self.store.transition(ticket_id, Status.TODO, reason=f"lane6 rejected: {vres.reason}")
            chain.append("lane6", "reject", {"unmet": vres.unmet})
            return PipelineResult(ticket_id, "reopened", vres.reason, diff=diff)
        chain.append("lane6", "verify_passed", {"checks": [c["name"] for c in vres.checks]})

        # ---- Lane 7: promote, seal evidence, mark done ----
        # Done REQUIRES the independent verify_passed entry in the chain.
        if not chain.has_action("verify_passed"):
            escalate(self.store, chain, ticket, lane="lane7",
                     reason="refusing Done without independent verification evidence")
            return PipelineResult(ticket_id, "escalated", "no verification evidence")

        commit_sha = self._promote(ticket, edits)
        chain.append("lane7", "promote", {"commit": commit_sha})
        # 'sealed' must be the final entry: sealing covers the whole chain
        # including this marker, so nothing may be appended afterwards.
        chain.append("lane7", "sealed", {"note": "chain sealed; signature in <chain>.seal"})
        self.store.comment(ticket_id, self._render_log(ticket, score, vres, commit_sha, chain))
        chain.seal(default_seal_key())
        self.store.transition(ticket_id, Status.DONE, reason=f"verified + sealed ({commit_sha[:8]})")
        return PipelineResult(ticket_id, "done", f"committed {commit_sha[:8]}",
                              evidence_sealed=True, diff=diff)

    # ------------------------------------------------------------------
    def _build_prompt(self, ticket: Ticket) -> str:
        return (
            f"{self.policy.prose}\n\n"
            f"# Ticket {ticket.id}: {ticket.title}\n\n{ticket.body}\n"
        )

    def _promote(self, ticket: Ticket, edits) -> str:
        """Apply verified edits to the repo and commit. (Real version: open a PR.)"""
        repo = Path(self.repo_path)
        for e in edits:
            target = repo / e.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(e.content)
        subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"{ticket.id}: {ticket.title}"],
            cwd=str(repo), check=True, capture_output=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True
        ).stdout.strip()
        return sha

    def _render_log(self, ticket, score, vres, commit_sha, chain) -> str:
        checks = "\n".join(f"  - {c['name']}: {'PASS' if c['passed'] else 'FAIL'}" for c in vres.checks)
        return (
            f"## SwiftConductor — ticket {ticket.id} closed\n\n"
            f"**Confidence (Lane 3, computed outside the model):** {score.value:.2f} "
            f"(autonomous)\n\n"
            f"**Independent verification (Lane 6):**\n{checks}\n\n"
            f"**Commit:** `{commit_sha[:8]}`\n\n"
            f"**Evidence chain:** {len(chain)} entries, sealed; head "
            f"`{chain.head()[:12]}...`\n"
        )
