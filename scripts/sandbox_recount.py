"""Recount what Ledgerline did on the Airwallex sandbox. Read-only.

Lists every transfer and conversion on the sandbox account (GET only), then
matches each transfer to an `execute` event in the audit logs given on the
command line by request_id. Prints a Markdown summary. Credentials come from
AIRWALLEX_CLIENT_ID / AIRWALLEX_API_KEY and are never printed.

    python scripts/sandbox_recount.py evidence/live-2026-11-09/*.audit.jsonl
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from ledgerline.config import resolve_base_url


def _get_all(client: httpx.Client, base: str, token: str, path: str) -> list[dict]:
    items: list[dict] = []
    page = 0
    while True:
        response = client.get(
            f"{base}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_num": page, "page_size": 100},
        )
        response.raise_for_status()
        body = response.json()
        batch = body.get("items", [])
        items.extend(batch)
        if not body.get("has_more") or not batch:
            return items
        page += 1


def main(paths: list[str]) -> int:
    base, _ = resolve_base_url(dict(os.environ))
    client = httpx.Client(timeout=30)
    login = client.post(
        f"{base}/api/v1/authentication/login",
        headers={"x-client-id": os.environ["AIRWALLEX_CLIENT_ID"], "x-api-key": os.environ["AIRWALLEX_API_KEY"]},
    )
    login.raise_for_status()
    token = login.json()["token"]
    transfers = _get_all(client, base, token, "/api/v1/transfers")

    runs = []
    for path in paths:
        events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
        executes = {}
        approved_at = None
        for event in events:
            if event["kind"] == "approved" and approved_at is None:
                approved_at = event["seq"]
            if event["kind"] == "execute" and event["payload"].get("request_id"):
                executes[event["payload"]["request_id"]] = event["seq"]
        runs.append({"path": path, "executes": executes, "approved_at": approved_at, "events": len(events)})

    by_run: dict[str, list[dict]] = {run["path"]: [] for run in runs}
    unmatched = []
    for transfer in transfers:
        owner = next((run for run in runs if transfer.get("request_id") in run["executes"]), None)
        if owner is None:
            unmatched.append(transfer)
        else:
            by_run[owner["path"]].append(transfer | {"_seq": owner["executes"][transfer["request_id"]]})

    print(f"Sandbox host: {base}")
    print(f"Transfers on the account: {len(transfers)}")
    matched = sum(len(items) for items in by_run.values())
    print(f"Matched to a Ledgerline audit `execute` event by request_id: {matched}")
    print(f"Not created by Ledgerline (manual probes and webhook tests): {len(unmatched)}\n")
    print("| Run | Transfers | Over-limit payments approved first | Payroll (ESCALATE) transfers | Paid twice |")
    print("|---|---|---|---|---|")
    for run in runs:
        items = by_run[run["path"]]
        supplier = [item for item in items if item.get("reference") == "obl_supplier"]
        approved_first = sum(1 for item in supplier if run["approved_at"] and run["approved_at"] < item["_seq"])
        payroll = sum(1 for item in items if item.get("reference") == "obl_payroll")
        paid: dict[str, int] = {}
        for item in items:
            if item.get("status") == "PAID":
                paid[item["reference"]] = paid.get(item["reference"], 0) + 1
        twice = sum(1 for count in paid.values() if count > 1)
        print(
            f"| {Path(run['path']).name} | {len(items)} | {approved_first} of {len(supplier)} | {payroll} | {twice} |"
        )
    print("\nUnmatched transfers (reference, amount, status):")
    for item in sorted(unmatched, key=lambda row: row.get("created_at", "")):
        print(f"- {item.get('created_at')} {item.get('reference')} {item.get('transfer_currency')} "
              f"{item.get('transfer_amount')} {item.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
