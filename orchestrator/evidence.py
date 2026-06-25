"""Hash-chained evidence log.

Every consequential step in a ticket's life is appended here as a JSON line.
Each entry embeds the SHA-256 of the previous entry, so any later tampering
with an earlier entry breaks the chain and is detectable by ``verify_chain``.

Honesty note: a hash chain is *tamper-evident*, not *tamper-proof*. ``seal``
adds an HMAC over the final head hash using a secret key, which detects
tampering by anyone without the key. For production accreditation you would
replace the HMAC seal with real signing (e.g. cosign / a KMS key) and verify
offline. The interface stays the same.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _canonical(obj: Any) -> bytes:
    """Stable JSON encoding so hashes are reproducible across runs/machines."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(prev: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(prev.encode("utf-8") + _canonical(payload)).hexdigest()


@dataclass
class EvidenceEntry:
    seq: int
    ts: float
    lane: str
    action: str
    detail: dict[str, Any]
    prev: str
    hash: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "seq": self.seq,
                "ts": self.ts,
                "lane": self.lane,
                "action": self.action,
                "detail": self.detail,
                "prev": self.prev,
                "hash": self.hash,
            },
            sort_keys=True,
        )

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EvidenceEntry":
        return EvidenceEntry(
            seq=d["seq"],
            ts=d["ts"],
            lane=d["lane"],
            action=d["action"],
            detail=d["detail"],
            prev=d["prev"],
            hash=d["hash"],
        )


@dataclass
class EvidenceChain:
    """Append-only, hash-linked record for a single ticket."""

    path: Path
    _now: Any = field(default=time.time, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ----- reading -------------------------------------------------------
    def __iter__(self) -> Iterator[EvidenceEntry]:
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                yield EvidenceEntry.from_dict(json.loads(line))

    def entries(self) -> list[EvidenceEntry]:
        return list(self)

    def head(self) -> str:
        last = GENESIS
        for entry in self:
            last = entry.hash
        return last

    def __len__(self) -> int:
        return sum(1 for _ in self)

    # ----- writing -------------------------------------------------------
    def append(self, lane: str, action: str, detail: dict[str, Any] | None = None) -> EvidenceEntry:
        detail = detail or {}
        existing = self.entries()
        seq = len(existing)
        prev = existing[-1].hash if existing else GENESIS
        ts = round(self._now(), 6)
        payload = {"seq": seq, "ts": ts, "lane": lane, "action": action, "detail": detail, "prev": prev}
        h = _hash(prev, payload)
        entry = EvidenceEntry(seq=seq, ts=ts, lane=lane, action=action, detail=detail, prev=prev, hash=h)
        with self.path.open("a") as fh:
            fh.write(entry.to_json() + "\n")
        return entry

    # ----- integrity -----------------------------------------------------
    def verify_chain(self) -> tuple[bool, str | None]:
        """Return (ok, reason). Recomputes every link from genesis."""
        prev = GENESIS
        for i, entry in enumerate(self):
            if entry.seq != i:
                return False, f"seq mismatch at {i}: got {entry.seq}"
            if entry.prev != prev:
                return False, f"broken link at seq {i}: prev={entry.prev} expected {prev}"
            payload = {
                "seq": entry.seq,
                "ts": entry.ts,
                "lane": entry.lane,
                "action": entry.action,
                "detail": entry.detail,
                "prev": entry.prev,
            }
            if _hash(prev, payload) != entry.hash:
                return False, f"hash mismatch at seq {i} (entry was modified)"
            prev = entry.hash
        return True, None

    def has_action(self, action: str) -> bool:
        return any(e.action == action for e in self)

    # ----- sealing -------------------------------------------------------
    def seal(self, key: bytes) -> str:
        """Seal the chain by HMAC-ing the head hash. Returns the seal token.

        Replace with real signing (cosign/KMS) for production. The seal is
        written alongside the chain as ``<path>.seal``.
        """
        ok, reason = self.verify_chain()
        if not ok:
            raise ValueError(f"refusing to seal a broken chain: {reason}")
        head = self.head()
        seal = hmac.new(key, head.encode("utf-8"), hashlib.sha256).hexdigest()
        Path(str(self.path) + ".seal").write_text(json.dumps({"head": head, "seal": seal}))
        return seal

    def verify_seal(self, key: bytes) -> bool:
        seal_path = Path(str(self.path) + ".seal")
        if not seal_path.exists():
            return False
        data = json.loads(seal_path.read_text())
        if data.get("head") != self.head():
            return False
        expected = hmac.new(key, self.head().encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, data.get("seal", ""))


def default_seal_key() -> bytes:
    """Seal key from env (placeholder for a real KMS-managed key)."""
    return os.environ.get("SUPERSPRINT_SEAL_KEY", "dev-insecure-seal-key").encode("utf-8")
