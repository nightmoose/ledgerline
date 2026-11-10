"""Scripted walkthrough of the treasury demo. Runs entirely in mock mode."""

from __future__ import annotations

from dataclasses import dataclass, field

from ledgerline.errors import ApprovalError, ExecutionError
from ledgerline.scenario import CUSTOMER_EMAIL, DEPOSIT_USD, OBLIGATIONS, RECEIPT, SEED_BALANCES
from ledgerline.service import Service

# When True, each transcript line is printed as it happens (the CLI sets this).
ECHO = False


@dataclass
class DemoReport:
    transcript: list[str] = field(default_factory=list)
    approval_id: str | None = None
    payroll_approval_id: str | None = None

    def say(self, message: str) -> None:
        self.transcript.append(message)
        if ECHO:
            print(message, flush=True)


def prepare_demo(service: Service) -> DemoReport:
    report = DemoReport()
    quarantined = service.ingest_ledger(
        [
            {"event_id": "led_1", "amount": "100.00", "currency": "USD", "unit": "major"},
            {"event_id": "led_1", "amount": "100.00", "currency": "USD", "unit": "major"},
            {"event_id": "led_2", "amount": "620000", "currency": "USD", "unit": "minor"},
        ]
    )
    if len(quarantined.rejected) != 2 or len(quarantined.accepted) != 1:
        raise RuntimeError("ledger gate did not quarantine the duplicate and the minor-unit row")
    report.say("Quarantined 1 duplicate ledger event and 1 minor-unit row.")

    for currency, amount in SEED_BALANCES.items():
        service.deposit(currency, amount)
    report.say(f"Seeded balances {_fmt(service.wallet())}.")

    loaded = service.load_obligations(OBLIGATIONS)
    if loaded.rejected or len(loaded.accepted) != 5:
        raise RuntimeError(f"obligation contract failed: {loaded.rejected}")
    service.set_receipts([RECEIPT])
    forecast = service.forecast()
    if forecast.confidence != service.limits.evidence.confidence_when_bank_and_invoice_agree:
        raise RuntimeError(f"expected bank+invoice confidence, got {forecast.confidence}")
    report.say(f"Forecast confidence {forecast.confidence} (bank and invoice agree).")

    service.build_plan()
    _expect(
        service,
        {
            "obl_shipping": "FUND",
            "obl_supplier": "CONVERT-MIN",
            "obl_saas": "DEFER",
            "obl_payroll": "ESCALATE",
            "obl_contractor": "DEFER",
        },
    )
    supplier = service.plan.by_id("obl_supplier")
    if supplier.approval_required:
        raise RuntimeError("high confidence should auto-clear the supplier conversion")
    report.say("Plan v1: FUND shipping · CONVERT-MIN supplier · DEFER SaaS · ESCALATE payroll · DEFER contractor.")

    service.tool("explain", {"obligation_id": "obl_supplier"})
    reading = service.apply_evidence(CUSTOMER_EMAIL)
    if not reading["contradicts"]:
        raise RuntimeError("the customer email should contradict the receipt")
    if service.confidence != service.limits.evidence.contradiction_cap:
        raise RuntimeError(f"confidence did not fall to the cap: {service.confidence}")
    supplier = service.plan.by_id("obl_supplier")
    if supplier.action != "CONVERT-MIN" or not supplier.approval_required:
        raise RuntimeError("the same conversion should now wait for approval")
    if service.plan.by_id("obl_payroll").action != "ESCALATE":
        raise RuntimeError("the email tried to override payroll and must not")
    report.say(
        f"Email contradicted the receipt. Confidence {service.confidence}. "
        f"FX auto limit {service.limits.fx_limit(service.confidence)}."
    )

    frozen_saas = service.plan.by_id("obl_saas").decision_id
    service.deposit("USD", DEPOSIT_USD, replan=True)
    changes = service.last_diff.changes
    if [item["obligation_id"] for item in changes] != ["obl_contractor"]:
        raise RuntimeError(f"replan changed unexpected lines: {changes}")
    if changes[0]["before"] != "DEFER" or changes[0]["after"] != "FUND":
        raise RuntimeError(f"contractor diff was {changes[0]}")
    if "obl_saas" in service.last_diff.recomputed:
        raise RuntimeError("SaaS was recomputed after a USD deposit")
    if service.plan.by_id("obl_saas").decision_id != frozen_saas:
        raise RuntimeError("frozen SaaS decision id changed")
    report.say("Deposit landed. Only contractor moved DEFER → FUND.")

    service.ensure_beneficiaries()
    service.request_quote("obl_supplier")
    card = service.open_approval("obl_supplier")
    payroll = service.open_approval("obl_payroll")
    report.approval_id = card.id
    report.payroll_approval_id = payroll.id
    report.say(f"Approval card {card.id} is bound to the supplier quote.")
    return report


