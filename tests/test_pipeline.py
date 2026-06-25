"""End-to-end tests of the spine.

Each test drives a real git worktree sandbox + the deterministic MockHarness,
proving the architectural guarantees:

  * confidence routes the ticket (Lane 3, outside the model),
  * out-of-scope work is BLOCKED and never touches the main branch,
  * categorical / low-confidence / oversized work ESCALATES to a human,
  * an incomplete fix that *passes the writer's own test* is still caught by
    INDEPENDENT verification (Lane 6) — "never fakes success",
  * "Done" only happens with a sealed evidence chain containing verify_passed,
  * pause/stop halts work.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orchestrator.control import Control
from orchestrator.evidence import EvidenceChain, default_seal_key
from orchestrator.pipeline import Pipeline
from orchestrator.tickets.base import Ticket, Status
from orchestrator.tickets.filestore import FileTicketStore

ACCEPT_MUL = [["python", "-c", "from src.calc import mul; assert mul(2, 3) == 6"]]


@pytest.fixture
def make(target_repo, policy, tmp_path):
    def _make():
        state = tmp_path / "state"
        store = FileTicketStore(state / "tickets.json")
        control = Control(state / "control.json")
        pipe = Pipeline(
            store=store,
            policy=policy,
            repo_path=target_repo,
            evidence_dir=state / "evidence",
            control=control,
            resolved_corpus=["add mul helper acceptance criteria"],
        )
        return pipe, store, control, state
    return _make


def _autonomous_ticket(tid, fix_spec, claimed=True, category=None, acceptance=None):
    return Ticket(
        id=tid,
        title="add mul helper",
        body="acceptance criteria: mul multiplies two numbers",
        category=category,
        meta={"fix_spec": fix_spec, "claimed_success": claimed,
              "acceptance_commands": acceptance or []},
    )


GOOD_CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
NO_MUL_CALC = "def add(a, b):\n    return a + b\n# TODO: add mul\n"
BROKEN_CALC = "def add(a, b):\n    return a - b\n"


def test_good_fix_reaches_done_and_seals(make):
    pipe, store, _, state = make()
    store.create(_autonomous_ticket("K-1", {"src/calc.py": GOOD_CALC}, acceptance=ACCEPT_MUL))
    res = pipe.process("K-1")

    assert res.outcome == "done", res.detail
    assert res.evidence_sealed
    assert store.get("K-1").status == Status.DONE

    # evidence chain: present, verifies, sealed, and contains verify_passed
    chain = EvidenceChain(state / "evidence" / "K-1.jsonl")
    ok, reason = chain.verify_chain()
    assert ok, reason
    assert chain.verify_seal(default_seal_key())
    assert chain.has_action("verify_passed")

    # the fix was actually committed to the main repo
    log = subprocess.run(["git", "log", "--oneline"], cwd=str(pipe.repo_path),
                         capture_output=True, text=True).stdout
    assert "K-1" in log


def test_incomplete_fix_passes_self_test_but_independent_verify_catches_it(make):
    """The core 'never fakes success' guarantee."""
    pipe, store, _, state = make()
    # Harness claims success and writes code that keeps the existing pytest
    # green, but never implements mul. The writer's own test (pytest) passes;
    # Lane 6's independently re-derived acceptance check fails.
    store.create(_autonomous_ticket("K-2", {"src/calc.py": NO_MUL_CALC},
                                    claimed=True, acceptance=ACCEPT_MUL))
    res = pipe.process("K-2")

    assert res.outcome == "reopened", res.detail
    assert store.get("K-2").status == Status.TODO  # bounced back, not done

    chain = EvidenceChain(state / "evidence" / "K-2.jsonl")
    # writer self-test passed...
    self_tests = [e for e in chain if e.action == "self_test"]
    assert self_tests and self_tests[0].detail["passed"] is True
    # ...but independent verification rejected, and there is NO verify_passed.
    assert not chain.has_action("verify_passed")
    assert chain.has_action("reject")
    # not sealed -> cannot be Done
    assert not chain.verify_seal(default_seal_key())


def test_broken_fix_fails_writer_test_and_bounces(make):
    pipe, store, _, _ = make()
    store.create(_autonomous_ticket("K-3", {"src/calc.py": BROKEN_CALC}))
    res = pipe.process("K-3")
    assert res.outcome == "reopened"
    assert store.get("K-3").status == Status.TODO


def test_out_of_scope_is_blocked_and_main_untouched(make):
    pipe, store, _, _ = make()
    store.create(_autonomous_ticket("K-4", {"infra/deploy.tf": "resource {}\n"}))
    res = pipe.process("K-4")
    assert res.outcome == "blocked"
    assert store.get("K-4").status == Status.REJECTED
    # the forbidden file never made it into the real repo
    assert not (Path(pipe.repo_path) / "infra" / "deploy.tf").exists()


def test_category_always_escalates(make):
    pipe, store, _, _ = make()
    store.create(_autonomous_ticket("K-5", {"src/calc.py": GOOD_CALC},
                                    category="schema_migration", acceptance=ACCEPT_MUL))
    res = pipe.process("K-5")
    assert res.outcome == "escalated"
    assert store.get("K-5").status == Status.ESCALATED


def test_low_confidence_escalates_at_lane3(make):
    pipe, store, _, _ = make()
    t = Ticket(id="K-6", title="improve security message", body="update text",
               meta={"fix_spec": {"src/calc.py": GOOD_CALC}})
    store.create(t)
    res = pipe.process("K-6")
    assert res.outcome == "escalated"


def test_very_risky_ticket_is_reingested(make):
    pipe, store, _, _ = make()
    t = Ticket(
        id="K-7",
        title="schema migration drop auth table",
        body="delete user records, change encryption and security credential",
        meta={"fix_spec": {"src/calc.py": GOOD_CALC}},
    )
    store.create(t)
    res = pipe.process("K-7")
    assert res.outcome == "reingest"
    assert store.get("K-7").status == Status.TODO


def test_stop_halts_processing(make):
    pipe, store, control, _ = make()
    store.create(_autonomous_ticket("K-8", {"src/calc.py": GOOD_CALC}, acceptance=ACCEPT_MUL))
    control.stop()
    res = pipe.process("K-8")
    assert res.outcome == "halted"
    assert store.get("K-8").status == Status.TODO  # untouched


def test_claim_lock_prevents_double_processing(make):
    pipe, store, _, _ = make()
    store.create(_autonomous_ticket("K-9", {"src/calc.py": GOOD_CALC}, acceptance=ACCEPT_MUL))
    assert store.claim("K-9", "other-worker") is True
    res = pipe.process("K-9")  # already claimed / not TODO
    assert res.outcome == "skipped"
