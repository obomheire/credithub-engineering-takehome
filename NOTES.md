# NOTES

## Key decisions

### Idempotency

`external_ref` is the rail's idempotency key. `PaymentEvent.external_ref` now has a
**DB-level unique constraint** (`app/models.py`) — the database, not application code,
is the final authority on "have we seen this payment before."

`reconcile_payment` (`app/services/payment_reconciliation.py`) does an application-level
pre-check first (cheap, avoids a round trip in the common case), then attempts the
insert. If two requests race past the pre-check, the loser's `db.flush()` raises
`IntegrityError` on the constraint — caught, rolled back, and turned into a
`rejected` / `duplicate_external_ref` response. No second `PaymentEvent` row is ever
written for a redelivery; only one `Repayment` can ever exist per `external_ref`.

### Transaction strategy

One `Session` per request (FastAPI's existing `Depends(get_db)`), one `db.commit()`
per reconciliation outcome. The flow inside `reconcile_payment`:

1. Insert `PaymentEvent` (status `pending`), `flush()` — this is what surfaces a
   duplicate before any loan row is touched.
2. Load the loan with `with_for_update()`.
3. Validate → either mark the event `rejected` with a reason, or create the
   `Repayment`, update the loan, mark the event `applied`.
4. Write an audit record via the existing `record_audit` helper (adds to the same
   session, doesn't commit — by design, per its docstring).
5. Single `db.commit()` covers the event, the loan mutation (if any), the repayment
   (if any), and the audit row together. A failure anywhere before that commit rolls
   everything back — there is no path that leaves `PaymentEvent.status == applied`
   without a matching `Repayment`, updated `Loan`, and `AuditLog` row.

### Concurrency strategy

Two scenarios, two different mechanisms:

- **Same `external_ref` racing** — protected by the DB unique constraint (see
  Idempotency above). This works regardless of database engine.
- **Same loan, two different payments racing** — the loan row is loaded with
  `with_for_update()`. On the real target database (Postgres, per `app/db.py`'s own
  docstring — SQLite here is only for zero-setup local running) this takes a row lock,
  so the second transaction blocks until the first commits, then reads the *updated*
  `total_paid` before validating — it cannot compute overpayment against a stale
  balance.

  **Honest limitation**: this repo runs on SQLite, and SQLite does not have real
  row-level locking — `with_for_update()` is close to a no-op there. What actually
  protects correctness in this test environment is SQLite's own single-writer
  serialization (one write transaction at a time at the file level); a second writer
  blocks/retries until the first finishes. I verified this empirically with a
  multi-threaded test (`test_concurrent_payments_same_loan_never_overdraw` in
  `tests/test_payments.py`, run 15x with no flakes) rather than just asserting it in
  prose. The `with_for_update()` call is still correct and left in place because it's
  the right statement of intent for the production database this schema is modeled
  on — removing it would be wrong for Postgres even though it's inert here. A true
  concurrent-Postgres integration test would be stronger evidence than what SQLite in
  this test harness can offer; I did not have that database available in this
  environment.

### Provider signature verification (optional extension)

Implemented as an **additional** valid credential, not a hard swap for the
shared token. `require_webhook_auth` (`app/auth.py`) accepts either:

- the original `X-Webhook-Token` header (unchanged), or
- a provider-style HMAC signature: `X-Webhook-Timestamp` + `X-Webhook-Signature`,
  where the signature is `HMAC-SHA256(signing_secret, "{timestamp}.{raw_body}")`
  — the same shape Stripe/Paystack use. Verification reads the *raw* request
  body (`await request.body()`), not the parsed Pydantic model, so what's
  checked is byte-for-byte what the sender transmitted — re-serializing the
  parsed body before checking would let a payload that round-trips
  differently (e.g. key order, float formatting) slip past a signature
  computed over the original bytes.

**Why additive, not "instead of," despite the README's wording**: the
existing `test_webhook_requires_a_valid_token` /
`test_webhook_rejects_invalid_token` tests are part of the graded contract
and authenticate via the shared token — replacing it outright would break
them. More importantly, the frontend's "Simulate"/"Resend" buttons
(`frontend/src/lib/api.js`) are the browser calling the webhook directly;
they have no server-side signing key to compute a real HMAC with (putting
the signing secret in frontend JS would defeat the entire point of a
signature — anyone could forge one). A real gateway signs server-side before
it ever reaches an HTTP client; a browser simulate button can't play that
role. So the token remains the credential for the demo/simulate path, and
the signature is the credential a real provider integration would use — both
are accepted, and the code and tests make that split explicit rather than
quietly picking one.

**Replay protection, not just integrity**: the timestamp is bound *inside*
the signed payload (not compared separately from an unsigned header), so a
captured valid signature can't be replayed later with a substituted
timestamp — the HMAC would no longer match. A request whose timestamp is
more than 5 minutes from server time is rejected even if the signature
itself is otherwise valid (`SIGNATURE_TOLERANCE_SECONDS`), which bounds how
long a captured request stays replayable. `hmac.compare_digest` is used for
the comparison specifically to avoid a timing side-channel on how many bytes
of the signature matched.

Tests: `test_webhook_accepts_valid_hmac_signature_with_no_token`,
`test_webhook_rejects_tampered_body_under_valid_signature`,
`test_webhook_rejects_signature_with_wrong_secret`,
`test_webhook_rejects_stale_signature_timestamp`,
`test_webhook_rejects_missing_signature_and_missing_token`,
`test_webhook_token_still_works_alongside_signature_support` — plus manual
`curl` verification against a running server (valid signature alone → 200
applied; no auth → 401; wrong signature → 401; token still works → 200).

**Still not production-grade**: `WEBHOOK_SIGNING_SECRET` is a hardcoded
constant (same gap as `WEBHOOK_TOKEN`, see "Before production"); there's no
secret rotation / key-id header to support rotating the signing secret
without a flag day; and there's no nonce/idempotency-key check independent
of `external_ref` for replay defense within the tolerance window — a
captured request replayed within 5 minutes with its original timestamp
would still verify (the `external_ref` uniqueness constraint is what
actually stops it from being applied twice, which is a business-logic
backstop, not a dedicated replay defense at the auth layer).

### Overpayment policy

**Reject the entire payment** if it would exceed the loan's outstanding balance — no
partial application. Example: outstanding 50,000, incoming payment 60,000 → the event
is rejected with `reason=overpayment`, no `Repayment` is created, and the loan is
untouched.

Rationale: partially applying a payment and leaving a residual 10,000 unaccounted for
creates an unresolved financial state with no defined owner. A real system needs an
explicit policy for that residual — refund to the payer, credit to the borrower's
account, or a suspense/clearing account pending manual review — and none of those
exist here. Rejecting the whole payment keeps every dollar traceable to a decision:
either it's fully applied, or it's sitting with the rail/gateway until someone
resolves it. This is the safer default in the absence of that policy.

### Audit strategy

Every reconciliation outcome writes an `AuditLog` row via the existing `record_audit`
helper, in the same transaction as the financial change:

- Applied: `action=payment.applied`, `entity=loan`, `entity_id=<loan id>`, detail
  includes the payment event id, `external_ref`, and amount.
- Rejected (loan-state / amount reasons): `action=payment.rejected`,
  `entity=payment_event`, `entity_id=<event id>`, detail includes `external_ref` and
  the reason code.
- Duplicate redeliveries do **not** get a fresh audit row, because no new
  `PaymentEvent` is persisted for them (see Idempotency) — there's nothing new to
  audit against. The original event's own audit trail (from when it first landed)
  already exists. This is a reasonable gap to flag, not a hidden one: a production
  system would likely still want a lightweight "redelivery observed" log line for
  operational visibility, even without a new business record. Not implemented here.

### Money handling

`Loan`, `PaymentEvent`, and `Repayment` amounts stay `Float` — that's the schema this
task says to treat as inherited, and changing it would mean an Alembic-style migration
this project has no tooling for. Instead, every comparison and arithmetic operation
that matters financially (overpayment check, exact-payoff check, balance update) goes
through `Decimal(str(x))` inside `app/services/payment_reconciliation.py`, and the
result is cast back to `float` only when writing to the column. `Decimal(str(x))`
(not `Decimal(x)`) specifically avoids importing the binary float's own rounding
error into the Decimal.

This is a mitigation, not a fix — floats are still the storage format, so values that
can't be exactly represented in binary floating point can still drift over many
operations. The correct fix is `Numeric`/fixed-point columns (or integer minor units)
on a real migration, which is out of scope here per the "don't rewrite the schema"
instruction. Flagged under "Before production" below.

**A real bug this caught, found during manual QA, not by the test suite**: the
overpayment/payoff check originally computed outstanding via `Decimal(str(loan.outstanding))`
— reusing the `Loan.outstanding` Python property (`total_repayable - total_paid`,
`app/models.py`). That property does the subtraction in plain `float` *before* any
`Decimal` conversion happens, so float rounding error from the subtraction itself was
already baked into the number by the time it reached `Decimal(str(...))`. Concretely:
after two payments of 9333.33 against a loan with `total_repayable=56000.0`,
`total_paid` was stored as an exact `46666.66`, but `56000.0 - 46666.66` in float
arithmetic evaluates to `9333.339999999997`, not `9333.34`. The borrower's exact,
correct final installment of `9333.34` was then rejected as an `overpayment` against
that drifted value. Fixed by computing outstanding directly from the two raw columns
as `Decimal(str(total_repayable)) - Decimal(str(total_paid))` (see `_outstanding()` in
`app/services/payment_reconciliation.py`), never through the float property, for the
reconciliation decision. Regression test:
`test_accumulated_float_drift_does_not_cause_false_overpayment_rejection`.

**A second display-only instance of the same class of bug, also fixed**: the
`outstanding` value *displayed* in API responses (`GET /loans/{id}`, `GET /loans`, and
the `loan` block returned from the webhook) went through `_loan_out` in `app/loans.py`,
which serialized the raw `Loan.outstanding` property — so a caller could still see
`9333.339999999997` in a response even after the reconciliation-decision bug above was
fixed. Fixed by computing `outstanding` in `_loan_out` the same way — Decimal
subtraction on the raw columns — rather than trusting the float property. The model
property itself (`Loan.outstanding` in `app/models.py`) is left as-is, since it's
existing "inherited" schema code outside this task's scope and other code may still
read it directly; the fix is at the serialization boundary, where display values are
actually produced. Regression test: `test_displayed_outstanding_has_no_float_rounding_artifacts`.

**Duplicate response no longer reports `id`/`received_at` as `null`**: the earlier
version built a fully transient `PaymentEvent` for a duplicate-rejection response,
with no `id` and no `received_at` — technically correct (no second row is persisted)
but an awkward shape for a caller to consume, since there was nothing to look up. Now
`_duplicate()` looks up the *original* event for that `external_ref` and copies its
`id`/`received_at`/`processed_at` onto the transient response object, so the response
points a caller back at the real record of what happened (e.g. via
`GET /payment-events`) instead of returning nulls. `status`/`reason` on the response
still correctly say `rejected`/`duplicate_external_ref` for *this* request — only the
identity/timestamp fields are borrowed from the original. Regression test:
`test_duplicate_response_references_original_event_id_and_received_at`.

### Admin reconciliation & issues panel (frontend)

Built as a genuinely separate page (`/admin`, via `react-router-dom`) rather than a
section bolted onto the existing feed screen, reachable via a small nav bar
(`frontend/src/components/NavBar.jsx`) shared by both routes. The existing feed
screen (`frontend/src/pages/Feed.jsx`) was moved there verbatim from the old
`App.jsx` — no logic changes — with `App.jsx` reduced to a router shell.

**Data sources**: primarily `GET /payment-events` (already had everything needed —
`status`, `reason`, timestamps — for the issues/health view, no backend change
required for that part). A new **`GET /audit-log`** endpoint
(`app/audit_log.py`) exposes the already-populated `AuditLog` table for a secondary
"activity trail" section. It's unauthenticated and unpaginated, deliberately
matching `GET /loans`/`GET /payment-events`'s existing convention — `X-Webhook-Token`
gates the *inbound webhook* specifically (a different trust boundary than an
internal read), so introducing a different auth model for one new GET endpoint
would be an inconsistency, not a real security improvement, at this scope.

**Layout, issues first**: a 3-tile KPI row (total reconciled, applied, failure rate
with a red left-border accent when > 0) sits above an "Issues needing attention"
card — filterable by a reason-code pill bar — which is placed *before* the
"Reconciled" (applied) section, per the requirement that issues be front and
centre. The activity trail is last and visually lightest (a compact list, not
another table), since its `detail` strings otherwise duplicate what the Issues/
Reconciled tables already show; its distinct value is being actor/action-centric.

**Reason-to-color mapping is deliberate, not "everything red":** `unknown_loan` is
red (most severe — money referencing a loan that doesn't exist, needs
investigation); `duplicate_external_ref` is grey (benign, expected rail
redelivery — not a failure of business logic); `loan_not_active`/`invalid_amount`
are amber (actionable, not urgent); `overpayment` is blue (informational — a
business decision about the money, not really an "error"). All five reuse the
existing CSS custom-property color pairs already defined for loan/payment status
badges — no new colors invented.

**A real, verified backend quirk surfaces in the UI, not silently "fixed":** a
duplicate redelivery never gets its own `PaymentEvent` row (see the idempotency
section above), so it's never separately audited either. The Issues table (from
`/payment-events`) will show a duplicate's *original* rejection reason if it was
rejected, or nothing distinct if it was applied — but the Activity trail (from
`/audit-log`) will show strictly fewer entries than payment events whenever
duplicates occurred. This was manually verified end-to-end (via `curl` and a
Playwright-driven browser check against the running dev servers) rather than
assumed, and is called out with a code comment in `AdminPanel.jsx` so it isn't
mistaken for a bug later.

**Frontend testing scope**: no new test framework (no Vitest/RTL) was introduced.
The panel's derived logic (grouping rejections by reason, computing failure rate)
is simple array filtering over already server-validated enum data — disproportionate
to justify new test tooling in an app that had deliberately stayed dependency-free
beyond React+Vite. Coverage instead comes from: the backend's `tests/test_audit_log.py`
(5 tests covering the new endpoint's behavior, including the duplicate-not-audited
case) and manual end-to-end verification (curl against every reconciliation outcome,
then a real browser session confirming both routes render correctly, the reason
filter interaction works, and the numbers match). If this were headed to
production or the panel grew more complex, Vitest + React Testing Library around
the derivation functions would be the natural next step.

## Edge cases

- **Duplicate webhook** (sequential redelivery): first call applies, second is
  rejected `duplicate_external_ref`, loan balance changes exactly once. Covered by
  `test_duplicate_external_ref_is_rejected` and
  `test_duplicate_reason_is_explicit_and_only_one_repayment_exists`.
- **Concurrent duplicate webhook**: two threads fire the same `external_ref`
  simultaneously; exactly one applies, the DB unique constraint decides the loser
  regardless of thread scheduling. Covered by
  `test_concurrent_duplicate_external_ref_applies_only_once`.
- **Concurrent payments on the same loan**: two different payments race, together
  exceeding the outstanding balance; the loan never goes negative, exactly one
  applies. Covered by `test_concurrent_payments_same_loan_never_overdraw`. See the
  SQLite-vs-Postgres caveat under Concurrency strategy above.
- **Unknown loan**: event is recorded and rejected `unknown_loan`; response's `loan`
  key is `null` (nothing to serialize). Covered by `test_unknown_loan_reason_is_explicit`.
- **Closed/inactive loan**: rejected `loan_not_active` (covers `cancelled`,
  `paid_off`, `written_off` uniformly), loan untouched. Covered by
  `test_closed_loan_reason_is_explicit`.
- **Overpayment**: rejected `overpayment`, no partial application, loan untouched.
  Covered by `test_overpayment_is_rejected` and
  `test_rejected_event_reports_reason_and_creates_no_repayment`.
- **Exact payoff**: `total_paid` reaches `total_repayable` exactly (via `Decimal`
  equality, not float `==`), loan flips to `paid_off`. Covered by
  `test_exact_payoff_closes_loan`.

## Before production

Being explicit about what's *not* here:

- **Provider signature verification is implemented** (`require_webhook_auth`,
  `app/auth.py`) — HMAC-SHA256 over `{timestamp}.{raw_body}`, constant-time
  compared, with a 5-minute timestamp tolerance. See "Provider signature
  verification" above for the full design and why it's additive to the
  shared token rather than a replacement. What's still missing for real
  production use: the signing secret is a hardcoded constant, not pulled
  from a secrets manager or rotatable via a key-id header; and there's no
  standalone replay defense within the tolerance window beyond the
  `external_ref` uniqueness constraint (see the next point).
- **Replay protection is partial.** The signature scheme has a 5-minute
  timestamp window, which bounds *how long* a captured request could be
  replayed, but nothing dedicated stops a replay *within* that window other
  than the `external_ref` uniqueness constraint — which exists for
  idempotency, not specifically as a replay defense, though it happens to
  serve both purposes here. A nonce/seen-signature cache would be the
  correct dedicated mechanism.
- **No structured logging or metrics.** No log lines around reconciliation decisions,
  no counters/histograms for applied vs rejected rates, latency, etc. An operator
  today can only see outcomes via `GET /payment-events`.
- **No alerting.** A spike in `overpayment` or `duplicate_external_ref` rejections
  (which could indicate a gateway bug or a fraud pattern) would go unnoticed.
- **No provider reconciliation job.** Nothing periodically cross-checks the
  provider's own ledger against ours to catch missed webhooks (rails can silently
  fail to deliver, not just redeliver).
