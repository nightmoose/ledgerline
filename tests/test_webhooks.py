from ledgerline.jsonutil import dumps
from ledgerline.webhooks.receiver import WebhookReceiver, sign


def test_hmac_rejects_a_bad_signature_and_dedupes():
    receiver = WebhookReceiver("test-secret")
    body = dumps(
        {
            "id": "evt_1",
            "name": "payout.transfer.paid",
            "created_at": "2026-11-09T14:07:10+0000",
            "data": {"id": "tr_1", "status": "PAID"},
        }
    ).encode()
    timestamp = "1762697230000"
    good = sign("test-secret", timestamp, body)
    assert receiver.receive(body, timestamp, "not-the-signature")["status"] == 400
    assert receiver.receive(body, timestamp, good)["duplicate"] is False
    assert receiver.receive(body, timestamp, good)["duplicate"] is True
    assert len(receiver.applied) == 1


def test_events_are_applied_in_created_at_order():
    receiver = WebhookReceiver("test-secret")
    later = _event("evt_later", "2026-11-09T14:09:00+0000")
    earlier = _event("evt_earlier", "2026-11-09T14:01:00+0000")
    timestamp = "1762697230000"
    receiver.receive(later, timestamp, sign("test-secret", timestamp, later), flush=False)
    receiver.receive(earlier, timestamp, sign("test-secret", timestamp, earlier), flush=False)
    receiver.flush()
    assert [item["id"] for item in receiver.ordered()] == ["evt_earlier", "evt_later"]


def _event(event_id: str, created_at: str) -> bytes:
    return dumps(
        {
            "id": event_id,
            "name": "payout.transfer.paid",
            "created_at": created_at,
            "data": {"id": event_id, "status": "PAID"},
        }
    ).encode()
