# SuperSprint

A governed, AI-assisted DevSecOps core — the buildable spine of a
SwiftConductor-style workflow. Tickets flow through a sandboxed
write → independent-verify → sealed-evidence loop, with confidence scored
*outside* the model and a human in the loop at every gate.

This repo implements the **solid core** first (see
[`docs/swiftconductor-setup-walkthrough.md`](docs/swiftconductor-setup-walkthrough.md)
for the full architecture and an honest take on what's real vs. aspirational):

- **Ticket → worktree sandbox → test loop** — `orchestrator/pipeline.py`, `sandbox.py`
- **Hash-chained, sealable evidence logs** — `orchestrator/evidence.py`
- **Markdown policy with deterministic, machine-parsed limits** — `orchestrator/policy.py`, `policy/profiles/`
- **HITL escalation queue + pause/stop controls** — `orchestrator/escalation.py`, `control.py`
- **The architectural spine** — confidence scored outside the model
  (`scoring.py`), an *independent* verification step (`verification.py`), and
  "Done" only with real, sealed evidence (enforced in `pipeline.py`)

Everything runs with **no LLM and no Jira**: the default harness is
deterministic (`harness/mock.py`) and the default ticket store is a JSON file
(`tickets/filestore.py`). Real adapters (LLM harnesses, Jira/GitHub) implement
the same interfaces.

## Quickstart

```bash
pip install -r requirements.txt

# Run the test suite (27 tests covering the spine guarantees)
python -m pytest -q

# Run the self-contained end-to-end demo
python examples/demo.py
```

The demo seeds four tickets and shows each outcome:

| Ticket  | Scenario                                            | Outcome     |
|---------|-----------------------------------------------------|-------------|
| DEMO-1  | Good fix, in scope, verifies                        | `done` (sealed) |
| DEMO-2  | Harness *claims* success + passes its own test, but is missing the feature | `reopened` (caught by independent verify) |
| DEMO-3  | Touches a forbidden path (`infra/`)                 | `blocked`   |
| DEMO-4  | In scope & confident, but a `schema_migration`      | `escalated` (categorical rule) |

## Operator CLI

```bash
python -m orchestrator.cli --repo <target-repo> run        # process TODO tickets
python -m orchestrator.cli queue                            # show HITL escalation queue
python -m orchestrator.cli pause [--lane lane4]             # humans can pause any lane
python -m orchestrator.cli resume
python -m orchestrator.cli stop                             # hard stop
python -m orchestrator.cli verify <ticket-id>              # check an evidence chain + seal
```

## The spine, in order

```
claim (lock)          TODO -> IN_PROGRESS, atomic
  -> Lane 3 score     confidence computed OUTSIDE the model
  -> Lane 4 write     harness runs in a git-worktree sandbox (main is safe)
  -> Lattice verdict  deterministic ALLOW / ESCALATE / BLOCK on the actual diff
  -> Lane 4 self-test writer's own tests (recorded, NOT trusted)
  -> Lane 6 verify    INDEPENDENT re-verification in a fresh sandbox
  -> Lane 7 seal+done DONE only with a sealed evidence chain
```

Any failed gate rolls back the sandbox (the main branch never contained the
change), records why in the hash-chained log, and either bounces the ticket
back with the specific unmet criterion or escalates to a human. **Done is
refused without an independent `verify_passed` entry — evidence outranks any
status or harness claim.**

## What's next (not yet built)

Real LLM harness adapter, Jira/GitHub ticket adapters, container/microVM
sandbox tiers, the continuous background lanes (audit + watch), and embedding-
based confidence calibration. See the walkthrough doc's phased roadmap.
