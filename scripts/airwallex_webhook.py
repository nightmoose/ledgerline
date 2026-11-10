"""Create, repoint, or list the Ledgerline webhook on the Airwallex sandbox.

Reads AIRWALLEX_CLIENT_ID / AIRWALLEX_API_KEY from the environment. The
signing secret returned by create is appended to the env file given with
--secret-file and is never printed.

    python scripts/airwallex_webhook.py list
    python scripts/airwallex_webhook.py create https://host/webhooks/airwallex --secret-file .env
    python scripts/airwallex_webhook.py update wh_... https://host/webhooks/airwallex
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

from ledgerline.config import resolve_base_url

EVENTS = ["payout.transfer.paid", "payout.transfer.failed", "payout.transfer.cancelled"]
VERSION = "2025-02-14"


def _token(client: httpx.Client, base: str) -> str:
    response = client.post(
        f"{base}/api/v1/authentication/login",
        headers={
            "x-client-id": os.environ["AIRWALLEX_CLIENT_ID"],
            "x-api-key": os.environ["AIRWALLEX_API_KEY"],
        },
    )
    response.raise_for_status()
    return response.json()["token"]


def _public(body: dict) -> dict:
    return {key: value for key, value in body.items() if key != "secret"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("url")
    create.add_argument("--secret-file", required=True)
    update = sub.add_parser("update")
    update.add_argument("webhook_id")
    update.add_argument("url")
    args = parser.parse_args(argv)

    base, _ = resolve_base_url(dict(os.environ))
    with httpx.Client(timeout=30) as client:
        headers = {"Authorization": f"Bearer {_token(client, base)}"}
        if args.cmd == "list":
            response = client.get(f"{base}/api/v1/webhooks", headers=headers)
            response.raise_for_status()
            print(json.dumps([_public(item) for item in response.json().get("items", [])], indent=2))
        elif args.cmd == "create":
            response = client.post(
                f"{base}/api/v1/webhooks/create",
                headers=headers,
                json={"request_id": str(uuid.uuid4()), "url": args.url,
                      "version": VERSION, "events": EVENTS},
            )
            response.raise_for_status()
            body = response.json()
            with Path(args.secret_file).open("a", encoding="utf-8") as handle:
                handle.write(f"AIRWALLEX_WEBHOOK_SECRET={body['secret']}\n")
            print(json.dumps(_public(body), indent=2))
        else:
            response = client.post(
                f"{base}/api/v1/webhooks/{args.webhook_id}/update",
                headers=headers,
                json={"url": args.url},
            )
            response.raise_for_status()
            print(json.dumps(_public(response.json()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
