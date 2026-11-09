"""Errors that stay inside the controller. Adapter errors live with the adapter."""

from __future__ import annotations


class LedgerlineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class ContractError(LedgerlineError):
    pass


class PolicyError(LedgerlineError):
    pass


class ApprovalError(LedgerlineError):
    pass


class ExecutionError(LedgerlineError):
    pass
