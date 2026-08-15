// Token mirrors app/auth.py's WEBHOOK_TOKEN.
export const WEBHOOK_TOKEN = "dev-webhook-secret";

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} HTTP ${r.status}`);
  return r.json();
}

export const getLoans = () => getJSON("/loans");
export const getPaymentEvents = () => getJSON("/payment-events");
export const getAuditLog = () => getJSON("/audit-log");

export function postPayment(payload) {
  return fetch("/webhooks/payments", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Webhook-Token": WEBHOOK_TOKEN },
    body: JSON.stringify(payload),
  });
}
