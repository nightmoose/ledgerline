"""Hash chain for the audit log.

Each event carries ``prev_hash`` (the previous event's ``hash``) and its own
``hash``: SHA-256 over the canonical JSON of the event without ``hash``. The
first event chains from 64 zeros. Editing, deleting, inserting or reordering
any line breaks every hash after it, so the head hash is a receipt for the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def canonical(body: dict[str, Any]) -> str:
    """Canonical text that gets hashed. Plain JSON types only (Decimals are
    already strings by the time an event is written)."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(body: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in body.items() if key != "hash"}
    return hashlib.sha256(canonical(unsigned).encode("utf-8")).hexdigest()


@dataclass
class ChainReport:
    ok: bool
    events: int
    head: str
    first_bad_seq: int | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def line(self) -> str:
        if self.ok:
            return f"OK: {self.events} events, hash chain intact, head {self.head}"
        return f"BROKEN at seq {self.first_bad_seq}: {self.reason} ({self.events} events read)"


def verify_events(events: list[dict[str, Any]]) -> ChainReport:
    prev = GENESIS
    expected_seq = None
    for index, event in enumerate(events):
        seq = event.get("seq", index + 1)
        if "hash" not in event or "prev_hash" not in event:
            return ChainReport(False, len(events), prev, seq, "event has no hash fields")
        if expected_seq is not None and seq != expected_seq:
            return ChainReport(False, len(events), prev, seq, f"sequence gap: expected {expected_seq}")
        if event["prev_hash"] != prev:
            return ChainReport(False, len(events), prev, seq, "prev_hash does not match the previous event")
        if event_hash(event) != event["hash"]:
            return ChainReport(False, len(events), prev, seq, "event content does not match its hash")
        prev = event["hash"]
        expected_seq = seq + 1
    return ChainReport(True, len(events), prev)


def read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    # Plain json (floats stay floats) so canonical() reproduces the written text.
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_file(path: Path) -> ChainReport:
    return verify_events(read_events(path))


def last_hash(path: Path) -> str:
    events = read_events(path)
    if not events:
        return GENESIS
    return str(events[-1].get("hash") or GENESIS)
