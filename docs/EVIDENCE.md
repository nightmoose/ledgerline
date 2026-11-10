# Evidence from the Airwallex sandbox (recounted Nov 10, 2026)

Every number here was recounted from the sandbox API, the host's request logs or the audit logs in
[`evidence/live-2026-11-09/`](../evidence/live-2026-11-09/). Nothing is estimated. Times are UTC.

The three run logs and the host's delivery list (`host-webhooks.json`) are committed. The public console's
**Live sandbox evidence** page (`/evidence`, JSON at `/evidence.json`) renders run C and those deliveries
read-only; it makes no Airwallex call. Run C is the run shown in the video. SHA-256 of the run logs:

| File | SHA-256 |
|---|---|
| `run-a-1907.audit.jsonl` | `dcb1c592a13ce2f6bb5372f7b2febc14ae85c045ed2a4addf1f1289f1b5208e1` |
| `run-b-1908.audit.jsonl` | `537b0a46b49393fcd1c351c5b7fcaba2d030725a28b9e16d683823217780ff4e` |
| `run-c-1943.audit.jsonl` | `40da196cc8e63e818d247155a7e5259246d27b45468b3016de9d68f21759fe11` |

## Headline

| Measure | Result | Source |
|---|---|---|
| Real Airwallex webhook deliveries HMAC-verified and accepted | **15 of 15** | host request + function logs |
| Forged webhook (bad signature) | rejected, 400 `invalid_signature` | host function log, 19:28:08 |
| Complete live runs of the kit sequence | **3** (about 35 s each) | audit logs |
| Ledgerline transfers on the sandbox | **12**, each matched to an audit `execute` event by `request_id` | `scripts/sandbox_recount.py` |
| Over-limit payments executed before a bound human approval | **0 of 3** (all 3 approved first; the other 9 transfers were inside the automatic limits) | audit order: `approved` precedes `execute` |
| Payroll exception (ESCALATE, EUR 9,800) transfers | **0** in 3 runs | sandbox transfer list |
| Obligations paid twice | **0** (3 failed contractor payouts, 3 single replacements) | sandbox transfer list |
| Reserves at or above floor at the end of each run | **3 of 3** | audit `result` events |
| Hostile cases refused by code | **26 of 26**, 0 money moved | `python -m ledgerline.redteam.runner` (mock adapter) |

The other 7 transfers on the account (USD 2 to 25, EUR 5) were made by hand while probing the API and
testing webhook delivery. They are listed below and not counted as Ledgerline's.

## Transfers (recount output)

```
Sandbox host: https://api-demo.airwallex.com
Transfers on the account: 19
Matched to a Ledgerline audit `execute` event by request_id: 12
Not created by Ledgerline (manual probes and webhook tests): 7

| Run | Transfers | Over-limit payments approved first | Payroll (ESCALATE) transfers | Paid twice |
|---|---|---|---|---|
| run-a-1907.audit.jsonl | 4 | 1 of 1 | 0 | 0 |
| run-b-1908.audit.jsonl | 4 | 1 of 1 | 0 | 0 |
| run-c-1943.audit.jsonl | 4 | 1 of 1 | 0 | 0 |

Unmatched transfers (reference, amount, status):
- 2026-11-09T19:00:34+0000 probe EUR 5 PAID
- 2026-11-09T19:00:56+0000 probe-fail USD 3 CANCELLED
- 2026-11-09T19:01:55+0000 probe-paid USD 2 CANCELLED
- 2026-11-09T19:28:23+0000 m2-webhook-paid USD 25 PAID
- 2026-11-09T19:28:26+0000 m2-webhook-failed USD 25 CANCELLED
- 2026-11-09T19:29:39+0000 m2-webhook-paid2 USD 25 PAID
- 2026-11-09T19:29:41+0000 m2-webhook-failed2 USD 25 CANCELLED
```

Each run made the same four payouts: shipping (USD 6,200 LOCAL, inside the auto limit), the Berlin supplier
(EUR 7,512.85 SWIFT after a USD→EUR conversion, over the auto limit, so it waited for the card), the contractor
(USD 1,960 LOCAL, failed by simulation) and one contractor replacement.

## Webhook deliveries to `https://ledgerline-inky.vercel.app/webhooks/airwallex`

All from Airwallex's delivery client. Every one returned 200 after the HMAC-SHA256 check over
`x-timestamp` + raw body; none was a duplicate.

| Time (UTC) | Event | Transfer |
|---|---|---|
| 19:28:26 | `16f35870-…` | webhook test |
| 19:28:29 | `8c2a2786-…` | webhook test |
| 19:28:29 | `e43a0142-…` | webhook test |
| 19:28:29 | `960effd7-…` | webhook test |
| 19:28:30 | `231b0d73-…` | webhook test |
| 19:29:41 | `bb316766-…` `payout.transfer.paid` | `13b4945c-…` (webhook test) |
| 19:29:43 | `7f1e4e18-…` `payout.transfer.paid` | `71579fa0-…` (webhook test) |
| 19:29:44 | `b9c71b64-…` `payout.transfer.failed` | `71579fa0-…` |
| 19:29:44 | `4d41caff-…` `payout.transfer.cancelled` | `71579fa0-…` |
| 19:44:11 | `99ed8b9b-…` `payout.transfer.paid` | `dae0f4dd-…` shipping, run C |
| 19:44:13 | `d0b0960d-…` `payout.transfer.paid` | `f1e59cd4-…` Berlin SWIFT, run C |
| 19:44:16 | `4c2f061a-…` `payout.transfer.paid` | `45319919-…` contractor, run C |
| 19:44:17 | `89488e02-…` `payout.transfer.failed` | `45319919-…` |
| 19:44:17 | `9a8d895c-…` `payout.transfer.cancelled` | `45319919-…` |
| 19:44:19 | `8cdea436-…` `payout.transfer.paid` | `061433ff-…` contractor replacement, run C |

Runs A and B (19:07, 19:08) ran before the subscription was repointed to the production host (updated 19:28),
and no deliveries for them appear in the host logs; their webhooks were checked as signed local echoes only. The sandbox sends a `paid` event for a
transfer that later fails; Ledgerline re-reads the transfer and trusts its status, not the event name.

## Re-check on Nov 10 after the submit deploy

After the recount, one USD 1.00 LOCAL test transfer (`4b4b1f78-1fd6-4200-ad76-d2e3d3bbea4a`, reference
`submit-webhook-check`) was moved SENT → PAID to confirm the rotated signing secret on the production
deploy. Airwallex delivered `payout.transfer.paid` event `625333fb-2855-490e-a793-0ae5affbac14` and it
returned 200 at about 17:55 UTC; a request signed with a wrong secret returned 400 `invalid_signature`.
This transfer is not Ledgerline's and is not in the counts above.

## Limits of this evidence

- The audit logs from Nov 9 predate the hash chain, so they are plain JSONL. Runs since then are chained
  and verify with `python -m ledgerline.receipt verify`.
- The hostile suite runs against the mock adapter, not the sandbox, and replays an obedient model's output
  instead of calling a hosted model.
- Webhook counts come from the host's logs for Nov 9. The public console does not keep state between
  serverless instances.
