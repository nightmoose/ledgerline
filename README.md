# Ledgerline

An adaptive treasury controller for the Airwallex demo host. When cash is short across USD, EUR, and GBP, Ledgerline chooses **FUND**, **CONVERT-MIN**, **DEFER**, or **ESCALATE** for each obligation due inside 72 hours. Limits, the reserve floor, quote age, and duplicate protection live in code (`policy/limits.yaml`). Anything over a limit waits for a person. A prompt cannot change the action.

Entry for the Airwallex Agentic Banking Hackathon, Track 1 (Adaptive Treasury Controller), with one payment-failure beat from Track Kit 3.

The default mode is **mock**. It runs the full demo and the tests with no credentials and no network. Live mode is the same interface pointed at the Airwallex demo or sandbox host.

## Setup

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Run the scripted demo:

```bash
python -m ledgerline.demo
```

Open the console:

```bash
uvicorn ledgerline.main:app --reload
```

Then use **Prepare demo**, approve the supplier card, and **Settle approved plan**. **Run full demo** does those steps in one pass. Pages: `/` console, `/trace` decision trace, `/policy` limit editor.

Checks:

```bash
ruff check src tests
pytest
```

## Mock and live mode

`LEDGERLINE_MODE=mock` (the default) uses an in-memory wallet. It follows the kit's documented behavior:

- amounts are major units
- FX quotes are single-use
- `request_id` retries return the original object
- reusing a `request_id` for a different body returns `duplicate_request_id`
- a SWIFT payout adds a flat EUR 12.85 fee; LOCAL payouts have no fee
- a failed transfer ends as `CANCELLED` with `failure_type`
- `SENT` stays in flight

`LEDGERLINE_MODE=live` calls the REST API. The client reads `AIRWALLEX_CLIENT_ID` and `AIRWALLEX_API_KEY` from the environment. They are never written to the repo.

The base URL comes from `AIRWALLEX_BASE_URL` when that variable is set. Otherwise `AIRWALLEX_ENV` selects the host:

| `AIRWALLEX_ENV` | Host |
|---|---|
| `demo` (default) | `https://api-demo.airwallex.com` |
| `sandbox` | `https://api.sandbox.airwallex.com` |

`AIRWALLEX_ENV=production` is rejected. Login is `POST /api/v1/authentication/login` with `x-client-id` and `x-api-key`. A 201 response carries `token` and `expires_at`. The token is reused until about a minute before `expires_at` (about 30 minutes on these hosts). FX calls do not send `x-api-version`.

A 401 body of `{"code":"unauthorized","message":"Insufficient permissions"}` is reported as **insufficient permissions**. That means the key is missing a scope. It is not treated as a bad client id or api key.

## Architecture

1. **Adapter.** One interface, two implementations: `MockAirwallex` and `LiveAirwallex`.
2. **Contracts.** Obligations and ledger rows are validated before planning. Minor units and duplicate ids are quarantined.
3. **Forecast.** A 72-hour view per currency. Confidence starts from bank and invoice agreement. Unstructured text can only lower it.
4. **Policy.** `policy/limits.yaml` sets the reserve floor, confidence-scaled FX auto limits, the transfer auto limit, quote age, the verified-beneficiary rule, and whether a no-penalty bill can be deferred.
5. **Tools.** `propose_plan`, `request_quote`, and `explain`. There is no tool that creates a conversion or a transfer.
6. **Approval.** A card is bound to amount, currency, counterparty, `quote_id`, and an evidence hash. Any change voids it.
7. **Executor.** Stable `request_id` values, one in-flight transfer per obligation, and polling that treats `SENT` as still in flight.
8. **Webhooks.** HMAC-SHA256 over the `x-timestamp` string plus the raw body. Event ids are deduped. A batch is applied in `created_at` order.
9. **Replan.** A balance change recomputes only the obligations that currency can affect, and writes a diff.
10. **Audit.** Append-only `data/audit.jsonl`, with a SQLite mirror. Replay reads the JSONL file.

The optional reader is Anthropic or xAI when `LEDGERLINE_MODEL_PROVIDER` is `anthropic` or `xai` and both `LEDGERLINE_MODEL` and the matching API key are set. Otherwise the offline reader is used. It does not raise confidence and it cannot move money.

## Demo

`python -m ledgerline.demo` walks this book, defined in `src/ledgerline/scenario.py`:

1. A duplicate ledger row and a minor-unit row are quarantined.
2. Five obligations are loaded (shipping USD, Berlin supplier EUR SWIFT, SaaS GBP, payroll EUR, contractor USD) and the wallet is seeded.
3. The ACME receipt is scored from agreeing bank and invoice evidence.
4. Plan v1 funds shipping, converts the minimum for the supplier, defers SaaS, escalates payroll, and defers the contractor.
5. A customer email that says the payment will slip lowers confidence from the agreed-evidence score to the contradiction cap in `limits.yaml`. The supplier conversion stays CONVERT-MIN and now needs approval. The email cannot force payroll to FUND.
6. A USD deposit is applied. The diff changes only the contractor, from DEFER to FUND.
7. The supplier card is bound to the quote. Execution is refused until it is approved.
8. The conversion settles, the SWIFT transfer is paid, and the webhook is reconciled.
9. The contractor transfer goes SENT (still in flight), then FAILED. The mock records CANCELLED plus `failure_type`. A replacement uses a new `request_id`. The in-flight lock rejects a second replacement.
10. The run stops only if every reserve is still at or above its floor, and the audit log replays.

