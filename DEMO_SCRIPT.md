# Ledgerline demo video plan

**Target length: about 3:40.** The narration is 416 words, about 3:00 at 140 words per minute. The rest is on-screen pauses. The narration text is also in `media/voiceover/narration.md` for the Eve voiceover.

The video follows the shape the hackathon guide asks for: **goal → initial plan → new information → revised decision → financial result**.

## Before recording

- **Console.** Use the public console at https://ledgerline-inky.vercel.app (mock mode, synthetic data). It runs on serverless functions, so press **Prepare demo** once before you start recording to warm it up. If an instance swap shows mismatched state, record scenes 2–5 from a local copy instead:
  - `uvicorn ledgerline.main:app`, with `LEDGERLINE_DATA_DIR` set to a fresh folder.
  - The local console gives the same screens and the same numbers.
- **Terminal.** Use a dark theme at a large font size, in the repo root, with credentials already loaded **off screen** (`set -a; source .env; set +a`). Never show `.env`, `env`, or a shell history that contains keys.
- **Live run.** Set a fresh `LEDGERLINE_DATA_DIR` for the CLI run. The run takes about 35 s, so record it in real time and speed up the middle 2×, with an on-screen "2× speed" label.
- **Browser.** Use a clean profile with no bookmarks bar and no other tabs visible. Zoom to 110–125% so the plan table is readable.

## Scenes

| # | Time | Screen action | On-screen text (optional) |
|---|---|---|---|
| 1 | 0:00–0:20 | Title card "Ledgerline", then cut to the console home page at https://ledgerline-inky.vercel.app. Slowly pan the three balance tiles (USD, EUR, GBP with their reserve floors) and "Due next 72h · 5 obligations". | "5 bills · 3 currencies · 72 hours" |
| 2 | 0:20–0:55 | Click **Prepare demo**. Open **Decision trace** and scroll to the top rows: `CONTRACT quarantined led_1: duplicate_event_id`, `quarantined led_2: minor_units`, `FORECAST 72h confidence 0.91`, `PLAN FUND shipping · CONVERT-MIN supplier · …`. Return to **Console**. | "Bad rows quarantined before planning" |
| 3 | 0:55–1:25 | Point at the trace row `POLICY confidence 0.91 → 0.62 · auto FX limit 10000 → 3000 USD`. Back on the console, highlight the CONVERT-MIN supplier row: "✗ over auto limit at conf 0.62 (limit 3,000.00)" with **Approve / Reject**. Highlight that payroll still reads ESCALATE ("✗ EUR reserve floor breach"). | "Email lowers confidence. It can't raise it, and can't fund payroll." |
| 4 | 1:25–1:45 | Point at the header "plan v2 — replanned after deposit" and the trace row `REPLAN … changes: obl_contractor DEFER→FUND`. The contractor row reads FUND. | "Only the affected line changes" |
| 5 | 1:45–2:10 | Zoom on the footer "Approval binds: amount · currency · counterparty · quote_id · evidence hash." Click **Approve** on the supplier card, then **Settle approved plan**. Rows turn PAID. The contractor row reads "Replaced · PAID". The tiles end at USD 12,919.67 / EUR 1,000.00 / GBP 640.00. | "Approval is bound to the exact quote and evidence" |
| 6 | 2:10–3:00 | Cut to the terminal and run `LEDGERLINE_MODE=live python -m ledgerline.demo --live`. Let the transcript print: seeded balances, the plan lines, the approval card, then the lines with real Airwallex ids for shipping, the Berlin SWIFT transfer and its conversion, the contractor transfer going SENT then FAILED, and the paid replacement. Freeze on the final "Reserves hold at …" line. | "Live: Airwallex demo sandbox" · "2× speed" over the middle |
| 7 | 3:00–3:30 | Open the public **Decision trace** and show the rows `WEBHOOK payout.transfer.paid · signature ok`, `payout.transfer.failed · signature ok` and `payout.transfer.cancelled · signature ok`. Then show the README section "Evidence from the sandbox", with its table of ids and the four webhook event ids. | "Real signed webhooks · HMAC verified" |
| 8 | 3:30–3:40 | End card: "Ledgerline", the repo URL and the console URL. | |

## Notes

- Scenes 2–5 run in mock mode on synthetic data. Scene 6 is the live sandbox run. Say this in the captions, and do not imply that the console is moving real money.
- The ids printed in scene 6 will differ from the ones in the README. Each run creates new objects. That is expected.
- The sandbox picks the failure type itself (`INCORRECT_ROUTING` in our runs). Do not caption it as "bank returned".
- Leave out: the Vercel dashboard (it shows account and team names), any terminal showing environment variables, and the policy editor (optional; cut it if the video runs over 4:00).
