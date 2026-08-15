import React, { useEffect, useMemo, useState } from "react";
import { getAuditLog, getPaymentEvents } from "../lib/api.js";
import { ngn, REASON_LABEL } from "../lib/format.js";

const REASONS = [
  "unknown_loan",
  "loan_not_active",
  "invalid_amount",
  "overpayment",
  "duplicate_external_ref",
];

const TRAIL_LIMIT = 20;

export default function AdminPanel() {
  const [events, setEvents] = useState(null);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [reasonFilter, setReasonFilter] = useState(null);

  useEffect(() => {
    setError(null);
    Promise.all([getPaymentEvents(), getAuditLog()])
      .then(([e, a]) => { setEvents(e); setAudit(a); })
      .catch((err) => setError(String(err.message || err)));
  }, []);

  const eventList = events ?? [];
  const applied = useMemo(() => eventList.filter((e) => e.status === "applied"), [eventList]);
  const rejected = useMemo(() => eventList.filter((e) => e.status === "rejected"), [eventList]);
  const total = eventList.length;
  const failureRate = total ? (rejected.length / total) * 100 : 0;

  const byReason = useMemo(
    () =>
      REASONS.map((reason) => ({
        reason,
        items: rejected.filter((e) => e.reason === reason),
      })).filter((g) => g.items.length > 0),
    [rejected]
  );

  const visibleIssues = reasonFilter ? rejected.filter((e) => e.reason === reasonFilter) : rejected;

  const auditList = audit ?? [];
  const trail = auditList.slice(0, TRAIL_LIMIT);

  const loading = events === null && !error;

  return (
    <>
      <p className="sub">The operational picture — what reconciled, and what needs attention.</p>

      {error && (
        <div className="banner">
          Couldn’t reach the API on <b>:8137</b> — is it running? ({error})
        </div>
      )}

      <div className="stats">
        <div className="stat">
          <div className="k">Total reconciled</div>
          <div className="v">{events ? total : "—"}</div>
        </div>
        <div className="stat">
          <div className="k">Applied</div>
          <div className="v">{events ? applied.length : "—"}</div>
        </div>
        <div className={`stat${events && rejected.length > 0 ? " warn" : ""}`}>
          <div className="k">Failure rate</div>
          <div className="v">{events ? `${failureRate.toFixed(1)}%` : "—"}</div>
          {events && <div className="sub-id">{rejected.length} of {total}</div>}
        </div>
      </div>

      {/* Issues — front and centre */}
      <div className="card">
        <div className="card-h">
          <span>Issues needing attention</span>
        </div>

        {byReason.length > 0 && (
          <div className="filter-bar">
            <button
              className={`filter-pill${reasonFilter === null ? " active" : ""}`}
              onClick={() => setReasonFilter(null)}
            >
              All ({rejected.length})
            </button>
            {byReason.map((g) => (
              <button
                key={g.reason}
                className={`filter-pill${reasonFilter === g.reason ? " active" : ""}`}
                onClick={() => setReasonFilter(reasonFilter === g.reason ? null : g.reason)}
              >
                {REASON_LABEL[g.reason] || g.reason} ({g.items.length})
              </button>
            ))}
          </div>
        )}

        <table className="feed">
          <thead>
            <tr>
              <th>Reference</th>
              <th>Loan</th>
              <th className="num">Amount</th>
              <th>Reason</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {loading &&
              [0, 1, 2].map((i) => (
                <tr key={i}><td colSpan="5"><div className="skeleton" /></td></tr>
              ))}

            {events && visibleIssues.length === 0 && (
              <tr><td colSpan="5" className="muted">No issues — everything reconciled cleanly.</td></tr>
            )}

            {events &&
              visibleIssues.map((e) => (
                <tr key={e.id}>
                  <td className="ref">
                    {e.external_ref}
                    <div className="chan">{e.channel}</div>
                  </td>
                  <td>Loan #{e.loan_id}</td>
                  <td className="num">{ngn.format(e.amount)}</td>
                  <td><span className={`rbadge ${e.reason}`}>{REASON_LABEL[e.reason] || e.reason}</span></td>
                  <td className="muted">{e.received_at ? new Date(e.received_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {/* Reconciled — secondary */}
      <div className="section-title">Reconciled</div>
      <div className="card">
        <table className="feed">
          <thead>
            <tr>
              <th>Reference</th>
              <th>Loan</th>
              <th className="num">Amount</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {loading &&
              [0, 1, 2].map((i) => (
                <tr key={i}><td colSpan="4"><div className="skeleton" /></td></tr>
              ))}

            {events && applied.length === 0 && (
              <tr><td colSpan="4" className="muted">Nothing applied yet.</td></tr>
            )}

            {events &&
              applied.map((e) => (
                <tr key={e.id}>
                  <td className="ref">
                    {e.external_ref}
                    <div className="chan">{e.channel}</div>
                  </td>
                  <td>Loan #{e.loan_id}</td>
                  <td className="num">{ngn.format(e.amount)}</td>
                  <td className="muted">{e.received_at ? new Date(e.received_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      {/* Activity trail — lowest priority, from GET /audit-log. Note: a
          duplicate redelivery never gets its own PaymentEvent row (see
          app/services/payment_reconciliation.py), so it's never separately
          audited either — it will appear in Issues above but not here. This
          is expected, not a bug to "fix". */}
      <div className="section-title">Activity trail</div>
      <div className="card">
        <div className="trail">
          {audit === null && !error && <div style={{ padding: "13px 18px" }}><div className="skeleton" /></div>}

          {audit && trail.length === 0 && (
            <div className="trail-row muted">No activity yet.</div>
          )}

          {audit &&
            trail.map((a) => (
              <div className="trail-row" key={a.id}>
                <div className="trail-action">{a.action}</div>
                <div className="trail-meta">
                  {a.entity} #{a.entity_id} · {a.actor} · {a.created_at ? new Date(a.created_at).toLocaleString() : "—"}
                </div>
                {a.detail && <div className="trail-detail">{a.detail}</div>}
              </div>
            ))}

          {audit && auditList.length > TRAIL_LIMIT && (
            <div className="trail-row muted">Showing latest {TRAIL_LIMIT} of {auditList.length}.</div>
          )}
        </div>
      </div>
    </>
  );
}
