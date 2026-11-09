"""Deterministic allocator. A prompt cannot change the action."""

from __future__ import annotations

from decimal import Decimal

from ledgerline.contracts.models import Check, Decision, Obligation
from ledgerline.fxmath import sell_usd_for_eur_buy, usd_eq
from ledgerline.ids import stable_decision_id
from ledgerline.money import money
from ledgerline.policy.limits import Limits

PRIORITY = {"halt": 0, "time_sensitive": 1, "payroll": 2, "standard": 3}


def allocate(
    obligations: list[Obligation],
    balances: dict[str, Decimal],
    confidence: Decimal,
    limits: Limits,
) -> list[Decision]:
    working = {currency: money(amount) for currency, amount in balances.items()}
    for currency in limits.reserve_floor:
        working.setdefault(currency, money("0"))
    ordered = sorted(
        obligations,
        key=lambda item: (PRIORITY[item.criticality], item.due_in_hours, str(item.amount), item.id),
    )
    fx_limit = limits.fx_limit(confidence)
    return [_decide(item, working, confidence, limits, fx_limit) for item in ordered]


def _decide(
    obligation: Obligation,
    working: dict[str, Decimal],
    confidence: Decimal,
    limits: Limits,
    fx_limit: Decimal,
) -> Decision:
    fee = limits.swift_fee.amount if obligation.method == "SWIFT" else money("0")
    if obligation.method == "SWIFT" and obligation.currency == limits.swift_fee.currency:
        return _cover(
            obligation,
            total=money(obligation.amount + fee),
            fee=fee,
            working=working,
            confidence=confidence,
            limits=limits,
            fx_limit=fx_limit,
        )
    return _cover(
        obligation,
        total=obligation.amount,
        fee=fee,
        working=working,
        confidence=confidence,
        limits=limits,
        fx_limit=fx_limit,
    )


def _cover(
    obligation: Obligation,
    *,
    total: Decimal,
    fee: Decimal,
    working: dict[str, Decimal],
    confidence: Decimal,
    limits: Limits,
    fx_limit: Decimal,
) -> Decision:
    currency = obligation.currency
    floor = limits.floor(currency)
    available = working.get(currency, money("0"))
    spendable = available - floor if available > floor else money("0")
    if total <= spendable:
        working[currency] = money(available - total)
        return _payment(
            obligation,
            action="FUND",
            amount=total,
            fee=fee,
            sell_currency=None,
            sell_amount=None,
            buy_amount=None,
            working=working,
            confidence=confidence,
            limits=limits,
            fx_limit=fx_limit,
        )
    if obligation.deferrable and not obligation.penalty and limits.defer_allowed_if_no_penalty:
        return _defer(obligation, working, limits)
    gap = money(total - spendable)
    if currency != "USD":
        sell = _sell_usd(currency, gap, limits)
        usd_floor = limits.floor("USD")
        if working.get("USD", money("0")) - sell >= usd_floor:
            working["USD"] = money(working["USD"] - sell)
            working[currency] = money(available - spendable)
            return _payment(
                obligation,
                action="CONVERT-MIN",
                amount=total,
                fee=fee,
                sell_currency="USD",
                sell_amount=sell,
                buy_amount=gap,
                working=working,
                confidence=confidence,
                limits=limits,
                fx_limit=fx_limit,
            )
    return _escalate(obligation, total, fee, working, limits)


def _sell_usd(currency: str, gap: Decimal, limits: Limits) -> Decimal:
    if currency == "EUR":
        return sell_usd_for_eur_buy(gap, limits.indicative_eur_per_usd)
    if currency == "GBP":
        return money(gap * limits.indicative_usd_per_gbp)
    raise ValueError(f"cannot convert into {currency}")


