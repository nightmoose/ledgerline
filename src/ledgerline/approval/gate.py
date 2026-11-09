"""Approvals are bound to amount, currency, counterparty, quote_id, and evidence."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ledgerline.jsonutil import dumps
from ledgerline.money import canonical


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    obligation_id: str
    amount: Decimal
    currency: str
    counterparty: str
    quote_id: str | None
    evidence_hash: str
    fingerprint: str
    status: Literal["pending", "approved", "rejected", "void"] = "pending"
    allows_exception: bool = False
    approver: str | None = None


def evidence_hash(material: dict[str, Any]) -> str:
    return hashlib.sha256(dumps(material).encode("utf-8")).hexdigest()


def fingerprint(
    *,
    amount: Decimal,
    currency: str,
    counterparty: str,
    quote_id: str | None,
    evidence_hash: str,
) -> str:
    body = {
        "amount": canonical(amount),
        "currency": currency,
        "counterparty": counterparty,
        "quote_id": quote_id,
        "evidence_hash": evidence_hash,
    }
    return hashlib.sha256(dumps(body).encode("utf-8")).hexdigest()


def bound_to(approval: Approval, **current: Any) -> bool:
    expected = fingerprint(
        amount=current["amount"],
        currency=current["currency"],
        counterparty=current["counterparty"],
        quote_id=current.get("quote_id"),
        evidence_hash=current["evidence_hash"],
    )
    return approval.status == "approved" and approval.fingerprint == expected


def void_if_changed(approval: Approval, **current: Any) -> Approval:
    if approval.status in {"rejected", "void"}:
        return approval
    if bound_to(approval, **current) or (
        approval.status == "pending" and approval.fingerprint == fingerprint(**current)
    ):
        return approval
    return approval.model_copy(update={"status": "void"})
