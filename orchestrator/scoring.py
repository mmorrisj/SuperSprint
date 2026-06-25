"""Deterministic confidence scoring (Lane 3) — computed OUTSIDE the model.

This is the architectural spine's first half: the system never asks the model
how confident it is. It computes a confidence in code from observable features:

  * similarity to previously-resolved tickets (token Jaccard over a corpus),
  * a complexity penalty from risk keywords in the ticket text,
  * a clarity bonus when the ticket has explicit acceptance criteria.

The score routes the ticket: ``autonomous`` / ``human`` / ``reingest``.

This is intentionally a *weak, transparent* heuristic. It is honest about what
it is: a calibratable gate, not a correctness oracle. In production you would
replace the similarity term with embeddings and *calibrate the thresholds on a
labeled dataset of past tickets with known outcomes*. The interface stays the
same; only ``score`` changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .policy import Policy
from .tickets.base import Ticket

_TOKEN = re.compile(r"[a-z0-9]+")

# Words that historically correlate with risky / hard-to-verify changes.
RISK_KEYWORDS = {
    "migration", "schema", "delete", "drop", "auth", "security", "credential",
    "secret", "permission", "concurrency", "race", "deadlock", "encryption",
    "payment", "refactor", "rewrite", "architecture",
}


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Score:
    value: float  # 0..1
    route: str  # "autonomous" | "human" | "reingest"
    features: dict[str, float]
    rationale: str


def score_ticket(ticket: Ticket, policy: Policy, resolved_corpus: list[str] | None = None) -> Score:
    text = f"{ticket.title}\n{ticket.body}"
    toks = _tokens(text)

    # 1. similarity to resolved work
    corpus = resolved_corpus or []
    best_sim = max((_jaccard(toks, _tokens(c)) for c in corpus), default=0.0)

    # 2. complexity penalty from risk keywords (capped)
    risk_hits = len(toks & RISK_KEYWORDS)
    complexity_penalty = min(0.45, 0.15 * risk_hits)

    # 3. clarity bonus for explicit acceptance criteria
    has_criteria = bool(
        re.search(r"acceptance criteria|given .* when .* then|- \[ \]", text, re.IGNORECASE)
    )
    clarity_bonus = 0.15 if has_criteria else 0.0

    # Base prior keeps brand-new (zero-corpus) tickets from auto-routing to
    # autonomous: with an empty corpus the score sits in the human-review band.
    base = 0.55
    value = max(0.0, min(1.0, base + 0.4 * best_sim + clarity_bonus - complexity_penalty))

    if value < policy.confidence.reingest_below:
        route = "reingest"
    elif value >= policy.confidence.autonomous_min:
        route = "autonomous"
    else:
        route = "human"

    rationale = (
        f"sim={best_sim:.2f}, risk_hits={risk_hits} (penalty {complexity_penalty:.2f}), "
        f"criteria={'yes' if has_criteria else 'no'} -> {value:.2f} -> {route}"
    )
    return Score(
        value=round(value, 4),
        route=route,
        features={
            "similarity": round(best_sim, 4),
            "complexity_penalty": round(complexity_penalty, 4),
            "clarity_bonus": clarity_bonus,
        },
        rationale=rationale,
    )
