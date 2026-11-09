# Ledgerline demo narration (Eve voiceover)

One paragraph per scene. Read at a calm pace. Scene numbers match DEMO_SCRIPT.md.

## Scene 1 — The problem (0:00–0:20)
A small finance team has five bills in three currencies due in the next seventy-two hours. There isn't enough cash to pay all of them and still keep a reserve. Ledgerline decides what happens to each one, and runs those decisions on the Airwallex sandbox.

## Scene 2 — The first plan (0:20–0:55)
Ledgerline starts by refusing bad data. A duplicate ledger row and a row in cents are quarantined before planning. Then it forecasts the next seventy-two hours. Bank and invoice data agree on the expected receipt, so confidence is zero point nine one. The plan, written in code, funds the shipping invoice that keeps orders moving, converts only the gap for the Berlin supplier, defers the SaaS bill that has no late fee, and escalates payroll, because paying it would break the euro reserve floor.

## Scene 3 — New information (0:55–1:25)
Then a customer email arrives. It says the payment will slip to next week, and it tries to order the controller to ignore the reserve and fund payroll. The evidence reader can only lower confidence. Confidence drops to zero point six two, and the automatic FX limit falls from ten thousand to three thousand dollars. The same supplier conversion now waits for a person. Payroll stays escalated.

## Scene 4 — Deposit and replan (1:25–1:45)
A deposit lands in dollars. Ledgerline recomputes only the obligations that dollars can affect. One line changes: the contractor moves from defer to fund. Everything else is left as it was.

## Scene 5 — Approval binding (1:45–2:10)
The approval card is bound to the amount, the currency, the counterparty, the quote id, and a hash of the evidence. Until it is approved, execution is refused. If any of those values change, the card is void. The tools available to the model can propose, quote, and explain. None of them can move money.

## Scene 6 — Live on the sandbox (2:10–3:00)
Now the same script runs against the live Airwallex sandbox. It seeds the book with simulated deposits and real conversions. The approved quote is booked as a conversion, and the SWIFT payment to Berlin is paid. The contractor payment goes out, is marked sent, and fails at the bank. Sent is still in flight, so a second payment is blocked until the first one resolves. After the failure, one replacement goes out with a new request id, and it is paid.

## Scene 7 — Proof (3:00–3:30)
Airwallex sends signed webhooks to the public console. Every delivery passed signature verification. Real deposit, conversion, and transfer ids are in the repository. The run ends with every reserve at or above its floor, and the full audit log replays.

## Scene 8 — Close (3:30–3:40)
Ledgerline. Decisions in code, approvals bound to evidence, and money that moves once.
