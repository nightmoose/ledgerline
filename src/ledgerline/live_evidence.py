"""Read-only view of the recorded Nov 9 live sandbox run (run C).

The public console runs in mock mode and cannot call Airwallex. This module only
reads files committed under evidence/ so a judge can compare the console's
"Live sandbox evidence" page with the video and with docs/EVIDENCE.md.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "evidence" / "live-2026-11-09"
RUN_FILE = "run-c-1943.audit.jsonl"
HOST_FILE = "host-webhooks.json"
REPO = "https://github.com/nightmoose/ledgerline/blob/v1.0-submit/evidence/live-2026-11-09/"

_LABELS = {
    "obl_shipping": "Shipping · Freightco · USD 6,200 LOCAL",
    "obl_supplier": "Supplier · Berlin GmbH · EUR 7,512.85 SWIFT",
    "obl_contractor": "Contractor · USD 1,960 LOCAL",
}


@lru_cache(maxsize=1)
def load(evidence_dir: Path = EVIDENCE_DIR) -> dict[str, Any]:
    run_path = evidence_dir / RUN_FILE
    raw = run_path.read_bytes()
    events = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    host = json.loads((evidence_dir / HOST_FILE).read_text("utf-8"))

    # transfer_id -> obligation, from the request_id order in the run.
    transfers: list[dict[str, Any]] = []
    statuses: dict[str, list[str]] = {}
    conversion = quote = approval = None
    obligation_for_attempt = ["obl_supplier", "obl_shipping", "obl_contractor", "obl_contractor"]
    for event in events:
        payload = event.get("payload") or {}
        kind = event.get("kind")
        if kind == "quote":
            quote = payload.get("quote_id")
        elif kind == "approved":
            approval = {
                "approval_id": payload.get("approval_id"),
                "fingerprint": payload.get("fingerprint"),
                "message": event.get("message"),
                "ts": event.get("ts"),
            }
        elif kind == "execute" and payload.get("conversion_id"):
            conversion = {"conversion_id": payload["conversion_id"], "ts": event.get("ts")}
        elif kind == "execute" and payload.get("transfer_id"):
            index = len(transfers)
            obligation = obligation_for_attempt[index] if index < len(obligation_for_attempt) else "?"
            transfers.append(
                {
                    "obligation": _LABELS.get(obligation, obligation),
                    "attempt": payload.get("attempt"),
                    "request_id": payload.get("request_id"),
                    "transfer_id": payload["transfer_id"],
                    "ts": event.get("ts"),
                }
            )
        elif kind == "transition":
            status = str(payload.get("status"))
            if payload.get("failure_type"):
                status += f" ({payload['failure_type']}, chosen by the sandbox)"
            statuses.setdefault(str(payload.get("transfer_id")), []).append(status)
    for item in transfers:
        item["statuses"] = " → ".join(["SCHEDULED", *statuses.get(item["transfer_id"], [])])
    result = next((e for e in events if e.get("kind") == "result"), {})
    run_c = [row for row in host["deliveries"] if row["note"].startswith("run C")]
    return {
        "run_file": RUN_FILE,
        "run_url": REPO + RUN_FILE,
        "run_sha256": hashlib.sha256(raw).hexdigest(),
        "events": len(events),
        "started": events[0]["ts"] if events else "",
        "finished": events[-1]["ts"] if events else "",
        "quote_id": quote,
        "approval": approval,
        "conversion": conversion,
        "transfers": transfers,
        "balances": (result.get("payload") or {}).get("balances", {}),
        "result": result.get("message", ""),
        "host": host,
        "host_run_c": run_c,
        "host_total": len(host["deliveries"]),
    }
