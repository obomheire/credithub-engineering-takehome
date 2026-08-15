import { expect, test } from "@playwright/test";

// Client-side routing between Feed ("/") and Admin ("/admin") via react-router-dom.

test.describe("Navigation", () => {
  test("navigates from Feed to Admin and back via the nav bar", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("/");

    await page.getByRole("link", { name: "Admin" }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("link", { name: "Admin" })).toHaveClass(/active/);
    await expect(page.getByRole("link", { name: "Feed" })).not.toHaveClass(/active/);
    await expect(page.getByText("Issues needing attention")).toBeVisible();

    await page.getByRole("link", { name: "Feed" }).click();
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("link", { name: "Feed" })).toHaveClass(/active/);
    await expect(page.getByText("Payments feed")).toBeVisible();
  });

  test("navigating directly to /admin renders the admin panel", async ({ page }) => {
    await page.goto("/admin");
    await expect(page.getByText("Issues needing attention")).toBeVisible();
    await expect(page.getByText("Reconciled", { exact: true })).toBeVisible();
    await expect(page.getByText("Activity trail")).toBeVisible();
  });
});
