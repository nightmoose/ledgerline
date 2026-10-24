# Ledgerline build plan

All times are ET. Sources were checked on Oct 24, 2026:
- https://airwallex.hackerearth.com/ (timeline, prizes, FAQ, deliverables)
- https://www.hackerearth.com/challengesapp/api/events/agentic-banking-hackathon/ (phase dates)
- https://airwallexdev.com/ and https://airwallexdev.com/guide (sandbox setup, starter kits, design criteria)

## Key dates
| Milestone | When (ET) |
|---|---|
| Registration & idea phase closes | Sun Oct 25, 2:29 PM EDT |
| Accepted teams notified; build period starts | Tue Oct 27, 12:30 AM EDT |
| **Final submission** | **Fri Nov 13, 1:29 PM EST** (HackerEarth phase end) |
| Finalists announced | Sun Nov 15 |
| Demo Day, SF (remote is optional) | Thu Nov 19 |

Entry to the build is gated: the timeline says "Accepted teams are notified" on Oct 27.

## Deliverables (per the FAQ)
- A working demo
- A video walkthrough **under 5 minutes**
- A repo link with setup instructions (README)

## How the event judges (from the builder guide; no scored rubric is published)
The guide asks for an agent that changes its decision when a balance, deadline, piece of evidence, or risk changes. The demo should show:
1. the user's goal
2. the agent's initial plan
3. the new information
4. the revised decision
5. the resulting balance, payment, or status

The demo must end with a financial action or an escalation to a person. Limits, reserves, validation, and duplicate protection belong in code. The model only gets typed tools. Approvals are bound to the amount, currency, counterparty, and evidence.

## Track 1 scope (Adaptive Treasury Controller)
Setup: fund a sandbox wallet with `POST /api/v1/simulation/deposit/create`.

**Scenario:** several obligations are due (supplier USD, payroll EUR, SaaS GBP), and the wallet doesn't have enough cash.
1. Ledgerline forecasts the shortfall and proposes a plan: fund, convert (FX quote), defer, or escalate.
2. Something changes: a late deposit, an FX move, or a failed transfer.
3. Ledgerline revises the plan. It executes idempotent transfers with a stable `request_id`. Anything above the limits in `policy/limits.yaml` is escalated for human approval.

### Modules
- `adapters`: Airwallex REST client (token login, 30-min refresh) and the simulation interface
- `contracts`: typed schemas (pydantic)
- `recon`: matches payouts against webhook events (dedupe on event id, ordered by `created_at`)
- `forecast`: a 14-day cash view per currency
- `policy`: limits, the reserve floor, and the approval matrix
- `executor`: transfers and conversions; branches on FAILED and CANCELLED
- `audit`: an append-only JSONL decision log

### Web console
A small console on Vercel showing the plan, the diff when the plan changes, and an approve button. It gets deployed only after the build starts.

### Stretch goal
The Visa or Metal awards ($15k each). These need partner tooling, so only attempt one if the core is done by Nov 10.

## Build schedule (one project active at a time)
| Dates | Ledgerline work |
|---|---|
| Sun Oct 25 | Setup only: sandbox account, API keys, Docs MCP, read the kit. No code. |
| Oct 26 – Nov 4 | Paused. Meta (top priority), Nebius, and Appwrite are building. |
| See the schedule decision | Core build, video, submit by Nov 13, 1:29 PM EST |

## Code-provenance decision
Rules: we didn't find any published rule that requires new code. We are still treating Oct 27 as the start for code, because the official build period begins then and acceptance is gated. The repo holds only docs until the build starts. Reconciliation code is **not** shared with the PayPal entry, to avoid any double-submission risk.
