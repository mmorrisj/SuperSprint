---
name: minimal
scope:
  writable_paths: ["src/**", "tests/**", "examples/**"]
  forbidden_paths: ["infra/**", "secrets/**", ".github/**", "policy/**"]
  allowed_tools: ["read", "write", "run_tests", "git"]
change_size:
  standard_max_lines: 50
  extended_max_lines: 200
confidence:
  autonomous_min: 0.70
  reingest_below: 0.30
always_escalate:
  - delete_user_records
  - schema_migration
  - security_config_change
  - grant_access
runtime:
  max_tokens_per_ticket: 2000000
  max_wallclock_minutes: 30
  test_command: ["python", "-m", "pytest", "-q"]
---

# Mandate (minimal profile): what the AI may do

You may implement and fix code within `src/`, `tests/`, and `examples/`. You may
run the test suite. You may **not** modify infrastructure, secrets, CI
configuration, or the policy files themselves.

Keep changes small and reviewable. Prefer the patterns already present in the
file you are editing. If a change would require touching a forbidden path,
deleting user data, a schema migration, or any security/access change, **stop
and escalate** — those always require a human, regardless of how confident you
are.

Every change must pass the test suite under independent re-verification before
it can be marked Done. Claiming success is not success; passing the independent
checks is.
