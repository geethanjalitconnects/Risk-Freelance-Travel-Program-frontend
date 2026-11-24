# Payments, refunds and Route: setup, test plan and security review

All money is integer paise; all maths is in `apps/payments/money.py`. Every money change is
written to the immutable earnings ledger and/or the financial audit log.

## Switches (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | empty | Payment Gateway keys. **Test keys (`rzp_test_…`) in development.** |
| `RAZORPAY_WEBHOOK_SECRET` | empty | Secret set on the webhook in the Razorpay Dashboard. Without it every webhook is rejected. |
| `PAYMENTS_ENABLED` | False | On: bookings wait in `pending_payment` until the payment is verified on the server. |
| `ROUTE_ENABLED` | False | **Keep off until Razorpay approves Route.** Off: no transfers, releases or reversals are sent. |
| `PAYOUTS_ENABLED` | False | Driver withdrawals. Work only when Route is on too. |
| `ROUTE_COOLING_HOURS` | 24 | Wait after a linked account is activated before its first transfer (to confirm with Razorpay). |
| `ROUTE_PROFILE_CATEGORY` / `_SUBCATEGORY` | transport / cab_hailing | Linked-account business category (to confirm with Razorpay). |

Production refuses to start with payments on but missing keys or webhook secret, or with test keys
(unless `RAZORPAY_ALLOW_TEST_KEYS=True` on a staging server).

## Scheduled jobs (cron / Windows Task Scheduler)

| Command | Every | Does |
|---|---|---|
| `expire_payment_holds` | 1 min | Releases seats of unpaid bookings whose 10-minute hold ran out |
| `process_refunds` | 5 min | Resends refunds Razorpay didn't accept (network errors) |
| `auto_complete_bookings` | 15 min | Completes rides 24 h after arrival when no problem was reported |
| `process_route` | 5 min | Route only: sends queued transfers, retries pending releases |
| `reconcile_earnings` | daily | Checks every balance against the ledger; exits 1 on a mismatch |
| `retry_failed_emails` | 5 min | (existing) |

## Money flow

```
book            -> pending_payment, seats held 10 min
pay             -> one Razorpay order per booking (reused on retry, so it can't be paid twice)
Checkout ok     -> server checks the signature AND fetches the payment from Razorpay -> confirmed
webhook         -> payment.captured does the same (whichever comes first; the other is a no-op)
confirmed       -> ledger: publisher's 90% of the ride amount HELD
                   Route on: transfer of that 90% to the linked account, settlement on hold
both confirm    -> ledger: held -> available (auto 24 h after arrival unless a problem is reported)
withdraw        -> Route: penalties owed are recovered by partially reversing a held transfer,
                   then the eligible transfers are released; transfer webhooks mark it paid
cancel          -> Route: the held transfer is reversed first, then the refund goes to the
                   original payment method (85% / 90% / 100% per the rules)
```

## Webhooks

URL: `https://<your-domain>/api/v1/payments/razorpay/webhook`. Locally, Razorpay can't reach
`127.0.0.1`: use a tunnel (`cloudflared tunnel --url http://127.0.0.1:8000` or ngrok) and put the
tunnel URL in the Dashboard. Without webhooks, local payments still confirm through the verify step.

Events to enable: `payment.captured`, `payment.failed`, `payment.authorized`, `order.paid`,
`refund.processed`, `refund.failed`, and for Route `transfer.processed`, `transfer.failed`,
`settlement.processed`. Unknown events are stored and ignored.

## Manual test checklist (Razorpay TEST mode)

Use the test cards / test UPI ids from Razorpay's "Test card details" docs page. No real money moves.

1. Set `PAYMENTS_ENABLED=True` and the test keys, then restart the backend.
2. **Happy path.** As a passenger, open a ride. The confirm dialog shows fare + 10% platform fee = total.
   Pay with a success test card. The booking shows **Confirmed**, the Trip log says "Payment of ₹… received",
   and the Django admin shows the Payment *captured*, the audit row and the driver's held earning.
3. **Closed window.** Close Checkout. The message says the seats are held. My trips shows **Pay** and the hold time; pay from there.
4. **Failed payment.** Use a failure test card. The booking stays awaiting payment, and retrying works.
5. **Hold expiry.** Book and don't pay. After 10 minutes run `expire_payment_holds`: the booking is **Expired** and the seat is free again.
6. **Passenger cancel > 24 h.** Cancel a paid booking for a ride 2+ days away. The dialog shows an 85% refund.
   The refund appears in the Razorpay Dashboard (Refunds) and in the Wallet → Payments and refunds tab.
