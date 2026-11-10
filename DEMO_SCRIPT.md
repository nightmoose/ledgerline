# Ledgerline demo video plan

**Target length: about 3:30, hard limit under 4:00.** Order: stakes first, proof second, the walkthrough, the live sandbox run, then the injection test as the climax, receipts, and limits last. The narration is in `media/voiceover/narration.md` (Eve voiceover).

The walkthrough still follows the hackathon guide's shape: **goal → initial plan → new information → revised decision → financial result**.

## Before recording

- **Console.** Use the public console at https://ledgerline-inky.vercel.app (mock mode, synthetic data) for the opening, the hostile tests page and the trace. For the step-by-step scenes, a local copy is more reliable on serverless: `uvicorn ledgerline.main:app` with `LEDGERLINE_DATA_DIR` set to a fresh folder and `LEDGERLINE_CLOCK=wall`.
- **Terminal.** Dark theme, large font, repo root, credentials loaded **off screen**. Never show `.env`, `env`, or a history containing keys.
- **Live run.** Fresh `LEDGERLINE_DATA_DIR`; record in real time, speed up the middle 2× with a "2× speed" label.
- **Browser.** Clean profile, no bookmarks bar, zoom 110–125%.

## Scenes

| # | Screen action | On-screen text |
|---|---|---|
| 1 | Title card: "Ledgerline pays what is due across USD, EUR and GBP, and no model can move a cent." Below it, the harm: one injected sentence can drain a reserve or pay the wrong account. | the promise |
| 2 | Proof card with the sandbox numbers: 3 live runs · 15 of 15 webhooks HMAC-verified · 0 over-limit payments before approval · 0 paid twice · 26 of 26 injections refused by code. | "Measured on the Airwallex sandbox" |
| 3 | Console: **Prepare demo**. Trace rows: `quarantined led_1: duplicate_event_id`, `72h confidence 0.91`, `PLAN FUND shipping · CONVERT-MIN supplier · …`. Back on the console, highlight each action. | "The plan is decided in code" |
| 4 | Trace row `confidence 0.91 → 0.62 · auto FX limit 10000 → 3000`. Console: the supplier row now needs approval; payroll still ESCALATE. | "The email can lower confidence. It can't fund payroll." |
| 5 | Header "replanned after deposit"; trace row `obl_contractor DEFER→FUND`. | "Only the affected line changes" |
| 6 | Footer "Approval binds: amount · currency · counterparty · quote_id · evidence hash". **Approve**, then **Settle approved plan**. Rows turn PAID; contractor "Replaced · PAID". | "Approval is bound to the exact quote and evidence" |
| 7 | Terminal: `LEDGERLINE_MODE=live python -m ledgerline.demo --live` against the Airwallex demo sandbox. Freeze on "Reserves hold at …". | "Live: Airwallex demo sandbox" · "2× speed" |
| 8 | **Climax.** Public console → **Hostile tests**: the five class tiles, then scroll the 26 cases, highlighting A2 (CEO wire), A6 (French), B3 (rush wire to a new payee), E3 (forged webhook), E1 (pay again while SENT). End on "26 of 26 refused by code · 0 money moved". | "The model obeys every injection. Code refuses." |
| 9 | **Decision trace** with the receipt line and per-row hashes. Terminal: `python -m ledgerline.receipt verify` → OK; edit one approval line; verify again → `BROKEN at seq N`. | "Every step leaves a receipt" |
| 10 | Limits card (synthetic console; suite tests code, not a model), then the end card with the repo and console URLs. | |

## Notes

- Scenes 3–6 and 8–9 run in mock mode on synthetic data. Scene 7 is the live sandbox run. Say this in the captions.
- The hostile suite replays a fully obedient model's output; do not caption it as a hosted model being tested.
- Ids printed in scene 7 differ from the README; each run creates new objects.
- The sandbox picks the failure type itself (`INCORRECT_ROUTING`). Do not caption it as "bank returned".
- Leave out the Vercel dashboard, any terminal showing environment variables, and the policy editor.
