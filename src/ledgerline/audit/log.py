"""Append-only, hash-chained JSONL audit log, mirrored into SQLite for queries.

Replay reads JSONL. Every event stores the previous event's hash, so the log
is its own receipt: ``python -m ledgerline.receipt verify <audit.jsonl>``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ledgerline.audit.chain import GENESIS, ChainReport, canonical, event_hash, last_hash, verify_file
from ledgerline.jsonutil import dumps, loads, to_plain


class AuditLog:
    def __init__(self, path: Path, db_path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute(
            """
            create table if not exists audit (
                seq integer primary key,
                ts text not null,
                kind text not null,
                message text not null,
                payload text not null
            )
            """
        )
        columns = {row[1] for row in self._db.execute("pragma table_info(audit)")}
        for column in ("prev_hash", "hash"):
            if column not in columns:
                self._db.execute(f"alter table audit add column {column} text")
        self._db.commit()
        self._seq = self._max_seq()
        self._prev = last_hash(self.path) if self.path.exists() else GENESIS

    @property
    def head(self) -> str:
        return self._prev

    def append(self, kind: str, message: str, *, ts: str, **payload: Any) -> dict[str, Any]:
        self._seq += 1
        body = to_plain(
            {
                "seq": self._seq,
                "ts": ts,
                "kind": kind,
                "message": message,
                "payload": payload,
                "prev_hash": self._prev,
            }
        )
        body["hash"] = event_hash(body)
        line = canonical(body)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        self._db.execute(
            "insert into audit (seq, ts, kind, message, payload, prev_hash, hash) values (?, ?, ?, ?, ?, ?, ?)",
            (self._seq, ts, kind, message, dumps(payload), body["prev_hash"], body["hash"]),
        )
        self._db.commit()
        self._prev = body["hash"]
        return body

    def replay(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(loads(line))
        return events

    def verify(self) -> ChainReport:
        return verify_file(self.path)

    def close(self) -> None:
        self._db.close()

    def _max_seq(self) -> int:
        row = self._db.execute("select coalesce(max(seq), 0) from audit").fetchone()
        return int(row[0] if row else 0)
