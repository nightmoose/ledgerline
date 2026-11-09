import pytest

from ledgerline.approval.gate import bound_to, evidence_hash, fingerprint
from ledgerline.demo_run import prepare_demo
from ledgerline.errors import ApprovalError
from ledgerline.money import D


def test_fingerprint_changes_when_any_bound_field_changes():
    base = dict(
        amount=D("7525.70"),
        currency="EUR",
        counterparty="Berlin GmbH",
        quote_id="q_9f2",
        evidence_hash=evidence_hash({"email": "payment will slip to next week"}),
    )
    original = fingerprint(**base)
    for field, value in (
        ("amount", D("7525.71")),
        ("currency", "USD"),
        ("counterparty", "Other GmbH"),
        ("quote_id", "q_other"),
        ("evidence_hash", evidence_hash({"email": "different"})),
    ):
        changed = dict(base)
        changed[field] = value
        assert fingerprint(**changed) != original


def test_changed_quote_voids_an_approved_card(service):
    prepare_demo(service)
    card = service._approval_for("obl_supplier")
    service.approve(card.id, approver="Alex")
    assert bound_to(
        service.approvals[card.id],
        amount=card.amount,
        currency=card.currency,
        counterparty=card.counterparty,
        quote_id=card.quote_id,
        evidence_hash=card.evidence_hash,
    )
    service.quotes["obl_supplier"]["quote_id"] = "q_other"
    with pytest.raises(ApprovalError) as caught:
        service.execute("obl_supplier")
    assert caught.value.code == "void"
    assert service.approvals[card.id].status == "void"
