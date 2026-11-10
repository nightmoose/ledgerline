"""Run the hostile suite and print the 'N of N refused by code' table.

    python -m ledgerline.redteam.runner            # summary + per-case table
    python -m ledgerline.redteam.runner --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

from .cases import CASES, CLASSES, CaseResult
from .harness import tmpdir


def run_all() -> list[CaseResult]:
    results = []
    for case in CASES:
        with tmpdir() as raw:
            results.append(case.run(Path(raw), case))
    return results


def summary_table(results: list[CaseResult]) -> str:
    grouped: OrderedDict[str, list[CaseResult]] = OrderedDict((key, []) for key in CLASSES)
    for item in results:
        grouped[item.klass].append(item)
    lines = ["| Attack class | Attempts | Refused by code | Money moved |", "|---|---|---|---|"]
    for key, items in grouped.items():
        refused = sum(1 for item in items if item.refused)
        moved = sum(1 for item in items if any("money moved" in v or "paid twice" in v for v in item.violations))
        lines.append(f"| {CLASSES[key]} | {len(items)} | {refused} of {len(items)} | {moved} |")
    total = len(results)
    refused = sum(1 for item in results if item.refused)
    moved = sum(1 for item in results if any("money moved" in v or "paid twice" in v for v in item.violations))
    lines.append(f"| **Total** | **{total}** | **{refused} of {total}** | **{moved}** |")
    return "\n".join(lines)


def case_table(results: list[CaseResult]) -> str:
    lines = ["| # | Attack | Refused | Stopped by |", "|---|---|---|---|"]
    for item in results:
        mark = "yes" if item.refused else "**NO**: " + "; ".join(item.violations)
        lines.append(f"| {item.case_id} | {item.title} | {mark} | {item.mechanism} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledgerline.redteam")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    results = run_all()
    refused = sum(1 for item in results if item.refused)
    if args.json:
        print(json.dumps([asdict(item) for item in results], indent=1))
    else:
        print(f"{refused} of {len(results)} hostile cases refused by code\n")
        print(summary_table(results))
        print()
        print(case_table(results))
    return 0 if refused == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
