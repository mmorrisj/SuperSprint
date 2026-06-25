"""Markdown policy with machine-readable, deterministic limits.

A policy file is plain-language Markdown with a YAML front-matter block. The
prose is what you'd inject into a harness prompt; the front-matter is the part
*enforced in code* (never by the model). This module parses the front-matter
into a typed ``Policy`` and exposes deterministic gate evaluation.

    ---
    scope:
      writable_paths: ["src/**", "tests/**"]
      forbidden_paths: ["infra/**", ".github/**"]
      allowed_tools: ["read", "write", "run_tests", "git"]
    change_size:
      standard_max_lines: 50
      extended_max_lines: 200
    confidence:
      autonomous_min: 0.75
      reingest_below: 0.30
    always_escalate: ["delete_user_records", "schema_migration"]
    runtime:
      max_tokens_per_ticket: 2000000
      max_wallclock_minutes: 30
    ---
    # Mandate: what the AI may do
    ...prose...
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FRONT_MATTER_DELIM = "---"


@dataclass
class ChangeSizeGates:
    standard_max_lines: int = 50
    extended_max_lines: int = 200


@dataclass
class ConfidenceGates:
    autonomous_min: float = 0.75
    reingest_below: float = 0.30


@dataclass
class Scope:
    writable_paths: list[str] = field(default_factory=lambda: ["**"])
    forbidden_paths: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=lambda: ["read", "write", "run_tests", "git"])


@dataclass
class Runtime:
    max_tokens_per_ticket: int = 2_000_000
    max_wallclock_minutes: int = 30
    test_command: list[str] = field(default_factory=lambda: ["pytest", "-q"])


@dataclass
class Policy:
    name: str
    prose: str
    scope: Scope = field(default_factory=Scope)
    change_size: ChangeSizeGates = field(default_factory=ChangeSizeGates)
    confidence: ConfidenceGates = field(default_factory=ConfidenceGates)
    always_escalate: list[str] = field(default_factory=list)
    runtime: Runtime = field(default_factory=Runtime)

    # ----- deterministic gates ------------------------------------------
    def path_writable(self, rel_path: str) -> bool:
        """A path is writable iff it matches a writable glob and no forbidden glob."""
        if any(fnmatch.fnmatch(rel_path, pat) for pat in self.scope.forbidden_paths):
            return False
        return any(fnmatch.fnmatch(rel_path, pat) for pat in self.scope.writable_paths)

    def tool_allowed(self, tool: str) -> bool:
        return tool in self.scope.allowed_tools

    def category_always_escalates(self, category: str | None) -> bool:
        return category is not None and category in self.always_escalate

    def change_size_tier(self, lines_changed: int) -> str:
        """'standard' (<=standard), 'extended' (<=extended), or 'human' (>extended)."""
        if lines_changed <= self.change_size.standard_max_lines:
            return "standard"
        if lines_changed <= self.change_size.extended_max_lines:
            return "extended"
        return "human"


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIM:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONT_MATTER_DELIM:
            end = i
            break
    if end is None:
        return {}, text
    front = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    data = yaml.safe_load(front) or {}
    if not isinstance(data, dict):
        raise ValueError("policy front-matter must be a mapping")
    return data, body


def load_policy(path: str | Path) -> Policy:
    path = Path(path)
    data, prose = _split_front_matter(path.read_text())
    scope_d = data.get("scope", {}) or {}
    cs_d = data.get("change_size", {}) or {}
    cf_d = data.get("confidence", {}) or {}
    rt_d = data.get("runtime", {}) or {}
    return Policy(
        name=data.get("name", path.stem),
        prose=prose,
        scope=Scope(
            writable_paths=scope_d.get("writable_paths", Scope().writable_paths),
            forbidden_paths=scope_d.get("forbidden_paths", []),
            allowed_tools=scope_d.get("allowed_tools", Scope().allowed_tools),
        ),
        change_size=ChangeSizeGates(
            standard_max_lines=cs_d.get("standard_max_lines", 50),
            extended_max_lines=cs_d.get("extended_max_lines", 200),
        ),
        confidence=ConfidenceGates(
            autonomous_min=cf_d.get("autonomous_min", 0.75),
            reingest_below=cf_d.get("reingest_below", 0.30),
        ),
        always_escalate=data.get("always_escalate", []),
        runtime=Runtime(
            max_tokens_per_ticket=rt_d.get("max_tokens_per_ticket", 2_000_000),
            max_wallclock_minutes=rt_d.get("max_wallclock_minutes", 30),
            test_command=rt_d.get("test_command", ["pytest", "-q"]),
        ),
    )
