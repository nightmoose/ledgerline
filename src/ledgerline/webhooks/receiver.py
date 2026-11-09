"""Verify Airwallex webhooks and reconcile them in created_at order.

The signature is HMAC-SHA256 of the x-timestamp string concatenated with the
raw body, hex-encoded. Delivery is at-least-once, so event id is the dedupe key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from ledgerline.jsonutil import loads


def sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    message = timestamp.encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    if not secret or not timestamp or not signature:
        return False
    expected = sign(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature.strip())


class WebhookReceiver:
    def __init__(self, secret: str, *, tolerance_ms: int = 5 * 60 * 1000) -> None:
        self.secret = secret
        self.tolerance_ms = tolerance_ms
        self.seen: set[str] = set()
        self.pending: list[dict[str, Any]] = []
        self.applied: list[dict[str, Any]] = []

    def receive(
        self,
        raw_body: bytes,
        timestamp: str,
        signature: str,
        *,
        now_ms: int | None = None,
        flush: bool = True,
    ) -> dict[str, Any]:
        if not verify(self.secret, timestamp, raw_body, signature):
            return {"status": 400, "code": "invalid_signature", "duplicate": False}
        if now_ms is not None and not _timestamp_fresh(timestamp, now_ms, self.tolerance_ms):
            return {"status": 400, "code": "stale_timestamp", "duplicate": False}
        try:
            event = loads(raw_body)
        except json.JSONDecodeError:
            return {"status": 400, "code": "invalid_json", "duplicate": False}
        if not isinstance(event, dict) or not event.get("id"):
            return {"status": 400, "code": "invalid_event", "duplicate": False}
        event_id = str(event["id"])
        if event_id in self.seen:
            return {"status": 200, "code": "duplicate", "duplicate": True, "event_id": event_id}
        self.seen.add(event_id)
        self.pending.append(event)
        if flush:
            self.flush()
        return {"status": 200, "code": "accepted", "duplicate": False, "event_id": event_id}

    def flush(self) -> list[dict[str, Any]]:
        batch = sorted(self.pending, key=lambda item: str(item.get("created_at") or ""))
        self.pending = []
        self.applied.extend(batch)
        return batch

    def ordered(self) -> list[dict[str, Any]]:
        return sorted(self.applied, key=lambda item: str(item.get("created_at") or ""))


def _timestamp_fresh(timestamp: str, now_ms: int, tolerance_ms: int) -> bool:
    try:
        sent = int(timestamp)
    except ValueError:
        return False
    return abs(now_ms - sent) <= tolerance_ms
