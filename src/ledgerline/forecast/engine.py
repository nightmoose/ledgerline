"""72-hour cash view. Confidence comes from evidence, and a model can only lower it."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ledgerline.contracts.models import Obligation
from ledgerline.money import D, money
from ledgerline.policy.limits import Limits


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    counterparty: str
    currency: str
    amount: Decimal
    expected_in_hours: int = Field(ge=0, le=72)
    bank_agrees: bool
    invoice_agrees: bool

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> Decimal:
        if isinstance(value, float):
            raise ValueError("amount must not be a float")
        quantized = money(D(value))
        if quantized <= 0:
            raise ValueError("amount must be positive")
        return quantized


class CurrencyForecast(BaseModel):
    currency: str
    opening: Decimal
    inflows: Decimal
    outflows: Decimal
    closing: Decimal


class Forecast(BaseModel):
    confidence: Decimal
    receipt_scores: dict[str, Decimal]
    currencies: list[CurrencyForecast]


def score_receipt(receipt: Receipt, limits: Limits) -> Decimal:
    if receipt.bank_agrees and receipt.invoice_agrees:
        return limits.evidence.confidence_when_bank_and_invoice_agree
    if receipt.bank_agrees or receipt.invoice_agrees:
        return limits.evidence.confidence_when_one_source_agrees
    return limits.evidence.confidence_when_sources_disagree


def build_forecast(
    balances: dict[str, Decimal],
    obligations: list[Obligation],
    receipts: list[Receipt],
    limits: Limits,
) -> Forecast:
    scores = {receipt.id: score_receipt(receipt, limits) for receipt in receipts}
    confidence = min(scores.values()) if scores else D("1")
    currencies: list[CurrencyForecast] = []
    for currency in ("USD", "EUR", "GBP"):
        opening = money(balances.get(currency, 0))
        inflows = money(
            sum(
                (receipt.amount for receipt in receipts if receipt.currency == currency),
                D("0"),
            )
        )
        outflows = money(
            sum(
                (item.amount for item in obligations if item.currency == currency),
                D("0"),
            )
        )
        currencies.append(
            CurrencyForecast(
                currency=currency,
                opening=opening,
                inflows=inflows,
                outflows=outflows,
                closing=money(opening + inflows - outflows),
            )
        )
    return Forecast(confidence=confidence, receipt_scores=scores, currencies=currencies)