- **No retry/dead-letter handling.** If reconciliation raises an unexpected
  (non-business) error, the request fails and it's entirely on the rail's own retry
  behavior to redeliver — there's no queue or DLQ on our side.
- **No settlement/reversal/chargeback flow.** A `Repayment` is permanent once
  applied; there's no way to reverse one if a payment later bounces or is disputed.
- **No refund or suspense-account flow.** The overpayment policy explicitly rejects
  the whole payment rather than partially applying it, precisely because those flows
  don't exist yet (see Overpayment policy above).
- **Money is still `Float` at rest.** Decimal is used for the comparisons that matter
  at reconciliation time, but the schema itself isn't precision-safe. A real
  migration to `Numeric`/integer minor units would be the fix.
- **No RBAC for admin operations.** There's no admin-facing mutation endpoint in this
  submission, but if one were added (e.g., manual reconciliation override), it would
  need real authorization beyond the webhook token.
- **No rate limiting** on the webhook endpoint.
- **Secrets management**: the webhook token is a hardcoded string in `app/auth.py`
  (`WEBHOOK_TOKEN = "dev-webhook-secret"`), unchanged from what was already there —
  a real deployment needs this in a secrets manager / env var, rotated periodically.
- **No operational monitoring / health checks beyond `GET /health`.**
- **SQLite in this environment** means the concurrency protection for
  same-loan races leans on SQLite's own single-writer behavior rather than a proven
  Postgres row lock — see the Concurrency strategy section for the full caveat.
