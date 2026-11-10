import json
from pathlib import Path

from fastapi.testclient import TestClient

from ledgerline.audit.chain import GENESIS, verify_file
from ledgerline.audit.log import AuditLog
from ledgerline.config import load_settings
from ledgerline.demo_run import run_demo
from ledgerline.main import create_app
from ledgerline.receipt import main as receipt_main

ROOT = Path(__file__).resolve().parents[1]


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_demo_run_produces_an_intact_chain(service):
    run_demo(service)
    report = service.audit.verify()
    assert report.ok, report
    events = service.replay()
    assert report.events == len(events) >= 30
    assert events[0]["prev_hash"] == GENESIS
    for previous, current in zip(events, events[1:], strict=False):
        assert current["prev_hash"] == previous["hash"]
    assert report.head == events[-1]["hash"]


def test_editing_a_decision_breaks_the_chain(service):
    run_demo(service)
    path = service.settings.audit_path
    lines = _lines(path)
    for index, line in enumerate(lines):
        event = json.loads(line)
        if event["kind"] == "approved":
            event["message"] = event["message"].replace("Alex", "Mallory")
            lines[index] = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            seq = event["seq"]
            break
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_file(path)
    assert not report.ok
    assert report.first_bad_seq == seq
    assert "hash" in report.reason


def test_deleting_or_reordering_breaks_the_chain(service):
    run_demo(service)
    path = service.settings.audit_path
    lines = _lines(path)
    deleted = lines[:5] + lines[6:]
    path.write_text("\n".join(deleted) + "\n", encoding="utf-8")
    assert not verify_file(path).ok
    swapped = lines[:]
    swapped[3], swapped[4] = swapped[4], swapped[3]
    path.write_text("\n".join(swapped) + "\n", encoding="utf-8")
    assert not verify_file(path).ok


def test_chain_continues_across_restarts(tmp_path: Path):
    log = AuditLog(tmp_path / "a.jsonl", tmp_path / "a.db")
    log.append("plan", "first", ts="t1", amount="1.00")
    head = log.head
    log.close()
    again = AuditLog(tmp_path / "a.jsonl", tmp_path / "a.db")
    event = again.append("execute", "second", ts="t2")
    again.close()
    assert event["prev_hash"] == head
    assert verify_file(tmp_path / "a.jsonl").ok


def test_verify_cli_exit_codes(service, capsys):
    run_demo(service)
    path = service.settings.audit_path
    assert receipt_main(["verify", str(path)]) == 0
    assert "hash chain intact" in capsys.readouterr().out
    lines = _lines(path)
    lines[-1] = lines[-1].replace("Reserves", "Reservez")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert receipt_main(["verify", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_console_receipt_endpoint_and_trace(tmp_path: Path):
    settings = load_settings(
        {
            "LEDGERLINE_MODE": "mock",
            "LEDGERLINE_MODEL_PROVIDER": "offline",
            "AIRWALLEX_ENV": "demo",
            "LEDGERLINE_LIMITS": str(ROOT / "policy" / "limits.yaml"),
            "LEDGERLINE_DATA_DIR": str(tmp_path),
            "LEDGERLINE_CLOCK": "wall",
        }
    )
    client = TestClient(create_app(settings))
    client.post("/demo/run", follow_redirects=True)
    receipt = client.get("/receipt").json()
    assert receipt["ok"] is True
    assert receipt["events"] == len(receipt["chain"]) >= 30
    trace = client.get("/trace").text
    assert "hash chain intact" in trace
    assert "14:02:11" not in trace  # real timestamps, not the frozen demo clock
    # A second run starts its own log and its own chain.
    client.post("/demo/run", follow_redirects=True)
    second = client.get("/receipt").json()
    assert second["ok"] is True and second["events"] == receipt["events"]
    page = client.get("/redteam").text
    assert "26 of 26 refused by code" in page
