"""SuperSprint orchestrator — the governed AI DevSecOps core.

This package implements the *solid core spine* of a SwiftConductor-style
workflow:

  * Ticket -> sandbox -> test -> result loop (``pipeline``, ``sandbox``)
  * Hash-chained evidence logs (``evidence``)
  * Markdown policy with machine-readable, deterministic thresholds (``policy``)
  * HITL escalation queue and pause/stop controls (``escalation``, ``control``)
  * The architectural principle: confidence is scored *outside* the model
    (``scoring``), verification is an *independent* step (``verification``),
    and "Done" requires *real evidence* (enforced in ``pipeline``).

Everything here runs with no external API or ticket system: the default
harness is deterministic (``harness.mock``) and the default ticket store is a
JSON file (``tickets.filestore``). Real adapters (LLM harnesses, Jira/GitHub)
implement the same interfaces.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