def settle_demo(service: Service, *, approver: str = "Alex") -> DemoReport:
    report = DemoReport()
    card = service._approval_for("obl_supplier")
    if card is None:
        raise RuntimeError("supplier approval card is missing")
    if card.status == "pending":
        try:
            service.execute("obl_supplier")
            raise RuntimeError("execution crossed the approval gate")
        except ApprovalError:
            report.say("Supplier conversion is blocked until the bound card is approved.")
        service.approve(card.id, approver=approver)
    elif card.status != "approved":
        raise RuntimeError(f"supplier approval is {card.status}")
    report.approval_id = card.id

    service.execute("obl_supplier")
    supplier_transfer = service._latest("obl_supplier")
    if supplier_transfer is None:
        raise RuntimeError("supplier transfer was not created")
    shipping = service.execute("obl_shipping")
    service.transition(shipping.transfer_id, "PAID")
    service.emit_webhook(service.adapter.get_transfer(shipping.transfer_id), "payout.transfer.paid")
    paid = service.transition(supplier_transfer.transfer_id, "PAID")
    service.emit_webhook(paid, "payout.transfer.paid")
    report.say(
        f"Shipping {shipping.transfer_id} and the Berlin SWIFT transfer "
        f"{supplier_transfer.transfer_id} are paid (conversion {supplier_transfer.conversion_id})."
    )

    contractor = service.execute("obl_contractor")
    sent = service.transition(contractor.transfer_id, "SENT")
    if service.poll(sent["id"])["terminal"]:
        raise RuntimeError("SENT was treated as terminal")
    try:
        service.execute("obl_contractor", replacement=True)
        raise RuntimeError("duplicate lock allowed a replacement while the transfer was SENT")
    except ExecutionError:
        report.say("Duplicate lock held while the contractor transfer was SENT.")
    failed = service.transition(sent["id"], "FAILED", failure_type="BENEFICIARY_BANK_RETURNED")
    # The mock ends a failure as CANCELLED with the requested failure_type. The
    # live demo host answers FAILED with its own failure_type and moves the
    # transfer to CANCELLED shortly after. Both are terminal failures.
    if failed["status"] not in {"FAILED", "CANCELLED"} or not failed.get("failure_type"):
        raise RuntimeError(f"failed transfer did not end FAILED/CANCELLED: {failed['status']}")
    if not service.poll(failed["id"])["terminal"]:
        raise RuntimeError("a failed transfer was treated as in flight")
    service.emit_webhook(failed, "payout.transfer.failed")
    replacement = service.execute("obl_contractor", replacement=True)
    if replacement.request_id == contractor.request_id or replacement.attempt != 2:
        raise RuntimeError("replacement did not use a new request_id")
    try:
        service.execute("obl_contractor", replacement=True)
        raise RuntimeError("duplicate lock allowed a second in-flight replacement")
    except ExecutionError:
        pass
    settled = service.transition(replacement.transfer_id, "PAID")
    service.emit_webhook(settled, "payout.transfer.paid")
    paid_attempts = [item for item in service.attempts["obl_contractor"] if item.status == "paid"]
    if len(paid_attempts) != 1:
        raise RuntimeError("contractor was paid more than once")
    report.say(
        f"Contractor transfer {contractor.transfer_id} went SENT, then {failed['status']} "
        f"({failed.get('failure_type')}); replacement {replacement.transfer_id} was paid."
    )

    if not service.reserves_hold():
        raise RuntimeError(f"reserve floor breached: {service.wallet()}")
    replay = service.replay()
    kinds = {event["kind"] for event in replay}
    for required in ("plan", "policy", "replan", "approved", "execute", "webhook"):
        if required not in kinds:
            raise RuntimeError(f"audit replay is missing {required}")
    service._log(
        "result",
        "Reserves are at or above the floor",
        balances={key: str(value) for key, value in service.wallet().items()},
    )
    report.say(f"Reserves hold at {_fmt(service.wallet())}. Audit events: {len(service.replay())}.")
    chain = service.audit.verify()
    if not chain.ok:
        raise RuntimeError(f"audit hash chain is broken: {chain.reason}")
    report.say(f"Receipt: hash chain intact over {chain.events} events, head {chain.head[:12]}.")
    return report


def run_demo(service: Service) -> DemoReport:
    prepared = prepare_demo(service)
    settled = settle_demo(service)
    prepared.transcript.extend(settled.transcript)
    prepared.approval_id = settled.approval_id
    return prepared


def _expect(service: Service, actions: dict[str, str]) -> None:
    actual = {line.obligation_id: line.action for line in service.plan.lines}
    if actual != actions:
        raise RuntimeError(f"plan actions {actual} != {actions}")


def _fmt(balances) -> str:
    return " · ".join(f"{currency} {amount:,.2f}" for currency, amount in balances.items())
