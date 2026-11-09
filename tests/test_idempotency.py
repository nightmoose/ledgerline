from decimal import Decimal

import pytest

from ledgerline.adapters.base import AirwallexError
from ledgerline.adapters.mock import MockAirwallex
from ledgerline.ids import request_id


def _beneficiary(mock: MockAirwallex) -> str:
    created = mock.create_beneficiary(
        {
            "request_id": request_id("bene", "1"),
            "beneficiary": {"company_name": "Freightco"},
            "transfer_methods": ["LOCAL"],
        }
    )
    return created["id"]


def _fund(mock: MockAirwallex, currency: str, amount: str) -> None:
    mock.register_global_account(f"ga_{currency}", currency)
    mock.simulate_deposit({"amount": amount, "global_account_id": f"ga_{currency}", "status": "SETTLED"})


def test_same_request_id_is_idempotent_and_a_different_body_is_rejected():
    mock = MockAirwallex()
    _fund(mock, "USD", "10000")
    beneficiary_id = _beneficiary(mock)
    payload = {
        "request_id": request_id("ship", "transfer", "1"),
        "beneficiary_id": beneficiary_id,
        "source_currency": "USD",
        "transfer_currency": "USD",
        "transfer_amount": "100.00",
        "transfer_method": "LOCAL",
        "fee_paid_by": "PAYER",
    }
    first = mock.create_transfer(payload)
    second = mock.create_transfer(dict(payload))
    assert second["id"] == first["id"]
    assert mock._balances["USD"] == Decimal("9900.00")
    changed = dict(payload)
    changed["transfer_amount"] = "50.00"
    with pytest.raises(AirwallexError) as caught:
        mock.create_transfer(changed)
    assert caught.value.code == "duplicate_request_id"
    assert mock._balances["USD"] == Decimal("9900.00")


def test_swift_fee_is_flat_eur_and_local_is_free():
    mock = MockAirwallex()
    _fund(mock, "EUR", "10000")
    _fund(mock, "USD", "1000")
    beneficiary_id = _beneficiary(mock)
    swift = mock.create_transfer(
        {
            "request_id": request_id("swift", "1"),
            "beneficiary_id": beneficiary_id,
            "source_currency": "EUR",
            "transfer_currency": "EUR",
            "transfer_amount": "100.00",
            "transfer_method": "SWIFT",
            "fee_paid_by": "PAYER",
        }
    )
    assert swift["fee_amount"] == Decimal("12.85")
    assert swift["fee_currency"] == "EUR"
    assert swift["amount_payer_pays"] == Decimal("112.85")
    local = mock.create_transfer(
        {
            "request_id": request_id("local", "1"),
            "beneficiary_id": beneficiary_id,
            "source_currency": "USD",
            "transfer_currency": "USD",
            "transfer_amount": "40.00",
            "transfer_method": "LOCAL",
        }
    )
    assert local["fee_amount"] == Decimal("0.00")


def test_quote_is_single_use_and_failed_transfer_ends_cancelled():
    mock = MockAirwallex()
    _fund(mock, "USD", "10000")
    _fund(mock, "EUR", "5000")
    beneficiary_id = _beneficiary(mock)
    quote = mock.create_quote(
        {
            "request_id": request_id("quote", "1"),
            "buy_currency": "EUR",
            "sell_currency": "USD",
            "buy_amount": "100.00",
            "validity": "MIN_1",
        }
    )
    assert quote["usage"] == "SINGLE_USE"
    assert "rate" in quote
    conversion = mock.create_conversion(
        {
            "request_id": request_id("conv", "1"),
            "quote_id": quote["quote_id"],
            "buy_currency": "EUR",
            "sell_currency": "USD",
            "buy_amount": quote["buy_amount"],
        }
    )
    assert conversion["status"] == "SETTLED"
    again = dict(conversion)
    with pytest.raises(AirwallexError) as caught:
        mock.create_conversion(
            {
                "request_id": request_id("conv", "2"),
                "quote_id": quote["quote_id"],
                "buy_currency": "EUR",
                "sell_currency": "USD",
                "buy_amount": quote["buy_amount"],
            }
        )
    assert "single-use" in caught.value.message
    assert again["conversion_id"] == conversion["conversion_id"]

    transfer = mock.create_transfer(
        {
            "request_id": request_id("fail", "1"),
            "beneficiary_id": beneficiary_id,
            "source_currency": "EUR",
            "transfer_currency": "EUR",
            "transfer_amount": "80.00",
            "transfer_method": "LOCAL",
        }
    )
    sent = mock.simulate_transfer_transition(transfer["id"], {"next_status": "SENT"})
    assert sent["status"] == "SENT"
    failed = mock.simulate_transfer_transition(
        transfer["id"],
        {"next_status": "FAILED", "failure_type": "BENEFICIARY_BANK_RETURNED"},
    )
    assert failed["status"] == "CANCELLED"
    assert failed["failure_type"] == "BENEFICIARY_BANK_RETURNED"


def test_paged_lists_reject_a_short_page_and_deposits_include_total_count():
    mock = MockAirwallex()
    _fund(mock, "USD", "10")
    with pytest.raises(AirwallexError) as caught:
        mock.list_deposits(page_num=0, page_size=9)
    assert caught.value.code == "invalid_argument"
    page = mock.list_deposits(page_num=0, page_size=10)
    assert page["total_count"] == 1
    assert page["has_more"] is False
    assert page["items"][0]["currency"] == "USD"
