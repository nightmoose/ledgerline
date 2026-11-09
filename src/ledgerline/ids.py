"""Stable ids. request_id values are UUIDs and are reused only for a retry."""

from __future__ import annotations

import uuid

NAMESPACE = uuid.UUID("8f1b6c2a-1d4e-4a7b-9c30-0a1b2c3d4e5f")


def request_id(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join(parts)))


def short_id(prefix: str, *parts: str) -> str:
    digest = uuid.uuid5(NAMESPACE, "|".join(parts)).hex[:8]
    return f"{prefix}_{digest}"


def stable_decision_id(obligation_id: str, action: str, amount: str, sell_amount: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{obligation_id}|{action}|{amount}|{sell_amount}"))
