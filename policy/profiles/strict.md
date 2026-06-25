---
name: strict
scope:
  writable_paths: ["src/**", "tests/**"]
  forbidden_paths: ["infra/**", "secrets/**", ".github/**", "policy/**", "migrations/**"]
  allowed_tools: ["read", "write", "run_tests", "git"]
change_size:
  standard_max_lines: 25
  extended_max_lines: 100
confidence:
  autonomous_min: 0.85
  reingest_below: 0.40
always_escalate:
  - delete_user_records
  - schema_migration
  - security_config_change
  - grant_access
  - dependency_change
  - public_api_change
runtime:
  max_tokens_per_ticket: 1000000
  max_wallclock_minutes: 20
  test_command: ["python", "-m", "pytest", "-q"]
---

# Mandate (strict profile): what the AI may do

A tighter profile for higher-stakes codebases. Smaller autonomous change
budget, higher confidence bar, and more categories that always escalate to a
human. Everything else is identical to the minimal profile — only the numbers
and the escalation list change. Tuning policy is editing this file, not
redeploying software.