The console shows the same state. The figures on screen are the ones this run computes from `limits.yaml` and the scenario file.

## What was checked against the live host

These response shapes were observed on `https://api-demo.airwallex.com`. The live client is built around them. Login was also observed to return 201 on `https://api.sandbox.airwallex.com`.

- `GET /api/v1/balances/current` returns a JSON array. Each row has `currency`, `available_amount`, `pending_amount`, `reserved_amount`, `total_amount`, `prepayment_amount`, and `account_type`.
- `GET /api/v1/fx/rates/current?buy_currency=EUR&sell_currency=USD&sell_amount=100` returns `buy_currency`, `currency_pair`, `dealt_currency`, `rate`, `rate_details` (with `buy_amount` and `level`), `conversion_date`, and `created_at`.
- `GET /api/v1/transfers?page_size=N` returns `{items: [...]}`.
- `GET /api/v1/beneficiaries`, `/api/v1/global_accounts`, `/api/v1/fx/conversions`, and `/api/v1/deposits` require both `page_num` (0-based) and `page_size` of at least 10. Otherwise they return 400 `invalid_argument`. They return `{has_more, items}`. Deposits also return `total_count`.

The client refuses `page_size` below 10 on those four lists before sending the request.

## Assumptions

These were not called on the live host in this workspace, because the API key is not stored here. The live client sends the kit paths and the fields below. If the host rejects one of them, the error code from Airwallex is surfaced as-is.

- `POST /api/v1/fx/quotes/create` with `buy_currency`, `sell_currency`, one of `buy_amount` or `sell_amount`, and `validity`. `request_id` is not sent on this call.
- `POST /api/v1/fx/conversions/create` with `quote_id`, currencies, `buy_amount`, and `request_id`. The kit says spot conversions settle immediately and quotes are single-use.
- `POST /api/v1/beneficiaries/schema` and `POST /api/v1/beneficiaries/create`.
- `POST /api/v1/transfers/create` with `beneficiary_id`, currencies, `transfer_amount`, `transfer_method` (`LOCAL` or `SWIFT`), `reason`, `reference`, `fee_paid_by`, and `request_id`.
- `GET /api/v1/transfers/{id}`.
- `POST /api/v1/simulation/deposit/create` needs `amount` and `global_account_id`. Currency comes from that global account.
- `POST /api/v1/simulation/transfers/{id}/transition` with `next_status`. `FAILED` also sends `failure_type`.
- Webhooks are subscribed in the web app (Settings > Developer > Webhooks), not via the API. The signature is HMAC-SHA256 of `x-timestamp` concatenated with the raw body.
- The kit says a failed transfer ends `CANCELLED` and the caller should read `failure_type`. The mock does that. If the live host returns `FAILED` before `CANCELLED`, the executor treats both as a terminal failure and will not send a replacement while the attempt is still in flight.
- The mock's indicative cross is 0.9213 EUR per 1 USD, from `limits.yaml`. It is used only until a quote exists. It is not a live rate. `rates/current.rate` is passed through and is not used to book a conversion.
- The mock fills `account_type` with `WALLET` so balance rows have the same keys. The live client returns the server's value unchanged.
- List item fields for beneficiaries, global accounts, conversions, and deposits are passed through. Only the page envelope was specified.

## Switching the demo to the live host

1. Put the credentials in `.env` (never commit it):

```bash
LEDGERLINE_MODE=live
AIRWALLEX_ENV=demo
AIRWALLEX_CLIENT_ID=...
AIRWALLEX_API_KEY=...
AIRWALLEX_WEBHOOK_SECRET=...
AIRWALLEX_GLOBAL_ACCOUNT_USD=...
AIRWALLEX_GLOBAL_ACCOUNT_EUR=...
AIRWALLEX_GLOBAL_ACCOUNT_GBP=...
```

2. Widen the key so it can read balances, FX rates, quotes, conversions, beneficiaries, transfers, global accounts, and deposits, and can call the simulation endpoints. A key without those scopes returns insufficient permissions, not an authentication failure.
3. In the sandbox web app, add a webhook endpoint aimed at `https://<your-host>/webhooks/airwallex` for `payout.transfer.paid`, `payout.transfer.failed`, and `payout.transfer.cancelled`. Use that endpoint's secret as `AIRWALLEX_WEBHOOK_SECRET`.
4. Run `python -m ledgerline.demo --live` only after the steps above. Without `--live`, the script refuses to call the host even if `LEDGERLINE_MODE=live`.

Nothing in this repo is deployed. `vercel.json` and `api/index.py` are there so the FastAPI app can be hosted later. On Vercel the SQLite file and the JSONL log live under `/tmp` and do not survive a new instance. For a durable demo, run `uvicorn ledgerline.main:app`.

## License

MIT
