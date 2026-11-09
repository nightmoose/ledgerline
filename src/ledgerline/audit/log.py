"""Append-only JSONL audit log, mirrored into SQLite for queries. Replay reads JSONL."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ledgerline.jsonutil import dumps, loads


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
        self._db.commit()
        self._seq = self._max_seq()

    def append(self, kind: str, message: str, *, ts: str, **payload: Any) -> dict[str, Any]:
        self._seq += 1
        event = {
            "seq": self._seq,
            "ts": ts,
            "kind": kind,
            "message": message,
            "payload": payload,
        }
        line = dumps(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        self._db.execute(
            "insert into audit (seq, ts, kind, message, payload) values (?, ?, ?, ?, ?)",
            (self._seq, ts, kind, message, dumps(payload)),
        )
        self._db.commit()
        return event

    def replay(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(loads(line))
        return events

    def close(self) -> None:
        self._db.close()

    def _max_seq(self) -> int:
        row = self._db.execute("select coalesce(max(seq), 0) from audit").fetchone()
        return int(row[0] if row else 0)
