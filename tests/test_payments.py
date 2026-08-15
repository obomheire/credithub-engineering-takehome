"""Behaviour spec for the payment webhook you're building.

Contract (see README): POST /webhooks/payments with an X-Webhook-Token header
and a JSON body {external_ref, loan_id, amount, channel?}. A payment is
reconciled ON RECEIPT — recorded and immediately applied or rejected.

- 401 without a valid token.
- On success: the event is "applied", a repayment is recorded, the loan
  balance drops, and the loan closes when fully repaid. Return {event, loan}.
- Reject (status "rejected" + reason, still 200) when it can't be applied: the
  loan isn't active, the loan is unknown, a duplicate external_ref was already
  applied (rails redeliver), or the amount overpays.

These fail against the stub — make them pass, then add your own.
"""

TOK = {"X-Webhook-Token": "dev-webhook-secret"}


def _signed_request(body: dict, *, secret="dev-webhook-signing-secret", ts=None, skew=0):
    """Build the exact raw bytes + headers a real provider would send: the
    body is serialized once, signed as those literal bytes (HMAC-SHA256 over
    "{timestamp}.{raw_body}"), and sent via ``content=`` so what's signed is
    byte-for-byte what's transmitted — ``skew`` pushes the timestamp outside
    the tolerance window for the replay-protection test.
    """
    import hashlib
    import hmac
    import json
    import time

    timestamp = str(int(time.time()) + skew) if ts is None else ts
    raw_body = json.dumps(body).encode()
    signed_payload = f"{timestamp}.".encode() + raw_body
    signature = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    headers = {
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": signature,
        "Content-Type": "application/json",
    }
    return raw_body, headers


def _pay(ref, loan_id, amount, channel="paystack"):
    return {"external_ref": ref, "loan_id": loan_id, "amount": amount, "channel": channel}


def test_webhook_applies_payment_and_reduces_outstanding(client):
    r = client.post("/webhooks/payments", json=_pay("R-1", 1, 20000), headers=TOK)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "applied"
    assert client.get("/loans/1").json()["outstanding"] == 36000


def test_exact_payoff_closes_loan(client):
    client.post("/webhooks/payments", json=_pay("R-2", 1, 56000), headers=TOK)
    assert client.get("/loans/1").json()["status"] == "paid_off"


def test_duplicate_external_ref_is_rejected(client):
    client.post("/webhooks/payments", json=_pay("R-1", 1, 20000), headers=TOK)
    r = client.post("/webhooks/payments", json=_pay("R-1", 1, 20000), headers=TOK)  # redelivery
    assert r.json()["event"]["status"] == "rejected"
    assert client.get("/loans/1").json()["outstanding"] == 36000  # applied once only


def test_payment_for_cancelled_loan_is_rejected(client):
    r = client.post("/webhooks/payments", json=_pay("R-3", 2, 100), headers=TOK)  # loan 2 cancelled
    assert r.json()["event"]["status"] == "rejected"
    assert client.get("/loans/2").json()["outstanding"] == 11000  # untouched


def test_unknown_loan_is_rejected(client):
    r = client.post("/webhooks/payments", json=_pay("R-4", 999, 100), headers=TOK)
    assert r.json()["event"]["status"] == "rejected"


def test_overpayment_is_rejected(client):
    r = client.post("/webhooks/payments", json=_pay("R-5", 1, 999999), headers=TOK)
    assert r.json()["event"]["status"] == "rejected"
    assert client.get("/loans/1").json()["outstanding"] == 56000  # untouched


def test_webhook_requires_a_valid_token(client):
    r = client.post("/webhooks/payments", json=_pay("R-6", 1, 100))  # no token
    assert r.status_code == 401


# --- provided endpoint (this already passes) ---

def test_feed_endpoint_lists_events(client):
    assert client.get("/payment-events").status_code == 200


# --- additional edge cases ---

def test_webhook_rejects_invalid_token(client):
    bad_tok = {"X-Webhook-Token": "not-the-real-token"}
    r = client.post("/webhooks/payments", json=_pay("R-7", 1, 100), headers=bad_tok)
    assert r.status_code == 401


def test_partial_repayment_keeps_loan_active(client):
    r = client.post("/webhooks/payments", json=_pay("R-8", 1, 1000), headers=TOK)
    assert r.json()["event"]["status"] == "applied"
    loan = client.get("/loans/1").json()
    assert loan["outstanding"] == 55000
    assert loan["status"] == "active"


