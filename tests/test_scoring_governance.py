from orchestrator.governance import PlannedChange, Verdict, lattice_verdict
from orchestrator.scoring import Score, score_ticket
from orchestrator.tickets.base import Ticket


def test_score_is_outside_model_and_deterministic(policy):
    t = Ticket(id="K-1", title="fix add helper", body="acceptance criteria: add works")
    s1 = score_ticket(t, policy, resolved_corpus=["fix add helper acceptance"])
    s2 = score_ticket(t, policy, resolved_corpus=["fix add helper acceptance"])
    assert s1.value == s2.value  # deterministic
    assert 0.0 <= s1.value <= 1.0


def test_risk_keywords_lower_confidence(policy):
    plain = Ticket(id="A", title="tweak label text", body="change a string")
    risky = Ticket(id="B", title="schema migration to drop auth table",
                   body="delete user records, change encryption")
    sp = score_ticket(plain, policy)
    sr = score_ticket(risky, policy)
    assert sr.value < sp.value


def _change(lines=10, paths=("src/calc.py",), tools=("write", "run_tests")):
    return PlannedChange(paths=list(paths), tools=list(tools), lines_changed=lines)


def _score(v):
    return Score(value=v, route="autonomous", features={}, rationale="test")


def test_block_on_out_of_scope_path(policy):
    t = Ticket(id="K", title="x")
    d = lattice_verdict(t, _change(paths=("infra/deploy.tf",)), _score(0.9), policy)
    assert d.verdict == Verdict.BLOCK


def test_block_on_forbidden_tool(policy):
    t = Ticket(id="K", title="x")
    d = lattice_verdict(t, _change(tools=("write", "network")), _score(0.9), policy)
    assert d.verdict == Verdict.BLOCK


def test_escalate_on_category(policy):
    t = Ticket(id="K", title="x", category="schema_migration")
    d = lattice_verdict(t, _change(), _score(0.99), policy)
    assert d.verdict == Verdict.ESCALATE


def test_escalate_on_large_change(policy):
    t = Ticket(id="K", title="x")
    d = lattice_verdict(t, _change(lines=500), _score(0.99), policy)
    assert d.verdict == Verdict.ESCALATE


def test_escalate_on_low_confidence(policy):
    t = Ticket(id="K", title="x")
    d = lattice_verdict(t, _change(), _score(0.50), policy)
    assert d.verdict == Verdict.ESCALATE


def test_allow_when_all_gates_pass(policy):
    t = Ticket(id="K", title="x")
    d = lattice_verdict(t, _change(lines=10), _score(0.9), policy)
    assert d.verdict == Verdict.ALLOW
