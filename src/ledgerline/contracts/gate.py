"""Reject bad feeds before they can reach the planner."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ledgerline.contracts.models import LedgerRow, Obligation
from ledgerline.errors import ContractError


class Rejection(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class GateReport:
    def __init__(self) -> None:
        self.accepted: list[Any] = []
        self.rejected: list[dict[str, str]] = []

    @property
    def ok(self) -> bool:
        return not self.rejected


def _from_validation(exc: ValidationError) -> Rejection:
    parts = []
    code = "schema"
    for error in exc.errors():
        loc = ".".join(str(item) for item in error["loc"])
        message = error["msg"]
        parts.append(f"{loc}: {message}" if loc else message)
        if "decimal" in message or "float" in message or "2 decimal" in message:
            code = "major_units"
        elif "72-hour" in message:
            code = "window"
        elif error["type"] == "extra_forbidden":
            code = "schema"
        elif error["type"] == "missing":
            code = "schema"
    return Rejection(code, "; ".join(parts) or "schema validation failed")


def parse_obligation(payload: dict[str, Any]) -> Obligation:
    if payload.get("unit") == "minor" or "amount_cents" in payload:
        raise Rejection("minor_units", "amount is in minor units; major units are required")
    try:
        return Obligation.model_validate(payload)
    except ValidationError as exc:
        raise _from_validation(exc) from exc
    except (ContractError, TypeError, ValueError) as exc:
        raise Rejection("major_units", str(exc)) from exc


def parse_obligations(payloads: list[dict[str, Any]]) -> GateReport:
    report = GateReport()
    seen: set[str] = set()
    for payload in payloads:
        try:
            obligation = parse_obligation(payload)
        except Rejection as exc:
            report.rejected.append(
                {
                    "id": str(payload.get("id", "")),
                    "code": exc.code,
                    "message": exc.message,
                }
            )
            continue
        if obligation.id in seen:
            report.rejected.append(
                {
                    "id": obligation.id,
                    "code": "duplicate_id",
                    "message": f"duplicate obligation id {obligation.id}",
                }
            )
            continue
        seen.add(obligation.id)
        report.accepted.append(obligation)
    return report


def parse_ledger_row(payload: dict[str, Any]) -> LedgerRow:
    if payload.get("unit") == "minor" or "amount_cents" in payload:
        raise Rejection("minor_units", "ledger amount is in minor units; major units are required")
    try:
        row = LedgerRow.model_validate(payload)
    except ValidationError as exc:
        raise _from_validation(exc) from exc
    if row.unit == "minor":
        raise Rejection("minor_units", "ledger amount is in minor units; major units are required")
    if row.amount <= 0:
        raise Rejection("major_units", "amount must be positive")
    return row


def ingest_ledger(payloads: list[dict[str, Any]], seen_ids: set[str] | None = None) -> GateReport:
    report = GateReport()
    seen = set(seen_ids or ())
    for payload in payloads:
        try:
            row = parse_ledger_row(payload)
        except Rejection as exc:
            report.rejected.append(
                {
                    "id": str(payload.get("event_id", "")),
                    "code": exc.code,
                    "message": exc.message,
                }
            )
            continue
        if row.event_id in seen:
            report.rejected.append(
                {
                    "id": row.event_id,
                    "code": "duplicate_event_id",
                    "message": f"duplicate ledger event {row.event_id}",
                }
            )
            continue
        seen.add(row.event_id)
        report.accepted.append(row)
    return report
