"""Recompute only the obligations a balance change can affect, and emit a diff."""

from __future__ import annotations

from decimal import Decimal

from ledgerline.contracts.models import Decision, Obligation, Plan
from ledgerline.money import money


def affected_ids(
    obligations: list[Obligation],
    previous: Plan,
    old_balances: dict[str, Decimal],
    new_balances: dict[str, Decimal],
) -> set[str]:
    changed = {
        currency
        for currency in set(old_balances) | set(new_balances)
        if money(old_balances.get(currency, 0)) != money(new_balances.get(currency, 0))
    }
    selected: set[str] = set()
    for obligation in obligations:
        if obligation.currency in changed:
            selected.add(obligation.id)
            continue
        line = previous.by_id(obligation.id)
        sells_changed_usd = "USD" in changed and line.action == "CONVERT-MIN"
        may_convert = "USD" in changed and not obligation.deferrable and obligation.currency != "USD"
        if sells_changed_usd or may_convert:
            selected.add(obligation.id)
    return selected


def merge(
    previous: Plan,
    fresh: list[Decision],
    affected: set[str],
) -> tuple[list[Decision], list[dict[str, str]], list[str]]:
    fresh_by_id = {line.obligation_id: line for line in fresh}
    merged: list[Decision] = []
    changes: list[dict[str, str]] = []
    recomputed: list[str] = []
    for old in previous.lines:
        if old.obligation_id not in affected:
            merged.append(old)
            continue
        recomputed.append(old.obligation_id)
        new = fresh_by_id[old.obligation_id]
        same = (
            old.action == new.action
            and old.amount == new.amount
            and old.sell_amount == new.sell_amount
            and old.approval_required == new.approval_required
        )
        if same:
            merged.append(new.model_copy(update={"decision_id": old.decision_id, "status": old.status}))
            continue
        merged.append(new)
        changes.append(
            {
                "obligation_id": old.obligation_id,
                "before": old.action,
                "after": new.action,
            }
        )
    return merged, changes, recomputed
