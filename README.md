# Ledgerline

An adaptive treasury controller agent built on Airwallex sandbox APIs.

When cash is short, Ledgerline decides which obligations to **fund, convert, defer, or escalate**, and changes that decision when a balance, deadline, FX rate, or risk signal changes. The agent can move money in the sandbox. Any action over a policy limit waits for a person to approve it.

Entry for the Airwallex Agentic Banking Hackathon, Track 1 (Treasury & Ops: Adaptive Treasury Controller).

## Status
Pre-build. The official build period starts Oct 27, 2026, so this repo only holds the plan for now (see `docs/plan.md`). No application code has been written yet.

## Design principles
- Amounts, limits, reserves, validation, duplicate protection, and state transitions are written as deterministic code (`policy/limits.yaml`).
- The model reads unstructured inputs, proposes a plan, and explains exceptions. It only gets typed tools, never raw credentials.
- Every approval is bound to the amount, currency, counterparty, and evidence the approver saw.
- Sandbox simulation calls sit behind one adapter interface.
- Every decision and money movement is written to an audit log.

## Planned layout
```
src/ledgerline/
  adapters/   # Airwallex sandbox client and simulation interface
  contracts/  # typed schemas for obligations, balances, and decisions
  recon/      # ledger vs. bank reconciliation
  forecast/   # short-horizon cash forecast
  policy/     # deterministic limits and the approval rules
  executor/   # idempotent transfers and conversions (stable request_id)
  audit/      # append-only decision log
tests/
policy/limits.yaml
docs/plan.md
```

## Setup
Coming during the build period. Credentials go in a local `.env` file, which is never committed.

## License
MIT
