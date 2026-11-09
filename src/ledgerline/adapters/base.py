"""One interface for the sandbox REST client and the in-memory mock."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol


class AirwallexError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        source: str = "",
        details: dict[str, Any] | None = None,
        kind: str = "request",
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.source = source
        self.details = details or {}
        # permissions | authentication | request | transport
        self.kind = kind
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
        }
        if self.details:
            body["details"] = self.details
        return body


class AirwallexAdapter(Protocol):
    def balances(self) -> list[dict[str, Any]]: ...

    def fx_rate(
        self,
        *,
        buy_currency: str,
        sell_currency: str,
        buy_amount: Decimal | None = None,
        sell_amount: Decimal | None = None,
    ) -> dict[str, Any]: ...

    def create_quote(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_quote(self, quote_id: str) -> dict[str, Any]: ...

    def create_conversion(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def beneficiary_schema(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def create_beneficiary(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def create_transfer(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_transfer(self, transfer_id: str) -> dict[str, Any]: ...

    def list_transfers(
        self, *, page_size: int = 10, request_id: str | None = None
    ) -> dict[str, Any]: ...

    def list_beneficiaries(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]: ...

    def list_global_accounts(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]: ...

    def list_conversions(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]: ...

    def list_deposits(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]: ...

    def simulate_deposit(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def simulate_transfer_transition(
        self, transfer_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...
