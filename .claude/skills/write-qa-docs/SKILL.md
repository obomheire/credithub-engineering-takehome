---
name: write-qa-docs
description: "Generate comprehensive QA test documentation in Markdown for a feature or requirement, saved to @api-docs/"
argument-hint: "<feature-name-or-description>"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
---

<objective>
Generate a comprehensive QA test documentation file in Markdown format for the specified feature or requirement, saved to `@api-docs/<feature>-qa.md`.

The output is designed for QA Engineers who need to test the feature end-to-end without reading source code. It must contain enough context, acceptance criteria, test scenarios, and setup instructions for the QA Engineer to execute a full test pass independently.

Output: `@api-docs/<feature>-qa.md`
</objective>

<context>
Feature or requirement to document: $ARGUMENTS

Project context:
- NestJS monorepo, REST API on port 9000, global prefix `api/v1`
- WebSocket service (Socket.io) on port 9001
- Auth: JWT Bearer tokens obtained via `POST /api/v1/auth/login`
- Pagination: cursor-based only (`cursor`, `limit`); never offset/page
- Validation: `whitelist: true` + `forbidNonWhitelisted: true` — unknown fields return 400
- Database: DigitalOcean managed PostgreSQL (connect via `DATABASE_URL` from `.env`)
- Background jobs: BullMQ workers (no HTTP server)
- Swagger UI: `http://localhost:9000/api/docs`
</context>

<process>

## Step 1 — Understand the feature

Search the codebase to understand the full scope of what was implemented:

```bash
find apps/ libs/ -type f -name "*.controller.ts" | xargs grep -l "<feature>" 2>/dev/null
find apps/ libs/ -type f -name "*.service.ts" | xargs grep -l "<feature>" 2>/dev/null
find apps/ libs/ -type f -name "*.dto.ts" | xargs grep -l "<feature>" 2>/dev/null
find apps/ libs/ -type f -name "*.gateway.ts" | xargs grep -l "<feature>" 2>/dev/null
find apps/ libs/ -type f -name "*.processor.ts" | xargs grep -l "<feature>" 2>/dev/null
```

Read all relevant files:
- `<feature>.controller.ts` — routes, guards, path/query params, response shapes
- `<feature>.service.ts` — business logic, state transitions, error conditions, side effects
- `dto/*.dto.ts` — request/response shapes, validation constraints, enum values
- `<feature>.gateway.ts` (if applicable) — WebSocket events emitted and received
- `<feature>.processor.ts` (if applicable) — background job behaviour and side effects
- Schema file `libs/shared/src/database/schema/index.ts` — DB column types, constraints, relationships

## Step 2 — Extract feature requirements

From the source files, derive:
- What the feature does (purpose, user-facing behaviour)
- Which endpoints, events, or jobs are involved
- What state transitions exist (e.g. `pending → active → completed`)
- What side effects occur (DB writes, queue jobs dispatched, WebSocket events emitted, cache invalidations)
- What invariants must hold (uniqueness constraints, foreign key rules, business rules enforced in service)
- What authentication and authorisation rules apply

## Step 3 — Identify all test surfaces

Map every testable surface:
- REST endpoints (method, path, auth, body, query params)
- WebSocket events (emitted by server, received from client)
- Background job triggers and outcomes
- Database state changes that should be verifiable
- Error paths and edge cases from `throw` statements in the service

## Step 4 — Write the documentation

Create `@api-docs/<feature>-qa.md` using the structure below. Omit sections that genuinely do not apply. Never leave a section with a placeholder or empty table — either populate it from the code or remove the section.

---

# `<Feature Name>` — QA Test Documentation

> **Environment:** `http://localhost:9000` (dev) / `https://api.loopscribe.com` (prod)  
> **WebSocket:** `http://localhost:9001` (dev) / `https://realtime.loopscribe.com` (prod)  
> **Swagger UI:** `http://localhost:9000/api/docs`

## 1. Feature Overview

### What this feature does

2–4 sentences describing the feature from a product/user perspective. Focus on observable behaviour, not implementation details.

### Scope of this document

List every component involved in this feature:

- [ ] REST endpoints (list them)
- [ ] WebSocket events (list them, or "None")
- [ ] Background jobs (list them, or "None")
- [ ] Database tables affected (list them)
- [ ] External integrations (list them, or "None")

### Out of scope

List anything explicitly NOT tested by this document (e.g. third-party integrations, future phases, unrelated endpoints).

