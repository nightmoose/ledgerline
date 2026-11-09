"""In-memory Airwallex sandbox.

Mimics the documented behavior the demo and tests rely on: major units,
single-use quotes, request_id idempotency, duplicate_request_id when the
same id is reused for a different body, a flat EUR 12.85 SWIFT fee, free
LOCAL payouts, and a failed transfer ending CANCELLED with failure_type.
SENT stays in flight. Conversions settle immediately.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from ledgerline.adapters.base import AirwallexError
from ledgerline.adapters.paging import page_slice
from ledgerline.clock import Clock
from ledgerline.fxmath import EUR_PER_USD, USD_PER_GBP, client_rate
from ledgerline.jsonutil import dumps
from ledgerline.money import D, money

SWIFT_FEE = money("12.85")
SWIFT_FEE_CURRENCY = "EUR"


class MockAirwallex:
    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self._balances: dict[str, Decimal] = {"USD": D("0"), "EUR": D("0"), "GBP": D("0")}
        self.global_accounts: dict[str, str] = {}
        self.quotes: dict[str, dict[str, Any]] = {}
        self.conversions: dict[str, dict[str, Any]] = {}
        self.beneficiaries: dict[str, dict[str, Any]] = {}
        self.transfers: dict[str, dict[str, Any]] = {}
        self.deposits: dict[str, dict[str, Any]] = {}
        self._idem: dict[str, tuple[str, dict[str, Any]]] = {}

    def register_global_account(self, account_id: str, currency: str) -> None:
        self.global_accounts[account_id] = currency
        self._balances.setdefault(currency, D("0"))

    def balances_current(self) -> list[dict[str, Any]]:
        return self.balances()

    def balances(self) -> list[dict[str, Any]]:
        rows = []
        for currency in sorted(self._balances):
            amount = money(self._balances[currency])
            rows.append(
                {
                    "currency": currency,
                    "available_amount": amount,
                    "pending_amount": money("0"),
                    "reserved_amount": money("0"),
                    "total_amount": amount,
                    "prepayment_amount": money("0"),
                    "account_type": "WALLET",
                }
            )
        return rows

    def fx_rate(
        self,
        *,
        buy_currency: str,
        sell_currency: str,
        buy_amount: Decimal | None = None,
        sell_amount: Decimal | None = None,
    ) -> dict[str, Any]:
        if (buy_amount is None) == (sell_amount is None):
            raise AirwallexError(
                "field_required",
                "Specify exactly one of buy_amount or sell_amount",
                source="amount",
            )
        pair_rate = self._buy_per_sell(buy_currency, sell_currency)
        if buy_amount is not None:
            buy = money(buy_amount)
            sell = money(D(buy) / pair_rate)
        else:
            sell = money(sell_amount)
            buy = money(D(sell) * pair_rate)
        dealt = buy_currency if buy_amount is not None else sell_currency
        pair = client_rate(buy, sell)
        return {
            "buy_currency": buy_currency,
            "sell_currency": sell_currency,
            "currency_pair": f"{sell_currency}{buy_currency}",
            "dealt_currency": dealt,
            "rate": pair,
            "rate_details": [
                {
                    "buy_amount": buy,
                    "sell_amount": sell,
                    "level": "CLIENT",
                    "rate": pair,
                }
            ],
            "conversion_date": self.clock.now().strftime("%Y-%m-%d"),
            "created_at": self.clock.iso(),
            "buy_amount": buy,
            "sell_amount": sell,
            "client_rate": pair,
        }

    def create_quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(payload, "buy_currency", "sell_currency")
        if (payload.get("buy_amount") is None) == (payload.get("sell_amount") is None):
            raise AirwallexError(
                "field_required",
                "Specify exactly one of buy_amount or sell_amount",
                source="amount",
            )
        request_key = payload.get("request_id")
        if request_key:
            cached = self._idempotent(str(request_key), payload)
            if cached is not None:
                return cached
        rate_quote = self.fx_rate(
            buy_currency=payload["buy_currency"],
            sell_currency=payload["sell_currency"],
            buy_amount=D(payload["buy_amount"]) if payload.get("buy_amount") is not None else None,
            sell_amount=D(payload["sell_amount"]) if payload.get("sell_amount") is not None else None,
        )
        validity = str(payload.get("validity") or "MIN_1")
        seconds = _validity_seconds(validity)
        now = self.clock.now()
        quote_id = f"q_{uuid.uuid4().hex[:8]}"
        if request_key:
            quote_id = f"q_{uuid.uuid5(_as_uuid(str(request_key)), 'quote').hex[:8]}"
        quote = {
            "quote_id": quote_id,
            "buy_currency": payload["buy_currency"],
            "sell_currency": payload["sell_currency"],
            "buy_amount": rate_quote["buy_amount"],
            "sell_amount": rate_quote["sell_amount"],
            "client_rate": rate_quote["client_rate"],
            "rate": rate_quote["rate"],
            "currency_pair": rate_quote["currency_pair"],
            "dealt_currency": rate_quote["dealt_currency"],
            "usage": "SINGLE_USE",
            "validity": validity,
            "valid_from_at": now.strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "valid_to_at": (now + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "used": False,
            "request_id": request_key,
        }
        self.quotes[quote_id] = quote
        if request_key:
            self._remember(str(request_key), payload, quote)
        return dict(quote)

    def get_quote(self, quote_id: str) -> dict[str, Any]:
        quote = self.quotes.get(quote_id)
        if quote is None:
            raise AirwallexError("not_found", f"quote {quote_id} not found", status=404, source="quote_id")
        return dict(quote)

    def create_conversion(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(payload, "request_id", "quote_id", "buy_currency", "sell_currency")
        cached = self._idempotent(str(payload["request_id"]), payload)
        if cached is not None:
            return cached
        quote = self.quotes.get(str(payload["quote_id"]))
        if quote is None:
            raise AirwallexError("invalid_argument", "Unknown quote_id", source="quote_id")
        if quote["used"]:
            raise AirwallexError(
                "invalid_argument",
                "Quote is single-use and has already been used",
                source="quote_id",
            )
        if self.clock.now() > _parse(quote["valid_to_at"]):
            raise AirwallexError("invalid_argument", "Quote has expired", source="quote_id")
        if payload["buy_currency"] != quote["buy_currency"] or payload["sell_currency"] != quote["sell_currency"]:
            raise AirwallexError("invalid_argument", "Conversion currencies do not match the quote", source="quote_id")
        buy_amount = money(payload.get("buy_amount", quote["buy_amount"]))
        if buy_amount != money(quote["buy_amount"]):
            raise AirwallexError("invalid_argument", "buy_amount does not match the quote", source="buy_amount")
        sell_amount = money(quote["sell_amount"])
        self._debit(quote["sell_currency"], sell_amount)
        self._balances[quote["buy_currency"]] = money(self._balances.get(quote["buy_currency"], 0) + buy_amount)
        quote["used"] = True
        conversion_id = str(uuid.uuid5(_as_uuid(str(payload["request_id"])), "conversion"))
        conversion = {
            "conversion_id": conversion_id,
            "quote_id": quote["quote_id"],
            "buy_currency": quote["buy_currency"],
            "sell_currency": quote["sell_currency"],
            "buy_amount": buy_amount,
            "sell_amount": sell_amount,
            "client_rate": quote["client_rate"],
            "currency_pair": quote["currency_pair"],
            "status": "SETTLED",
            "request_id": payload["request_id"],
            "created_at": self.clock.iso(),
        }
        self.conversions[conversion_id] = conversion
        self._remember(str(payload["request_id"]), payload, conversion)
        return dict(conversion)

    def beneficiary_schema(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload.get("transfer_method", "LOCAL")
        fields = ["account_name", "account_currency", "bank_country_code"]
        if method == "SWIFT":
            fields.append("swift_code")
        else:
            fields.append("account_number")
        return {
            "condition": payload,
            "fields": [{"key": name, "required": True} for name in fields],
            "transfer_method": method,
        }

    def create_beneficiary(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(payload, "request_id", "beneficiary")
        cached = self._idempotent(str(payload["request_id"]), payload)
        if cached is not None:
            return cached
        beneficiary_id = str(uuid.uuid5(_as_uuid(str(payload["request_id"])), "beneficiary"))
        record = {
            "id": beneficiary_id,
            "beneficiary": payload["beneficiary"],
            "transfer_methods": payload.get("transfer_methods") or [],
            "request_id": payload["request_id"],
        }
        self.beneficiaries[beneficiary_id] = record
        self._remember(str(payload["request_id"]), payload, record)
        return dict(record)

    def create_transfer(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(
            payload,
            "request_id",
            "beneficiary_id",
            "source_currency",
            "transfer_currency",
            "transfer_amount",
            "transfer_method",
        )
        cached = self._idempotent(str(payload["request_id"]), payload)
        if cached is not None:
            return cached
        if payload["beneficiary_id"] not in self.beneficiaries:
            raise AirwallexError("invalid_argument", "Unknown beneficiary_id", source="beneficiary_id")
        method = payload["transfer_method"]
        if method not in {"LOCAL", "SWIFT"}:
            raise AirwallexError("invalid_argument", "transfer_method must be LOCAL or SWIFT", source="transfer_method")
        transfer_amount = money(payload["transfer_amount"])
        if transfer_amount <= 0:
            raise AirwallexError("invalid_argument", "transfer_amount must be positive", source="transfer_amount")
        fee_amount = SWIFT_FEE if method == "SWIFT" else money("0")
        fee_currency = SWIFT_FEE_CURRENCY if method == "SWIFT" else payload["source_currency"]
        fee_paid_by = payload.get("fee_paid_by", "PAYER")
        source_currency = payload["source_currency"]
        transfer_currency = payload["transfer_currency"]
        if source_currency != transfer_currency:
            raise AirwallexError(
                "invalid_argument",
                "Mock transfers are same-currency; convert first",
                source="source_currency",
            )
        if fee_paid_by == "PAYER" and fee_currency == source_currency:
            payer_pays = money(transfer_amount + fee_amount)
            beneficiary_receives = transfer_amount
        elif fee_paid_by == "PAYER":
            payer_pays = transfer_amount
            beneficiary_receives = transfer_amount
        else:
            payer_pays = transfer_amount
            if fee_currency == transfer_currency:
                beneficiary_receives = money(transfer_amount - fee_amount)
            else:
                beneficiary_receives = transfer_amount
        self._debit(source_currency, payer_pays)
        if fee_amount and fee_currency != source_currency and fee_paid_by == "PAYER":
            self._debit(fee_currency, fee_amount)
        transfer_id = str(uuid.uuid5(_as_uuid(str(payload["request_id"])), "transfer"))
        transfer = {
            "id": transfer_id,
            "request_id": payload["request_id"],
            "beneficiary_id": payload["beneficiary_id"],
            "source_currency": source_currency,
            "transfer_currency": transfer_currency,
            "transfer_amount": transfer_amount,
            "source_amount": payer_pays,
            "amount_payer_pays": payer_pays,
            "amount_beneficiary_receives": beneficiary_receives,
            "fee_amount": fee_amount,
            "fee_currency": fee_currency,
            "fee_paid_by": fee_paid_by,
            "transfer_method": method,
            "reason": payload.get("reason", ""),
            "reference": payload.get("reference", ""),
            "status": "PROCESSING",
            "failure_type": None,
            "failure_reason": None,
            "created_at": self.clock.iso(),
            "refunded": False,
        }
        self.transfers[transfer_id] = transfer
        self._remember(str(payload["request_id"]), payload, transfer)
        return dict(transfer)

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        transfer = self.transfers.get(transfer_id)
        if transfer is None:
            raise AirwallexError("not_found", f"transfer {transfer_id} not found", status=404, source="id")
        return dict(transfer)

    def list_transfers(
        self, *, page_size: int = 10, request_id: str | None = None
    ) -> dict[str, Any]:
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise AirwallexError(
                "invalid_argument",
                "page_size must be a positive integer",
                status=400,
                source="page_size",
            )
        items = list(self.transfers.values())
        if request_id:
            items = [item for item in items if item["request_id"] == request_id]
        return {"items": [dict(item) for item in items[:page_size]]}

    def list_beneficiaries(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        items = [dict(item) for item in self.beneficiaries.values()]
        return page_slice(items, page_num, page_size)

    def list_global_accounts(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        items = [
            {"id": account_id, "currency": currency, "status": "ACTIVE"}
            for account_id, currency in sorted(self.global_accounts.items())
        ]
        return page_slice(items, page_num, page_size)

    def list_conversions(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        items = [dict(item) for item in self.conversions.values()]
        return page_slice(items, page_num, page_size)

    def list_deposits(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        items = [dict(item) for item in self.deposits.values()]
        return page_slice(items, page_num, page_size, total_count=True)

    def simulate_deposit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require(payload, "amount", "global_account_id")
        account_id = str(payload["global_account_id"])
        currency = self.global_accounts.get(account_id)
        if currency is None:
            raise AirwallexError("invalid_argument", "Unknown global_account_id", source="global_account_id")
        amount = money(payload["amount"])
        if amount <= 0:
            raise AirwallexError("invalid_argument", "amount must be positive", source="amount")
        status = str(payload.get("status") or "SETTLED")
        if status not in {"PENDING", "REJECTED", "SETTLED"}:
            raise AirwallexError("invalid_argument", "Unsupported deposit status", source="status")
        if status == "SETTLED":
            self._balances[currency] = money(self._balances.get(currency, 0) + amount)
        deposit_id = str(uuid.uuid4())
        deposit = {
            "id": deposit_id,
            "amount": amount,
            "currency": currency,
            "status": status,
            "deposit_type": "CREDIT",
            "global_account_id": account_id,
            "payer_name": payload.get("payer_name", ""),
            "reference": payload.get("reference", ""),
            "create_time": self.clock.iso(),
        }
        self.deposits[deposit_id] = deposit
        return dict(deposit)

    def simulate_transfer_transition(self, transfer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        transfer = self.transfers.get(transfer_id)
        if transfer is None:
            raise AirwallexError("not_found", f"transfer {transfer_id} not found", status=404, source="id")
        next_status = str(payload.get("next_status") or "")
        allowed = {
            "PROCESSING": {"SENT", "PAID", "FAILED", "CANCELLED"},
            "SENT": {"PAID", "FAILED", "CANCELLED"},
            "PAID": set(),
            "CANCELLED": set(),
        }
        current = transfer["status"]
        if next_status not in {"PROCESSING", "SENT", "PAID", "FAILED", "CANCELLED"}:
            raise AirwallexError("invalid_argument", "invalid next status", source="next_status")
        if next_status not in allowed.get(current, set()):
            raise AirwallexError(
                "invalid_argument",
                f"cannot transition {current} to {next_status}",
                source="next_status",
            )
        if next_status == "FAILED":
            failure_type = payload.get("failure_type")
            if not failure_type:
                raise AirwallexError(
                    "field_required",
                    "failure_type is required when next_status is FAILED",
                    source="failure_type",
                )
            transfer["status"] = "CANCELLED"
            transfer["failure_type"] = failure_type
            transfer["failure_reason"] = failure_type
            self._refund(transfer)
        elif next_status == "CANCELLED":
            transfer["status"] = "CANCELLED"
            self._refund(transfer)
        else:
            transfer["status"] = next_status
        return dict(transfer)

    def _buy_per_sell(self, buy: str, sell: str) -> Decimal:
        usd_value = {"USD": D("1"), "EUR": D("1") / EUR_PER_USD, "GBP": USD_PER_GBP}
        if buy not in usd_value or sell not in usd_value:
            raise AirwallexError("unsupported_currency", f"unsupported pair {sell}/{buy}", source="currency")
        return usd_value[sell] / usd_value[buy]

    def _debit(self, currency: str, amount: Decimal) -> None:
        available = money(self._balances.get(currency, 0))
        needed = money(amount)
        if available < needed:
            raise AirwallexError(
                "balance_insufficient",
                f"Insufficient {currency} balance",
                source="transfer",
            )
        self._balances[currency] = money(available - needed)

    def _refund(self, transfer: dict[str, Any]) -> None:
        if transfer["refunded"]:
            return
        currency = transfer["source_currency"]
        self._balances[currency] = money(self._balances.get(currency, 0) + transfer["amount_payer_pays"])
        if (
            transfer["fee_amount"]
            and transfer["fee_currency"] != currency
            and transfer["fee_paid_by"] == "PAYER"
        ):
            fee_currency = transfer["fee_currency"]
            self._balances[fee_currency] = money(self._balances.get(fee_currency, 0) + transfer["fee_amount"])
        transfer["refunded"] = True

    def _idempotent(self, request_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        digest = _digest(payload)
        previous = self._idem.get(request_id)
        if previous is None:
            return None
        previous_digest, response = previous
        if previous_digest != digest:
            raise AirwallexError(
                "duplicate_request_id",
                (
                    f"The request ID {request_id} has already been used. "
                    "Use a different request_id for a different operation."
                ),
                source="request_id",
                details={
                    "id": response.get("id") or response.get("conversion_id") or response.get("quote_id"),
                    "request_id": request_id,
                },
            )
        return dict(response)

    def _remember(self, request_id: str, payload: dict[str, Any], response: dict[str, Any]) -> None:
        self._idem[request_id] = (_digest(payload), response)

    @staticmethod
    def _require(payload: dict[str, Any], *fields: str) -> None:
        missing = [field for field in fields if payload.get(field) in (None, "")]
        if missing:
            raise AirwallexError("field_required", f"missing {', '.join(missing)}", source=missing[0])


def _as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, value)


def _digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "request_id"}
    return hashlib.sha256(dumps(body).encode("utf-8")).hexdigest()


def _validity_seconds(validity: str) -> int:
    table = {
        "MIN_1": 60,
        "MIN_15": 15 * 60,
        "MIN_30": 30 * 60,
        "HR_1": 3600,
        "HR_4": 4 * 3600,
        "HR_8": 8 * 3600,
        "HR_24": 24 * 3600,
    }
    if validity not in table:
        raise AirwallexError("invalid_argument", "unsupported quote validity", source="validity")
    return table[validity]


def _parse(value: str):
    from ledgerline.adapters.live import parse_airwallex_time

    return parse_airwallex_time(value)
