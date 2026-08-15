"""Read endpoint for the audit trail (new — exposes AuditLog read-only).

Every payment reconciliation (applied or rejected-non-duplicate) already
writes an AuditLog row via app/audit.py, in the same transaction as the
financial change. This endpoint just exposes that existing trail.
"""

from fastapi import APIRouter, Depends

from .db import get_db
from .models import AuditLog

router = APIRouter()


def _audit_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "action": a.action,
        "entity": a.entity,
        "entity_id": a.entity_id,
        "actor": a.actor,
        "detail": a.detail,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/audit-log")
def list_audit_log(db=Depends(get_db)):
    """The audit trail (newest first) — matches /payment-events' convention."""
    entries = db.query(AuditLog).order_by(AuditLog.id.desc()).all()
    return [_audit_out(a) for a in entries]