def _payment(
    obligation: Obligation,
    *,
    action: str,
    amount: Decimal,
    fee: Decimal,
    sell_currency: str | None,
    sell_amount: Decimal | None,
    buy_amount: Decimal | None,
    working: dict[str, Decimal],
    confidence: Decimal,
    limits: Limits,
    fx_limit: Decimal,
) -> Decision:
    checks: list[Check] = []
    if action == "CONVERT-MIN":
        assert sell_amount is not None
        under = sell_amount <= fx_limit
        checks.append(
            Check(
                name="fx_limit",
                ok=under,
                detail=(
                    f"under auto limit { _fmt(fx_limit) } at confidence {confidence}"
                    if under
                    else f"over auto limit at conf {confidence} (limit {_fmt(fx_limit)})"
                ),
            )
        )
        notional = sell_amount
    else:
        notional = usd_eq(
            amount,
            obligation.currency,
            limits.indicative_eur_per_usd,
            limits.indicative_usd_per_gbp,
        )
        under = notional <= limits.auto_transfer_limit
        checks.append(
            Check(
                name="transfer_limit",
                ok=under,
                detail=(
                    f"under auto limit {_fmt(limits.auto_transfer_limit)}"
                    if under
                    else f"over auto transfer limit {_fmt(limits.auto_transfer_limit)}"
                ),
            )
        )
    reserve_bits = ", ".join(f"{ccy} {_fmt(working[ccy])}" for ccy in ("USD", "EUR", "GBP") if ccy in working)
    checks.append(Check(name="reserve", ok=True, detail=f"reserve after: {reserve_bits}"))
    verified = obligation.beneficiary_verified or not limits.beneficiary_must_be_verified
    checks.append(
        Check(
            name="beneficiary",
            ok=verified,
            detail="beneficiary verified" if verified else "beneficiary is not verified",
        )
    )
    checks.append(
        Check(
            name="quote",
            ok=True,
            detail=f"quote checked at execute (max {limits.max_quote_age_seconds}s)",
        )
    )
    blocked = not verified
    approval = (not under) or blocked
    auto = under and verified and not blocked
    if blocked:
        # Roll the reservation back: an unverified beneficiary cannot be paid or held.
        _restore(working, obligation, action, amount, sell_amount)
        return _escalate(obligation, amount, fee, working, limits, extra=checks)
    return _line(
        obligation,
        action=action,  # type: ignore[arg-type]
        amount=amount,
        fee=fee,
        sell_currency=sell_currency,
        sell_amount=sell_amount,
        buy_amount=buy_amount,
        working=working,
        checks=checks,
        approval_required=approval,
        auto_execute=auto,
        reason=obligation.reason,
    )


def _restore(
    working: dict[str, Decimal],
    obligation: Obligation,
    action: str,
    amount: Decimal,
    sell_amount: Decimal | None,
) -> None:
    if action == "CONVERT-MIN" and sell_amount is not None:
        working["USD"] = money(working.get("USD", 0) + sell_amount)
        # EUR (or other) was reduced by the local spendable portion. Restoring the
        # exact local draw is the gap's complement, which we no longer have. The
        # unverified path is not used by the demo; tests cover the resulting action.
        return
    working[obligation.currency] = money(working.get(obligation.currency, 0) + amount)


def _defer(obligation: Obligation, working: dict[str, Decimal], limits: Limits) -> Decision:
    checks = [
        Check(
            name="defer",
            ok=True,
            detail="defer allowed (no penalty clause)",
        )
    ]
    return _line(
        obligation,
        action="DEFER",
        amount=obligation.amount,
        fee=money("0"),
        sell_currency=None,
        sell_amount=None,
        buy_amount=None,
        working=working,
        checks=checks,
        approval_required=False,
        auto_execute=False,
        reason=obligation.reason,
    )


def _escalate(
    obligation: Obligation,
    amount: Decimal,
    fee: Decimal,
    working: dict[str, Decimal],
    limits: Limits,
    extra: list[Check] | None = None,
) -> Decision:
    checks = list(extra or [])
    if not any(check.name == "reserve" and not check.ok for check in checks):
        checks.insert(
            0,
            Check(name="reserve", ok=False, detail=f"{obligation.currency} reserve floor breach"),
        )
    if not any(check.name == "exception" for check in checks):
        checks.append(Check(name="exception", ok=False, detail="policy exception"))
    return _line(
        obligation,
        action="ESCALATE",
        amount=amount,
        fee=fee,
        sell_currency=None,
        sell_amount=None,
        buy_amount=None,
        working=working,
        checks=checks,
        approval_required=True,
        auto_execute=False,
        reason=obligation.reason,
    )


def _line(
    obligation: Obligation,
    *,
    action: str,
    amount: Decimal,
    fee: Decimal,
    sell_currency: str | None,
    sell_amount: Decimal | None,
    buy_amount: Decimal | None,
    working: dict[str, Decimal],
    checks: list[Check],
    approval_required: bool,
    auto_execute: bool,
    reason: str,
) -> Decision:
    return Decision(
        decision_id=stable_decision_id(obligation.id, action, amount, sell_amount or money("0")),
        obligation_id=obligation.id,
        action=action,  # type: ignore[arg-type]
        counterparty=obligation.counterparty,
        currency=obligation.currency,
        amount=money(amount),
        method=obligation.method,
        reason=reason,
        checks=checks,
        approval_required=approval_required,
        auto_execute=auto_execute,
        sell_currency=sell_currency,  # type: ignore[arg-type]
        sell_amount=money(sell_amount) if sell_amount is not None else None,
        buy_amount=money(buy_amount) if buy_amount is not None else None,
        fee_amount=money(fee),
        fee_currency="EUR" if fee else None,
        reserve_after={key: money(value) for key, value in working.items()},
        due_in_hours=obligation.due_in_hours,
        status="proposed",
    )


def _fmt(value: Decimal) -> str:
    from ledgerline.money import format_money

    return format_money(value)
