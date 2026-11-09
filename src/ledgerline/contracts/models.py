"""Pydantic contracts. Bad shapes are rejected before planning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ledgerline.money import D, money

Action = Literal["FUND", "CONVERT-MIN", "DEFER", "ESCALATE"]
Criticality = Literal["halt", "time_sensitive", "payroll", "standard"]
Method = Literal["LOCAL", "SWIFT"]
Currency = Literal["USD", "EUR", "GBP"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Obligation(StrictModel):
    id: str = Field(min_length=1)
    counterparty: str = Field(min_length=1)
    currency: Currency
    amount: Decimal
    due_in_hours: int
    method: Method
    deferrable: bool
    penalty: bool
    criticality: Criticality
    beneficiary_id: str = Field(min_length=1)
    beneficiary_verified: bool
    reason: str = Field(min_length=1)
    label: str | None = None
    unit: Literal["major"] = "major"

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> Decimal:
        if isinstance(value, float):
            raise ValueError("amount must be a major-unit decimal string, not a float")
        quantized = money(D(value))
        if quantized != D(value):
            raise ValueError("amount has more than 2 decimal places; major units only")
        if quantized <= 0:
            raise ValueError("amount must be positive")
        return quantized

    @field_validator("due_in_hours")
    @classmethod
    def _window(cls, value: int) -> int:
        if value < 0 or value > 72:
            raise ValueError("due_in_hours must be inside the 72-hour window")
        return value


class LedgerRow(StrictModel):
    event_id: str = Field(min_length=1)
    currency: Currency
    amount: Decimal
    unit: Literal["major", "minor"] = "major"

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> Decimal:
        if isinstance(value, float):
            raise ValueError("amount must be a decimal string, not a float")
        return D(value)


class Check(StrictModel):
    name: str
    ok: bool
    detail: str


class Decision(StrictModel):
    decision_id: str
    obligation_id: str
    action: Action
    counterparty: str
    currency: Currency
    amount: Decimal
    method: Method
    reason: str
    checks: list[Check]
    approval_required: bool
    auto_execute: bool
    sell_currency: Currency | None = None
    sell_amount: Decimal | None = None
    buy_amount: Decimal | None = None
    fee_amount: Decimal = Decimal("0")
    fee_currency: Currency | None = None
    reserve_after: dict[str, Decimal] = Field(default_factory=dict)
    due_in_hours: int
    status: str = "proposed"


class Plan(StrictModel):
    version: int
    confidence: Decimal
    fx_limit: Decimal
    lines: list[Decision]
    created_at: datetime

    def by_id(self, obligation_id: str) -> Decision:
        for line in self.lines:
            if line.obligation_id == obligation_id:
                return line
        raise KeyError(obligation_id)


class QuoteView(StrictModel):
    quote_id: str
    buy_currency: str
    sell_currency: str
    buy_amount: Decimal
    sell_amount: Decimal
    client_rate: Decimal
    usage: str
    valid_from_at: str
    valid_to_at: str
    request_id: str
    currency_pair: str


class EvidenceReading(StrictModel):
    contradicts: bool
    explanation: str
    confidence_before: Decimal
    confidence_after: Decimal
    fx_limit_before: Decimal
    fx_limit_after: Decimal