---

## 2. Acceptance Criteria

These are the conditions that must ALL be true for the feature to be considered complete and correct.

| # | Criterion | How to verify |
|---|-----------|---------------|
| AC-01 | Description of expected behaviour | REST call / DB check / WebSocket event |
| AC-02 | … | … |

> Derive these directly from business rules enforced in the service layer (guard clauses, thrown exceptions, state machine transitions). Every `throw` in the service should map to at least one acceptance criterion.

---

## 3. Test Environment Setup

### Prerequisites

Before running any test, ensure the following are in place:

- [ ] API service is running (`npm run dev:api` or `npm run start:api` on port 9000)
- [ ] Realtime service is running (`npm run dev:realtime` on port 9001) *(if WebSocket events are involved)*
- [ ] Workers service is running (`npm run dev:workers`) *(if background jobs are involved)*
- [ ] PostgreSQL database is accessible (via `DATABASE_URL` in `.env`)
- [ ] Redis is running (required for BullMQ queues and cache)

### Test user accounts

| Role | How to obtain |
|------|---------------|
| `admin` | `POST /api/v1/auth/login` with admin credentials |
| `user` | `POST /api/v1/auth/login` with standard user credentials |

### Seed data required

Describe any records that must exist before tests can run (e.g. a show must exist before testing show sessions).

```bash
# Example: obtain a JWT for use in all requests
curl -s -X POST http://localhost:9000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"password"}' \
  | jq .accessToken
```

### Database verification

To inspect DB state after test steps:

```js
require('dotenv').config({ path: '.env' });
const postgres = require('./node_modules/postgres');
const sql = postgres(process.env.DATABASE_URL, { ssl: 'require' });
// example: const rows = await sql`SELECT * FROM <table> WHERE id = ${id}`;
await sql.end();
```

---

## 4. API Reference (QA Cheat Sheet)

A condensed reference for every endpoint involved. Full field-level documentation is in the companion `<feature>.md` file if it exists.

### `<HTTP_METHOD> /api/v1/<path>`

| Property | Value |
|----------|-------|
| Auth required | Yes — `Authorization: Bearer <token>` |
| Role required | `admin` / `user` / none |
| Success status | `200 OK` / `201 Created` / `204 No Content` |

**Request body (if applicable):**

```json
{
  "field": "value"
}
```

**Key fields:**

| Field | Type | Required | Allowed values / constraints |
|-------|------|----------|------------------------------|
| `field` | `string` | Yes | min 1 char |

**Success response:**

```json
{
  "id": "uuid",
  "field": "value",
  "createdAt": "2026-01-01T00:00:00.000Z"
}
```

**Error responses:**

| Status | Cause |
|--------|-------|
| `400` | Validation failed — missing or invalid fields |
| `401` | Missing or invalid JWT |
| `403` | Insufficient role |
| `404` | Resource not found |
| `409` | Conflict — duplicate or constraint violation |
| `422` | Business rule violation |

*(Repeat this block for every endpoint in the feature)*

---

## 5. WebSocket Events *(omit if not applicable)*

### Connection

```
URL: http://localhost:9001
Namespace: / (or /<namespace>)
Transport: websocket
Auth: { token: "<jwt>" }  (passed in handshake auth object)
```

### Events

#### Server → Client

| Event | Payload | When emitted |
|-------|---------|--------------|
| `event:name` | `{ field: value }` | Description of trigger |

#### Client → Server

| Event | Payload | Expected response |
|-------|---------|-------------------|
| `event:name` | `{ field: value }` | ACK or follow-up server event |

---

## 6. Test Scenarios

Each scenario is self-contained: it lists its own setup, steps, and expected results. Execute steps in order. A `✓` in the result column means the scenario passes.

### TC-01 — Happy path: [brief description]

**Setup:** [any specific state required before this test]  
**Auth:** [role required]

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | `POST /api/v1/...` with valid body | `201 Created` — response contains `id`, all fields match input |
| 2 | `GET /api/v1/.../{id}` | `200 OK` — returned resource matches created data |
| 3 | Verify DB: `SELECT * FROM <table> WHERE id = '<id>'` | Row exists with correct field values |

---

### TC-02 — [Next scenario title]

**Setup:** …  
**Auth:** …

| Step | Action | Expected result |
|------|--------|-----------------|
| 1 | … | … |

---

