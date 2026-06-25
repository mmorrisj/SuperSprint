"""Ticket model and the store interface.

The store is the "locked contract" from the pitch: ``TODO -> IN_PROGRESS`` is
an atomic claim so two harnesses never grab the same ticket; ``IN_PROGRESS ->
DONE`` only happens after verified, committed work.

``FileTicketStore`` is the runnable default. A ``JiraTicketStore`` or
``GitHubTicketStore`` would implement the same ``TicketStore`` interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Protocol


class Status(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"  # waiting on a human (HITL queue)
    DONE = "done"
    REJECTED = "rejected"


@dataclass
class Ticket:
    id: str
    title: str
    body: str = ""
    status: Status = Status.TODO
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    # Optional category used by categorical always-escalate rules
    # (e.g. "schema_migration", "delete_user_records").
    category: str | None = None
    # Free-form metadata; the mock harness reads ``fix_spec`` from here.
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Ticket":
        return Ticket(
            id=d["id"],
            title=d["title"],
            body=d.get("body", ""),
            status=Status(d.get("status", "todo")),
            assignee=d.get("assignee"),
            labels=d.get("labels", []),
            category=d.get("category"),
            meta=d.get("meta", {}),
        )


class TicketStore(Protocol):
    def list(self, status: Status | None = None) -> list[Ticket]: ...

    def get(self, ticket_id: str) -> Ticket: ...

    def create(self, ticket: Ticket) -> Ticket: ...

    def claim(self, ticket_id: str, worker: str) -> bool:
        """Atomically move TODO -> IN_PROGRESS for ``worker``. False if already claimed."""
        ...

    def transition(self, ticket_id: str, to: Status, *, reason: str | None = None) -> Ticket: ...

    def comment(self, ticket_id: str, markdown: str) -> None: ...
