"""Verify a Ledgerline audit log's hash chain.

    python -m ledgerline.receipt verify data/audit.jsonl
    python -m ledgerline.receipt verify data/audit.jsonl --json

Exit code 0 when the chain is intact, 1 when any event was edited, removed,
inserted or reordered.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ledgerline.audit.chain import verify_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerline.receipt")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify", help="verify the hash chain of an audit JSONL file")
    check.add_argument("path", nargs="?", default="data/audit.jsonl")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = verify_file(Path(args.path))
    if args.json:
        print(json.dumps(report.as_dict()))
    else:
        print(report.line())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