- **The admin panel is entirely read-only and unauthenticated**, like the rest of
  the read endpoints it's built on. A real ops tool would need its own
  authentication/RBAC (not the webhook token, which is a different trust boundary),
  and likely audit logging of *who* viewed sensitive reconciliation data, not just
  the payment/loan mutations themselves.

## AI usage

This implementation was built with Claude Code (Claude models), used as follows:

- **Exploration**: I had Claude read the full backend (`models.py`, `db.py`,
  `auth.py`, `audit.py`, `payments.py`, `loans.py`, the existing test suite, and
  `conftest.py`) and report back the exact model fields, session/transaction
  lifecycle, and test expectations before any code was written, specifically to
  avoid guessing at conventions that already existed (e.g., that `record_audit`
  intentionally doesn't commit, that there's no Alembic, that SQLite doesn't enforce
  FKs by default).
- **Design**: I asked Claude to draft the reconciliation algorithm, transaction
  boundaries, and idempotency/concurrency strategy as a plan before writing code, and
  reviewed it against the task's explicit requirements line by line (e.g., confirming
  the `{event, loan}` response shape matched what the existing tests actually assert,
  not just what seemed reasonable).
- **Implementation**: Claude wrote `app/services/payment_reconciliation.py` and the
  route wiring in `app/payments.py`. I reviewed and corrected one real bug in the
  first draft: the initial duplicate-handling path returned the *original* (already
  applied) `PaymentEvent` row for a redelivery, which would have reported
  `status=applied` instead of `status=rejected` for the second request — failing the
  existing `test_duplicate_external_ref_is_rejected` test. I redirected the design to
  build a transient, unpersisted `PaymentEvent` for the duplicate response instead of
  persisting or mutating a second row, and to add an application-level pre-check
  ahead of the DB constraint so the common (non-racing) duplicate case doesn't need a
  failed insert + rollback round trip.
