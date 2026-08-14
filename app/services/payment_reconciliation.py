"""Payment webhook reconciliation.

A payment lands from a rail and is reconciled *on receipt*, in one
transaction: record it as a ``PaymentEvent``, then either apply it (create a
``Repayment``, reduce the loan's outstanding balance, close the loan on exact
payoff) or reject it with a machine-readable reason. See NOTES.md for the
idempotency/concurrency/overpayment reasoning.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..models import Loan, LoanStatus, PaymentEvent, PaymentStatus, Repayment


@dataclass
class PaymentPayload:
    external_ref: str
    loan_id: int
    amount: float
    channel: str


def _d(x) -> Decimal:
    """Decimal via str() to avoid binary float artifacts in comparisons."""
    return Decimal(str(x))


def _outstanding(loan: Loan) -> Decimal:
    """Decimal outstanding computed from the raw columns.

    Deliberately does NOT read ``Loan.outstanding`` — that property subtracts
    two floats in plain float arithmetic before we'd have a chance to convert
    to Decimal, so any rounding error from the subtraction itself is already
    baked into the result. Subtracting as Decimal from the start avoids that.
    """
    return _d(loan.total_repayable) - _d(loan.total_paid)


def reconcile_payment(db: Session, payload: PaymentPayload) -> tuple[PaymentEvent, Loan | None]:
    """Reconcile one incoming payment. Returns (event, loan) — loan is None
    only when the referenced loan doesn't exist. Commits exactly once.

    A redelivered external_ref never gets a second PaymentEvent row: the
    application-level pre-check below handles the common case cheaply, and
    the DB's unique constraint on external_ref (see models.py) is the real
    authority — if two requests race past the pre-check, the loser's insert
    violates the constraint and is turned into the same duplicate outcome.
    """
    original = (
        db.query(PaymentEvent).filter(PaymentEvent.external_ref == payload.external_ref).first()
    )
    if original is not None:
        loan = db.query(Loan).filter(Loan.id == payload.loan_id).first()
        return _duplicate(payload, original), loan

    event = PaymentEvent(
        external_ref=payload.external_ref,
        loan_id=payload.loan_id,
        amount=payload.amount,
        channel=payload.channel,
        status=PaymentStatus.pending,
    )
    db.add(event)
    try:
        db.flush()  # surfaces a duplicate external_ref before we touch any loan
    except IntegrityError:
        db.rollback()
        original = (
            db.query(PaymentEvent)
            .filter(PaymentEvent.external_ref == payload.external_ref)
            .first()
        )
        loan = db.query(Loan).filter(Loan.id == payload.loan_id).first()
        return _duplicate(payload, original), loan

    loan = db.query(Loan).filter(Loan.id == payload.loan_id).with_for_update().first()

    reason = _rejection_reason(loan, payload.amount)
    if reason is not None:
        event.status = PaymentStatus.rejected
        event.reason = reason
        _audit_rejected(db, event, reason)
        db.commit()
        db.refresh(event)
        return event, loan

    assert loan is not None  # _rejection_reason already checked this
    repayment = Repayment(loan_id=loan.id, payment_event_id=event.id, amount=payload.amount)
    db.add(repayment)

    new_total_paid = _d(loan.total_paid) + _d(payload.amount)
    loan.total_paid = float(new_total_paid)
    if new_total_paid == _d(loan.total_repayable):
        loan.status = LoanStatus.paid_off

    event.status = PaymentStatus.applied
    event.processed_at = event.received_at

    record_audit(
        db,
        action="payment.applied",
        entity="loan",
        entity_id=loan.id,
        actor=f"webhook:{payload.channel}",
        detail=f"payment_event={event.id} external_ref={payload.external_ref} amount={payload.amount}",
    )

    db.commit()
    db.refresh(event)
    db.refresh(loan)
    return event, loan


def _rejection_reason(loan: Loan | None, amount: float) -> str | None:
    if loan is None:
        return "unknown_loan"
    if loan.status != LoanStatus.active:
        return "loan_not_active"
    if _d(amount) <= 0:
        return "invalid_amount"
    if _d(amount) > _outstanding(loan):
        return "overpayment"
    return None


def _audit_rejected(db: Session, event: PaymentEvent, reason: str) -> None:
    record_audit(
        db,
        action="payment.rejected",
        entity="payment_event",
        entity_id=event.id,
        actor=f"webhook:{event.channel}",
        detail=f"external_ref={event.external_ref} reason={reason}",
    )


def _duplicate(payload: PaymentPayload, original: PaymentEvent) -> PaymentEvent:
    """This external_ref already has a PaymentEvent (idempotency key already
    used) — either seen by the pre-check or discovered via a unique-constraint
    violation on a concurrent insert. We do not persist a second row for this
    redelivery: the object below is transient, built only to serialize a
    'rejected: duplicate' response for *this* request. Its id/received_at
    reference the original event — the real record of what actually happened
    for this external_ref — rather than being null, so a caller can look the
    original up (e.g. via GET /payment-events).
    """
    return PaymentEvent(
        id=original.id,
        external_ref=payload.external_ref,
        loan_id=payload.loan_id,
        amount=payload.amount,
        channel=payload.channel,
        status=PaymentStatus.rejected,
        reason="duplicate_external_ref",
        received_at=original.received_at,
        processed_at=original.processed_at,
    )
