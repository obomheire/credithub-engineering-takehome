# Payment Webhook Reconciliation — QA Test Documentation

> **Environment:** `http://localhost:8137` (only environment — no staging/prod deployment exists for this take-home)
> **Interactive API docs:** `http://localhost:8137/docs` (FastAPI auto-generated Swagger UI)
> **Database:** SQLite file `takehome.db` in the project root (dev and tests use separate lifecycles — see §3)

## 1. Feature Overview

### What this feature does

A payment gateway/rail (Paystack, NIBSS GSI, core-banking system) sends a webhook every time
a borrower's repayment lands. `POST /webhooks/payments` reconciles that payment **immediately
on receipt**: it records the event, matches it to a loan, and either applies the money
(reducing the loan's outstanding balance, closing the loan if fully repaid) or rejects it
with an explicit, machine-readable reason (unknown loan, closed loan, overpayment, or
duplicate delivery). There is no separate "review and apply" step — one webhook call does
the whole thing, atomically.

### Scope of this document

- [x] REST endpoints: `POST /webhooks/payments`, `GET /payment-events`, `GET /loans`, `GET /loans/{loan_id}`
- [x] WebSocket events: **None** — this system has no realtime/WebSocket layer
- [x] Background jobs: **None** — reconciliation happens synchronously inside the request
- [x] Database tables affected: `payment_events`, `repayments`, `loans`, `audit_log`
- [x] External integrations: **None** — the "gateway" is simulated by the frontend's "Simulate incoming payment" button or by QA calling the webhook directly

### Out of scope

- The frontend UI (React/Vite) — this document is API-only.
- Provider signature verification — not implemented; auth is a static shared token (see §2, AC-01).
- Any admin/reconciliation panel — not part of the backend under test here.
- Refund, reversal, chargeback, or settlement flows — do not exist in this system.

---

## 2. Acceptance Criteria

| # | Criterion | How to verify |
|---|-----------|---------------|
| AC-01 | Request without a valid `X-Webhook-Token` header returns `401` | TC-01, TC-02 |
| AC-02 | Every incoming webhook call creates or resolves to exactly one `PaymentEvent` record — never zero, never more than one per unique `external_ref` | TC-03 through TC-10, DB check |
| AC-03 | A valid payment against an `active` loan, not exceeding outstanding balance, is applied: a `Repayment` is created, `loan.total_paid` increases by the payment amount, `PaymentEvent.status` becomes `applied` | TC-03 |
| AC-04 | When a payment brings `total_paid` to exactly `total_repayable`, the loan's `status` becomes `paid_off` | TC-04 |
| AC-05 | A payment against a non-`active` loan (`cancelled`, `paid_off`, `written_off`) is rejected with `reason=loan_not_active`; the loan is left completely untouched | TC-06 |
| AC-06 | A payment against a `loan_id` that doesn't exist is rejected with `reason=unknown_loan`; the response's `loan` field is `null` | TC-07 |
| AC-07 | A payment amount exceeding the loan's outstanding balance is rejected **in full** with `reason=overpayment` — no partial application, no `Repayment` created, loan unchanged | TC-08 |
| AC-08 | A zero or negative payment amount is rejected with `reason=invalid_amount` | TC-09 |
| AC-09 | Redelivering a webhook with an `external_ref` that has already been seen is rejected with `reason=duplicate_external_ref`; **only one `Repayment` ever exists** for that `external_ref`, no matter how many times it's redelivered | TC-10, TC-11 |
| AC-10 | Two webhooks with the *same* `external_ref` arriving concurrently: exactly one applies, the other is rejected as a duplicate — never both applied | TC-14 |
| AC-11 | Two different payments arriving concurrently against the *same* loan, together exceeding its outstanding balance: the loan's outstanding balance never goes negative — exactly one applies | TC-15 |
| AC-12 | Every successfully applied payment writes an `AuditLog` entry (`action=payment.applied`) in the same transaction as the financial change | TC-12 |
| AC-13 | Every rejected payment (except duplicates) writes an `AuditLog` entry (`action=payment.rejected`) with the reason in `detail` | TC-13 |
| AC-14 | `outstanding` values returned by any endpoint are exact (no floating-point artifacts like `9333.339999999997`), even after several fractional-amount payments | TC-16, TC-17 |
| AC-15 | `GET /payment-events`, `GET /loans`, `GET /loans/{loan_id}` continue to behave exactly as before this feature was added | TC-18 (regression) |

---

## 3. Test Environment Setup

### Prerequisites

- [ ] Python 3.11+ available
- [ ] Repo dependencies installed: `pip install -r requirements.txt` (inside a venv is recommended, e.g. `.venv`)
- [ ] Dev database seeded and API server running (see below)

### Starting the backend for manual/exploratory QA

```bash
# from the project root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed              # populates takehome.db with 6 loans + 3 historical events
uvicorn app.main:app --reload --port 8137
```

Or simply run `./run-local.sh` from the project root (also starts the frontend; Ctrl-C stops both).

**Re-seeding:** re-run `python -m app.seed` at any point to reset `takehome.db` back to the
canonical starting state below. Seeding deletes and recreates `loans` and `payment_events`
data (it does not drop the schema).

### No authentication "user accounts" — single shared webhook token

There are no user logins or roles in this system. The webhook is gated by a single static
shared secret, sent as a request header:

```
X-Webhook-Token: dev-webhook-secret
```

This value is hardcoded in `app/auth.py` (`WEBHOOK_TOKEN = "dev-webhook-secret"`) — not an
environment variable, not rotatable. Any other value, or a missing header, is rejected.

### Seed data (canonical starting state after `python -m app.seed`)

| loan_id | borrower_name | principal | total_repayable | total_paid | outstanding | status |
|---|---|---|---|---|---|---|
| 1 | Adaeze Okafor | 100000 | 112000 | 0 | 112000 | `active` |
| 2 | Bola Adeyemi | 50000 | 56000 | 28000 | 28000 | `active` |
| 3 | Chidi Nwosu | 200000 | 224000 | 224000 | 0 | `paid_off` |
| 4 | Fatima Bello | 75000 | 84000 | 0 | 84000 | `cancelled` |
| 5 | Emeka Obi | 300000 | 339000 | 100000 | 239000 | `written_off` |
| 6 | Ngozi Eze | 33333 | 37333.33 | 0 | 37333.33 | `active` |

Historical `payment_events` are also seeded (already-reconciled history, so the feed isn't
empty on first load): `PSK-8001` (applied, loan 2), `PSK-8002` (applied, loan 3), `PSK-8003`
(rejected, loan 4).

> **Tip for QA:** loans 1, 2, and 6 (`active`) are your primary targets for the happy-path and
> money-precision scenarios below. Loan 4 (`cancelled`) is the fixed target for the
> inactive-loan rejection scenario. Loans 3 (`paid_off`) and 5 (`written_off`) are useful for
> confirming `loan_not_active` triggers on every non-`active` status, not just `cancelled`.

### Database verification

`takehome.db` is a plain SQLite file in the project root. To inspect state directly:

```bash
sqlite3 takehome.db "SELECT id, external_ref, loan_id, amount, status, reason FROM payment_events ORDER BY id DESC;"
sqlite3 takehome.db "SELECT id, loan_id, payment_event_id, amount FROM repayments;"
sqlite3 takehome.db "SELECT id, action, entity, entity_id, detail FROM audit_log ORDER BY id DESC;"
sqlite3 takehome.db "SELECT id, total_paid, status FROM loans;"
```

### How the automated test suite differs from the manual dev DB

`pytest` does **not** use `takehome.db` seeded state. `tests/conftest.py`'s `client` fixture
drops and recreates every table fresh for **each individual test**, then inserts exactly two
loans:

| loan_id | outstanding | status |
|---|---|---|
| 1 | 56000 | `active` |
| 2 | 11000 | `cancelled` |

Running `pytest` does not require running `python -m app.seed` first, and does not touch your
manually-seeded `takehome.db`. Run tests with:

```bash
pytest                 # from repo root, with the venv active
# or
.venv/bin/python -m pytest -v
```

---

## 4. API Reference (QA Cheat Sheet)

### `POST /webhooks/payments`

| Property | Value |
|----------|-------|
| Auth required | Yes — `X-Webhook-Token: dev-webhook-secret` header |
| Success status | `200 OK` — **always**, once authenticated. Business outcomes (applied/rejected) are reported in the response body, not via HTTP status. |

**Request body:**

```json
{
  "external_ref": "PAY-12345",
  "loan_id": 1,
  "amount": 20000,
  "channel": "paystack"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `external_ref` | `string` | Yes | The rail's own payment ID — this is the idempotency key. Unique per successful/first delivery. |
| `loan_id` | `integer` | Yes | Need not correspond to an existing loan — an unknown ID produces a `rejected`/`unknown_loan` outcome, not a 404. |
| `amount` | `number` | Yes | Any JSON number; negative/zero values are valid *requests* but rejected as a *business outcome* (`invalid_amount`). |
| `channel` | `string` | No | Defaults to `"paystack"` if omitted. Free text — not validated against an enum. |

**Success response — applied (`200`):**

```json
{
  "event": {
    "id": 4,
    "external_ref": "PAY-12345",
    "loan_id": 1,
    "amount": 20000.0,
    "channel": "paystack",
    "status": "applied",
    "reason": null,
    "received_at": "2026-08-14T22:23:56.920203",
    "processed_at": "2026-08-14T22:23:56.920203"
  },
  "loan": {
    "id": 1,
    "borrower_name": "Adaeze Okafor",
    "principal": 100000.0,
    "total_repayable": 112000.0,
    "total_paid": 20000.0,
    "outstanding": 92000.0,
    "status": "active"
  }
}
```

**Rejected response (still `200`):** same shape, with `event.status = "rejected"` and
`event.reason` set to one of the codes below. `loan` is `null` only for `unknown_loan`;
otherwise it reflects the loan's state (which will be **unchanged** by the rejected payment).

**Reason codes** (exact strings — check for these literal values in tests, not prose):

| `reason` | Meaning |
|---|---|
| `unknown_loan` | `loan_id` does not correspond to any loan in the database |
| `loan_not_active` | Loan exists but its `status` is not `active` (covers `cancelled`, `paid_off`, `written_off` uniformly) |
| `invalid_amount` | `amount` is `<= 0` |
| `overpayment` | `amount` exceeds the loan's current outstanding balance |
| `duplicate_external_ref` | This `external_ref` has already been seen (applied or rejected) — a redelivery |

**Error responses:**

| Status | Cause |
|--------|-------|
| `401` | Missing or incorrect `X-Webhook-Token` header |
| `422` | Malformed request body — missing required field, wrong JSON type (FastAPI/Pydantic validation, not a business rejection) |

> **Important distinction for QA:** `401` and `422` are infrastructure/validation failures.
> Every *business* outcome — even "this loan doesn't exist" or "this is a duplicate" — is a
> `200` with details in the body. Do not report a rejected/duplicate/overpayment case as a bug
> just because the HTTP status is `200`; that is the documented, intended contract (AC-07 through AC-09).

---

### `GET /payment-events`

| Property | Value |
|----------|-------|
| Auth required | No |
| Success status | `200 OK` |

Returns all `PaymentEvent` records, newest first (`id` descending). Same per-event shape as
the `event` object above. No pagination, no filtering — returns the full table.

---

### `GET /loans`

| Property | Value |
|----------|-------|
| Auth required | No |
| Success status | `200 OK` |

Returns all loans as a JSON array. Per-loan shape:

```json
{
  "id": 1,
  "borrower_name": "Adaeze Okafor",
  "principal": 100000.0,
  "total_repayable": 112000.0,
  "total_paid": 0.0,
  "outstanding": 112000.0,
  "status": "active"
}
```

`status` is one of: `active`, `paid_off`, `cancelled`, `written_off`.

---

### `GET /loans/{loan_id}`

| Property | Value |
|----------|-------|
| Auth required | No |
| Success status | `200 OK` |

Same per-loan shape as above, for a single loan.

**Error responses:**

| Status | Cause |
|--------|-------|
| `404` | `loan_id` does not exist |

---

## 5. WebSocket Events

**Not applicable.** This system has no WebSocket/realtime layer. The frontend polls/re-fetches
REST endpoints; there is nothing to test here.

---

## 6. Background Jobs

**Not applicable.** Reconciliation is fully synchronous — the `POST /webhooks/payments` call
does the recording, matching, applying/rejecting, balance update, and audit logging all within
the single HTTP request/response cycle. There is no queue, no worker, no async side effect to
wait for.

---

## 7. Test Scenarios

Each scenario is self-contained. `TOK` below always means the header
`X-Webhook-Token: dev-webhook-secret`. Steps assume the canonical seed state from §3 unless
a scenario's own prior steps have already changed it — run scenarios against a freshly
reseeded DB (`python -m app.seed`) if you need a clean baseline, or track state as you go.

### TC-01 — Missing token is rejected

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST /webhooks/payments` with a valid body, **no** `X-Webhook-Token` header | `401` |
| 2 | Verify DB: no new `payment_events` row was created | Confirmed — auth failure happens before any DB write |

### TC-02 — Invalid token is rejected

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST /webhooks/payments` with a valid body and `X-Webhook-Token: wrong-token` | `401` |

### TC-03 — Happy path: partial payment applies and reduces outstanding

**Setup:** loan 1, `outstanding = 112000`, `active`.

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST /webhooks/payments` `{"external_ref":"QA-01","loan_id":1,"amount":20000}` with `TOK` | `200`; `event.status = "applied"`; `event.reason = null` |
| 2 | `GET /loans/1` | `total_paid = 20000`, `outstanding = 92000`, `status = "active"` (still active — not fully repaid) |
| 3 | DB check: `repayments` table | Exactly one new row: `loan_id=1`, `amount=20000`, `payment_event_id` matching the event's `id` |

### TC-04 — Exact payoff closes the loan

**Setup:** loan 1, `outstanding = 112000`, `active` (fresh state).

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST /webhooks/payments` `{"external_ref":"QA-02","loan_id":1,"amount":112000}` with `TOK` | `200`; `event.status = "applied"` |
| 2 | `GET /loans/1` | `total_paid = 112000`, `outstanding = 0`, **`status = "paid_off"`** |
| 3 | `POST /webhooks/payments` `{"external_ref":"QA-03","loan_id":1,"amount":10}` with `TOK` (payment against the now-closed loan) | `200`; `event.status = "rejected"`, `event.reason = "loan_not_active"`; loan untouched |

### TC-05 — Partial repayment keeps loan active

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | Loan 2 starts `outstanding = 28000`, `active`. `POST` `{"external_ref":"QA-04","loan_id":2,"amount":5000}` with `TOK` | `200`; applied |
| 2 | `GET /loans/2` | `outstanding = 23000`; `status` still `"active"` |

### TC-06 — Payment against a non-active loan is rejected

Run once per status to confirm `loan_not_active` isn't `cancelled`-specific.

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-05","loan_id":4,"amount":100}` with `TOK` (loan 4 = `cancelled`) | `200`; `reason = "loan_not_active"`; `GET /loans/4` shows `total_paid` and `outstanding` **unchanged** |
| 2 | `POST` `{"external_ref":"QA-06","loan_id":5,"amount":100}` with `TOK` (loan 5 = `written_off`) | `200`; `reason = "loan_not_active"`; loan 5 unchanged |
| 3 | `POST` `{"external_ref":"QA-07","loan_id":3,"amount":100}` with `TOK` (loan 3 = already `paid_off`) | `200`; `reason = "loan_not_active"`; loan 3 unchanged |

### TC-07 — Unknown loan is rejected

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-08","loan_id":99999,"amount":100}` with `TOK` | `200`; `event.status = "rejected"`, `event.reason = "unknown_loan"`, **`loan` field in response is `null`** |
| 2 | DB check: `payment_events` | A row for `QA-08` was still created (loan_id 99999, status rejected) — the event is recorded even though the loan doesn't exist |

### TC-08 — Overpayment is rejected in full (no partial application)

**Setup:** loan 1 or 2, note current `outstanding`.

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` an amount strictly greater than the loan's current `outstanding`, e.g. `{"external_ref":"QA-09","loan_id":1,"amount":999999}` with `TOK` | `200`; `reason = "overpayment"` |
| 2 | `GET /loans/1` | `total_paid` and `outstanding` **exactly unchanged** from before step 1 — no partial credit |
| 3 | DB check: `repayments` | No new row was created |

### TC-09 — Invalid (zero/negative) amount is rejected

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-10","loan_id":1,"amount":0}` with `TOK` | `200`; `reason = "invalid_amount"` |
| 2 | `POST` `{"external_ref":"QA-11","loan_id":1,"amount":-500}` with `TOK` | `200`; `reason = "invalid_amount"` |

### TC-10 — Sequential duplicate delivery only applies once

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-12","loan_id":1,"amount":10000}` with `TOK` | `200`; `event.status = "applied"`; note the returned `event.id` and `event.received_at` |
| 2 | Immediately re-send the **exact same body** (simulating a rail redelivery) | `200`; `event.status = "rejected"`, `event.reason = "duplicate_external_ref"` |
| 3 | Compare the two responses' `event.id` and `event.received_at` | **Identical** — the duplicate response references the original event, not `null` (see §9 Known Limitations for the reasoning) |
| 4 | `GET /loans/1` | Balance reflects the payment being applied **exactly once** |
| 5 | DB check: `repayments` filtered by that loan | Exactly one row for this `external_ref`'s amount |

### TC-11 — Duplicate detection works even for a redelivery of a *rejected* payment

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-13","loan_id":99999,"amount":100}` with `TOK` (unknown loan — rejected) | `200`; `reason = "unknown_loan"` |
| 2 | Re-send the identical body | `200`; `reason = "duplicate_external_ref"` — **not** `unknown_loan` again. Once an `external_ref` has been seen at all (applied or rejected), any redelivery is a duplicate, regardless of the original outcome. |

### TC-12 — Applying a payment writes an audit log entry

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` a valid applying payment, e.g. `{"external_ref":"QA-14","loan_id":1,"amount":5000}` with `TOK`; note the returned `event.id` | `200`; applied |
| 2 | DB check: `sqlite3 takehome.db "SELECT * FROM audit_log WHERE action='payment.applied' ORDER BY id DESC LIMIT 1;"` | One row exists; `entity='loan'`, `entity_id` = the loan's id; `detail` contains the payment event's id, the `external_ref`, and the amount |

### TC-13 — Rejecting a payment (non-duplicate) writes an audit log entry

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-15","loan_id":99999,"amount":100}` with `TOK` (unknown loan) | `200`; rejected |
| 2 | DB check: `sqlite3 takehome.db "SELECT * FROM audit_log WHERE action='payment.rejected' ORDER BY id DESC LIMIT 1;"` | One row exists; `entity='payment_event'`; `detail` contains `unknown_loan` |
| 3 | Repeat TC-11's duplicate scenario and check for a *second* `payment.rejected` row for the duplicate attempt | **No new row** — duplicates intentionally do not get a fresh audit entry, since no new `PaymentEvent` is persisted for them (documented limitation, see §9) |

### TC-14 — Concurrency: same `external_ref` racing (requires a scripted client, not manual curl)

This scenario requires firing two requests as close to simultaneously as possible — timing
this reliably by hand with two terminal windows is not realistic. Use the automated regression
test instead, or a small script with real threads/async requests hitting the running server at
the same time.

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | Fire two `POST` requests with the **identical** `external_ref` (e.g. `RACE-1`) against the same loan, as close to simultaneously as possible | Exactly one response has `event.status = "applied"`; the other has `"rejected"` / `reason = "duplicate_external_ref"` |
| 2 | DB check: `repayments` for that loan/ref | Exactly **one** row — never zero, never two |
| 3 | `GET /loans/{id}` | Balance reflects the payment applied exactly once |

**Automated equivalent (recommended for QA sign-off):**
`pytest tests/test_payments.py::test_concurrent_duplicate_external_ref_applies_only_once -v`
This test uses `threading.Barrier` to line up two real threads hitting the endpoint at the
same instant, then asserts on both the response and the DB state.

### TC-15 — Concurrency: two different payments racing on the same loan never overdraw it

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | Fire two `POST` requests with **different** `external_ref`s against the same loan, where each individual amount is valid but the sum of both exceeds the loan's outstanding balance, as close to simultaneously as possible | Exactly one applies; the other is rejected as `overpayment` (evaluated against the *already-updated* balance from the winner) |
| 2 | `GET /loans/{id}` | `outstanding` is **never negative** |

**Automated equivalent:**
`pytest tests/test_payments.py::test_concurrent_payments_same_loan_never_overdraw -v`

> **Note on concurrency test strength:** the dev/test database is SQLite, which does not
> provide real row-level locking — `SELECT ... FOR UPDATE` is effectively a no-op there. The
> actual serialization guarantee in this environment comes from SQLite's own single-writer
> behavior at the file level. The code additionally uses `with_for_update()` when loading the
> loan, which is the correct mechanism for the system's intended production database
> (PostgreSQL, per `app/db.py`'s own docstring) but isn't meaningfully exercised by SQLite here.
> Treat TC-14/TC-15 as strong regression tests, not as proof the system is safe under
> PostgreSQL-grade concurrent load — that would require testing against a real PostgreSQL
> instance.

### TC-16 — Money precision: exact payoff on a loan with fractional amounts

**Setup:** loan 6, `total_repayable = 37333.33`, `total_paid = 0`, `active`.

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-16","loan_id":6,"amount":37333.33}` with `TOK` | `200`; `event.status = "applied"` (not incorrectly rejected as an overpayment due to float comparison error) |
| 2 | `GET /loans/6` | `outstanding = 0` exactly (not `0.00000000001` or similar); `status = "paid_off"` |

### TC-17 — Money precision: accumulated fractional payments don't cause a false overpayment rejection or a corrupted displayed balance

This is a regression scenario for a real bug found during backend QA (see `NOTES.md`).

**Setup:** loan 1, fresh state, `outstanding = 112000` (reseed first, or use loan 2 at `28000`
outstanding and adjust the numbers below proportionally).

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST` `{"external_ref":"QA-17a","loan_id":1,"amount":46666.66}` with `TOK` | Applied |
| 2 | `GET /loans/1` | `outstanding` displays as a clean value with no trailing float artifacts (e.g. `65333.34`, never `65333.33999999997`-style output) |
| 3 | `POST` a second payment for the *exact* remaining outstanding amount shown in step 2 | Must be **applied**, and must close the loan (`status = "paid_off"`) — must **not** be rejected as `overpayment` due to accumulated float drift |

If step 3 is ever rejected as `overpayment` when the amount sent exactly matches what step 2
displayed, that is a critical regression — this is precisely the bug that was found and fixed
during backend implementation.

### TC-18 — Regression: existing read endpoints are unaffected

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `GET /health` | `200`, `{"status": "ok"}` |
| 2 | `GET /loans` | `200`; array of all loans, unchanged shape |
| 3 | `GET /loans/999` (non-existent) | `404` |
| 4 | `GET /payment-events` | `200`; array including both seeded history and everything created during this test pass, newest first |

---

### Required scenario coverage checklist

- [x] TC-happy-path — TC-03, TC-04, TC-05
- [x] TC-auth-missing — TC-01
- [x] TC-auth-invalid — TC-02
- [x] TC-validation — malformed body → `422` (not separately numbered above; verify with e.g. `POST` missing `loan_id`)
- [x] TC-not-found (loan) — TC-07 (business rejection, not HTTP 404 — this is intentional, see §4)
- [x] TC-not-found (loan detail endpoint) — TC-18 step 3 (`GET /loans/999` → `404`, this one *is* a real 404)
- [x] TC-business-rule — TC-06, TC-08, TC-09, TC-10
- [x] TC-state-transition (`active → paid_off`) — TC-04
- [x] TC-invalid-state-transition (payment against closed loan) — TC-04 step 3, TC-06
- [x] TC-concurrency — TC-14, TC-15
- [x] TC-money-precision — TC-16, TC-17
- [x] TC-audit-side-effect — TC-12, TC-13
- [ ] TC-websocket-event — not applicable, no WebSocket layer
- [ ] TC-background-job — not applicable, fully synchronous
- [ ] TC-pagination — not applicable, no list endpoint paginates

---

## 8. State Machine — Loan status

```
                 ┌──────────────┐
                 │    active    │◄── initial state (set at loan creation/seed)
                 └──────┬───────┘
                        │ payment brings total_paid == total_repayable exactly
                        ▼
                 ┌──────────────┐
                 │   paid_off   │  (terminal — no further payments accepted)
                 └──────────────┘

     `cancelled` and `written_off` are also terminal-for-payments states,
     but this system's webhook has no transition INTO them — they only
     appear in seed data. No endpoint under test drives a loan into
     `cancelled` or `written_off`.
```

| Transition | Trigger | Side effects |
|-----------|---------|--------------|
| `active → paid_off` | `POST /webhooks/payments` with an amount that brings `total_paid` to exactly `total_repayable` | `Repayment` created, `AuditLog` entry (`payment.applied`) written, `PaymentEvent.status = applied` |

**Invalid transitions** (must be rejected, not silently accepted or erroring):

| Attempted action | Expected outcome |
|---------------------|----------------|
| Payment against a loan already `paid_off` | `200`, `reason = "loan_not_active"`, loan and balances unchanged |
| Payment against a `cancelled` loan | `200`, `reason = "loan_not_active"`, loan and balances unchanged |
| Payment against a `written_off` loan | `200`, `reason = "loan_not_active"`, loan and balances unchanged |
| Payment amount that would push `total_paid` above `total_repayable` | `200`, `reason = "overpayment"`, **entire** payment rejected, no partial credit toward the loan |

---

## 9. Known Limitations & Gotchas

- **HTTP status is not the signal for business failure.** `401` only ever means "bad/missing
  webhook token." Everything else — unknown loan, closed loan, overpayment, duplicate — is a
  `200` with the outcome in the response body. Do not file these as bugs based on status code
  alone; check `event.status` and `event.reason`.
- **Duplicate responses reuse the original event's `id`/`received_at`/`processed_at`.** No
  second `PaymentEvent` row is ever persisted for a redelivery (that's how the idempotency
  guarantee is enforced at the DB level), so the response for a duplicate is a
  reconstructed object referencing the *original* event's identity/timestamps, not the
  redelivery's own receipt time. This is intentional — it lets a caller trace the duplicate
  back to `GET /payment-events` to find out what actually happened — but it means
  `received_at`/`processed_at` on a duplicate response describe when the *original* landed,
  not when this redelivery arrived.
- **Duplicate redeliveries don't get their own audit log entry.** Only the original
  apply/reject outcome for a given `external_ref` is audited (TC-13 step 3). A high-volume
  redelivery storm would currently be invisible in the audit trail beyond the original event —
  flagged as a gap in `NOTES.md`, not fixed.
- **The webhook token is a single hardcoded shared secret**, not per-integration, not
  rotatable, not a real provider signature. Anyone with the string `dev-webhook-secret` can
  call the endpoint. There is no replay protection beyond `external_ref` uniqueness (no
  timestamp window, no nonce).
- **`channel` is unvalidated free text.** Sending `"channel": "anything-at-all"` is accepted —
  there's no enum check. Don't expect a `422` for an unusual channel value.
- **Concurrency guarantees are strongest evidence, not a proof, on SQLite.** See the note under
  TC-15 — this test environment's database doesn't support real row-level locking, so the
  concurrency tests demonstrate correct behavior under SQLite's own single-writer semantics
  rather than proving safety under PostgreSQL-grade concurrent load.
- **Loan `outstanding` display was previously float-inaccurate; this is fixed, but watch for
  regressions.** Two backend bugs (both fixed, both regression-tested — TC-16/TC-17 above)
  involved plain `float` subtraction producing values like `9333.339999999997` instead of
  `9333.34`, in both the reconciliation *decision* and the *displayed* value. If either
  reappears in a future change, it will most likely surface as a payment that should apply
  cleanly (its amount exactly matches the displayed outstanding balance) being wrongly
  rejected as `overpayment`, or as a suspicious-looking many-decimal-digit `outstanding` value
  in a `GET /loans` response.
- **No pagination anywhere.** `GET /payment-events` and `GET /loans` always return the full
  table. This is fine for take-home-scale seed data; don't expect `cursor`/`limit`/`page`
  query parameters — none exist.

---

*Generated by the `write-qa-docs` skill for the CreditHub payment webhook reconciliation
backend. Update this document if `app/payments.py`, `app/services/payment_reconciliation.py`,
`app/loans.py`, or `app/models.py` change behavior.*
