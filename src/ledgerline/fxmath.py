"""Shared FX rounding for the planner and the mock sandbox.

The mock rate is 0.9213 EUR per 1 USD (synthetic sandbox cross from the
console design). client_rate on a quote is buy_amount / sell_amount.
"""

from __future__ import annotations

from decimal import Decimal

from ledgerline.money import D, money, rate

EUR_PER_USD = D("0.9213")
USD_PER_GBP = D("1.27")


def usd_per_unit(currency: str, eur_per_usd: Decimal = EUR_PER_USD, usd_per_gbp: Decimal = USD_PER_GBP) -> Decimal:
    if currency == "USD":
        return D("1")
    if currency == "EUR":
        return D(1) / D(eur_per_usd)
    if currency == "GBP":
        return D(usd_per_gbp)
    raise ValueError(f"unsupported currency {currency}")


def usd_eq(
    amount: Decimal,
    currency: str,
    eur_per_usd: Decimal = EUR_PER_USD,
    usd_per_gbp: Decimal = USD_PER_GBP,
) -> Decimal:
    return money(D(amount) * usd_per_unit(currency, eur_per_usd, usd_per_gbp))


def sell_usd_for_eur_buy(buy_eur: Decimal, eur_per_usd: Decimal = EUR_PER_USD) -> Decimal:
    """USD major units a buyer must sell to receive exactly buy_eur."""
    return money(D(buy_eur) / D(eur_per_usd))


def client_rate(buy_amount: Decimal, sell_amount: Decimal) -> Decimal:
    if sell_amount == 0:
        raise ValueError("sell_amount is zero")
    return rate(D(buy_amount) / D(sell_amount))
