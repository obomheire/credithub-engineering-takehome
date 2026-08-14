"""Payment ingestion + reconciliation.

``GET /payment-events`` is the payments feed. ``POST /webhooks/payments`` is
where an incoming payment lands and is reconciled on receipt — see
app/services/payment_reconciliation.py for the reconciliation logic and
NOTES.md for the design rationale.

The frontend's "Simulate incoming payment" button POSTs a synthetic payment to
this webhook — exactly as a real gateway/rail would. There is no separate
"apply" step: a payment arrives and is reconciled in the same call.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import require_webhook_token
from .db import get_db
from .loans import _loan_out
from .models import PaymentEvent
from .services.payment_reconciliation import PaymentPayload, reconcile_payment

router = APIRouter()


class PaymentIn(BaseModel):
    external_ref: str
    loan_id: int
    amount: float
    channel: str = "paystack"


def _event_out(e: PaymentEvent) -> dict:
    return {
        "id": e.id,
        "external_ref": e.external_ref,
        "loan_id": e.loan_id,
        "amount": e.amount,
        "channel": e.channel,
        "status": e.status.value,
        "reason": e.reason,
        "received_at": e.received_at.isoformat() if e.received_at else None,
        "processed_at": e.processed_at.isoformat() if e.processed_at else None,
    }


@router.get("/payment-events")
def list_payment_events(db=Depends(get_db)):
    """The payments feed (newest first) — provided."""
    events = db.query(PaymentEvent).order_by(PaymentEvent.id.desc()).all()
    return [_event_out(e) for e in events]


@router.post("/webhooks/payments")
def receive_payment(
    body: PaymentIn, db=Depends(get_db), _token=Depends(require_webhook_token)
):
    """A payment arrived from a rail — reconcile it on receipt. Always 200
    once authenticated: business outcomes (applied/rejected) are reported in
    the response body, not via HTTP status. See NOTES.md.
    """
    payload = PaymentPayload(
        external_ref=body.external_ref,
        loan_id=body.loan_id,
        amount=body.amount,
        channel=body.channel,
    )
    event, loan = reconcile_payment(db, payload)
    return {
        "event": _event_out(event),
        "loan": _loan_out(loan) if loan is not None else None,
    }
