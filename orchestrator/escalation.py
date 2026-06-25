"""HITL escalation queue.

When Lattice returns ESCALATE (or a lane gets halted), the ticket is parked in
the ESCALATED status with a recorded reason and an evidence entry. The queue is
just "every ticket in ESCALATED status" plus the human-readable reason — a real
deployment renders this as a dashboard / Jira board column.

This module keeps the escalation behavior in one place so the pipeline stays
readable and humans have a single API to inspect and resolve the queue.
"""

from __future__ import annotations

from dataclasses import dataclass

from .evidence import EvidenceChain
from .tickets.base import Ticket, TicketStore, Status


@dataclass
class EscalationItem:
    ticket_id: str
    title: str
    reason: str


def escalate(
    store: TicketStore,
    chain: EvidenceChain,
    ticket: Ticket,
    *,
    lane: str,
    reason: str,
) -> None:
    chain.append(lane, "escalate", {"reason": reason})
    store.comment(
        ticket.id,
        f"**Escalated to human** (from {lane})\n\n> {reason}\n\n"
        "A human must review and approve before this can proceed.",
    )
    store.transition(ticket.id, Status.ESCALATED, reason=reason)


def queue(store: TicketStore) -> list[EscalationItem]:
    items = []
    for t in store.list(Status.ESCALATED):
        # last transition reason isn't stored on the ticket; surface title.
        items.append(EscalationItem(ticket_id=t.id, title=t.title, reason="see ticket comments"))
    return items
