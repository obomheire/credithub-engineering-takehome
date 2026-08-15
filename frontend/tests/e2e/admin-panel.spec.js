import { expect, test } from "@playwright/test";

// Admin panel ("/admin") — backed by GET /payment-events and GET /audit-log.
// Seeds deterministic applied/rejected payments directly via the real webhook
// API (not mocked) so the Issues/Reconciled/Activity sections have known
// content to assert against. Each test uses its own unique external_ref
// prefix and asserts deltas/row-content rather than absolute counts, since
// the suite shares one backend/DB across the whole run (no per-test reset).

const WEBHOOK = "http://localhost:8137/webhooks/payments";
const TOK = { "X-Webhook-Token": "dev-webhook-secret", "Content-Type": "application/json" };

async function post(request, body) {
  return request.post(WEBHOOK, { headers: TOK, data: body });
}

test.describe("Admin panel", () => {
  test("shows KPI stats, Issues, Reconciled, and Activity trail sections", async ({ page, request }) => {
    const ref = "ADMIN-SECTIONS-" + Date.now();
    await post(request, { external_ref: ref, loan_id: 1, amount: 1000, channel: "paystack" });
    await post(request, { external_ref: ref + "-over", loan_id: 1, amount: 999999, channel: "paystack" });

    await page.goto("/admin");

    await expect(page.getByText("Total reconciled")).toBeVisible();
    await expect(page.getByText("Applied", { exact: true })).toBeVisible();
    await expect(page.getByText("Failure rate")).toBeVisible();
    await expect(page.locator(".stat .v").first()).not.toHaveText("—");

    await expect(page.getByText("Issues needing attention")).toBeVisible();
    const issuesCard = page.locator(".card", { hasText: "Issues needing attention" });
    await expect(issuesCard.locator("tr", { hasText: ref + "-over" })).toBeVisible();
    await expect(issuesCard.locator("tr", { hasText: ref + "-over" }).getByText("Overpayment")).toBeVisible();

    await expect(page.locator(".section-title", { hasText: "Reconciled" })).toBeVisible();

    await expect(page.getByText("Activity trail")).toBeVisible();
    await expect(page.getByText("payment.applied").first()).toBeVisible();
    await expect(page.getByText("payment.rejected").first()).toBeVisible();
  });

  test("filtering Issues by a reason pill narrows the table to only that reason", async ({ page, request }) => {
    const ref = "ADMIN-FILTER-" + Date.now();
    // Two different reasons, both fresh, so we know at least one of each
    // exists no matter what earlier tests already added.
    await post(request, { external_ref: ref + "-over", loan_id: 1, amount: 999999, channel: "paystack" });
    await post(request, { external_ref: ref + "-unknown", loan_id: 999999, amount: 100, channel: "paystack" });

    await page.goto("/admin");
    const issuesCard = page.locator(".card", { hasText: "Issues needing attention" });
    const overpaymentPill = issuesCard.getByRole("button", { name: /Overpayment \(\d+\)/ });
    await expect(overpaymentPill).toBeVisible();

    const rowsBefore = await issuesCard.locator("table tbody tr").count();
    expect(rowsBefore).toBeGreaterThanOrEqual(2); // at least our two fresh rows

    await overpaymentPill.click();
    await expect(overpaymentPill).toHaveClass(/active/);

    // Every visible row is now an overpayment, and ours is among them.
    const rows = issuesCard.locator("table tbody tr");
    const count = await rows.count();
    for (let i = 0; i < count; i++) {
      await expect(rows.nth(i)).toContainText("Overpayment");
    }
    await expect(issuesCard.locator("tr", { hasText: ref + "-over" })).toBeVisible();
    await expect(issuesCard.locator("tr", { hasText: ref + "-unknown" })).toHaveCount(0);

    // Toggling the same pill off restores the full (unfiltered) list.
    await overpaymentPill.click();
    await expect(overpaymentPill).not.toHaveClass(/active/);
    await expect(issuesCard.locator("table tbody tr")).toHaveCount(rowsBefore);
    await expect(issuesCard.locator("tr", { hasText: ref + "-unknown" })).toBeVisible();
  });

  test("a duplicate redelivery is rejected and does not add a second Activity trail entry", async ({ page, request }) => {
    const ref = "ADMIN-DUP-" + Date.now();
    const first = await post(request, { external_ref: ref, loan_id: 1, amount: 1000, channel: "paystack" });
    expect((await first.json()).event.status).toBe("applied");

    const dup = await post(request, { external_ref: ref, loan_id: 1, amount: 1000, channel: "paystack" });
    const dupBody = await dup.json();
    expect(dupBody.event.status).toBe("rejected");
    expect(dupBody.event.reason).toBe("duplicate_external_ref");

    await page.goto("/admin");
    // /audit-log only ever gets ONE entry for this ref (the original
    // application) — the redelivery, being rejected without a new
    // PaymentEvent row, is never separately audited.
    const trailEntriesForRef = page.locator(".trail-row", { hasText: ref });
    await expect(trailEntriesForRef).toHaveCount(1);
    await expect(trailEntriesForRef.first()).toContainText("payment.applied");
  });

  test("All pill resets the filter and restores the full row count", async ({ page, request }) => {
    const ref = "ADMIN-ALL-" + Date.now();
    await post(request, { external_ref: ref + "-unknown", loan_id: 999999, amount: 100, channel: "paystack" });

    await page.goto("/admin");
    const issuesCard = page.locator(".card", { hasText: "Issues needing attention" });
    const allPill = issuesCard.getByRole("button", { name: /All \(\d+\)/ });
    await expect(allPill).toHaveClass(/active/);

    const totalRows = await issuesCard.locator("table tbody tr").count();
    expect(totalRows).toBeGreaterThanOrEqual(1);

    const unknownPill = issuesCard.getByRole("button", { name: /Unknown loan \(\d+\)/ });
    await unknownPill.click();
    const filteredRows = await issuesCard.locator("table tbody tr").count();
    expect(filteredRows).toBeLessThanOrEqual(totalRows);
    await expect(issuesCard.locator("tr", { hasText: ref + "-unknown" })).toBeVisible();

    await allPill.click();
    await expect(issuesCard.locator("table tbody tr")).toHaveCount(totalRows);
  });
});