def test_rejected_event_reports_reason_and_creates_no_repayment(client):
    from app.db import SessionLocal
    from app.models import Repayment

    r = client.post("/webhooks/payments", json=_pay("R-9", 1, 999999), headers=TOK)
    assert r.json()["event"]["reason"] == "overpayment"

    db = SessionLocal()
    try:
        assert db.query(Repayment).count() == 0
    finally:
        db.close()


def test_unknown_loan_reason_is_explicit(client):
    r = client.post("/webhooks/payments", json=_pay("R-10", 999, 100), headers=TOK)
    assert r.json()["event"]["reason"] == "unknown_loan"
    assert r.json()["loan"] is None


def test_closed_loan_reason_is_explicit(client):
    r = client.post("/webhooks/payments", json=_pay("R-11", 2, 100), headers=TOK)
    assert r.json()["event"]["reason"] == "loan_not_active"


def test_duplicate_reason_is_explicit_and_only_one_repayment_exists(client):
    from app.db import SessionLocal
    from app.models import Repayment

    client.post("/webhooks/payments", json=_pay("R-12", 1, 20000), headers=TOK)
    r = client.post("/webhooks/payments", json=_pay("R-12", 1, 20000), headers=TOK)
    assert r.json()["event"]["reason"] == "duplicate_external_ref"

    db = SessionLocal()
    try:
        assert db.query(Repayment).count() == 1
    finally:
        db.close()


def test_duplicate_response_references_original_event_id_and_received_at(client):
    """The duplicate rejection response must not report id/received_at as
    null — it should point back at the original event that actually landed,
    so a caller can look it up (e.g. via GET /payment-events).
    """
    first = client.post("/webhooks/payments", json=_pay("R-15", 1, 20000), headers=TOK).json()
    original_id = first["event"]["id"]
    original_received_at = first["event"]["received_at"]
    assert original_id is not None
    assert original_received_at is not None

    dup = client.post("/webhooks/payments", json=_pay("R-15", 1, 20000), headers=TOK).json()
    assert dup["event"]["id"] == original_id
    assert dup["event"]["received_at"] == original_received_at


def test_applied_payment_writes_audit_log(client):
    from app.db import SessionLocal
    from app.models import AuditLog

    r = client.post("/webhooks/payments", json=_pay("R-13", 1, 20000), headers=TOK)
    event_id = r.json()["event"]["id"]

    db = SessionLocal()
    try:
        entries = db.query(AuditLog).filter(AuditLog.action == "payment.applied").all()
        assert len(entries) == 1
        assert f"payment_event={event_id}" in entries[0].detail
        assert "R-13" in entries[0].detail
    finally:
        db.close()


def test_rejected_payment_writes_audit_log(client):
    from app.db import SessionLocal
    from app.models import AuditLog

    client.post("/webhooks/payments", json=_pay("R-14", 999, 100), headers=TOK)

    db = SessionLocal()
    try:
        entries = db.query(AuditLog).filter(AuditLog.action == "payment.rejected").all()
        assert len(entries) == 1
        assert "unknown_loan" in entries[0].detail
    finally:
        db.close()


def test_accumulated_float_drift_does_not_cause_false_overpayment_rejection(client):
    """Regression test for a real bug found during QA: paying a loan down in
    fractional-cent installments can leave Loan.total_paid such that the plain
    float subtraction in Loan.outstanding drifts (e.g. 9333.339999999997
    instead of 9333.34). The exact correct final installment must still be
    accepted and close the loan — the overpayment check must not compare
    against that drifted float value.
    """
    client.post("/webhooks/payments", json=_pay("DRIFT-1", 1, 46666.66), headers=TOK)  # 56000 - 46666.66 = 9333.34 remaining, float sub drifts
    r = client.post("/webhooks/payments", json=_pay("DRIFT-2", 1, 9333.34), headers=TOK)
    assert r.json()["event"]["status"] == "applied"
    loan = client.get("/loans/1").json()
    assert loan["status"] == "paid_off"
    assert loan["outstanding"] == 0


def test_displayed_outstanding_has_no_float_rounding_artifacts(client):
    """Regression test: GET /loans/{id} and the webhook's loan block must
    show a clean outstanding value, not a float subtraction artifact like
    9333.339999999997, even mid-loan (before any payoff).
    """
    client.post("/webhooks/payments", json=_pay("DISP-1", 1, 9333.33), headers=TOK)
    r = client.post("/webhooks/payments", json=_pay("DISP-2", 1, 9333.33), headers=TOK)
    assert r.json()["loan"]["outstanding"] == 37333.34  # 56000 - 18666.66, not ...66.6600000001
    assert client.get("/loans/1").json()["outstanding"] == 37333.34


