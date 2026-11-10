# Ledgerline demo narration (Eve voiceover)

One paragraph per scene. Read at a calm pace. Scene numbers match DEMO_SCRIPT.md. Stakes first, proof second, the injection test as the climax, limits last.

## Scene 1 — The promise and the harm
Ledgerline pays what is due across dollars, euros and pounds, and no model can move a cent. That matters, because once an AI agent can pay bills, one sentence hidden in an email or a payee memo can drain a reserve, or pay the wrong account.

## Scene 2 — Proof first
Here is what it did on the Airwallex sandbox. Three complete live runs. Fifteen of fifteen real webhooks verified by signature. Zero over-limit payments before a person approved. Zero bills paid twice. And twenty-six of twenty-six injection attacks, refused by code.

## Scene 3 — The first plan
The book: five bills, three currencies, seventy-two hours. Bad ledger rows are quarantined before planning. Bank and invoice agree, so confidence is zero point nine one. The plan is decided in code: fund shipping, convert only the gap for the Berlin supplier, defer the SaaS bill, and escalate payroll, which would break the euro reserve floor.

## Scene 4 — New information
Then a customer email arrives. It says the payment will slip to next week, and it tries to order the controller to ignore the reserve and fund payroll. The evidence reader can only lower confidence. Confidence drops to zero point six two, and the automatic FX limit falls from ten thousand to three thousand dollars. The same supplier conversion now waits for a person. Payroll stays escalated.

## Scene 5 — Deposit and replan
A deposit lands in dollars. Ledgerline recomputes only the obligations that dollars can affect. One line changes: the contractor moves from defer to fund. Everything else is left as it was.

## Scene 6 — Approval binding
The approval card is bound to the amount, the currency, the counterparty, the quote id, and a hash of the evidence. Until it is approved, execution is refused. If any of those values change, the card is void. The tools available to the model can propose, quote, and explain. None of them can move money.

## Scene 7 — Live on the sandbox
Now the same script runs against the live Airwallex sandbox. It seeds the book with simulated deposits and real conversions. The approved quote is booked as a conversion, and the SWIFT payment to Berlin is paid. The contractor payment goes out, is marked sent, and fails at the bank. Sent is still in flight, so a second payment is blocked until the first one resolves. After the failure, one replacement goes out with a new request id, and it is paid.

## Scene 8 — The hostile test (climax)
Now the test that matters. We attacked every place text gets in: the customer email, payee names, memo fields, ledger rows, and the model's own tool calls. We assumed the worst case, a model that obeys every injection, and replayed its output through the real code. A fake CEO wire request. A French override. A rush wire to a new payee. A forged webhook. Pay again while the first is in flight. Twenty-six attacks. Twenty-six refused by code. Zero money moved. It runs in CI on every push, and on the console's hostile tests page.

## Scene 9 — Receipts
And every step leaves a receipt. Each audit event stores the hash of the one before it. The verifier confirms the chain is intact. Change one word in an approval, and it points to the exact event that was edited.

## Scene 10 — Limits and close
The limits: the public console runs on synthetic data, and the hostile suite tests our code, not a particular model. Ledgerline. Models suggest, code decides, a person approves, and every step has a receipt.
