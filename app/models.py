"""ORM models for the loan-servicing slice.

Kept intentionally close to the real platform's shape — including the fact
that money is stored as ``Float``. Treat this as the production schema you've
inherited.

Flow: payments arrive as ``PaymentEvent`` rows (simulated gateway callbacks) in
``pending`` status. Reconciling them — matching to a loan, applying the money,
and ticking the event off — is the candidate's task.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LoanStatus(str, enum.Enum):
    active = "active"
    paid_off = "paid_off"
    cancelled = "cancelled"
    written_off = "written_off"


class PaymentStatus(str, enum.Enum):
    pending = "pending"    # landed, not yet reconciled
    applied = "applied"    # ticked off against a loan
    rejected = "rejected"  # could not be applied (bad loan state, duplicate, …)


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True)
    borrower_name = Column(String, nullable=False)
    # NOTE: NGN amounts are stored as Float here, mirroring the platform's
    # current models. This is deliberate — do not assume it's correct.
    principal = Column(Float, nullable=False)
    total_repayable = Column(Float, nullable=False)  # principal + interest
    total_paid = Column(Float, nullable=False, default=0.0)
    status = Column(Enum(LoanStatus), nullable=False, default=LoanStatus.active)
    disbursed_at = Column(DateTime, default=_utcnow)

    @property
    def outstanding(self) -> float:
        return self.total_repayable - self.total_paid


class PaymentEvent(Base):
    """An incoming payment from a rail (gateway/GSI/CBS). Starts ``pending``.

    ``external_ref`` is the rail's own id for the payment — the idempotency key.
    It is intentionally NOT unique at the DB level: real rails redeliver, so the
    same ``external_ref`` can arrive more than once, and de-duplicating is part
    of the task.
    """

    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True)
    # Unique at the DB level: this is the idempotency key. A rail redelivering
    # the same external_ref must never result in two applied repayments — see
    # app/services/payment_reconciliation.py for how the resulting
    # IntegrityError on a race is turned into a "duplicate" rejection.
    external_ref = Column(String, nullable=False, unique=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    amount = Column(Float, nullable=False)
    channel = Column(String, nullable=False, default="paystack")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.pending)
    reason = Column(String, nullable=True)  # why it was rejected, if it was
    received_at = Column(DateTime, default=_utcnow)
    processed_at = Column(DateTime, nullable=True)


class Repayment(Base):
    """Ledger row created when a payment event is applied to a loan."""

    __tablename__ = "repayments"

    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    payment_event_id = Column(Integer, ForeignKey("payment_events.id"), nullable=True)
    amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)
    entity = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