# --- concurrency ---


def test_concurrent_duplicate_external_ref_applies_only_once(client):
    """Two webhooks with the same external_ref race. Only one may apply, and
    exactly one Repayment must exist — the DB unique constraint on
    external_ref is the final authority, not just an app-level check.
    """
    import threading

    from app.db import SessionLocal
    from app.models import Repayment

    barrier = threading.Barrier(2)
    results = []

    def fire():
        barrier.wait()
        r = client.post("/webhooks/payments", json=_pay("RACE-1", 1, 20000), headers=TOK)
        results.append(r.json())

    t1 = threading.Thread(target=fire)
    t2 = threading.Thread(target=fire)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    statuses = sorted(r["event"]["status"] for r in results)
    assert statuses == ["applied", "rejected"]

    db = SessionLocal()
    try:
        assert db.query(Repayment).filter(Repayment.loan_id == 1).count() == 1
    finally:
        db.close()

    assert client.get("/loans/1").json()["outstanding"] == 36000


def test_concurrent_payments_same_loan_never_overdraw(client):
    """Two different payments race against the same loan, together exceeding
    the outstanding balance. The final outstanding must never go negative —
    exactly one payment applies, the other is rejected as an overpayment
    against the (now-updated) balance.
    """
    import threading

    barrier = threading.Barrier(2)
    results = []

    def fire(ref):
        barrier.wait()
        r = client.post("/webhooks/payments", json=_pay(ref, 1, 40000), headers=TOK)
        results.append(r.json())

    t1 = threading.Thread(target=fire, args=("RACE-2A",))
    t2 = threading.Thread(target=fire, args=("RACE-2B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    statuses = sorted(r["event"]["status"] for r in results)
    assert statuses == ["applied", "rejected"]

    outstanding = client.get("/loans/1").json()["outstanding"]
    assert outstanding >= 0
    assert outstanding == 16000


# --- provider HMAC signature (optional extension, see README + NOTES.md) ---


def test_webhook_accepts_valid_hmac_signature_with_no_token(client):
    """A request with a correct signature and NO X-Webhook-Token must still
    authenticate — signature is a fully valid, independent credential, not
    just a fallback checked after the token.
    """
    body = _pay("SIG-1", 1, 20000)
    raw_body, headers = _signed_request(body)
    r = client.post("/webhooks/payments", content=raw_body, headers=headers)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "applied"


def test_webhook_rejects_tampered_body_under_valid_signature(client):
    """The signature must cover the actual bytes sent — if the body is
    altered after signing (e.g. a MITM bumping the amount), verification
    must fail even though a signature is present and well-formed.
    """
    signed_body = _pay("SIG-2", 1, 100)
    _, headers = _signed_request(signed_body)
    tampered_raw_body = b'{"external_ref": "SIG-2", "loan_id": 1, "amount": 999999, "channel": "paystack"}'
    r = client.post("/webhooks/payments", content=tampered_raw_body, headers=headers)
    assert r.status_code == 401


def test_webhook_rejects_signature_with_wrong_secret(client):
    body = _pay("SIG-3", 1, 100)
    raw_body, headers = _signed_request(body, secret="not-the-real-signing-secret")
    r = client.post("/webhooks/payments", content=raw_body, headers=headers)
    assert r.status_code == 401


def test_webhook_rejects_stale_signature_timestamp(client):
    """A signature computed against a timestamp far outside the tolerance
    window must be rejected even if the HMAC itself is valid — this is the
    replay-protection half of the signature scheme, not just integrity.
    """
    body = _pay("SIG-4", 1, 100)
    raw_body, headers = _signed_request(body, skew=-3600)  # 1 hour old
    r = client.post("/webhooks/payments", content=raw_body, headers=headers)
    assert r.status_code == 401


def test_webhook_rejects_missing_signature_and_missing_token(client):
    body = _pay("SIG-5", 1, 100)
    import json

    r = client.post(
        "/webhooks/payments",
        content=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_webhook_token_still_works_alongside_signature_support(client):
    """The original shared-token mechanism must keep working unchanged —
    it's what the frontend's Simulate/Resend buttons use, and neither can
    produce a real HMAC signature client-side. See NOTES.md.
    """
    r = client.post("/webhooks/payments", json=_pay("SIG-6", 1, 100), headers=TOK)
    assert r.status_code == 200
    assert r.json()["event"]["status"] == "applied"
