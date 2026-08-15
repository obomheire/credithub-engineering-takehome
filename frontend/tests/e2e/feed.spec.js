import { expect, test } from "@playwright/test";

// Feed page ("/") — backed by GET /loans, GET /payment-events, and
// POST /webhooks/payments via the "Simulate incoming payment" / "Resend ↻"
// buttons. No mocking — this exercises the real FastAPI backend on :8137.

test.describe("Feed page", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("loads nav, stats, payments feed, and loans table", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "CreditHub" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Feed" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Admin" })).toBeVisible();

    // Stats row populates from GET /loans + GET /payment-events (skeletons resolve).
    await expect(page.getByText("Active loans")).toBeVisible();
    await expect(page.getByText("Outstanding · active")).toBeVisible();
    await expect(page.getByText("Payments received")).toBeVisible();
    await expect(page.locator(".stat .v").first()).not.toHaveText("—");

    // Payments feed table (seeded history from GET /payment-events).
    await expect(page.getByRole("columnheader", { name: "Reference" })).toBeVisible();
    await expect(page.locator("table.feed tbody tr").first()).toBeVisible();

    // Loans table (GET /loans).
    await expect(page.getByText("Loans", { exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Borrower" })).toBeVisible();
    await expect(page.getByText("Adaeze Okafor")).toBeVisible();
  });

  test("Feed nav link is active on /", async ({ page }) => {
    await expect(page.getByRole("link", { name: "Feed" })).toHaveClass(/active/);
    await expect(page.getByRole("link", { name: "Admin" })).not.toHaveClass(/active/);
  });

  test("Simulate incoming payment posts to the webhook and updates the feed", async ({ page }) => {
    // Wait for the initial mount fetch to resolve (skeleton rows replaced by
    // real data) before capturing a baseline — otherwise "before" may still
    // reflect the 3 loading-skeleton placeholder rows, not real event rows.
    const paymentsReceivedStat = page.locator(".stat .v").nth(2);
    await expect(paymentsReceivedStat).not.toHaveText("—");
    const feedRows = page.locator("table.feed tbody tr");
    const rowCountBefore = await feedRows.count();
    const paymentsReceivedBefore = Number(await paymentsReceivedStat.innerText());

    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/webhooks/payments") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Simulate incoming payment" }).click(),
    ]);
    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body).toHaveProperty("event");
    expect(["applied", "rejected"]).toContain(body.event.status);

    // UI refetches after the POST — feed grows by exactly one row, stat
    // increments by exactly one (this test's own baseline was captured after
    // the mount fetch settled, so the delta is exact regardless of how much
    // data other tests have added to the shared backend before this point).
    await expect(feedRows).toHaveCount(rowCountBefore + 1);
    await expect(paymentsReceivedStat).toHaveText(String(paymentsReceivedBefore + 1));
  });

  test("Resend ↻ redelivers a payment and the backend rejects it as a duplicate", async ({ page }) => {
    // First, create a fresh applied payment via Simulate so we have a known,
    // real external_ref to redeliver (seeded rows may already be duplicated
    // by earlier tests' Simulate clicks — using our own keeps this independent).
    const [simResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/webhooks/payments") && r.request().method() === "POST"),
      page.getByRole("button", { name: "Simulate incoming payment" }).click(),
    ]);
    const simBody = await simResponse.json();
    const ref = simBody.event.external_ref;

    const row = page.locator("table.feed tbody tr", { hasText: ref });
    await expect(row).toBeVisible();

    const [resendResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/webhooks/payments") && r.request().method() === "POST"),
      row.getByRole("button", { name: "Resend ↻" }).click(),
    ]);
    expect(resendResponse.status()).toBe(200);
    const resendBody = await resendResponse.json();
    expect(resendBody.event.status).toBe("rejected");
    expect(resendBody.event.reason).toBe("duplicate_external_ref");
  });
});
