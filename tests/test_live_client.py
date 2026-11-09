"""Live client against a fake transport. No network and no credentials."""

from datetime import UTC, datetime

import httpx
import pytest

from ledgerline.adapters.base import AirwallexError
from ledgerline.adapters.live import LiveAirwallex
from ledgerline.adapters.paging import collect_pages
from ledgerline.clock import Clock
from ledgerline.config import DEMO_BASE_URL, load_settings
from ledgerline.money import D


def _client(handler) -> LiveAirwallex:
    clock = Clock(datetime(2026, 11, 9, 14, 0, 0, tzinfo=UTC))
    return LiveAirwallex(
        base_url=DEMO_BASE_URL,
        client_id="cid",
        api_key="secret-key",
        clock=clock,
        transport=httpx.MockTransport(handler),
    )


def _login(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/api/v1/authentication/login":
        assert request.headers["x-client-id"] == "cid"
        assert request.headers["x-api-key"] == "secret-key"
        return httpx.Response(
            201,
            json={"token": "tok-1", "expires_at": "2026-11-09T14:30:00+0000"},
        )
    return None


def test_default_base_url_follows_demo_env(tmp_path, monkeypatch):
    limits = tmp_path / "limits.yaml"
    limits.write_text("version: 1\n", encoding="utf-8")
    monkeypatch.delenv("AIRWALLEX_BASE_URL", raising=False)
    settings = load_settings(
        {
            "LEDGERLINE_MODE": "mock",
            "AIRWALLEX_ENV": "demo",
            "LEDGERLINE_LIMITS": str(limits),
            "LEDGERLINE_DATA_DIR": str(tmp_path),
        }
    )
    assert settings.base_url == "https://api-demo.airwallex.com"
    assert settings.mode == "mock"


def test_balances_are_a_json_array():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        login = _login(request)
        if login:
            return login
        seen["path"] = request.url.path
        seen["auth"] = request.headers["authorization"]
        assert "x-api-version" not in {key.lower() for key in request.headers}
        return httpx.Response(
            200,
            json=[
                {
                    "currency": "USD",
                    "available_amount": 18420.5,
                    "pending_amount": 0,
                    "reserved_amount": 1,
                    "total_amount": 18421.5,
                    "prepayment_amount": 0,
                    "account_type": "WALLET",
                }
            ],
        )

    rows = _client(handler).balances()
    assert seen["path"] == "/api/v1/balances/current"
    assert seen["auth"] == "Bearer tok-1"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["available_amount"] == D("18420.5")
    assert rows[0]["prepayment_amount"] == D("0")
    assert rows[0]["account_type"] == "WALLET"
    assert rows[0]["reserved_amount"] == D("1")


def test_fx_rate_uses_rate_and_rate_details():
    def handler(request: httpx.Request) -> httpx.Response:
        login = _login(request)
        if login:
            return login
        assert request.url.params["buy_currency"] == "EUR"
        assert request.url.params["sell_currency"] == "USD"
        assert request.url.params["sell_amount"] == "100"
        return httpx.Response(
            200,
            json={
                "buy_currency": "EUR",
                "currency_pair": "USDEUR",
                "dealt_currency": "USD",
                "rate": 0.9213,
                "rate_details": [{"buy_amount": 92.13, "level": "CLIENT", "rate": 0.9213}],
                "conversion_date": "2026-11-09",
                "created_at": "2026-11-09T14:00:00+0000",
            },
        )

    body = _client(handler).fx_rate(buy_currency="EUR", sell_currency="USD", sell_amount=D("100"))
    assert body["rate"] == D("0.9213")
    assert body["rate_details"][0]["buy_amount"] == D("92.13")
    assert body["rate_details"][0]["level"] == "CLIENT"
    assert body["currency_pair"] == "USDEUR"
    assert "client_rate" not in body


def test_transfers_list_sends_page_size_and_reads_items():
    def handler(request: httpx.Request) -> httpx.Response:
        login = _login(request)
        if login:
            return login
        assert request.url.params["page_size"] == "20"
        assert "page_num" not in request.url.params
        return httpx.Response(200, json={"items": [{"id": "tr_1", "status": "SENT"}]})

    body = _client(handler).list_transfers(page_size=20)
    assert body["items"][0]["id"] == "tr_1"


@pytest.mark.parametrize(
    ("method", "path", "total"),
    [
        ("list_beneficiaries", "/api/v1/beneficiaries", False),
        ("list_global_accounts", "/api/v1/global_accounts", False),
        ("list_conversions", "/api/v1/fx/conversions", False),
        ("list_deposits", "/api/v1/deposits", True),
    ],
)
def test_paged_lists_require_page_num_and_minimum_page_size(method, path, total):
    def handler(request: httpx.Request) -> httpx.Response:
        login = _login(request)
        if login:
            return login
        assert request.url.path == path
        assert request.url.params["page_num"] == "0"
        assert request.url.params["page_size"] == "10"
        payload = {"has_more": False, "items": [{"id": "row-1"}]}
        if total:
            payload["total_count"] = 1
        return httpx.Response(200, json=payload)

    client = _client(handler)
    body = getattr(client, method)()
    assert body["has_more"] is False
    assert body["items"][0]["id"] == "row-1"
    if total:
        assert body["total_count"] == 1


def test_page_size_below_10_is_invalid_argument_before_the_call():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/v1/authentication/login":
            raise AssertionError("page_size < 10 must not be sent")
        return _login(request)

    with pytest.raises(AirwallexError) as caught:
        _client(handler).list_deposits(page_num=0, page_size=9)
    assert caught.value.code == "invalid_argument"
    assert caught.value.source == "page_size"


def test_missing_scope_is_a_permissions_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": "unauthorized", "message": "Insufficient permissions"},
        )

    with pytest.raises(AirwallexError) as caught:
        _client(handler).balances()
    err = caught.value
    assert err.kind == "permissions"
    assert err.code == "insufficient_permissions"
    assert "bad client id" in err.message
    assert err.kind != "authentication"


def test_credentials_invalid_stays_an_authentication_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": "credentials_invalid", "message": "client id or api key is wrong"},
        )

    with pytest.raises(AirwallexError) as caught:
        _client(handler).balances()
    assert caught.value.kind == "authentication"
    assert caught.value.code == "credentials_invalid"


def test_collect_pages_walks_has_more():
    pages = {
        0: {"has_more": True, "items": [{"id": "a"}]},
        1: {"has_more": False, "items": [{"id": "b"}], "total_count": 2},
    }

    def fetch(page_num: int, page_size: int) -> dict:
        assert page_size == 10
        return pages[page_num]

    assert [row["id"] for row in collect_pages(fetch)] == ["a", "b"]