- **Testing**: I directed the concurrency test design explicitly (real `threading`
  + `threading.Barrier` against the same `TestClient`, not mocked), and asked for the
  concurrency tests to be run repeatedly (15x) to check for flakiness before trusting
  them, since a single green run of a race-condition test proves little.
- **What I verified manually, not just trusted**: ran the full test suite (`pytest`,
  21 tests, all passing); inspected the actual SQLite schema after a fresh seed to
  confirm the `UNIQUE (external_ref)` constraint was really created; ran the server
  and hit the webhook directly with `curl` for the no-token/valid/duplicate/unknown-loan
  cases to see real HTTP responses, not just test assertions; read every line of the
  final diff against each numbered requirement in the assignment brief.

### Admin panel (frontend extension)

- **Design**: had Claude explore the existing frontend in full (all 3 source files,
  `package.json`, `vite.config.js`) before proposing anything, to confirm it was
  genuinely a zero-dependency, router-free, single-file app rather than assuming so.
  I made the explicit product/architecture calls myself via targeted questions —
  separate route vs. same-page section, `react-router-dom` vs. tab state, whether to
  add `GET /audit-log` — rather than letting the model default to the "smallest diff"
  option; a take-home explicitly asking for product judgment warranted a real decision,
  not the path of least resistance.
