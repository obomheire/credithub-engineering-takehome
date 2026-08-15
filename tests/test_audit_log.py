"""Behaviour spec for GET /audit-log — exposes the AuditLog trail already
written by the webhook's reconciliation flow.
"""

TOK = {"X-Webhook-Token": "dev-webhook-secret"}


def _pay(ref, loan_id, amount, channel="paystack"):
    return {"external_ref": ref, "loan_id": loan_id, "amount": amount, "channel": channel}


def test_audit_log_empty_by_default(client):
    assert client.get("/audit-log").json() == []


def test_audit_log_lists_applied_payment(client):
    client.post("/webhooks/payments", json=_pay("AL-1", 1, 20000), headers=TOK)
    entries = client.get("/audit-log").json()
    assert len(entries) == 1
    assert entries[0]["action"] == "payment.applied"
    assert entries[0]["entity"] == "loan"
    assert "AL-1" in entries[0]["detail"]


def test_audit_log_lists_rejected_payment(client):
    client.post("/webhooks/payments", json=_pay("AL-2", 999, 100), headers=TOK)
    entries = client.get("/audit-log").json()
    assert len(entries) == 1
    assert entries[0]["action"] == "payment.rejected"
    assert entries[0]["entity"] == "payment_event"
    assert "unknown_loan" in entries[0]["detail"]


def test_audit_log_is_newest_first(client):
    client.post("/webhooks/payments", json=_pay("AL-3", 1, 1000), headers=TOK)
    client.post("/webhooks/payments", json=_pay("AL-4", 1, 1000), headers=TOK)
    entries = client.get("/audit-log").json()
    assert "AL-4" in entries[0]["detail"]
    assert "AL-3" in entries[1]["detail"]


def test_duplicate_does_not_write_a_second_audit_row(client):
    """A redelivery is rejected without ever creating a new PaymentEvent row
    (see app/services/payment_reconciliation.py's _duplicate()), so there is
    nothing new to audit — only the original outcome is recorded.
    """
    client.post("/webhooks/payments", json=_pay("AL-5", 1, 1000), headers=TOK)
    client.post("/webhooks/payments", json=_pay("AL-5", 1, 1000), headers=TOK)
    assert len(client.get("/audit-log").json()) == 1
