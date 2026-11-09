"""Composes the adapter, policy, approvals, executor, webhooks, and audit log."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC
from decimal import Decimal
from typing import Any

from ledgerline.adapters.factory import build_adapter
from ledgerline.adapters.live import parse_airwallex_time
from ledgerline.agent.providers import build_reader
from ledgerline.agent.tools import dispatch
from ledgerline.approval.gate import Approval, bound_to, evidence_hash, fingerprint, void_if_changed
from ledgerline.audit.log import AuditLog
from ledgerline.clock import Clock, WallClock
from ledgerline.config import Settings, load_settings
from ledgerline.contracts.gate import GateReport, ingest_ledger, parse_obligations
from ledgerline.contracts.models import Obligation, Plan
from ledgerline.errors import ApprovalError, ExecutionError, PolicyError
from ledgerline.forecast.engine import Receipt, build_forecast
from ledgerline.ids import request_id, short_id
from ledgerline.jsonutil import dumps
from ledgerline.money import money
from ledgerline.policy.engine import allocate
from ledgerline.policy.limits import Limits, load_limits
from ledgerline.replan.replanner import affected_ids, merge
from ledgerline.webhooks.receiver import WebhookReceiver, sign

IN_FLIGHT = {"SCHEDULED", "PROCESSING", "SENT"}
TERMINAL_OK = {"PAID"}
TERMINAL_FAIL = {"CANCELLED", "FAILED"}
COUNTRY = {"USD": "US", "EUR": "DE", "GBP": "GB"}
BOOK_CURRENCIES = ("USD", "EUR", "GBP")

# Sandbox test bank details that pass POST /beneficiaries/validate on the demo
# host (observed 2026-11-09). They are public test values, not real accounts.
_ADDRESSES = {
    "US": {"street_address": "100 Harbor Way", "city": "Oakland", "state": "CA",
           "postcode": "94607", "country_code": "US"},
    "DE": {"street_address": "Friedrichstrasse 10", "city": "Berlin",
           "postcode": "10117", "country_code": "DE"},
    "GB": {"street_address": "1 Old Street", "city": "London",
           "postcode": "EC1V 9HL", "country_code": "GB"},
}


def _bank_details(name: str, currency: str, method: str) -> dict[str, Any]:
    country = COUNTRY[currency]
    details: dict[str, Any] = {
        "account_name": name,
        "account_currency": currency,
        "bank_country_code": country,
    }
    if currency == "USD":
        details.update(
            account_number="123456789",
            account_routing_type1="aba",
            account_routing_value1="026009593",
            bank_account_category="Checking",
            local_clearing_system="ACH",
        )
    elif currency == "EUR":
        details["iban"] = "DE89370400440532013000"
        if method == "SWIFT":
            details["swift_code"] = "COBADEFFXXX"
    elif currency == "GBP":
        details.update(
            account_number="31926819",
            account_routing_type1="sort_code",
            account_routing_value1="200415",
            local_clearing_system="FASTER_PAYMENTS",
        )
    return details


@dataclass
class Attempt:
    obligation_id: str
    attempt: int
    request_id: str
    transfer_id: str
    conversion_id: str | None
    status: str
    amount: Decimal
    currency: str


@dataclass
class Diff:
    changes: list[dict[str, str]] = field(default_factory=list)
    recomputed: list[str] = field(default_factory=list)
    frozen: list[str] = field(default_factory=list)


class Service:
    def __init__(self, settings: Settings | None = None, clock: Clock | None = None) -> None:
        self.settings = settings or load_settings()
        self.clock = clock or (WallClock() if self.settings.live else Clock())
        self.limits = load_limits(self.settings.limits_path)
        if self.settings.live and self.limits.swift_fee_live is not None:
            self.limits = self.limits.model_copy(update={"swift_fee": self.limits.swift_fee_live})
        # Live request ids carry a run id so a second demo run against the same
        # sandbox does not collide with the first run's request_id values.
        # Retries inside one run still reuse the same id.
        self.run_id = self.settings.run_id or (uuid.uuid4().hex[:8] if self.settings.live else "")
        # The sandbox wallet is shared and pre-funded. In live mode Ledgerline
        # plans against a ring-fenced book: live balance minus the balance seen
        # when the run started. Set LEDGERLINE_LIVE_BOOK=wallet to plan against
        # the whole wallet instead.
        self._baseline: dict[str, Decimal] | None = None
        self.adapter = build_adapter(self.settings, self.clock)
        self.audit = AuditLog(self.settings.audit_path, self.settings.db_path)
        self.reader = build_reader(self.settings)
        self.webhook = WebhookReceiver(self.settings.webhook_secret)
        self.obligations: list[Obligation] = []
        self.receipts: list[Receipt] = []
        self.plan: Plan | None = None
        self.confidence = Decimal("1")
        self.email_text = ""
        self.explanation = ""
        self.quotes: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, Approval] = {}
        self.attempts: dict[str, list[Attempt]] = {}
        self.beneficiary_ids: dict[str, str] = {}
        self.last_diff = Diff()
        self.reconciled: set[str] = set()
        self._seen_ledger: set[str] = set()
        self.policy_draft: Limits | None = None
        self.policy_preview: dict[str, str] | None = None

    def close(self) -> None:
        self.audit.close()
        close = getattr(self.adapter, "close", None)
        if close:
            close()

    def wallet(self) -> dict[str, Decimal]:
        balances = self._raw_wallet()
        if not self.settings.live or self.settings.live_book != "ringfenced":
            return balances
        if self._baseline is None:
            self._baseline = dict(balances)
            self._log(
                "contract",
                "Ring-fenced live book opened at the current sandbox balance",
                baseline={key: str(value) for key, value in balances.items()},
            )
        return {
            currency: money(balances[currency] - self._baseline.get(currency, money("0")))
            for currency in BOOK_CURRENCIES
        }

    def _raw_wallet(self) -> dict[str, Decimal]:
        balances = {currency: money("0") for currency in BOOK_CURRENCIES}
        for row in self.adapter.balances():
            currency = str(row["currency"])
            if currency in balances:
                balances[currency] = money(row["available_amount"])
        return balances

    def _rid(self, *parts: str) -> str:
        return request_id(self.run_id, *parts) if self.run_id else request_id(*parts)

    def ingest_ledger(self, rows: list[dict[str, Any]]) -> GateReport:
        report = ingest_ledger(rows, self._seen_ledger)
        for row in report.accepted:
            self._seen_ledger.add(row.event_id)
            self._log("contract", f"accepted ledger {row.event_id}", event_id=row.event_id)
        for rejected in report.rejected:
            self._log(
                "contract",
                f"quarantined {rejected['id']}: {rejected['code']}",
                rejection=rejected,
            )
        return report

    def load_obligations(self, payloads: list[dict[str, Any]]) -> GateReport:
        report = parse_obligations(payloads)
        if report.rejected:
            self._log("contract", "obligations rejected", rejected=report.rejected)
            return report
        self.obligations = list(report.accepted)
        self._log(
            "contract",
            f"{len(self.obligations)} obligations passed schema; 0 rejected",
            count=len(self.obligations),
        )
        return report

    def set_receipts(self, payloads: list[dict[str, Any]]) -> None:
        self.receipts = [Receipt.model_validate(item) for item in payloads]

    def forecast(self):
        view = build_forecast(self.wallet(), self.obligations, self.receipts, self.limits)
        if not self.email_text:
            self.confidence = view.confidence
        self._log(
            "forecast",
            f"72h confidence {self.confidence}",
            confidence=str(self.confidence),
            scores={key: str(value) for key, value in view.receipt_scores.items()},
        )
        return view

    def build_plan(self) -> Plan:
        self.plan = self._plan(version=1)
        self._log("plan", self._summary(self.plan), version=1, actions=self._action_map())
        return self.plan

    def apply_evidence(self, text: str) -> dict[str, Any]:
        self.email_text = text
        reading = self.reader.interpret(text)
        before = self.confidence
        limit_before = self.limits.fx_limit(before)
        if reading["contradicts"]:
            self.confidence = min(self.confidence, self.limits.evidence.contradiction_cap)
        limit_after = self.limits.fx_limit(self.confidence)
        self.explanation = str(reading["explanation"])
        if self.plan is not None:
            self.plan = self._plan(version=self.plan.version)
        self._log(
            "policy",
            (
                f"confidence {before} → {self.confidence} · "
                f"auto FX limit {limit_before} → {limit_after} USD"
            ),
            confidence_before=str(before),
            confidence_after=str(self.confidence),
            fx_limit_before=str(limit_before),
            fx_limit_after=str(limit_after),
            explanation=self.explanation,
            provider=reading.get("provider", "offline"),
        )
        return reading

    def deposit(self, currency: str, amount: Decimal, *, replan: bool = False) -> dict[str, Decimal]:
        before = self.wallet()
        extra: dict[str, Any] = {}
        account_id = self._deposit_account(currency)
        if account_id:
            created = self.adapter.simulate_deposit(
                {
                    "amount": str(money(amount)),
                    "global_account_id": account_id,
                    "status": "SETTLED",
                    "reference": f"seed-{currency}",
                }
            )
            extra["deposit_id"] = created.get("id")
            message = f"Simulated deposit {currency} {money(amount)}"
        elif self.settings.live:
            extra = self._fund_by_conversion(currency, money(amount))
            message = (
                f"Funded {currency} {money(amount)} with a simulated USD deposit of "
                f"{extra['usd_deposit']} and conversion {extra['conversion_id']}"
            )
        else:
            raise ExecutionError(
                "config", f"Set AIRWALLEX_GLOBAL_ACCOUNT_{currency} before simulating a deposit"
            )
        after = self._wait_for(currency, before[currency] + money(amount)) if self.settings.live else self.wallet()
        self._log(
            "deposit",
            message,
            currency=currency,
            amount=str(money(amount)),
            **extra,
        )
        if replan and self.plan is not None:
            self._replan(before, after)
        return after

    def _deposit_account(self, currency: str) -> str:
        account_id = self.settings.global_accounts.get(currency, "")
        if account_id or not self.settings.live:
            return account_id
        finder = getattr(self.adapter, "deposit_account_for", None)
        found = finder(currency) if finder else None
        if found:
            self.settings.global_accounts[currency] = found
        return found or ""

    def _fund_by_conversion(self, currency: str, amount: Decimal) -> dict[str, Any]:
        """No global account takes this currency (and the key cannot create one),
        so land a USD deposit and convert exactly the needed amount. The USD
        side of the book nets to zero."""
        usd_account = self._deposit_account("USD")
        if not usd_account:
            raise ExecutionError("config", f"No global account can receive {currency} or USD")
        usd_before = self._raw_wallet()["USD"]
        quote = self.adapter.create_quote(
            {"buy_currency": currency, "sell_currency": "USD",
             "buy_amount": str(amount), "validity": "MIN_1"}
        )
        sell = money(quote["sell_amount"])
        self.adapter.simulate_deposit(
            {"amount": str(sell), "global_account_id": usd_account,
             "status": "SETTLED", "reference": f"seed-{currency}-via-USD"}
        )
        self._wait_raw("USD", usd_before + sell)
        conversion = self.adapter.create_conversion(
            {
                "request_id": self._rid("seed", currency, str(amount)),
                "quote_id": quote["quote_id"],
                "buy_currency": currency,
                "sell_currency": "USD",
                "buy_amount": str(amount),
            }
        )
        return {
            "usd_deposit": str(sell),
            "conversion_id": str(conversion["conversion_id"]),
            "quote_id": quote["quote_id"],
        }

    def _wait_raw(self, currency: str, target: Decimal, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while self._raw_wallet()[currency] < target:
            if time.monotonic() > deadline:
                raise ExecutionError("deposit_pending", f"{currency} deposit did not settle in {timeout}s")
            time.sleep(1.0)

    def _wait_for(self, currency: str, target: Decimal, timeout: float = 30.0) -> dict[str, Decimal]:
        deadline = time.monotonic() + timeout
        while True:
            current = self.wallet()
            if current[currency] >= target:
                return current
            if time.monotonic() > deadline:
                raise ExecutionError("deposit_pending", f"{currency} deposit did not settle in {timeout}s")
            time.sleep(1.0)

    def tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return dispatch(self, name, arguments)

    def ensure_beneficiaries(self) -> None:
        for obligation in self.obligations:
            country = COUNTRY[obligation.currency]
            self.adapter.beneficiary_schema(
                {
                    "account_currency": obligation.currency,
                    "bank_country_code": country,
                    "entity_type": "COMPANY",
                    "transfer_method": obligation.method,
                }
            )
            created = self.adapter.create_beneficiary(
                {
                    "request_id": self._rid(obligation.id, "beneficiary", "1"),
                    "transfer_methods": [obligation.method],
                    "beneficiary": {
                        "entity_type": "COMPANY",
                        "company_name": obligation.counterparty,
                        "address": _ADDRESSES[country],
                        "bank_details": _bank_details(
                            obligation.counterparty, obligation.currency, obligation.method
                        ),
                    },
                }
            )
            self.beneficiary_ids[obligation.id] = str(created.get("id") or created.get("beneficiary_id"))

    def request_quote(self, obligation_id: str) -> dict[str, Any]:
        line = self._line(obligation_id)
        if line.action != "CONVERT-MIN" or line.buy_amount is None:
            raise ExecutionError("not_a_conversion", f"{obligation_id} is not a conversion")
        payload = {
            "buy_currency": line.currency,
            "sell_currency": "USD",
            "buy_amount": str(line.buy_amount),
            "validity": "MIN_1",
            "request_id": self._rid(obligation_id, "quote", "1"),
        }
        quote = self.adapter.create_quote(payload)
        self.quotes[obligation_id] = quote
        self._log(
            "quote",
            (
                f"POST /fx/quotes/create {line.sell_currency}→{line.currency} "
                f"rate {quote.get('rate', quote.get('client_rate'))} · quote {quote['quote_id']}"
            ),
            quote_id=quote["quote_id"],
            obligation_id=obligation_id,
        )
        return quote

    def open_approval(self, obligation_id: str) -> Approval:
        line = self._line(obligation_id)
        if not line.approval_required:
            raise ApprovalError("not_required", f"{obligation_id} is inside the auto limit")
        quote_id = self.quotes.get(obligation_id, {}).get("quote_id")
        if line.action == "CONVERT-MIN" and not quote_id:
            raise ApprovalError("quote_required", "Bind the quote before asking for approval")
        material = self._evidence_material(obligation_id, quote_id)
        digest = evidence_hash(material)
        current = dict(
            amount=line.amount,
            currency=line.currency,
            counterparty=line.counterparty,
            quote_id=quote_id,
            evidence_hash=digest,
        )
        existing = self._approval_for(obligation_id)
        if existing is not None:
            existing = void_if_changed(existing, **current)
            self.approvals[existing.id] = existing
            if existing.status in {"pending", "approved"} and existing.fingerprint == fingerprint(**current):
                return existing
        approval = Approval(
            id=short_id("apr", obligation_id, fingerprint(**current)[:12]),
            obligation_id=obligation_id,
            amount=line.amount,
            currency=line.currency,
            counterparty=line.counterparty,
            quote_id=quote_id,
            evidence_hash=digest,
            fingerprint=fingerprint(**current),
            allows_exception=line.action == "ESCALATE",
        )
        self.approvals[approval.id] = approval
        self._set_status(obligation_id, "awaiting_approval")
        self._log("gate", f"{line.amount} {line.currency} requires approval", approval_id=approval.id)
        return approval

    def approve(self, approval_id: str, *, approver: str) -> Approval:
        approval = self._refresh_approval(approval_id)
        if approval.status == "void":
            raise ApprovalError("void", "This approval was voided because a bound field changed")
        if approval.status != "pending":
            raise ApprovalError("not_pending", f"approval is {approval.status}")
        approval = approval.model_copy(update={"status": "approved", "approver": approver})
        self.approvals[approval.id] = approval
        self._log(
            "approved",
            (
                f"by {approver} · bound to amount, {approval.currency}, "
                f"{approval.counterparty}, {approval.quote_id}, evidence {approval.evidence_hash[:8]}"
            ),
            approval_id=approval.id,
            fingerprint=approval.fingerprint,
        )
        return approval

    def reject(self, approval_id: str, *, approver: str) -> Approval:
        approval = self.approvals[approval_id].model_copy(update={"status": "rejected", "approver": approver})
        self.approvals[approval.id] = approval
        self._set_status(approval.obligation_id, "rejected")
        self._log("rejected", f"by {approver}", approval_id=approval.id)
        return approval

    def execute(self, obligation_id: str, *, replacement: bool = False) -> Attempt:
        line = self._line(obligation_id)
        obligation = self._obligation(obligation_id)
        if line.action == "DEFER":
            raise ExecutionError("deferred", "A deferred obligation is not paid")
        if line.action == "ESCALATE":
            self._require_exception(line)
        elif line.approval_required:
            self._require_bound(line)
        if self.limits.beneficiary_must_be_verified and not obligation.beneficiary_verified:
            raise PolicyError("beneficiary_unverified", "Beneficiary must be pre-verified")
        latest = self._latest(obligation_id)
        if latest and latest.status == "in_flight":
            if replacement:
                raise ExecutionError("duplicate_lock", "A transfer for this obligation is still in flight")
            return latest
        if latest and latest.status == "paid":
            raise ExecutionError("duplicate_lock", "This obligation is already paid")
        if latest and latest.status == "cancelled" and not replacement:
            return latest
        attempt_no = 1 if latest is None or latest.status != "cancelled" else latest.attempt + 1
        conversion_id = None
        if line.action == "CONVERT-MIN":
            quote = self.quotes.get(obligation_id)
            if quote is None:
                raise ExecutionError("quote_required", "Create a quote before converting")
            self._assert_fresh(quote)
            if line.approval_required and quote["quote_id"] != self._approval_for(obligation_id).quote_id:
                raise ApprovalError("void", "quote_id changed after approval")
            conversion = self.adapter.create_conversion(
                {
                    "request_id": self._rid(obligation_id, "conversion", str(attempt_no)),
                    "quote_id": quote["quote_id"],
                    "buy_currency": quote["buy_currency"],
                    "sell_currency": quote["sell_currency"],
                    "buy_amount": str(quote["buy_amount"]),
                }
            )
            conversion_id = str(conversion["conversion_id"])
            self._log(
                "execute",
                f"POST /fx/conversions/create {conversion['request_id']} → {conversion['status']}",
                conversion_id=conversion_id,
            )
        transfer_amount = obligation.amount
        transfer = self.adapter.create_transfer(
            {
                "request_id": self._rid(obligation_id, "transfer", str(attempt_no)),
                "beneficiary_id": self.beneficiary_ids[obligation_id],
                "source_currency": obligation.currency,
                "transfer_currency": obligation.currency,
                "transfer_amount": str(transfer_amount),
                "transfer_method": obligation.method,
                "reason": "goods_purchased" if obligation.method == "SWIFT" else "bill_payment",
                "reference": obligation.id,
                "fee_paid_by": "PAYER",
            }
        )
        record = Attempt(
            obligation_id=obligation_id,
            attempt=attempt_no,
            request_id=str(transfer["request_id"]),
            transfer_id=str(transfer["id"]),
            conversion_id=conversion_id,
            status=_attempt_status(str(transfer["status"])),
            amount=money(transfer["amount_payer_pays"]),
            currency=obligation.currency,
        )
        self.attempts.setdefault(obligation_id, []).append(record)
        self._set_status(obligation_id, record.status)
        self._log(
            "execute",
            f"POST /transfers/create {obligation.method} {record.request_id} → {transfer['status']}",
            transfer_id=record.transfer_id,
            request_id=record.request_id,
            attempt=attempt_no,
        )
        return record

    def poll(self, transfer_id: str) -> dict[str, Any]:
        transfer = self.adapter.get_transfer(transfer_id)
        transfer["terminal"] = str(transfer["status"]) in TERMINAL_OK | TERMINAL_FAIL
        return transfer

    def transition(self, transfer_id: str, next_status: str, failure_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"next_status": next_status}
        if failure_type:
            payload["failure_type"] = failure_type
        transfer = self.adapter.simulate_transfer_transition(transfer_id, payload)
        self._sync(transfer)
        self._log(
            "transition",
            f"{transfer_id} → {transfer['status']}",
            transfer_id=transfer_id,
            status=transfer["status"],
            failure_type=transfer.get("failure_type"),
        )
        return transfer

    def emit_webhook(self, transfer: dict[str, Any], name: str) -> dict[str, Any]:
        """Sign and feed a transfer event through the same receiver as real
        deliveries. In live mode this is a local echo of the transfer the host
        returned; real Airwallex deliveries arrive at POST /webhooks/airwallex."""
        if not self.settings.webhook_secret:
            self._log("webhook", f"{name} · local echo skipped: AIRWALLEX_WEBHOOK_SECRET is not set",
                      name=name, transfer_id=transfer["id"])
            return {"status": 0, "code": "no_secret", "duplicate": False}
        event = {
            "id": short_id("evt", self.run_id, transfer["id"], name, str(transfer["status"])),
            "name": name,
            "account_id": "acct_local_echo" if self.settings.live else "acct_mock",
            "created_at": self.clock.iso(),
            "data": {
                "id": transfer["id"],
                "status": transfer["status"],
                "request_id": transfer.get("request_id"),
                "failure_type": transfer.get("failure_type"),
            },
        }
        raw = dumps(event).encode("utf-8")
        timestamp = str(int(self.clock.now().timestamp() * 1000))
        signature = sign(self.settings.webhook_secret, timestamp, raw)
        result = self.receive_webhook(raw, timestamp, signature)
        return result

    def receive_webhook(
        self, raw_body: bytes, timestamp: str, signature: str, *, now_ms: int | None = None
    ) -> dict[str, Any]:
        # Real HTTP deliveries pass wall-clock now_ms. The mock console runs on a
        # fixed demo clock, which would mark every real delivery stale.
        if now_ms is None:
            now_ms = int(self.clock.now().timestamp() * 1000)
        result = self.webhook.receive(raw_body, timestamp, signature, now_ms=now_ms)
        if result["status"] == 200 and not result.get("duplicate"):
            self._reconcile()
        return result

    def reserves_hold(self) -> bool:
        balances = self.wallet()
        return all(balances.get(currency, money("0")) >= floor for currency, floor in self.limits.reserve_floor.items())

    def replay(self) -> list[dict[str, Any]]:
        return self.audit.replay()

    def _replan(self, before: dict[str, Decimal], after: dict[str, Decimal]) -> Diff:
        assert self.plan is not None
        selected = affected_ids(self.obligations, self.plan, before, after)
        fresh = allocate(self.obligations, after, self.confidence, self.limits)
        merged, changes, recomputed = merge(self.plan, fresh, selected)
        self.plan = self.plan.model_copy(
            update={
                "version": self.plan.version + 1,
                "lines": merged,
                "created_at": self.clock.now(),
                "confidence": self.confidence,
                "fx_limit": self.limits.fx_limit(self.confidence),
            }
        )
        frozen = [line.obligation_id for line in self.plan.lines if line.obligation_id not in recomputed]
        self.last_diff = Diff(changes=changes, recomputed=recomputed, frozen=frozen)
        described = ", ".join(
            f"{item['obligation_id']} {item['before']}→{item['after']}" for item in changes
        ) or "none"
        self._log(
            "replan",
            f"Recomputed {len(recomputed)}; changes: {described}",
            changes=changes,
            recomputed=recomputed,
            frozen=frozen,
        )
        return self.last_diff

    def _plan(self, version: int) -> Plan:
        lines = allocate(self.obligations, self.wallet(), self.confidence, self.limits)
        return Plan(
            version=version,
            confidence=self.confidence,
            fx_limit=self.limits.fx_limit(self.confidence),
            lines=lines,
            created_at=self.clock.now(),
        )

    def _require_bound(self, line) -> Approval:
        approval = self._approval_for(line.obligation_id)
        if approval is None:
            raise ApprovalError("approval_required", f"{line.obligation_id} is over the auto limit")
        current = self._binding_kwargs(line)
        refreshed = void_if_changed(approval, **current)
        self.approvals[refreshed.id] = refreshed
        if not bound_to(refreshed, **current):
            raise ApprovalError("void", "Approval does not match amount, currency, counterparty, quote_id, or evidence")
        return refreshed

    def _require_exception(self, line) -> Approval:
        approval = self._require_bound(line)
        if not approval.allows_exception:
            raise ApprovalError("exception_required", "Payroll needs an exception approval")
        return approval

    def _binding_kwargs(self, line) -> dict[str, Any]:
        quote_id = self.quotes.get(line.obligation_id, {}).get("quote_id")
        if line.action != "CONVERT-MIN":
            existing = self._approval_for(line.obligation_id)
            quote_id = existing.quote_id if existing else None
        digest = evidence_hash(self._evidence_material(line.obligation_id, quote_id))
        return dict(
            amount=line.amount,
            currency=line.currency,
            counterparty=line.counterparty,
            quote_id=quote_id,
            evidence_hash=digest,
        )

    def _evidence_material(self, obligation_id: str, quote_id: str | None) -> dict[str, Any]:
        return {
            "obligation_id": obligation_id,
            "email": self.email_text,
            "confidence": str(self.confidence),
            "quote_id": quote_id,
            "plan_version": self.plan.version if self.plan else 0,
        }

    def _assert_fresh(self, quote: dict[str, Any]) -> None:
        opened = parse_airwallex_time(str(quote["valid_from_at"]))
        expires = parse_airwallex_time(str(quote["valid_to_at"]))
        now = self.clock.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age = (now - opened).total_seconds()
        if age > self.limits.max_quote_age_seconds or now > expires:
            raise PolicyError("quote_stale", "Quote is older than the policy maximum")

    def _reconcile(self) -> None:
        for event in self.webhook.ordered():
            event_id = str(event["id"])
            if event_id in self.reconciled:
                continue
            self.reconciled.add(event_id)
            data = event.get("data") or {}
            # Airwallex deliveries wrap the resource in data.object.
            if isinstance(data.get("object"), dict):
                data = data["object"]
            transfer_id = str(data.get("id") or "")
            name = str(event.get("name") or "")
            matched = any(
                attempt.transfer_id == transfer_id
                for attempts in self.attempts.values()
                for attempt in attempts
            )
            if transfer_id and hasattr(self.adapter, "transfers") and transfer_id in self.adapter.transfers:
                self._sync(self.adapter.get_transfer(transfer_id))
            elif transfer_id and matched and self.settings.live:
                self._sync(self.adapter.get_transfer(transfer_id))
            self._log(
                "webhook",
                f"{name} · signature ok · deduped · {'reconciled' if matched else 'unmatched'}",
                event_id=event_id,
                name=name,
                transfer_id=transfer_id,
                matched=matched,
                created_at=event.get("created_at"),
            )

    def _sync(self, transfer: dict[str, Any]) -> None:
        status = _attempt_status(str(transfer["status"]))
        for attempts in self.attempts.values():
            for attempt in attempts:
                if attempt.transfer_id == transfer["id"]:
                    attempt.status = status
                    self._set_status(attempt.obligation_id, status)

    def _set_status(self, obligation_id: str, status: str) -> None:
        if self.plan is None:
            return
        lines = []
        for line in self.plan.lines:
            if line.obligation_id == obligation_id:
                lines.append(line.model_copy(update={"status": status}))
            else:
                lines.append(line)
        self.plan = self.plan.model_copy(update={"lines": lines})

    def _latest(self, obligation_id: str) -> Attempt | None:
        rows = self.attempts.get(obligation_id) or []
        return rows[-1] if rows else None

    def _approval_for(self, obligation_id: str) -> Approval | None:
        found = [item for item in self.approvals.values() if item.obligation_id == obligation_id]
        if not found:
            return None
        return found[-1]

    def _refresh_approval(self, approval_id: str) -> Approval:
        approval = self.approvals[approval_id]
        line = self._line(approval.obligation_id)
        current = self._binding_kwargs(line)
        refreshed = void_if_changed(approval, **current)
        self.approvals[approval.id] = refreshed
        return refreshed

    def _line(self, obligation_id: str):
        if self.plan is None:
            raise ExecutionError("no_plan", "Build a plan first")
        return self.plan.by_id(obligation_id)

    def _obligation(self, obligation_id: str) -> Obligation:
        for obligation in self.obligations:
            if obligation.id == obligation_id:
                return obligation
        raise KeyError(obligation_id)

    def _action_map(self) -> dict[str, str]:
        if self.plan is None:
            return {}
        return {line.obligation_id: line.action for line in self.plan.lines}

    def _summary(self, plan: Plan) -> str:
        parts = [f"{line.action} {line.obligation_id.removeprefix('obl_')}" for line in plan.lines]
        return " · ".join(parts)

    def _log(self, kind: str, message: str, **payload: Any) -> None:
        self.audit.append(kind, message, ts=self.clock.iso(), **payload)

    def dry_run(self, draft: Limits) -> int:
        if not self.obligations:
            return 0
        current = {line.obligation_id: line for line in (self.plan.lines if self.plan else [])}
        proposed = allocate(self.obligations, self.wallet(), self.confidence, draft)
        stricter = 0
        for line in proposed:
            old = current.get(line.obligation_id)
            if old is None:
                continue
            if _rank(line) > _rank(old):
                stricter += 1
        return stricter


    def preview_limit(self, name: str, raw: str) -> dict[str, str]:
        if name not in {
            "fx_auto_limit_high_conf",
            "fx_auto_limit_low_conf",
            "auto_transfer_limit",
            "confidence_threshold",
        }:
            raise PolicyError("unknown_limit", f"{name} cannot be edited here")
        data = self.limits.model_dump()
        data[name] = raw
        draft = Limits.model_validate(data)
        before = getattr(self.limits, name)
        self.policy_draft = draft
        preview = {
            "name": name,
            "before": f"{before}",
            "after": f"{getattr(draft, name)}",
            "stricter": str(self.dry_run(draft)),
        }
        self.policy_preview = preview
        return preview

    def apply_draft(self) -> None:
        if self.policy_draft is None:
            raise PolicyError("no_draft", "There is no pending limit change")
        self.limits = self.policy_draft
        self.policy_draft = None
        self.policy_preview = None
        if self.obligations:
            version = self.plan.version if self.plan else 1
            self.plan = self._plan(version=version)
        self._log("policy", "approved a limit change", version=self.limits.version)

    def discard_draft(self) -> None:
        self.policy_draft = None
        self.policy_preview = None


def _attempt_status(transfer_status: str) -> str:
    if transfer_status in TERMINAL_OK:
        return "paid"
    if transfer_status in TERMINAL_FAIL:
        return "cancelled"
    return "in_flight"


def _rank(line) -> int:
    if line.action == "ESCALATE":
        return 3
    if line.approval_required:
        return 2
    if line.action == "DEFER":
        return 1
    return 0
