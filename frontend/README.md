# Frontend (React + Vite)

The base screen is **provided** — a payments feed + live loan balances. It fires
payments at the backend webhook and reflects the results; **"Simulate incoming
payment"** sends a new payment and **"Resend ↻"** re-fires an existing one (a rail
redelivery). You don't need to change it for the core task (the backend webhook).

As a **frontend extension**, build an **admin reconciliation & issues panel** on
top of this — see *Your task* in the root `README.md`.

```bash
npm install
npm run dev          # http://localhost:5137  (proxies the API to :8137)
```

The Vite dev server proxies API calls to the backend on `:8137`, so there's no
CORS to configure. Start the backend first (see the root `README.md`).

## E2E tests (Playwright)

Full end-to-end coverage of the frontend against the real FastAPI backend (no
mocking) — the Feed page, the Admin reconciliation panel, and navigation between
them, exercising `GET /loans`, `GET /payment-events`, `GET /audit-log`, and
`POST /webhooks/payments`.

```bash
npx playwright install chromium   # one-time browser install
npm run test:e2e                  # headless
npx playwright test --headed      # headed — watch the browser run
```

Both servers (backend on `:8137`, frontend on `:5137`) are started and stopped
automatically by `playwright.config.js` — no need to run them yourself first. The
backend is reseeded fresh (`python -m app.seed`) at the start of the run.

Test files live in `tests/e2e/`:
- `feed.spec.js` — nav, stats, payments feed, loans table, Simulate/Resend against the real webhook.
- `navigation.spec.js` — routing between `/` and `/admin`.
- `admin-panel.spec.js` — KPI stats, Issues filtering by reason, Reconciled section, Activity trail, and the duplicate-redelivery/audit-log edge case.