7. **Passenger cancel < 24 h.** For a ride departing within 24 h, the dialog shows 90%.
8. **Driver cancel.** Cancel a booked ride. Every passenger is refunded 100%. Within 24 h, the driver's Wallet shows the 10% penalty (owed or deducted).
9. **Completion.** Both sides swipe complete. The driver's Wallet moves the earning from On hold to Available.
10. **Webhooks** (with a tunnel + secret): repeat 2; the webhook log in the Django admin shows *processed*.
    Redelivering the event from the Dashboard shows *duplicate*, and nothing happens twice.
11. **Tampering.** Call `/payment/verify` with a wrong signature: 400, booking unchanged, audit row `payment_failed`.
12. `reconcile_earnings` reports every account reconciles.

## Route: what must happen before `ROUTE_ENABLED=True`

The test keys don't have Route: `/v1/transfers` and `/v2/accounts` both answer "not found" (checked 2026-11-20).

**Razorpay Dashboard configuration:**
1. Get Route activated on the account (Dashboard → Route, or Support). Razorpay reviews the use case:
   turnover proof or GST self-declaration, plus a description showing the driver serves the passenger directly.
2. Enable Route in **Test mode** too, so this integration can be tested before live.
3. Check the account's **settlement schedule** (Route settlements can't be faster than the main account's).
4. Create the webhook (URL above) with a strong secret, subscribed to the events listed above.
5. Turn on **automatic capture** of payments (Settings → Payment capture). The code captures
   "authorized" payments itself as a fallback.
6. **Payouts to linked accounts:** confirm that transfers can be created with `on_hold: true` and
   released later with `PATCH /transfers/:id {"on_hold": false}` on this account.

**Questions to confirm with Razorpay in writing:**
- Linked-account onboarding for an **individual driver**: required KYC (PAN? Aadhaar? bank proof), which business
  category and subcategory to use, and whether `stakeholders` + the `route` product with bank settlements is the right sequence.
- The **cooling period** after a linked account is activated before transfers are accepted (24 h assumed).
- The **maximum hold duration** of a transfer, and whether hold/release is enabled for this account.
- Transfer and reversal **fees**, and whether reversals of held transfers are free.
- Whether `X-Razorpay-Idempotency` is honoured on transfers, reversals and refunds. The code also prevents
  repeats with locked rows and unique keys on its own side.
- The exact webhook event names for transfer settlement on this account.

**Then:** set `ROUTE_ENABLED=True` in a test environment, onboard one test driver (`route.onboard`),
and run through test plan steps 2, 6, 8 and 9, plus a withdrawal. Only after that run, enable `PAYOUTS_ENABLED`.

## Security review (Phase 9)

| Area | Status |
|---|---|
| Secrets | Only in `.env` (gitignored); `.env.example` has placeholders. The key secret never reaches the browser; only the public key id does. Razorpay errors are logged without secrets or bodies. |
| Booking confirmation | Never from the browser alone: signature check **and** server-side fetch of the payment, order and amount from Razorpay, or a signature-verified webhook. |
| Webhooks | HMAC checked on the raw body before parsing; stored once per event id; no auth/CSRF needed and none accepted. |
| Duplicates | One order per booking; one captured payment per booking (DB constraint); refunds, transfers, reversals and ledger entries each have a unique key; rows locked while changing. |
| Amounts | Integer paise; splits proven to add up (5,000+ combinations tested); DB constraint on every cancellation; amounts frozen per booking. |
| Bank details | Fernet-encrypted with their own key; only last 4 digits / masked UPI shown; never logged, never in errors or audit details; owner-only API; edits rate-limited and audited. |
| Withdrawals | Off until Route; idempotency key per swipe; one in flight; 3/day; minimum; frozen and owed checks; rate-limited. |
| Ledger | Append-only (updates and deletes raise); daily reconciliation; balances can't go negative (DB constraint). |
| Passenger details | The driver sees a passenger's name and phone only for **their own ride** and only once the booking is **confirmed** (paid). Unpaid bookings show "N seats requested"; cancelled/expired aren't listed. Enforced in the ride serializer (`apps/bookings/privacy.py`); never in search. Phone hidden `PASSENGER_CONTACT_HOURS` (6, proposed) after arrival. |
| Admin | Money rows read-only; settings changes and freezes audited; problem decisions need a note. |

**Known limits / follow-ups**
- The test key secret was shared in chat: **regenerate it** in the Dashboard (Settings → API Keys) and update `.env`.
- Refunds Razorpay rejects outright stay *failed* for an admin (shown in the Django admin); they aren't retried automatically.
- With Route on, ledger credits not backed by a transfer (manual adjustments) can't be withdrawn through Route.
- No Content-Security-Policy yet. If one is added, allow `checkout.razorpay.com` and `api.razorpay.com`.
- The browser flows (Checkout, swipes, wallet) still need a manual pass with the checklist above.
