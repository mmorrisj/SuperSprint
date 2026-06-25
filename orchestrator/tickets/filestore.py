"""JSON-file-backed ticket store with atomic claim.

Runnable with zero infrastructure. Concurrency safety uses an OS-level file
lock (``fcntl``) around read-modify-write so the TODO->IN_PROGRESS claim is
atomic across processes on the same host. (A real Jira/GitHub adapter relies
on the server's conditional updates instead.)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .base import Ticket, Status

try:
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - non-unix fallback
    _HAVE_FCNTL = False


class FileTicketStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = Path(str(self.path) + ".lock")
        if not self.path.exists():
            self.path.write_text(json.dumps({"tickets": {}, "comments": {}}, indent=2))

    # ----- low-level locked IO ------------------------------------------
    @contextmanager
    def _locked(self) -> Iterator[dict]:
        with self.lock_path.open("w") as lock:
            if _HAVE_FCNTL:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = json.loads(self.path.read_text())
                yield data
                self.path.write_text(json.dumps(data, indent=2))
            finally:
                if _HAVE_FCNTL:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    # ----- TicketStore interface ----------------------------------------
    def list(self, status: Status | None = None) -> list[Ticket]:
        data = self._read()
        out = [Ticket.from_dict(t) for t in data["tickets"].values()]
        if status is not None:
            out = [t for t in out if t.status == status]
        return sorted(out, key=lambda t: t.id)

    def get(self, ticket_id: str) -> Ticket:
        data = self._read()
        if ticket_id not in data["tickets"]:
            raise KeyError(ticket_id)
        return Ticket.from_dict(data["tickets"][ticket_id])

    def create(self, ticket: Ticket) -> Ticket:
        with self._locked() as data:
            if ticket.id in data["tickets"]:
                raise ValueError(f"ticket {ticket.id} already exists")
            data["tickets"][ticket.id] = ticket.to_dict()
        return ticket

    def claim(self, ticket_id: str, worker: str) -> bool:
        with self._locked() as data:
            raw = data["tickets"].get(ticket_id)
            if raw is None:
                raise KeyError(ticket_id)
            if raw["status"] != Status.TODO.value:
                return False
            raw["status"] = Status.IN_PROGRESS.value
            raw["assignee"] = worker
        return True

    def transition(self, ticket_id: str, to: Status, *, reason: str | None = None) -> Ticket:
        with self._locked() as data:
            raw = data["tickets"].get(ticket_id)
            if raw is None:
                raise KeyError(ticket_id)
            raw["status"] = to.value
            if to in (Status.TODO, Status.REJECTED):
                raw["assignee"] = None
            if reason:
                data.setdefault("comments", {}).setdefault(ticket_id, []).append(
                    f"[transition -> {to.value}] {reason}"
                )
            updated = Ticket.from_dict(raw)
        return updated

    def comment(self, ticket_id: str, markdown: str) -> None:
        with self._locked() as data:
            data.setdefault("comments", {}).setdefault(ticket_id, []).append(markdown)

    def comments(self, ticket_id: str) -> list[str]:
        return self._read().get("comments", {}).get(ticket_id, [])
