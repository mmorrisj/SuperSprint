# Building a SwiftConductor-style Capability — Setup Walkthrough

A practical, engineering-grounded guide to setting up an AI-driven DevSecOps
workflow like the one described in the SwiftConductor pitch: governed AI
"harnesses" that pull tickets from a backlog, plan and write fixes inside
sandboxes, verify them independently, and record a tamper-evident evidence
chain — with a human in the loop at every gate.

This document deliberately separates **what is real and buildable today** from
**marketing claims that need to be earned or verified** (see
[Appendix A](#appendix-a--claims-to-verify-vs-what-you-actually-build)). The goal is to give you a
build plan, not a sales deck.

---

## 1. What this actually is (de-marketed)

Strip away the branding and SwiftConductor is three things glued together:

1. **An agentic coding tool** (the "harness") — Claude Code CLI, OpenAI Codex
   CLI, Aider, etc. — running headless instead of interactively.
2. **An orchestrator** (the "agent" — Python code) that decides *which* work the
   harness does, *with what context*, *under what limits*, and *what happens to
   the result*. This is where most of your engineering effort goes.
3. **A governance layer** (the "MLT stack" — Mandate, Lattice, Trace) that sits
   between the orchestrator and the outside world: it bounds what actions are
   allowed, gates them on a confidence/authorization decision, and records
   everything in an append-only, hash-chained log.

The "7 lanes" are just a **state machine** that a ticket moves through. The
"markdown files" are **plain-language policy** that both (a) gets injected into
the harness prompt and (b) is parsed by a deterministic policy engine for the
hard limits (thresholds, forbidden actions). "Harness/model agnostic" simply
means you talk to the AI through a thin adapter interface, so swapping
Claude for Codex for a self-hosted model is a config change.

> **Key design insight worth keeping:** the system never trusts the model to
> grade its own work. Confidence is computed *outside* the model
> (deterministic scoring + an independent verification lane), and "Done"
> requires real evidence (tests that actually passed, verified by a different
> step than the one that wrote the code). Everything else is plumbing around
> that principle.

---

## 2. Core mental model

```
            ┌────────────────────────────────────────────────────────┐
            │                      ORCHESTRATOR                        │
            │   (Python "agents" — owns the 7-lane state machine)      │
            └───────┬───────────────────────────────────┬────────────┘
                    │ reads policy                       │ invokes
        ┌───────────▼───────────┐           ┌────────────▼───────────┐
        │   MARKDOWN POLICY      │           │   HARNESS ADAPTER       │
        │ (plain-language rules) │           │ (Claude / Codex / vLLM) │
        └───────────┬───────────┘           └────────────┬───────────┘
                    │ parsed for hard limits              │ tool calls
        ┌───────────▼─────────────────────────────────────▼──────────┐
        │                    MLT GOVERNANCE                            │
        │  MANDATE: what's allowed (scope, tools, complexity)          │
        │  LATTICE: confidence + per-action verdict (ALLOW/ESC/BLOCK)  │
        │  TRACE:  tool-call gateway + sandbox + hash-chained evidence  │
        └───────────┬─────────────────────────────────────┬──────────┘
                     │                                      │
            ┌────────▼────────┐                  ┌──────────▼─────────┐
            │  TICKET SYSTEM   │                  │   SANDBOX EXEC      │
            │  (Jira / GitHub) │                  │ (worktree/container)│
            └─────────────────┘                  └────────────────────┘
```

| Pitch term      | What it really is                                              |
|-----------------|---------------------------------------------------------------|
| Harness         | An agentic coding CLI/SDK run in headless mode                 |
| Agent           | Your Python orchestration code                                 |
| Markdown file   | Policy-as-prose: prompt context + machine-parsed limits        |
| MANDATE         | Policy/scope engine (allowed actions, tools, complexity tiers) |
| LATTICE         | Authorization gate + deterministic confidence scorer           |
| TRACE           | Tool-call broker + sandbox provisioner + hash-chained audit log|
| 7 Lanes         | A ticket-processing state machine                              |
| Evidence chain  | Append-only, hash-linked record per ticket                     |
| HITL            | Escalation queue + approval gates a human owns                 |

---

## 3. Prerequisites

- **A backlog/ticket system with an API.** Jira (Cloud or Data Center) is the
  pitch's default; GitHub Issues works identically for a smaller start.
- **Version control you can branch/worktree freely** (Git).
- **A container runtime** for sandboxing (Docker/Podman minimum; Firecracker or
  gVisor for the high-isolation tier later).
- **At least one model endpoint:** a commercial API (Anthropic/OpenAI) to start,
  and/or self-hosted weights (vLLM serving a Qwen-class model) for the
  air-gapped story.
- **An agentic harness** that supports non-interactive runs — e.g. Claude Code
  in headless/`-p` mode, Codex CLI, or Aider with `--yes`.
- **Python 3.11+** for the orchestrator.

---

## 4. Step-by-step setup

The order below is a build order — each step is usable on its own, and you can
stop at any step and still have something that works.

### Step 1 — Stand up a harness adapter (model/harness agnostic)

Define one interface and write thin adapters behind it. This is what makes you
"agnostic."

```python
# orchestrator/harness/base.py
from dataclasses import dataclass

@dataclass
class HarnessResult:
    success: bool
    diff: str | None          # unified diff produced in the sandbox
    transcript: list[dict]     # every step the harness took
    tool_calls: list[dict]     # brokered tool calls (for TRACE)
    tokens_in: int
    tokens_out: int

class Harness:
    def run(self, prompt: str, workdir: str, *, budget_tokens: int,
            allowed_tools: list[str]) -> HarnessResult: ...
```

Implement `ClaudeCodeHarness`, `CodexHarness`, `VLLMHarness`. Each one knows how
to launch its tool headless, point it at `workdir` (the sandbox), enforce the
token budget, and capture the transcript. The orchestrator only ever sees
`Harness`.

> **Honest note:** "agnostic" is real but not free — each harness reports tool
> calls and transcripts differently, so each adapter has real work to normalize
> output into `HarnessResult`. Budget for one adapter per harness you support.

### Step 2 — Connect the ticket system

Write a small client with the operations the lanes need:

- `list_tickets(status, jql)` — pull the work queue.
- `transition(ticket, to_status)` — the "locked contract" in the pitch:
  `To Do → In Progress` is the lock (one harness owns it); `In Progress → Done`
  only after committed, verified code.
- `comment(ticket, markdown)` — how the evidence chain becomes human-readable.
- `create_ticket(...)` — for Lane 1 (intake) and Lane 2 (self-filed audit gaps).

Use a status-field lock so two harnesses never grab the same ticket (atomic
transition + assignee check).

### Step 3 — Author the markdown policy layer

This is the "customizable interface." Keep two kinds of content in these files:

- **Prose guidance** injected verbatim into the harness prompt (coding
  standards, how to document, what "done" means).
- **Machine-readable limits** in fenced front-matter or a sidecar that a
  deterministic policy engine parses. *Do not rely on the model to enforce its
  own limits* — parse them and enforce in code.

Example `policy/mandate.md`:

```markdown
---
# Machine-parsed limits (enforced in code, NOT by the model)
scope:
  writable_paths: ["src/**", "tests/**"]
  forbidden_paths: ["infra/**", "secrets/**", ".github/**"]
  allowed_tools: ["read", "write", "run_tests", "git"]
change_size_gates:
  standard_max_lines: 50          # <50: standard gates
  extended_max_lines: 200         # 50-200: extended verification
  # >200: held for human review
always_escalate:                  # categorical rules — escalate regardless of confidence
  - delete_user_records
  - grant_access
  - schema_migration
  - security_config_change
runtime:
  max_tokens_per_ticket: 2_000_000
  max_wallclock_minutes: 30
  checkpoint_every_minutes: 5
---

# Mandate: what the AI may do

You may implement and fix code within `src/` and `tests/`. You may run the test
suite. You may not touch infrastructure, secrets, or CI configuration. If a
change requires any of those, stop and escalate with a clear explanation.

Write small, reviewable changes. Prefer the existing patterns in the file you
are editing...
```

Ship **profiles** (`minimal`, `strict`) and let the customer tune them.
Changing a threshold is editing this file — not redeploying software.

### Step 4 — Build the orchestrator (the 7-lane state machine)

Model the lanes as states. Two of them run **continuously in the background**
(audit + watch); the rest are steps on a ticket's path.

| Lane | Name              | Type        | DevSecOps | What it does                                                   |
|------|-------------------|-------------|-----------|----------------------------------------------------------------|
| 1    | Read & Sort       | per-ticket  | Dev       | Turn raw requests (Slack/email/notes/scans) into clean tickets |
| 2    | Audit the code    | background  | Sec       | Scan codebase for unfiled issues; file gap tickets             |
| 3    | Dedupe & Decide   | per-ticket  | Ops       | Deterministic confidence score → autonomous / human / re-ingest|
| 4    | Write the fix     | per-ticket  | Dev       | Sandbox; plan; patch; run every test; rollback on failure      |
| 5    | Watch the system  | background  | Ops       | Flag stalled lanes / failing dependencies; tripwires           |
| 6    | Double check      | per-ticket  | Sec       | Independent re-verification of acceptance criteria + NIST checks|
| 7    | Keep docs in sync | per-ticket  | Ops       | Reconcile specs to shipped code; seal evidence; mark Done       |

> The Dev/Sec/Ops mapping above is taken from the pitch as-is; treat it as a
> presentation aid, not an architectural constraint.

Critical wiring rules:

- **Lane 6 is independent of Lane 4.** The step that verifies must never be the
  step that wrote the code. Re-derive acceptance criteria from the ticket and
  re-run tests from scratch.
- **Bounce-back:** Lane 6 failure → ticket returns to Lane 3 or 4 with the
  *specific unmet criterion* attached, so each retry starts with new
  information (this is what prevents wasteful loops).
- **Evidence outranks status.** A ticket is "Done" only when the evidence chain
  is sealed — a Jira status of Done with no evidence is treated as a failure.

A minimal driver:

```python
def process(ticket):
    score = lane3_score(ticket)                 # deterministic, model-free
    if score.route == "human":   return escalate(ticket, score)
    if score.route == "reingest":return lane1_reingest(ticket)

    plan = mandate_plan(ticket)                 # MANDATE: N plans w/ risk tiers
    verdict = lattice_authorize(plan)           # LATTICE: ALLOW/ESCALATE/BLOCK
    if verdict != "ALLOW":       return escalate(ticket, verdict)

    with trace_sandbox(ticket) as sbx:          # TRACE: sandbox + tripwires
        result = lane4_write_fix(ticket, plan, sbx)
        if not result.success:   return rollback_and_reopen(ticket, result)

        check = lane6_verify(ticket, sbx)       # independent verification
        if not check.passed:     return bounce_back(ticket, check.reason)

        lane7_sync_docs_and_seal(ticket, sbx, result, check)
        commit_and_transition(ticket, "Done")
```

### Step 5 — Implement MLT governance

**MANDATE — what's allowed.** A policy engine that, given a ticket, produces one
or more candidate plans each tagged with a risk tier, and a function that checks
any proposed action against the scope rules from Step 3. Implement with plain
Python first; graduate to OPA/Rego if you want policy decoupled from code.

**LATTICE — confidence + authorization.** Two distinct levels, *neither of which
is the model grading itself*:

1. *Ticket-level deterministic score* (Lane 3): a weighted blend of similarity
   to known/resolved work (embeddings), estimated complexity, and change-size
   prediction. Output gates: autonomous vs. human-review vs. re-ingest.
2. *Per-action authorization verdict*: for each planned action, return
   `ALLOW` / `ESCALATE` / `BLOCK` against numeric thresholds **and** categorical
   always-escalate rules. **Re-check at execution time** (state may have
   changed between plan and run).

```python
def lattice_verdict(action, policy, score):
    if action.category in policy.always_escalate:      return "ESCALATE"
    if action.lines_changed > policy.extended_max:     return "ESCALATE"
    if score.confidence < policy.min_confidence:       return "ESCALATE"
    if action.tool not in policy.allowed_tools:        return "BLOCK"
    if not within_scope(action.paths, policy):         return "BLOCK"
    return "ALLOW"
```

**TRACE — gateway + sandbox + evidence.** Three responsibilities:

- *Tool-call broker:* every external tool call the harness makes is routed
  through TRACE, which re-checks authorization and records it. The harness never
  touches the outside world directly.
- *Sandbox provisioner:* see Step 6.
- *Evidence chain:* an append-only log where each entry includes the hash of the
  previous entry (a hash chain), making tampering detectable.

```python
import hashlib, json
def append_evidence(chain_path, entry: dict):
    prev = last_hash(chain_path)
    entry["prev"] = prev
    entry["hash"] = hashlib.sha256(
        (prev + json.dumps(entry, sort_keys=True)).encode()).hexdigest()
    append_line(chain_path, json.dumps(entry))
```

> **Honest note:** a hash chain is *tamper-evident*, not *tamper-proof*. To make
> the "sealed/signed evidence" claim real, sign each sealed chain with a key the
> orchestrator controls (e.g. Sigstore/cosign or a KMS key) and verify offline.

### Step 6 — Sandbox execution tiers

The harness only ever executes inside a sandbox; the main branch never contains
unverified code. Provision by risk tier:

| Risk tier | Isolation                                  | Use for                       |
|-----------|--------------------------------------------|-------------------------------|
| Low       | Git worktree pinned to the approved commit | Small, in-scope code changes  |
| Medium    | Container (Docker/Podman)                   | Anything running build/tests  |
| High      | microVM (Firecracker) or gVisor            | Untrusted/large/risky changes |

Before execution, TRACE re-verifies the (signed) approval bundle. **Failure =
any gate unmet** (failing/regressed tests, unmet acceptance criteria, policy
violation, tripped wire, or a success claim without evidence). On failure:
discard the sandbox, return the ticket to To Do, record why.

### Step 7 — Human-in-the-loop (HITL)

HITL is concrete, not a slogan:

- **An escalation queue** the human owns (a Jira status/label, plus a dashboard).
- **Approval gates** — any `ESCALATE` verdict parks the ticket pending a human
  decision; consequential/categorical actions can never auto-execute.
- **Pause/stop any lane at any time** — a control flag the orchestrator checks
  at every checkpoint.
- **Full visibility** — the human can open any ticket and read the evidence
  chain rendered as plain-language Jira comments (what I examined / what I found
  / root cause / approach chosen / files modified).

### Step 8 — Drift & hallucination safeguards

Measure drift at four scopes (all enforced in code, not by trusting the model):

- **Per action:** every tool call passes the LATTICE gate and is recorded.
- **Per ticket:** Lane 6 independently re-derives acceptance criteria and
  re-verifies. The executor never audits itself.
- **Per system:** Lane 5 tripwires with escalating containment levels up to an
  emergency halt.
- **Periodic:** a fixed audit checklist run until two consecutive clean passes.

This sits *alongside* your existing deterministic CI/CD gates (test suites,
SAST/DAST, dependency/container scanning). Those stay authoritative — the
governance layer decides *what reaches them* and *records what happened*. The
governance layer can also author new acceptance tests (Lane 6) and file new
tickets (Lane 2).

### Step 9 — Self-hosted / air-gapped path (optional)

For the "no mission data leaves the enclave" story: serve open weights with
vLLM (a Qwen-class model, optionally with LoRA adapters) and point the
`VLLMHarness` at it. Develop and prove the workflow on the low side; what
crosses to the high side are *artifacts that survive transfer review* — markdown
policy files, orchestrator code, signed policy bundles, container images (with
SBOMs), and evidence chains — then rebuild and re-baseline on the high side.

> **Honest note:** the accreditation/transfer story is organizational, not
> something you "build." The buildable part is: keep all components offline-
> verifiable (signed bundles, offline evidence verification, no hard dependency
> on a commercial endpoint).

---

## 5. Proposed repo layout

```
SuperSprint/
├── orchestrator/
│   ├── lanes/              # one module per lane (1..7)
│   ├── harness/            # base.py + claude.py / codex.py / vllm.py adapters
│   ├── mlt/
│   │   ├── mandate.py      # scope/plan engine
│   │   ├── lattice.py      # scorer + authorization verdicts
│   │   └── trace.py        # gateway, sandbox provisioner, evidence chain
│   ├── tickets/            # Jira / GitHub client
│   ├── sandbox/            # worktree / container / microvm provisioners
│   └── statemachine.py     # the 7-lane driver
├── policy/
│   ├── mandate.md          # scope, forbidden paths, change-size gates
│   ├── lattice.md          # thresholds, always-escalate categories
│   ├── trace.md            # logging/sealing/tripwire rules
│   └── profiles/           # minimal.md, strict.md
├── evidence/               # per-ticket hash-chained logs (gitignored)
├── tests/
└── docs/
    └── swiftconductor-setup-walkthrough.md   # this file
```

---

## 6. Phased roadmap (crawl → walk → run)

1. **Crawl (1 harness, 1 lane, 1 repo).** Manually drop a ticket → run Lane 4 in
   a git-worktree sandbox → run tests → post a plain-language comment. No
   governance yet. Proves the harness adapter and sandbox.
2. **Walk (add governance + verification).** Add Lane 3 scoring, the LATTICE
   gate, the TRACE evidence chain, and an independent Lane 6. Add the
   escalation queue. Now you have HITL and "never fakes success."
3. **Run (continuous + multi-lane).** Add background Lanes 2 and 5, Jira polling,
   runtime budgets/checkpoints, tripwires, and the strict policy profile. Add a
   second harness adapter to demonstrate agnosticism.
4. **Harden (the IC story).** Signed policy bundles + evidence, container images
   with SBOMs, self-hosted vLLM path, offline evidence verification.

---

## Appendix A — Claims to verify vs. what you actually build

The pitch mixes shipped engineering with aspirational/contractual claims. Before
repeating any of these, confirm them with engineering:

| Claim in the script                              | Status / what to do                                                        |
|--------------------------------------------------|----------------------------------------------------------------------------|
| "TRL 95"                                          | **Not a real scale** — TRL runs 1–9. Drop it or restate as TRL 4 (claimed).|
| "1.4 hours vs ~38 days per ticket"                | A lab measurement — define the methodology and keep the data to back it.    |
| "229 tickets / 18 escalations in a 5-day run"     | Operational record — keep the raw logs; it's only credible with evidence.   |
| "9.5M lines of code"                              | Per the script this is ~355K hand-written + ~8.9M generated schemas/fixtures + ~211K docs. State the split. |
| "Approved / in use on NSA systems" (AEGIS/MLT)    | Contractual/accreditation claim — not something you build; verify before use.|
| "Never fakes success"                             | **Buildable and true** *only if* deterministic gates enforce it (independent tests, evidence required for Done). Don't claim it without Lane 6. |
| "Sealed / signed evidence"                        | Hash chain = tamper-*evident*. Add real signing (cosign/KMS) to earn "signed".|
| "Harness/model agnostic"                          | Real, but costs one adapter per harness. Demo with ≥2 to prove it.          |
| Self-hosted vLLM / air-gapped / low-to-high       | Architecture is sound; the transfer/ATO part is organizational, not code.    |

## Appendix B — Suggested technology choices

| Concern            | Pragmatic default                | Heavier/secure option            |
|--------------------|----------------------------------|----------------------------------|
| Harness            | Claude Code (headless)           | + Codex CLI, self-hosted vLLM    |
| Orchestrator       | Python 3.11 + a job queue        | Temporal / Celery for durability |
| Ticket system      | GitHub Issues                    | Jira (Cloud / Data Center)       |
| Policy engine      | Plain Python + YAML front-matter | OPA / Rego                       |
| Sandbox            | Git worktree → Docker            | Firecracker microVM / gVisor     |
| Evidence chain     | SHA-256 hash chain (JSONL)       | + cosign/KMS signing             |
| Confidence scoring | Embeddings similarity + heuristics| Tuned model + calibration set    |
| Secrets/tool broker| Env + allowlist in TRACE         | Vault + brokered short-lived creds|
```