*(Add one scenario per meaningful test case. Cover at minimum: happy path, auth failure, validation failure, not-found, business rule violation, and any state-machine transitions)*

### Required scenario coverage checklist

- [ ] TC-happy-path — full success flow end-to-end
- [ ] TC-auth-missing — request without `Authorization` header returns `401`
- [ ] TC-auth-invalid-role — request with wrong role returns `403` *(if role-restricted)*
- [ ] TC-validation-missing-required — omit a required field, expect `400`
- [ ] TC-validation-bad-enum — supply an invalid enum value, expect `400`
- [ ] TC-not-found — use a non-existent ID, expect `404`
- [ ] TC-conflict — trigger a duplicate/constraint violation, expect `409` *(if applicable)*
- [ ] TC-business-rule — violate a service-level invariant, expect `422` *(if applicable)*
- [ ] TC-state-transition — drive through every valid state transition *(if applicable)*
- [ ] TC-invalid-state-transition — attempt a forbidden transition, expect correct error *(if applicable)*
- [ ] TC-websocket-event — verify the correct Socket.io event fires after trigger *(if applicable)*
- [ ] TC-background-job — verify job is enqueued and produces expected DB side effect *(if applicable)*
- [ ] TC-pagination — verify cursor-based pagination works across multiple pages *(if list endpoint exists)*

---

## 7. State Machine *(omit if not applicable)*

Describe the lifecycle of the primary resource managed by this feature.

```
[initial_state] → [state_a] → [state_b] → [terminal_state]
                      ↓
                 [cancelled]
```

| Transition | Trigger | Who can initiate | Side effects |
|-----------|---------|-----------------|--------------|
| `initial → state_a` | `POST /api/v1/...` | `admin` | Job enqueued, event emitted |
| `state_a → state_b` | `PATCH /api/v1/.../{id}` | `user` | Cache invalidated |
| `state_a → cancelled` | `DELETE /api/v1/.../{id}` | `admin` | Soft-deleted, event emitted |

**Invalid transitions** (must return an error):

| Attempted transition | Expected error |
|---------------------|----------------|
| `terminal → state_a` | `422 Unprocessable Entity` |

---

## 8. Background Jobs *(omit if not applicable)*

| Job | Queue | Triggered by | Expected outcome | Verification |
|-----|-------|-------------|-----------------|--------------|
| `job-name` | `queue-name` | `POST /api/v1/...` | Record created in `<table>` | Query DB after short delay |

**Testing background jobs:**

1. Trigger the job via its REST endpoint.
2. Wait for the worker to process (typically < 2 s in dev with a running worker).
3. Query the database to confirm the expected side effect occurred.
4. Check worker logs for any errors.

---

## 9. Regression Checklist

After verifying the new feature, run a quick smoke test on related features to confirm no regressions:

- [ ] [Related feature 1] — [specific thing to check]
- [ ] [Related feature 2] — [specific thing to check]
- [ ] Authentication endpoints still return tokens correctly
- [ ] Unrelated list endpoints still paginate correctly

---

## 10. Known Limitations & Gotchas

- **Cursor stability** — list cursors are only valid while the sort order is unchanged; inserts during pagination may cause items to appear or be skipped.
- **JWT expiry** — tokens expire; re-authenticate if you receive `401` mid-session.
- **Worker dependency** — background job side effects require the workers service to be running; if it is stopped, REST calls may succeed but DB side effects will not appear until the worker restarts and drains the queue.
- Add any other feature-specific edge cases discovered during implementation here.

---

*Generated by the `write-qa-docs` skill. Update this document whenever the feature implementation changes.*

---

## Step 5 — Validate completeness

Before finishing, verify:
- [ ] Feature overview accurately describes observable behaviour (not implementation internals)
- [ ] Every acceptance criterion maps to at least one test scenario
- [ ] Every endpoint in the feature has a cheat-sheet block in Section 4
- [ ] Every enum lists all allowed values
- [ ] Every `throw` / error path in the service maps to a negative test scenario
- [ ] State machine section present if the resource has status/state transitions
- [ ] WebSocket section present if `apps/realtime/` contains a gateway for this feature
- [ ] Background job section present if a processor handles this feature's jobs
- [ ] Regression checklist names at least two adjacent features that share data or routes
- [ ] Section 10 lists at least one real gotcha derived from the implementation (not a generic placeholder)

If the `@api-docs/` directory does not exist in the project root, create it before writing the file.
</process>
