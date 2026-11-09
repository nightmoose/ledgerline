from pathlib import Path

from fastapi.testclient import TestClient

from ledgerline.config import load_settings
from ledgerline.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def _app(tmp_path: Path):
    settings = load_settings(
        {
            "LEDGERLINE_MODE": "mock",
            "LEDGERLINE_MODEL_PROVIDER": "offline",
            "AIRWALLEX_ENV": "demo",
            "LEDGERLINE_LIMITS": str(ROOT / "policy" / "limits.yaml"),
            "LEDGERLINE_DATA_DIR": str(tmp_path),
        }
    )
    return create_app(settings)


def test_console_prepare_approve_and_settle(tmp_path: Path):
    app = _app(tmp_path)
    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["mode"] == "mock"
    assert health.json()["base_url"] == "https://api-demo.airwallex.com"

    prepared = client.post("/demo/prepare", follow_redirects=True)
    assert prepared.status_code == 200
    assert b"CONVERT-MIN" in prepared.content
    assert b"Approve" in prepared.content
    assert b"Berlin GmbH" not in prepared.content or b"Supplier" in prepared.content

    service = app.state.service
    card = service._approval_for("obl_supplier")
    assert card is not None and card.status == "pending"
    approved = client.post(
        f"/approvals/{card.id}/approve",
        data={"approver": "Alex"},
        follow_redirects=True,
    )
    assert approved.status_code == 200
    assert service.approvals[card.id].status == "approved"

    finished = client.post("/demo/finish", follow_redirects=True)
    assert finished.status_code == 200
    assert service.reserves_hold()
    assert b"PAID" in finished.content

    trace = client.get("/trace")
    assert trace.status_code == 200
    assert b"REPLAN" in trace.content
    assert b"WEBHOOK" in trace.content

    policy = client.get("/policy")
    assert b"fx_limit" in policy.content
    preview = client.post(
        "/policy/preview",
        data={"fx_auto_limit_low_conf": "2000"},
        follow_redirects=True,
    )
    assert b"fx_auto_limit_low_conf" in preview.content
    assert b"Dry-run" in preview.content or b"more action" in preview.content
    client.post("/policy/discard", follow_redirects=True)
    assert app.state.service.policy_draft is None


def test_webhook_route_rejects_a_bad_signature(tmp_path: Path):
    app = _app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/webhooks/airwallex",
        content=b'{"id":"evt_x","created_at":"2026-11-09T14:00:00+0000","name":"payout.transfer.paid","data":{}}',
        headers={"x-timestamp": "1762697230000", "x-signature": "00"},
    )
    assert response.status_code == 400
