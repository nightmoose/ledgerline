# Ledgerline demo video plan

**Length: 4:04, under the 5-minute limit.** Order: stakes first, proof second, the walkthrough on the mock, the live sandbox run and its ids on the evidence page, then the injection test as the climax, receipts, and limits last. The narration is in `media/voiceover/narration.md` (Eve voiceover); subtitles ship with the video.

The walkthrough follows the hackathon guide's shape: **goal → initial plan → new information → revised decision → financial result**.

## Mock or sandbox: what each scene is

| Scenes | Runs on | On-screen label |
|---|---|---|
| 3–6, 8, 9 | the mock adapter, synthetic data, no Airwallex key | red bar "… mock mode · synthetic data", corner chip "local console · mock mode · synthetic data" |
| 7 | the live Airwallex demo sandbox (`api-demo.airwallex.com`), run C, Nov 9 | "Live run · Airwallex sandbox (api-demo.airwallex.com) · real output, pauses shortened" |
| 7b | the console's `/evidence` page: run C's recorded ids, read-only | "Recorded sandbox run C · read-only" |

The proof card (scene 2) separates the sandbox numbers from the hostile suite, which runs on the mock.

## Before recording

- **Console.** Use the public console at https://ledgerline-inky.vercel.app (mock mode, synthetic data) for the opening, the hostile tests page, the trace and `/evidence`. For the step-by-step scenes, a local copy is more reliable on serverless: `uvicorn ledgerline.main:app` with `LEDGERLINE_DATA_DIR` set to a fresh folder and `LEDGERLINE_CLOCK=wall`.
- **Terminal.** Dark theme, large font, repo root, credentials loaded **off screen**. Never show `.env`, `env`, or a history containing keys.
- **Live run.** Fresh `LEDGERLINE_DATA_DIR`; record in real time, shorten pauses and say so on screen.
- **Browser.** Clean profile, no bookmarks bar, zoom 110–125%.

## Scenes

| # | Screen action | On-screen text |
|---|---|---|
| 1 | Title card: "Ledgerline pays what is due across USD, EUR and GBP, and no model can move a cent." Below it, the harm: one injected sentence can drain a reserve or pay the wrong account. | the promise |
| 2 | Proof card. "Measured on the Airwallex sandbox": 3 live runs · 15 of 15 webhooks HMAC-verified · 0 over-limit payments before approval · 0 paid twice. Then, under "Hostile suite · mock adapter": 26 of 26 injections refused by code. | as listed |
| 3 | Console: **Prepare demo**. Trace rows: `quarantined led_1: duplicate_event_id`, `72h confidence 0.91`, `PLAN FUND shipping · CONVERT-MIN supplier · …`. Back on the console, highlight each action. | "The plan is decided in code" |
| 4 | Trace row `confidence 0.91 → 0.62 · auto FX limit 10000 → 3000`. Console: the supplier row now needs approval; payroll still ESCALATE. | "The email can lower confidence. It can't fund payroll." |
| 5 | Header "replanned after deposit"; trace row `obl_contractor DEFER→FUND`. | "Only the affected line changes" |
| 6 | Footer "Approval binds: amount · currency · counterparty · quote_id · evidence hash". **Approve**, then **Settle approved plan**. Rows turn PAID; contractor "Replaced · PAID". | "Approval is bound to the exact quote and evidence" |
| 7 | Terminal: `LEDGERLINE_MODE=live python -m ledgerline.demo --live` against the Airwallex demo sandbox (run C). Freeze on "Reserves hold at …". | "Live run · Airwallex sandbox" |
| 7b | Public console → **Live sandbox evidence**: highlight the Berlin SWIFT `f1e59cd4-…`, the contractor `45319919-…` SENT → FAILED, the replacement `061433ff-…`, then the 6 webhook rows. | "The same ids, recorded · read-only" |
| 8 | **Climax.** Public console → **Hostile tests**: the five class tiles, then scroll the 26 cases, highlighting A2 (CEO wire), A6 (French), B3 (rush wire to a new payee), E3 (forged webhook), E1 (pay again while SENT). End on "26 of 26 refused by code · 0 money moved". | "The model obeys every injection. Code refuses." |
| 9 | **Decision trace** with the receipt line and per-row hashes. Terminal: `python -m ledgerline.receipt verify` → OK; edit one approval line; verify again → `BROKEN at seq N`. | "Every step leaves a receipt" |
| 10 | Limits card (demo pages are a mock; only `/evidence` shows the sandbox run; default reader is deterministic; suite tests code, not a model), then the end card with the repo and console URLs. | |

## Notes

- Say "mock" for scenes 3–6 and 8–9 and "sandbox" only for scenes 7 and 7b. Do not imply the public console moved sandbox money; it holds no Airwallex key.
- The hostile suite replays a fully obedient model's output; do not caption it as a hosted model being tested.
- The default evidence reader is deterministic. A hosted model, if enabled, is under the same "can only lower confidence" cap.
- The sandbox picks the failure type itself (`INCORRECT_ROUTING`). Say "the sandbox fails it", never "the bank returned it".
- Leave out the Vercel dashboard, any terminal showing environment variables, and the policy editor.
