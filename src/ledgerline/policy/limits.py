"""Load limits.yaml. Amounts stay Decimal; YAML floats are rejected."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from ledgerline.money import D


def _decimal(value: Any) -> Decimal:
    if isinstance(value, float):
        raise TypeError("limits must be quoted decimal strings, not YAML floats")
    if isinstance(value, bool):
        raise TypeError("unexpected boolean where a decimal was required")
    return D(value)


class SwiftFee(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal
    currency: str

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> Decimal:
        return _decimal(value)


class EvidenceScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confidence_when_bank_and_invoice_agree: Decimal
    confidence_when_one_source_agrees: Decimal
    confidence_when_sources_disagree: Decimal
    contradiction_cap: Decimal

    @field_validator("*", mode="before")
    @classmethod
    def _scores(cls, value: object) -> Decimal:
        return _decimal(value)


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    reserve_floor: dict[str, Decimal]
    fx_auto_limit_high_conf: Decimal
    fx_auto_limit_low_conf: Decimal
    confidence_threshold: Decimal
    auto_transfer_limit: Decimal
    beneficiary_must_be_verified: bool
    max_quote_age_seconds: int
    defer_allowed_if_no_penalty: bool
    swift_fee: SwiftFee
    evidence: EvidenceScores
    indicative_eur_per_usd: Decimal
    indicative_usd_per_gbp: Decimal

    @field_validator(
        "fx_auto_limit_high_conf",
        "fx_auto_limit_low_conf",
        "confidence_threshold",
        "auto_transfer_limit",
        "indicative_eur_per_usd",
        "indicative_usd_per_gbp",
        mode="before",
    )
    @classmethod
    def _money_fields(cls, value: object) -> Decimal:
        return _decimal(value)

    @field_validator("reserve_floor", mode="before")
    @classmethod
    def _floors(cls, value: object) -> dict[str, Decimal]:
        if not isinstance(value, dict):
            raise TypeError("reserve_floor must be a map")
        return {str(key): _decimal(item) for key, item in value.items()}

    def fx_limit(self, confidence: Decimal) -> Decimal:
        if D(confidence) >= self.confidence_threshold:
            return self.fx_auto_limit_high_conf
        return self.fx_auto_limit_low_conf

    def floor(self, currency: str) -> Decimal:
        if currency not in self.reserve_floor:
            raise KeyError(currency)
        return self.reserve_floor[currency]


def load_limits(path: Path) -> Limits:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Limits.model_validate(raw)


def dump_limits(limits: Limits) -> dict[str, Any]:
    payload = limits.model_dump(mode="json")
    return payload
