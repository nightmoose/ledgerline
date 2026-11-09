"""Typed tools. There is no tool that creates a conversion or a transfer."""

from __future__ import annotations

from typing import Any

from ledgerline.errors import LedgerlineError

TOOL_NAMES = ("propose_plan", "request_quote", "explain")


def dispatch(service: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    if name not in TOOL_NAMES:
        raise LedgerlineError("unknown_tool", f"{name} is not available")
    arguments = arguments or {}
    if name == "propose_plan":
        # Notes are untrusted. The allocator does not read them.
        _ = arguments.get("notes", "")
        if service.plan is None:
            service.build_plan()
        return [
            {"obligation_id": line.obligation_id, "action": line.action, "reason": line.reason}
            for line in service.plan.lines
        ]
    if name == "request_quote":
        return service.request_quote(str(arguments["obligation_id"]))
    line = service.plan.by_id(str(arguments["obligation_id"]))
    checks = ", ".join(f"{'ok' if check.ok else 'fail'} {check.detail}" for check in line.checks)
    return f"{line.reason}. Policy: {checks}"
