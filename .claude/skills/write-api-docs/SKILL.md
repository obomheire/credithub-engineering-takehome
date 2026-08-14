---
name: write-api-docs
description: "Generate comprehensive frontend-facing API documentation in Markdown for a feature or module, saved to /Users/zackoverflow/Documents/Projects/loopscribe/api/loopscribe-v2-api/api-docs/"
argument-hint: "<feature-name-or-description>"
allowed-tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
---

<objective>
Generate a comprehensive, frontend-facing API documentation file in Markdown format for the specified feature or module, saved to `/Users/zackoverflow/Documents/Projects/loopscribe/api/loopscribe-v2-api/api-docs/<feature>.md`.

The output is designed for frontend engineers who need to integrate with the API without reading backend source code. It must be complete enough to implement the entire integration without additional backend clarification.

Output: `/Users/zackoverflow/Documents/Projects/loopscribe/api/loopscribe-v2-api/api-docs/<feature>.md`
</objective>

<context>
Feature or module to document: $ARGUMENTS

Project context:
- NestJS monorepo, REST API on port 9000, global prefix `api/v1`
- Auth: JWT Bearer tokens obtained via `POST /api/v1/auth/login`
- Pagination: cursor-based only (`cursor`, `limit`); never offset/page
- All list responses include a `pagination` envelope with `nextCursor`, `hasNextPage`, `limit`
- Validation: `whitelist: true` + `forbidNonWhitelisted: true` — unknown fields return 400
- Swagger UI available at `http://localhost:9000/api/docs`
</context>

<process>

## Step 1 — Locate the implementation

Search the codebase for the feature's controller, service, and DTOs:

```bash
find apps/api/src -type f -name "*.controller.ts" | xargs grep -l "<feature>" 2>/dev/null
find apps/api/src -type f -name "*.dto.ts" | xargs grep -l "<feature>" 2>/dev/null
```

Read all relevant files:
- `<feature>.controller.ts` — routes, guards, decorators, path/query params
- `<feature>.service.ts` — business logic, error conditions, return shapes
- `dto/*.dto.ts` — request/response shapes, validation rules, field constraints
- Schema file at `libs/shared/src/database/schema/index.ts` — DB column types and constraints

## Step 2 — Extract all endpoint details

For each endpoint, extract:
- HTTP method + full path (include `api/v1` prefix)
- Authentication requirement (public vs. `@UseGuards(JwtAuthGuard)`)
- Role requirement (if `@Roles(...)` decorator present)
- Path parameters
- Query parameters (including pagination fields)
- Request body DTO (every field: type, required/optional, validation rules, allowed enum values)
- Response DTO (every field)
- All thrown exceptions (`NotFoundException`, `ConflictException`, etc.) → HTTP status codes

## Step 3 — Identify the integration flow

From the controller and service logic, determine:
- The correct order to call endpoints (e.g. create before read)
- State machine transitions (e.g. `pending → active → completed`)
- Any prerequisite data (e.g. must have a show before creating a beat)
- Realtime/WebSocket events that accompany REST calls (check `apps/realtime/src/` if applicable)

## Step 4 — Write the documentation

Create `/Users/zackoverflow/Documents/Projects/loopscribe/api/loopscribe-v2-api/api-docs/<feature>.md` using the structure below. Omit sections that genuinely do not apply (e.g. no WebSocket section for a pure REST feature). Never leave a section empty — either populate it or remove it.

---

# `<Feature Name>` API

> **Base URL:** `http://localhost:9000/api/v1` (dev) / `https://api.loopscribe.com/api/v1` (prod)

## 1. Overview

Brief description of the feature, its purpose, and which part of the product it powers. 2–4 sentences.

## 2. Authentication & Authorization

| Requirement | Value |
|---|---|
| Auth method | Bearer JWT |
| Token endpoint | `POST /api/v1/auth/login` |
| Required role | `admin` / `user` / public |
| Header | `Authorization: Bearer <token>` |

> **Note:** Include any role-specific endpoint restrictions here.

## 3. API Endpoints

### `<HTTP_METHOD> /api/v1/<path>`

**Description:** One-sentence description.

**Auth required:** Yes / No  
**Role required:** `admin` / `user` / none

#### Request Headers

| Header | Required | Description |
|---|---|---|
| `Authorization` | Yes | `Bearer <jwt>` |
| `Content-Type` | Yes (POST/PATCH) | `application/json` |

#### Path Parameters

| Parameter | Type | Description |
|---|---|---|
| `id` | `string (UUID)` | Resource identifier |

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `cursor` | `string` | No | — | Opaque pagination cursor from previous response |
| `limit` | `number` | No | `20` | Max items per page (1–100) |

#### Request Body

```json
{
  "field": "value"
}
```

| Field | Type | Required | Validation | Description |
|---|---|---|---|---|
| `field` | `string` | Yes | min 1 char | Description of the field |

#### Success Response — `200 OK`

```json
{
  "id": "uuid",
  "field": "value",
  "createdAt": "2026-01-01T00:00:00.000Z"
}
```

| Field | Type | Description |
|---|---|---|
| `id` | `string (UUID)` | Unique identifier |
| `createdAt` | `string (ISO 8601)` | Creation timestamp |

#### Error Responses

