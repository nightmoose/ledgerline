"""Major-unit money helpers. Floats are not used for amounts."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

TWOPLACES = Decimal("0.01")
SIXPLACES = Decimal("0.000001")


def D(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        raise TypeError("money amounts must be Decimal or str, not float")
    return Decimal(str(value))


def money(value: Any) -> Decimal:
    return D(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def rate(value: Any) -> Decimal:
    return D(value).quantize(SIXPLACES, rounding=ROUND_HALF_UP)


def format_money(value: Any) -> str:
    quantized = money(value)
    sign = "-" if quantized < 0 else ""
    whole, frac = f"{abs(quantized):.2f}".split(".")
    return f"{sign}{int(whole):,}.{frac}"


def canonical(value: Any) -> str:
    return f"{money(value):.2f}"
