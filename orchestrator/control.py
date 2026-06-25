"""HITL pause/stop controls.

A small JSON control file a human owns. The pipeline checks it before every
consequential step, so a human can pause or stop any lane at any time. This is
the concrete mechanism behind "humans can pause or stop any lane at any time."

  * ``stopped``: hard stop — the pipeline refuses to start consequential work.
  * ``paused``: global soft pause — same effect, intended to be temporary.
  * ``paused_lanes``: pause specific lanes by name (e.g. "lane4").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class Paused(Exception):
    """Raised when a lane is paused/stopped; the pipeline parks the ticket."""

    def __init__(self, scope: str):
        super().__init__(f"halted: {scope}")
        self.scope = scope


@dataclass
class Control:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"stopped": False, "paused": False, "paused_lanes": []})

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    # ----- queries -------------------------------------------------------
    def is_halted(self, lane: str | None = None) -> str | None:
        """Return a human-readable scope if halted, else None."""
        d = self._read()
        if d.get("stopped"):
            return "stopped (global)"
        if d.get("paused"):
            return "paused (global)"
        if lane and lane in d.get("paused_lanes", []):
            return f"paused (lane {lane})"
        return None

    def check(self, lane: str | None = None) -> None:
        scope = self.is_halted(lane)
        if scope:
            raise Paused(scope)

    # ----- mutations (a human / operator calls these) --------------------
    def stop(self) -> None:
        d = self._read()
        d["stopped"] = True
        self._write(d)

    def resume(self) -> None:
        self._write({"stopped": False, "paused": False, "paused_lanes": []})

    def pause(self, lane: str | None = None) -> None:
        d = self._read()
        if lane is None:
            d["paused"] = True
        else:
            lanes = set(d.get("paused_lanes", []))
            lanes.add(lane)
            d["paused_lanes"] = sorted(lanes)
        self._write(d)