| Status | Code | Message | Cause |
|---|---|---|---|
| `400` | `BAD_REQUEST` | Validation error | Invalid/missing fields |
| `401` | `UNAUTHORIZED` | Unauthorized | Missing or invalid JWT |
| `404` | `NOT_FOUND` | Resource not found | ID does not exist |
| `409` | `CONFLICT` | Resource already exists | Duplicate key |

---

*(Repeat the endpoint block above for every endpoint in the feature)*

## 4. Data Models

### `<ResourceDto>`

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | `string (UUID)` | No | Primary key |
| `createdAt` | `string (ISO 8601)` | No | UTC creation time |
| `updatedAt` | `string (ISO 8601)` | No | UTC last-modified time |

### `<CreateResourceDto>`

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `name` | `string` | Yes | 1–255 chars | Human-readable name |

### Enums

#### `<EnumName>`

| Value | Description |
|---|---|
| `value_a` | What this value means |
| `value_b` | What this value means |

## 5. Pagination

All list endpoints use **cursor-based pagination**.

### Request

```
GET /api/v1/<resource>?limit=20
GET /api/v1/<resource>?cursor=<nextCursor>&limit=20
```

### Response envelope

```json
{
  "data": [...],
  "pagination": {
    "nextCursor": "eyJjcmVhdGVkQXQiOiIyMDI2LTAxLTAxVDAwOjAwOjAwLjAwMFoiLCJpZCI6InV1aWQifQ",
    "hasNextPage": true,
    "limit": 20
  }
}
```

- Omit `cursor` on the first request.
- Pass `pagination.nextCursor` as `cursor` to fetch the next page.
- `hasNextPage: false` means you have reached the last page.
- Cursors are opaque — do not parse or construct them manually.

## 6. Frontend Integration Notes

### Integration flow

1. Step one (e.g. authenticate and store JWT)
2. Step two (e.g. fetch list on page load)
3. Step three (e.g. create resource, then refetch or append optimistically)

### State transitions

```
pending → active → completed
           ↓
        cancelled
```

Describe what triggers each transition and whether it is user-initiated or system-driven.

### Caching recommendations

- Cache list responses keyed by cursor + limit for the current session.
- Invalidate the list cache after any create/update/delete operation.
- Single-resource responses can be cached by ID with a short TTL (e.g. 60 s).

### Optimistic updates

For create and delete operations, apply the change to local state immediately and roll back on error. For updates, wait for the server response before updating local state (to avoid showing stale enum values).

### Realtime events (if applicable)

If the feature emits Socket.io events from `apps/realtime`, document them here:

| Event | Direction | Payload | Trigger |
|---|---|---|---|
| `show:beat` | Server → Client | `{ beatId, content }` | Beat delivered during live show |

## 7. Error Handling

| HTTP Status | When it occurs | Recommended handling |
|---|---|---|
| `400 Bad Request` | DTO validation failed | Display field-level errors from `message` array |
| `401 Unauthorized` | JWT missing, expired, or invalid | Redirect to login; clear stored token |
| `403 Forbidden` | Insufficient role | Show permission denied message |
| `404 Not Found` | Resource ID does not exist | Show empty state or 404 page |
| `409 Conflict` | Duplicate resource | Show inline conflict error |
| `422 Unprocessable Entity` | Business rule violation | Display `message` to the user |
| `500 Internal Server Error` | Unexpected server error | Show generic error; log to monitoring |

### Validation error shape (`400`)

```json
{
  "statusCode": 400,
  "message": ["field must be a string", "field should not be empty"],
  "error": "Bad Request"
}
```

Iterate `message` and map each string to the relevant form field for inline display.

## 8. Sequence Examples

### Create and retrieve a resource

```
1. POST   /api/v1/auth/login             → { accessToken }
2. POST   /api/v1/<resource>             → { id, ... }        (store id)
3. GET    /api/v1/<resource>/{id}        → full resource
4. PATCH  /api/v1/<resource>/{id}        → updated resource
5. DELETE /api/v1/<resource>/{id}        → 204 No Content
```

### Paginate through a list

```
1. GET /api/v1/<resource>?limit=20
   → { data: [...20 items], pagination: { nextCursor: "abc", hasNextPage: true } }

2. GET /api/v1/<resource>?cursor=abc&limit=20
   → { data: [...20 items], pagination: { nextCursor: "def", hasNextPage: true } }

3. GET /api/v1/<resource>?cursor=def&limit=20
   → { data: [...5 items], pagination: { nextCursor: null, hasNextPage: false } }
```

## 9. Assumptions & Limitations

- **Auth tokens expire** — implement refresh or re-login logic; the API does not return a specific "token expired" error code beyond `401`.
- **Cursor stability** — cursors are only valid within the same sort order; if items are added while paginating, new items may appear or be skipped.
- **Soft vs. hard delete** — describe whether resources are soft-deleted (still visible with `deletedAt`) or hard-deleted.
- List any known rate limits, maximum payload sizes, or other constraints relevant to this feature.

---

*Generated by the `write-api-docs` skill. Keep in sync with backend changes.*

---

## Step 5 — Validate completeness

Before finishing, verify:
- [ ] Every endpoint in the controller is documented
- [ ] Every DTO field is in a table with type, required flag, and validation rules
- [ ] Every enum lists all allowed values
- [ ] Pagination section present if any list endpoint exists
- [ ] All error status codes are listed
- [ ] At least one sequence example covering the main user flow

If the `/Users/zackoverflow/Documents/Projects/loopscribe/api/loopscribe-v2-api/api-docs/` directory does not exist in the project root, create it before writing the file.
</process>