- **Implementation**: Claude wrote the new backend endpoint, the router restructure
  (moving the existing Feed screen verbatim to avoid regressing working code), and
  `AdminPanel.jsx`. I directed the reason-to-color mapping rationale explicitly
  (severity-based, not "just make rejections red") rather than accepting an arbitrary
  first pass.
- **What I verified, not just trusted**: ran the full backend suite after adding the
  new endpoint (29 tests passing); built the frontend (`npm run build`) to catch
  import/syntax errors before manual testing; ran both dev servers together and
  exercised the real reconciliation flow via `curl` (applied, overpayment, unknown
  loan, closed loan, and a duplicate redelivery) to generate real data; then drove an
  actual browser via Playwright against the running app to confirm both routes render
  correctly, the KPI numbers match the data exactly, the reason filter pills work
  (clicking "Overpayment (1)" correctly narrowed the table to one row), and — the one
  thing that was easy to get subtly wrong — that the duplicate redelivery appears
  in the Issues feed's underlying event count but does *not* produce a phantom extra
  row or an extra audit entry, matching the documented idempotency behavior.

### Provider signature verification (optional extension)

- **Design**: the README says "instead of the shared token," but I checked the
  existing test suite and frontend first rather than implementing a literal
  swap — `tests/test_payments.py` already asserts 401/200 behavior against
  `X-Webhook-Token`, and `frontend/src/lib/api.js` hardcodes that header with
  no signing key available client-side. I made the call to implement
  signature verification as an *additional* accepted credential rather than a
  replacement, and had Claude confirm the reasoning (a browser "simulate"
  button structurally cannot hold a server-side signing secret without
  defeating the purpose of a signature) before writing any code.
