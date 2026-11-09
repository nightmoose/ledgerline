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

## Live run on the demo host (observed 2026-11-09)

`LEDGERLINE_MODE=live python -m ledgerline.demo --live` ran the full script end to end on `https://api-demo.airwallex.com`, twice. Each run takes about 35 seconds. What the host does, and how the client handles it:

- **Ring-fenced book.** The sandbox wallet comes pre-funded (about 10M in each of USD, EUR, and GBP). The planner works on a ring-fenced book: the live balance minus the balance seen when the run started. Set `LEDGERLINE_LIVE_BOOK=wallet` to plan against the whole wallet instead.
- **Seeding.** `POST /simulation/deposit/create` with `amount` and `global_account_id` answers `PENDING` and settles about a second later, so the service waits for the balance. The sandbox has a USD global account only, and the key cannot create others (`POST /global_accounts/create` returns 401 insufficient permissions). EUR and GBP are funded by a simulated USD deposit plus a live conversion of exactly the needed amount, so the USD side nets to zero. If `AIRWALLEX_GLOBAL_ACCOUNT_<CCY>` is unset, an ACTIVE account with a DEPOSIT feature in that currency is looked up.
- **Lists.** `GET /global_accounts` returns `{items}` with no `has_more`.
- **Quotes.** `POST /fx/quotes/create` returns `quote_id`, `client_rate`, `buy_amount`, `sell_amount`, `valid_from_at`, `valid_to_at`, and `usage: MULTI_USE`. Live mode runs on a wall clock, so quote age and webhook timestamps are compared against real time.
- **Conversions.** `POST /fx/conversions/create` with `request_id`, `quote_id`, currencies, and `buy_amount` returns `conversion_id` and `SETTLED`.
- **Beneficiaries.** Creating one needs an `address` and real-format bank details. The service uses public test values that pass `/beneficiaries/validate`:
  - USD ACH: ABA routing number plus `bank_account_category`.
  - EUR SWIFT: IBAN plus BIC.
  - EUR LOCAL: IBAN only. Setting `local_clearing_system` returns `beneficiary_type_unsupported`.
  - GBP: sort code and account number.
- **Transfers.**
  - `POST /transfers/create` returns `SCHEDULED`.
  - A SWIFT EUR payout paid by the payer charged a flat EUR 13.39 fee. Live mode plans with `swift_fee_live` in `limits.yaml`.
  - Reusing a `request_id` returns 400 `duplicate_request_id`, even for an identical body. The client looks the original up by `request_id` and returns it.
- **Simulation.**
  - `SCHEDULED → PAID` and `SCHEDULED → PROCESSING` return 500 `operation_failed`. The client moves the transfer to `SENT` first.
  - `FAILED` answers `FAILED` with a failure_type that the host chooses itself (`INCORRECT_ROUTING` was observed even when `BENEFICIARY_BANK_RETURNED` was requested). The transfer then reads `CANCELLED`.
- **Request ids.** Live request ids include a per-run id (`LEDGERLINE_RUN_ID`, random by default), so a second run does not collide with the first. Retries within a run reuse the same id.
- **Webhooks.**
  - The key can manage them over the API. `POST /api/v1/webhooks/create` takes `url`, `events`, `version`, and `request_id`, and returns the signing `secret`.
  - Real deliveries wrap the resource in `data.object`, and the receiver reads it there.
  - In the CLI, the signed events are a local echo of each transfer the host returned. Real deliveries go to `POST /webhooks/airwallex`.
