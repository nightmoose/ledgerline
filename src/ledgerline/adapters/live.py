"""Airwallex REST client.

Login is POST /api/v1/authentication/login with x-client-id and x-api-key.
A 201 body carries token and expires_at. The token is reused until shortly
before expires_at (about 30 minutes when the server follows the published
lifetime). FX calls do not send x-api-version.

A 401 of {"code":"unauthorized","message":"Insufficient permissions"} means
the key is missing a scope. That is raised as insufficient_permissions, not
as a bad client id or api key.

Observed list and read shapes on the demo host:
- GET /balances/current is a JSON array. Each row has currency,
  available_amount, pending_amount, reserved_amount, total_amount,
  prepayment_amount, and account_type.
- GET /fx/rates/current returns rate (not client_rate), rate_details,
  currency_pair, dealt_currency, buy_currency, conversion_date, created_at.
- GET /transfers?page_size=N returns {items: [...]}.
- GET beneficiaries, global_accounts, fx/conversions, and deposits require
  page_num (0-based) and page_size >= 10. They return {has_more, items}.
  Deposits also return total_count.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from ledgerline.adapters.base import AirwallexError
from ledgerline.adapters.paging import expect_items, expect_page, require_page
from ledgerline.clock import Clock
from ledgerline.jsonutil import loads, wire_dumps

_REFRESH_SKEW = timedelta(seconds=60)
_DEFAULT_TOKEN_TTL = timedelta(minutes=30)


def parse_airwallex_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":":
        text = text[:-2] + ":" + text[-2:]
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class LiveAirwallex:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        api_key: str,
        clock: Clock | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not client_id or not api_key:
            raise AirwallexError(
                "config",
                "AIRWALLEX_CLIENT_ID and AIRWALLEX_API_KEY are required for live mode",
                status=500,
                source="config",
                kind="request",
            )
        self.base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._api_key = api_key
        self._clock = clock or Clock(datetime.now(UTC))
        self._http = httpx.Client(transport=transport, timeout=timeout)
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._global_times: deque[float] = deque()
        self._endpoint_times: dict[str, deque[float]] = defaultdict(deque)

    def close(self) -> None:
        self._http.close()

    def balances(self) -> list[dict[str, Any]]:
        body = self._request("GET", "/api/v1/balances/current")
        if not isinstance(body, list):
            raise AirwallexError(
                "invalid_response",
                "GET /balances/current did not return a JSON array",
                status=502,
                source="/api/v1/balances/current",
            )
        return body

    def fx_rate(
        self,
        *,
        buy_currency: str,
        sell_currency: str,
        buy_amount: Decimal | None = None,
        sell_amount: Decimal | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "buy_currency": buy_currency,
            "sell_currency": sell_currency,
        }
        if buy_amount is not None:
            params["buy_amount"] = format(buy_amount, "f")
        if sell_amount is not None:
            params["sell_amount"] = format(sell_amount, "f")
        return self._request("GET", "/api/v1/fx/rates/current", params=params)

    def create_quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Documented quote fields only. request_id is not part of this call.
        body = {
            "buy_currency": payload["buy_currency"],
            "sell_currency": payload["sell_currency"],
            "validity": payload.get("validity", "MIN_1"),
        }
        if payload.get("buy_amount") is not None:
            body["buy_amount"] = payload["buy_amount"]
        if payload.get("sell_amount") is not None:
            body["sell_amount"] = payload["sell_amount"]
        return self._request("POST", "/api/v1/fx/quotes/create", json_body=body)

    def get_quote(self, quote_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/fx/quotes/{quote_id}")

    def create_conversion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/fx/conversions/create", json_body=payload)

    def beneficiary_schema(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/beneficiaries/schema", json_body=payload)

    def create_beneficiary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/beneficiaries/create", json_body=payload)

    def create_transfer(self, payload: dict[str, Any]) -> dict[str, Any]:
        # The live host answers a retried request_id with 400 duplicate_request_id
        # even when the body is identical. Look the original up so a retry
        # returns it, as the mock does. A different body still raises.
        try:
            return self._request("POST", "/api/v1/transfers/create", json_body=payload)
        except AirwallexError as exc:
            if exc.code != "duplicate_request_id" or not payload.get("request_id"):
                raise
            found = self.list_transfers(page_size=10, request_id=str(payload["request_id"]))
            for item in found.get("items", []):
                same = (
                    item.get("request_id") == payload["request_id"]
                    and str(item.get("beneficiary_id")) == str(payload.get("beneficiary_id"))
                    and Decimal(str(item.get("transfer_amount")))
                    == Decimal(str(payload.get("transfer_amount")))
                )
                if same:
                    return self.get_transfer(str(item["id"]))
            raise

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/transfers/{transfer_id}")

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
        params: dict[str, Any] = {"page_size": page_size}
        if request_id:
            params["request_id"] = request_id
        body = self._request("GET", "/api/v1/transfers", params=params)
        return expect_items(body, path="/api/v1/transfers")

    def list_beneficiaries(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        return self._paged("/api/v1/beneficiaries", page_num=page_num, page_size=page_size)

    def list_global_accounts(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        return self._paged(
            "/api/v1/global_accounts",
            page_num=page_num,
            page_size=page_size,
            has_more_optional=True,
        )

    def list_conversions(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        return self._paged("/api/v1/fx/conversions", page_num=page_num, page_size=page_size)

    def list_deposits(self, *, page_num: int = 0, page_size: int = 10) -> dict[str, Any]:
        return self._paged(
            "/api/v1/deposits",
            page_num=page_num,
            page_size=page_size,
            total_count=True,
        )

    def _paged(
        self,
        path: str,
        *,
        page_num: int,
        page_size: int,
        total_count: bool = False,
        has_more_optional: bool = False,
    ) -> dict[str, Any]:
        params = require_page(page_num, page_size)
        body = self._request("GET", path, params=params)
        return expect_page(
            body, path=path, total_count=total_count, has_more_optional=has_more_optional
        )

    def simulate_deposit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/simulation/deposit/create", json_body=payload)

    def simulate_transfer_transition(
        self, transfer_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        # Observed on the demo host: a new transfer is SCHEDULED, and moving it
        # straight to PROCESSING or PAID returns 500 operation_failed. SENT is
        # accepted from SCHEDULED, and PAID or FAILED are accepted from SENT.
        path = f"/api/v1/simulation/transfers/{transfer_id}/transition"
        target = str(payload.get("next_status", ""))
        if target in {"PAID", "FAILED"}:
            current = str(self.get_transfer(transfer_id).get("status", ""))
            if current in {"SCHEDULED", "OVERDUE", "PROCESSING"}:
                self._request("POST", path, json_body={"next_status": "SENT"})
        return self._request("POST", path, json_body=payload)

    def deposit_account_for(self, currency: str) -> str | None:
        """First ACTIVE global account that takes deposits in this currency."""
        page = 0
        while True:
            body = self.list_global_accounts(page_num=page, page_size=50)
            for item in body.get("items", []):
                if item.get("status") != "ACTIVE":
                    continue
                for feature in item.get("supported_features") or []:
                    if feature.get("currency") == currency and feature.get("type") == "DEPOSIT":
                        return str(item["id"])
            if not body.get("has_more"):
                return None
            page += 1

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        self._pace(path)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._bearer()}"
        # x-api-version is intentionally omitted. FX calls reject it, and the
        # rest of this client stays on the account's default version.
        response = self._http.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            content=wire_dumps(json_body) if json_body is not None else None,
            params=params,
        )
        return self._decode(response)

    def _bearer(self) -> str:
        now = self._clock.now()
        if self._token and self._expires_at and now < self._expires_at - _REFRESH_SKEW:
            return self._token
        self._login()
        assert self._token is not None
        return self._token

    def _login(self) -> None:
        self._pace("/api/v1/authentication/login")
        response = self._http.post(
            f"{self.base_url}/api/v1/authentication/login",
            headers={
                "Content-Type": "application/json",
                "x-client-id": self._client_id,
                "x-api-key": self._api_key,
            },
        )
        body = self._decode(response)
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            raise AirwallexError(
                "credentials_invalid",
                "Login did not return a token",
                status=response.status_code,
                source="authentication",
                kind="authentication",
            )
        expires_raw = body.get("expires_at") if isinstance(body, dict) else None
        if expires_raw:
            expires_at = parse_airwallex_time(str(expires_raw))
        else:
            expires_at = self._clock.now() + _DEFAULT_TOKEN_TTL
        self._token = str(token)
        self._expires_at = expires_at

    def _decode(self, response: httpx.Response) -> Any:
        raw = response.content
        body: Any = None
        if raw:
            try:
                body = loads(raw)
            except json.JSONDecodeError:
                body = {"message": response.text}
        if response.status_code < 400:
            return body
        self._raise(response.status_code, body if isinstance(body, dict) else {})
        raise AssertionError("unreachable")

    def _raise(self, status: int, body: dict[str, Any]) -> None:
        code = str(body.get("code") or "")
        message = str(body.get("message") or "")
        if _is_insufficient_permissions(status, code, message):
            raise AirwallexError(
                "insufficient_permissions",
                (
                    "Insufficient permissions: the API key is missing a scope for this call "
                    f"({message or 'Insufficient permissions'}). "
                    "Widen the key's permissions in the Airwallex console. "
                    "Ledgerline did not treat this as a bad client id or api key."
                ),
                status=401,
                source="permissions",
                details={"upstream_code": code, "upstream_message": message},
                kind="permissions",
            )
        if status == 401:
            raise AirwallexError(
                code or "credentials_invalid",
                message or "Airwallex rejected the client id or api key",
                status=401,
                source=str(body.get("source") or "authentication"),
                details=body.get("details") if isinstance(body.get("details"), dict) else {},
                kind="authentication",
            )
        raise AirwallexError(
            code or "operation_failed",
            message or "Airwallex request failed",
            status=status,
            source=str(body.get("source") or ""),
            details=body.get("details") if isinstance(body.get("details"), dict) else {},
            kind="request",
        )

    def _pace(self, path: str) -> None:
        now = time.monotonic()
        window = 1.0
        self._trim(self._global_times, now, window)
        bucket = self._endpoint_times[path]
        self._trim(bucket, now, window)
        if len(self._global_times) >= 20 or len(bucket) >= 10:
            time.sleep(0.05)
            now = time.monotonic()
        self._global_times.append(now)
        bucket.append(now)

    @staticmethod
    def _trim(bucket: deque[float], now: float, window: float) -> None:
        while bucket and now - bucket[0] >= window:
            bucket.popleft()


def _is_insufficient_permissions(status: int, code: str, message: str) -> bool:
    return (
        status == 401
        and code == "unauthorized"
        and "insufficient permission" in message.lower()
    )