- **Implementation**: Claude wrote `verify_webhook_signature` /
  `require_webhook_auth` in `app/auth.py` and wired it into
  `app/payments.py` in place of `require_webhook_token` directly. I asked
  specifically for: HMAC computed over the *raw* body (not a re-serialized
  Pydantic model, which could drift from what was actually signed), a bound
  timestamp for replay-window protection (not just an unsigned freshness
  check), and `hmac.compare_digest` instead of `==` for the comparison —
  these are the three most common ways a hand-rolled signature check goes
  wrong, and I wanted them addressed by design rather than found in review.
- **Testing**: wrote `_signed_request` as a test helper that signs the exact
  raw bytes it sends via `content=`, deliberately avoiding `client.post(json=...)`
  for these tests since httpx's own JSON serialization could silently diverge
  from what was signed. Directed six specific test cases: valid signature
  alone (no token), tampered body under an otherwise-valid signature, wrong
  signing secret, stale timestamp, neither credential present, and — the one
  most likely to regress silently — that the original token path still works
  unchanged.
- **What I verified manually, not just trusted**: ran the full suite (35
  tests passing, up from 29); started a real server and hit
  `/webhooks/payments` with `curl` using a hand-computed `HMAC-SHA256` in a
  one-off Python snippet (not reusing the app's own code) with a valid
  signature and no token, with a wrong signature, with no auth at all, and
  confirmed the original `X-Webhook-Token` request still returns 200 —
  checking the real HTTP status codes rather than trusting the test suite's
  account of its own correctness.
</content>
