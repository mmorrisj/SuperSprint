"""Self-contained demo of the SuperSprint core spine.

Creates a throwaway target git repo, seeds a few tickets, and runs them through
the pipeline with the deterministic MockHarness (no LLM, no Jira). Prints each
outcome and then verifies one sealed evidence chain.

    python examples/demo.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.control import Control
from orchestrator.evidence import EvidenceChain, default_seal_key
from orchestrator.pipeline import Pipeline
from orchestrator.policy import load_policy
from orchestrator.tickets.base import Ticket, Status
from orchestrator.tickets.filestore import FileTicketStore

ROOT = Path(__file__).resolve().parents[1]
GOOD = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
NO_MUL = "def add(a, b):\n    return a + b\n# TODO mul\n"
ACCEPT_MUL = [["python", "-c", "from src.calc import mul; assert mul(2, 3) == 6"]]


def make_target_repo(base: Path) -> Path:
    repo = base / "target"
    repo.mkdir()

    def git(*a):
        subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "demo@example.com")
    git("config", "user.name", "Demo")
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    (repo / "pytest.ini").write_text("[pytest]\n")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return repo


def ticket(tid, title, body, fix_spec, claimed=True, category=None, acceptance=None):
    return Ticket(id=tid, title=title, body=body, category=category,
                  meta={"fix_spec": fix_spec, "claimed_success": claimed,
                        "acceptance_commands": acceptance or []})


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        repo = make_target_repo(base)
        state = base / "state"
        store = FileTicketStore(state / "tickets.json")
        pipe = Pipeline(
            store=store,
            policy=load_policy(ROOT / "policy" / "profiles" / "minimal.md"),
            repo_path=repo,
            evidence_dir=state / "evidence",
            control=Control(state / "control.json"),
            resolved_corpus=["add mul helper acceptance criteria"],
        )

        store.create(ticket("DEMO-1", "add mul helper",
                            "acceptance criteria: mul multiplies two numbers",
                            {"src/calc.py": GOOD}, acceptance=ACCEPT_MUL))
        store.create(ticket("DEMO-2", "add mul helper",
                            "acceptance criteria: mul multiplies two numbers",
                            {"src/calc.py": NO_MUL}, claimed=True, acceptance=ACCEPT_MUL))
        store.create(ticket("DEMO-3", "rotate prod secrets",
                            "acceptance criteria: update terraform",
                            {"infra/deploy.tf": "resource {}\n"}))
        # High confidence, in scope, small change — but the category always
        # escalates regardless of how confident the system is.
        store.create(ticket("DEMO-4", "add mul helper",
                            "acceptance criteria: mul multiplies two numbers",
                            {"src/calc.py": GOOD}, category="schema_migration",
                            acceptance=ACCEPT_MUL))

        print("=" * 64)
        print("Running tickets through the SwiftConductor-style spine")
        print("=" * 64)
        for t in store.list(Status.TODO):
            res = pipe.process(t.id)
            print(f"  {res.ticket_id:8} -> {res.outcome:10} | {res.detail}")

        print("\nFinal ticket states:")
        for t in store.list():
            print(f"  {t.id:8} {t.status.value}")

        print("\nEvidence chain for DEMO-1 (the one that reached Done):")
        chain = EvidenceChain(state / "evidence" / "DEMO-1.jsonl")
        ok, reason = chain.verify_chain()
        for e in chain:
            print(f"  [{e.seq}] {e.lane}/{e.action}")
        print(f"  chain integrity: {'OK' if ok else 'BROKEN: ' + str(reason)}")
        print(f"  seal valid:      {chain.verify_seal(default_seal_key())}")

        print("\nKey point: DEMO-2's harness CLAIMED success and passed its own")
        print("test, but independent verification (Lane 6) caught the missing")
        print("feature -> bounced back, never sealed, never Done.")
        c2 = EvidenceChain(state / "evidence" / "DEMO-2.jsonl")
        print(f"  DEMO-2 has verify_passed? {c2.has_action('verify_passed')}")
        print(f"  DEMO-2 sealed?            {c2.verify_seal(default_seal_key())}")


if __name__ == "__main__":
    main()
