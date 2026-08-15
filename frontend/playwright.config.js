import { defineConfig, devices } from "@playwright/test";

// Full E2E suite for the CreditHub frontend against the real FastAPI backend
// (no mocking) — both servers are started automatically for the test run.
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false, // tests share one backend DB; keep them sequential
  workers: 1,
  reporter: "line",
  use: {
    baseURL: "http://localhost:5137",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command:
        "cd .. && rm -f takehome.db && .venv/bin/python -m app.seed && .venv/bin/python -m uvicorn app.main:app --port 8137",
      url: "http://localhost:8137/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5137",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
