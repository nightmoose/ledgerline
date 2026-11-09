"""Live-host shapes observed on api-demo.airwallex.com on 2026-11-09.

Fake transport only. No network and no credentials.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest

from ledgerline.adapters.base import AirwallexError
from ledgerline.adapters.live import LiveAirwallex
from ledgerline.clock import Clock, WallClock
from ledgerline.config import DEMO_BASE_URL, load_settings
from ledgerline.service import Service


def _client(handler) -> LiveAirwallex:
    return LiveAirwallex(
        base_url=DEMO_BASE_URL,
        client_id="cid",
        api_key="secret-key",
        clock=Clock(datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC)),
        transport=httpx.MockTransport(handler),
    )


def _login(request: httpx.Request):
    if request.url.path == "/api/v1/authentication/login":
        return httpx.Response(201, json={"token": "t", "expires_at": "2026-11-09T14:30:00+0000"})
    return None


def test_global_accounts_without_has_more_is_a_single_page():
    def handler(request):
        return _login(request) or httpx.Response(200, json={"items": [{"id": "ga_1"}]})

    body = _client(handler).list_global_accounts()
    assert body["has_more"] is False
    assert body["items"][0]["id"] == "ga_1"


def test_other_pages_still_require_has_more():
    def handler(request):
        return _login(request) or httpx.Response(200, json={"items": []})

    with pytest.raises(AirwallexError):
        _client(handler).list_beneficiaries()


def test_deposit_account_for_picks_active_deposit_feature():
    def handler(request):
        return _login(request) or httpx.Response(
            200,
            json={
                "items": [
                    {"id": "ga_closed", "status": "CLOSED",
                     "supported_features": [{"currency": "USD", "type": "DEPOSIT"}]},
                    {"id": "ga_usd", "status": "ACTIVE",
                     "supported_features": [{"currency": "USD", "type": "DEPOSIT"}]},
                ]
            },
        )

    client = _client(handler)
    assert client.deposit_account_for("USD") == "ga_usd"
    assert client.deposit_account_for("EUR") is None


def test_transition_to_paid_steps_through_sent_from_scheduled():
    calls = []

    def handler(request):
        login = _login(request)
        if login:
            return login
        if request.method == "GET":
            return httpx.Response(200, json={"id": "tr_1", "status": "SCHEDULED"})
        calls.append(json.loads(request.content)["next_status"])
        return httpx.Response(200, json={"id": "tr_1", "status": calls[-1]})

    result = _client(handler).simulate_transfer_transition("tr_1", {"next_status": "PAID"})
    assert calls == ["SENT", "PAID"]
    assert result["status"] == "PAID"


def test_transition_from_sent_does_not_resend_sent():
    calls = []

    def handler(request):
        login = _login(request)
        if login:
            return login
        if request.method == "GET":
            return httpx.Response(200, json={"id": "tr_1", "status": "SENT"})
        calls.append(json.loads(request.content)["next_status"])
        return httpx.Response(200, json={"id": "tr_1", "status": "FAILED", "failure_type": "OTHER"})

    _client(handler).simulate_transfer_transition("tr_1", {"next_status": "FAILED"})
    assert calls == ["FAILED"]


def _dup_handler(existing_amount):
    def handler(request):
        login = _login(request)
        if login:
            return login
        if request.url.path == "/api/v1/transfers/create":
            return httpx.Response(
                400, json={"code": "duplicate_request_id", "message": "used", "source": "request_id"}
            )
        if request.url.path == "/api/v1/transfers":
            assert request.url.params["request_id"] == "rid-1"
            return httpx.Response(
                200,
                json={"items": [{"id": "tr_9", "request_id": "rid-1", "beneficiary_id": "b1",
                                 "transfer_amount": existing_amount}]},
            )
        if request.url.path == "/api/v1/transfers/tr_9":
            return httpx.Response(200, json={"id": "tr_9", "status": "SENT"})
        raise AssertionError(request.url.path)

    return handler


def test_retried_transfer_request_id_returns_the_original():
    body = {"request_id": "rid-1", "beneficiary_id": "b1", "transfer_amount": "10.00"}
    assert _client(_dup_handler(10)).create_transfer(body)["id"] == "tr_9"


def test_reused_request_id_with_a_different_body_still_raises():
    body = {"request_id": "rid-1", "beneficiary_id": "b1", "transfer_amount": "11.00"}
    with pytest.raises(AirwallexError) as caught:
        _client(_dup_handler(10)).create_transfer(body)
    assert caught.value.code == "duplicate_request_id"


def _live_settings(tmp_path, **extra):
    env = {
        "LEDGERLINE_MODE": "live",
        "AIRWALLEX_CLIENT_ID": "cid",
        "AIRWALLEX_API_KEY": "key",
        "LEDGERLINE_DATA_DIR": str(tmp_path),
    }
    env.update(extra)
    return load_settings(env)


class _Balances:
    def __init__(self):
        self.rows = {"USD": 10_000_000, "EUR": 10_000_000, "GBP": 10_000_000}

    def balances(self):
        return [{"currency": c, "available_amount": v} for c, v in self.rows.items()]

    def close(self):
        pass


def test_live_book_is_ring_fenced_from_the_prefunded_sandbox(tmp_path):
    service = Service(_live_settings(tmp_path))
    fake = _Balances()
    service.adapter = fake
    assert service.wallet() == {"USD": 0, "EUR": 0, "GBP": 0}
    fake.rows["USD"] += 20000
    assert service.wallet()["USD"] == 20000
    assert isinstance(service.clock, WallClock)
    assert service.run_id


def test_live_book_wallet_mode_plans_against_the_whole_wallet(tmp_path):
    service = Service(_live_settings(tmp_path, LEDGERLINE_LIVE_BOOK="wallet"))
    service.adapter = _Balances()
    assert service.wallet()["EUR"] == 10_000_000


def test_live_mode_plans_with_the_observed_swift_fee(tmp_path):
    service = Service(_live_settings(tmp_path))
    assert str(service.limits.swift_fee.amount) == "13.39"


def test_real_delivery_shape_reconciles_through_data_object(tmp_path):
    from ledgerline.webhooks.receiver import sign

    settings = load_settings({"LEDGERLINE_DATA_DIR": str(tmp_path)})
    service = Service(settings)
    raw = json.dumps(
        {"id": "evt_1", "name": "payout.transfer.paid", "created_at": "2026-11-09T19:00:00+0000",
         "data": {"object": {"id": "tr_unknown", "status": "PAID"}}}
    ).encode()
    ts = str(int(service.clock.now().timestamp() * 1000))
    result = service.receive_webhook(raw, ts, sign(settings.webhook_secret, ts, raw))
    assert result["status"] == 200
    logged = [e for e in service.replay() if e["kind"] == "webhook"]
    assert logged and logged[-1]["payload"]["transfer_id"] == "tr_unknown"
