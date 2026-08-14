# Loopscribe V2 API — Claude Context

## Project Overview

NestJS monorepo containing three independently deployable microservices:

- `apps/api` — REST API (Fastify, port 9000). Main user-facing service.
- `apps/realtime` — WebSocket service (Fastify + Socket.io, port 9001).
- `apps/workers` — Background job processor (BullMQ, no HTTP server).

Shared infrastructure lives in `libs/`:
- `libs/config` — Zod-validated env schema, global `ConfigModule`
- `libs/shared` — Drizzle ORM database module + schema, queue constants
- `libs/redis` — Global `RedisModule` (ioredis)

## Content Ownership & Ingestion Architecture

### Important Architectural Principle

Loopscribe does **not** create authors, personas, articles, podcast episodes, or panel blueprint content internally.

All content is generated and managed by an external content platform running on Replit.

The Replit platform is the source of truth for content creation and editorial workflows.

### Exception — Chat Simulation Shows

**Chat simulation shows are authored and managed entirely within Loopscribe.** This is the one exception to the principle above.

Shows (topics, outlines, talking points, author assignments, scheduling) are created and managed via Loopscribe's own admin API. Scripts are pre-generated internally by Loopscribe's worker service using the LLM pipeline. The external Replit platform plays no role in chat simulation content.

This means CRUD endpoints and admin management endpoints **are** appropriate and expected for the following chat simulation entities:

- `Show` — topic, outline, talking points, schedule, status
- `ShowAuthor` — author assignments per show
- `ShowBeat` — the pre-generated script (beats/turns)
- `ShowSession` — user join sessions (single-player now, multiplayer later)
- `ShowInteraction` — user interruptions and AI responses during live shows

When implementing chat simulation features, do not defer to webhook ingestion. Build full internal management flows.

### Content Flow

```text
Replit Content Platform
        │
        │ Publish Approved
        ▼
POST /api/v1/webhooks/content
        │
        ▼
Loopscribe Backend
        │
        ├── Persist content
        ├── Index content
        ├── Generate embeddings
        ├── Generate audio (when applicable)
        └── Serve content to clients
```

### Source of Truth

The following entities originate from the external Replit platform:

* Authors
* Personas
* Articles
* Podcast Episodes
* Panel Blueprints
* Other editorial content

The Loopscribe backend should treat these records as externally managed content.

### Development Guidelines

The Loopscribe backend is not responsible for creating or managing editorial content.

Assume that all content entities are created and maintained by the external Replit content platform and delivered to Loopscribe through webhook ingestion.

This includes, but is not limited to:

* Authors
* Personas
* Articles
* Podcast Episodes
* Panel Blueprints
* Editorial Metadata
* Future Content Types introduced by the content platform

When implementing new features:

* Do not create CRUD endpoints for content creation or content management unless explicitly requested.
* Do not assume content is authored inside the Loopscribe backend.
* Assume content enters the platform through webhook ingestion workflows.
* Treat the Replit platform as the source of truth for all content-related entities.
* Focus Loopscribe functionality on content ingestion, storage, indexing, search, transformation, caching, delivery, personalization, analytics, and user interaction.
* Any content modifications performed within Loopscribe should be considered derived or platform-specific data and must not replace the source content managed by the Replit platform.
* When designing new features, default to extending webhook ingestion contracts rather than introducing internal content creation workflows.

Existing content should generally be ingested, validated, stored, indexed, transformed, searched, cached, personalized, and served to clients rather than authored within this system.


### Content Ingestion Endpoint

```http
POST /api/v1/webhooks/content
```

This endpoint receives content payloads from the external Replit content platform.

The webhook ingestion flow is responsible for:

* Creating new content records
* Updating existing content records
* Triggering indexing jobs
* Triggering embedding generation
* Triggering audio generation workflows
* Triggering cache invalidation when necessary

### Future Development Assumption

Unless explicitly stated otherwise, all content-related features should assume that content already exists in the system as a result of webhook ingestion from the external Replit platform.

## Build & Run

```bash
# Build individual services
npm run build:api
npm run build:realtime
npm run build:workers

# Run built output
npm run start:api       # port 9000
npm run start:realtime  # port 9001
npm run start:workers   # no HTTP

# Dev (hot reload via nodemon + ts-node)
npm run dev:api
npm run dev:realtime
npm run dev:workers
```

## Database

PostgreSQL via Drizzle ORM. Schema defined in `libs/shared/src/database/schema/index.ts`.

```bash
npm run db:generate   # generate migration files from schema changes
npm run db:migrate    # apply migrations
npm run db:push       # push schema directly (dev only)
npm run db:studio     # Drizzle Studio UI
```

Migration config: `drizzle.config.ts` at repo root.

## Database Schema Changes — Critical Rule

**Never write migration SQL files manually.** Always use the generate → migrate workflow:

1. Update `libs/shared/src/database/schema/index.ts`
2. Run `npm run db:generate` — drizzle diffs the schema and produces a correctly formatted `.sql` file with `-->statement-breakpoint` separators and registers it in `migrations/meta/_journal.json`
3. Run `npm run db:migrate` — applies the migration to the database

### Why this matters

Drizzle's migrator works off `migrations/meta/_journal.json`, **not** the filesystem. A manually created `.sql` file that is not registered in the journal will be silently ignored by both `drizzle-kit migrate` and the app's `runMigrations()` on startup — the migration will never be applied to any environment.

Drizzle also splits migration SQL on `-->statement-breakpoint` comments before executing. A manually written file without these markers may have statements silently dropped by the migrator's internal parser.

**If a one-off SQL statement is needed** (e.g. enabling a Postgres extension like `vector`) that cannot be expressed in the Drizzle schema, add it as a `sql` statement inside a custom migration file generated via `db:generate` and then manually prepend the raw SQL before the first breakpoint — never create the file from scratch.

## Key Architecture Decisions

- **Fastify adapter** throughout (not Express). Use `FastifyRequest` types, not `express.Request`.
- **Drizzle ORM** (not TypeORM/Prisma). Queries use `db.db` (the raw drizzle instance from `DatabaseService`).
- **BullMQ / Bull** for job queues. Queue names and job payload types are defined in `libs/shared/src/queues/`.
- **Argon2** for password hashing.
- **JWT** for auth. Guard: `JwtAuthGuard` in `apps/api/src/auth/guards/`.
- **Global ValidationPipe** with `whitelist: true` + `forbidNonWhitelisted: true`. Every DTO **must** use `class-validator` decorators or all fields will be stripped and the request will be rejected with 400.
- **Swagger** available at `/api/docs` (api service only).
- **Global prefix** `api/v1` on the api service.

## Adding a New Environment Variable

When a new env var is needed, update **all four** of these locations — missing any one will cause silent failures or startup crashes:

### 1. `libs/config/src/config.schema.ts`
Add the variable to the Zod schema. The app validates all env vars at startup via `envSchema.parse()` — a missing required variable will crash the process immediately.

```typescript
// Required variable
MY_VAR: z.string().min(1),

// Optional variable with default
MY_VAR: z.string().default('default-value'),

// Optional variable
MY_VAR: z.string().optional(),
```

### 2. `.env.example`
Add the variable with a placeholder value so developers know it exists.

```
# Description of what this var does
MY_VAR=your-value-here
```

### 3. `docker-compose.yml` (local dev)
Add to the environment block of whichever service(s) need it. Use `${MY_VAR}` or `${MY_VAR:-default}` syntax.

Only add to the service(s) that actually use the variable — not all three.

### 4. `docker-compose.prod.yml` (production)
Same as above for the production compose file.

**Example — `WEBHOOK_SECRET` was added to `api` only:**
```yaml
# docker-compose.yml and docker-compose.prod.yml — api service only
WEBHOOK_SECRET: ${WEBHOOK_SECRET}
```

**Quick checklist when adding an env var:**
- [ ] `libs/config/src/config.schema.ts` — Zod schema entry
- [ ] `.env.example` — placeholder entry with comment
- [ ] `docker-compose.yml` — correct service(s)
- [ ] `docker-compose.prod.yml` — correct service(s)

## Module Structure Convention

Follow the auth module as the reference pattern:

```
apps/api/src/<feature>/
  <feature>.module.ts      — imports/exports, registers controller + service
  <feature>.controller.ts  — route handlers, @ApiTags, validation via DTOs
  <feature>.service.ts     — business logic
  dto/
    <name>.dto.ts          — class-validator decorators required on every field
```

Register every new module in `apps/api/src/app.module.ts` imports array.

## DTOs — Critical Rule

The global `ValidationPipe` runs with `whitelist: true` and `forbidNonWhitelisted: true`. This means:

- Any property on a DTO class **without** a `class-validator` decorator will be **stripped** from the request body.
- Any property in the incoming JSON that has no corresponding DTO property will cause a **400 Bad Request**.
- Every DTO must import and apply decorators from `class-validator`. Bare TypeScript interfaces/classes without decorators will silently receive empty objects.

```typescript
// WRONG — fields will be stripped, endpoint receives {}
export class MyDto {
  name: string;
  value: number;
}

// CORRECT
import { IsString, IsInt } from 'class-validator';
export class MyDto {
  @IsString()
  name: string;

  @IsInt()
  value: number;
}
```

For nested objects, use `@ValidateNested()` + `@Type(() => NestedClass)` from `class-transformer`.

## Database — Testing & Verification

The app uses a **DigitalOcean managed PostgreSQL** database, not a local Postgres instance. `DATABASE_URL` in `.env` points to the DigitalOcean database.

**Do not query the local `loopscribe` Postgres database** — it only has the first migration and will not reflect any data written by the running app.

When verifying data after a test, always connect via the `DATABASE_URL` from `.env`:

```js
require('dotenv').config({ path: '.env' });
const postgres = require('./node_modules/postgres');
const sql = postgres(process.env.DATABASE_URL, { ssl: 'require' });
// ... your queries ...
await sql.end();
```

Drizzle migrations (`npm run db:generate` / `npm run db:migrate`) also run against DigitalOcean via the same `DATABASE_URL`.

## Task Tracking Requirement

Before starting any non-trivial implementation task (a new feature, endpoint, bug fix, refactor, migration, or multi-step change), create a todo list to track progress. Update it in real time as work proceeds — mark each step in progress before starting it and completed immediately after finishing it, rather than batching updates at the end. This applies to every agent working in this repository, not just the one that started the task.

## Post-Implementation Verification Requirements

After every code change, feature implementation, refactor, bug fix, or configuration update, perform a complete verification before considering the task finished.

### Service Validation

Verify that all services start successfully and remain healthy:

* API service starts without errors or warnings.
* Realtime service starts without errors or warnings.
* Worker service starts without errors or warnings.
* Confirm there are no startup crashes, dependency injection issues, configuration errors, or runtime exceptions.

### Functional Validation

Verify that all newly added or modified functionality works as expected:

* Test every new endpoint.
* Test every modified endpoint.
* Validate request and response payloads.
* Verify success scenarios.
* Verify relevant error scenarios and edge cases.
* Confirm database operations execute correctly.
* Confirm background jobs, events, and message queues function correctly where applicable.

## Test Accounts

Use these accounts when verifying endpoints that require authentication. If they do not exist in the database, create them via the registration endpoint (or directly via the DB) before running tests.

### Admin Account
- **First Name:** Test
- **Last Name:** Admin
- **Email:** testadmin@loopscribe.com
- **Password:** Secret@123
- **Role:** `admin`

### User Account
- **First Name:** Test
- **Last Name:** User
- **Email:** testauser@loopscribe.com
- **Password:** Secret@123
- **Role:** `user`

When a test requires a JWT, obtain it by calling `POST /api/v1/auth/login` with the relevant credentials and use the returned token as a `Bearer` token in subsequent requests.


## Engineering Standards

### Role & Code Quality Bar

All code written here is held to a **Senior Backend Engineer** standard (10+ years). Every implementation must prioritise:

- **Correctness first** — no happy-path-only logic; handle edge cases explicitly.
- **Performance** — avoid N+1 queries, unnecessary round-trips, and blocking operations.
- **Scalability** — design for horizontal scale; avoid process-local state for shared data.
- **Readability** — clear naming, minimal cleverness, no unnecessary abstractions.

### Swagger / API Documentation

Every endpoint **must** be fully documented for frontend consumers. Required decorators on every route:

```typescript
@ApiTags('resource-name')
@ApiOperation({ summary: 'Brief description of what this endpoint does' })
@ApiResponse({ status: 200, description: 'Success', type: ResponseDto })
@ApiResponse({ status: 400, description: 'Validation error' })
@ApiResponse({ status: 401, description: 'Unauthorised' })
@ApiResponse({ status: 404, description: 'Resource not found' })
```

Additional rules:
- All request bodies must reference a DTO class with `@ApiProperty()` on every field.
- Query params must use `@ApiQuery()` with type, description, and `required` flag.
- Path params must use `@ApiParam()`.
- Enums must be declared with `enum` (without `enumName`) in `@ApiProperty()` / `@ApiQuery()`. **Do not use `enumName`** — it causes Swagger to extract the enum into a shared `$ref` schema, which drops the property-level `description` entirely, so allowed values never appear in the UI.
- Every `@ApiOperation` `description` on a POST or PATCH endpoint **must** list the allowed values for every enum field accepted in the request body, in the format: `For \`fieldName\`, provide one of: \`value1\` | \`value2\` | \`value3\`.` This mirrors the pattern used in the Authentication endpoints and ensures the values are visible at the top of the endpoint panel without having to open the Schema tab.
- Error shapes must reference a shared error response DTO or use `@ApiResponse({ schema: { ... } })`.

### Pagination Standard — Cursor-Based Only

**All list endpoints must use cursor-based pagination.** Offset/page-number pagination (`page`, `offset`) is not permitted in this codebase.

#### Query DTO shape
```typescript
cursor?: string;  // opaque base64url token; omit for first page
limit?: number;   // default 20, max 100 (or resource-appropriate cap)
```

#### Response shape
```typescript
{
  data: ResourceDto[];
  pagination: {
    nextCursor: string | null;  // null on last page
    hasNextPage: boolean;
    limit: number;
  };
}
```

#### Implementation pattern
- Encode the cursor as `Buffer.from(JSON.stringify({ <sortField>, id })).toString('base64url')`.
- Decode with validation — throw `BadRequestException('Invalid pagination cursor')` on any malformed input.
- Fetch `limit + 1` rows; if the extra row exists, `hasNextPage = true` and `nextCursor` is built from the last row of the trimmed set.
- The cursor sort key must be the same field used in `ORDER BY`. For creation-ordered lists use `createdAt DESC, id DESC` and a `(createdAt, id)` compound where clause: `createdAt < cursor.createdAt OR (createdAt = cursor.createdAt AND id < cursor.id)`.
- Add a Drizzle index on `(sortField, id)` if one does not already exist.

#### Reference implementations
- `apps/api/src/authors/authors.service.ts` — `listAuthors` (alphabetical, name+id cursor)
- `apps/api/src/shows/shows.service.ts` — `listShows` (reverse-chronological, createdAt+id cursor)

### Database Query Optimisation

- All queries must select only the columns needed — never `SELECT *` via `db.db.select()` without a column projection when the table is large.
- Every foreign key and every column used in a `WHERE`, `ORDER BY`, or `JOIN` condition **must** have a Drizzle index defined in the schema. Add it at the same time as the column.
- Use `LIMIT` on all list queries; never return unbounded result sets.
- Prefer a single joined query over multiple sequential queries for related data.
- Use Drizzle transactions (`db.db.transaction()`) for any operation that writes to more than one table.

### Controller vs Service Separation

- **Controllers** handle only: routing, request extraction, DTO binding, guard/decorator application, and calling one service method. No business logic.
- **Services** own all business logic, DB access, cache interaction, and queue dispatch. A controller method body should rarely exceed 3–5 lines.

```typescript
// WRONG — business logic in controller
@Post()
async create(@Body() dto: CreateDto) {
  const exists = await this.db.findOne(...);
  if (exists) throw new ConflictException();
  return this.db.insert(...);
}

// CORRECT
@Post()
async create(@Body() dto: CreateDto) {
  return this.myService.create(dto);
}
```

### Clarification Before Implementation

In plan mode **or** before starting any non-trivial implementation, assess whether the request contains sufficient information to proceed correctly. When ambiguity exists — around business rules, data shape, access control, or edge cases — ask targeted clarifying questions **before writing any code**. Do not make assumptions that could require rework. when you ask clarify questions in plan mode, indicate your recommended option and the reason you recommend it.

### No Assumptions — Verify Against Official Docs Before Implementing

Never plan or implement against internal/trained knowledge of a third-party API, SDK, or library behavior. Trained knowledge can be outdated, wrong, or describe a deprecated version of the integration — this has already caused real bugs in this codebase (e.g. the ElevenLabs voice sync assumed `GET /v2/voices` returned all voices in one call; the real API paginates at `page_size=10` by default, and the wrong assumption meant the sync silently synced only 10 of 376 voices for months).

This rule applies to **any** external API/SDK integration — ElevenLabs, Google/Gemini, OpenAI, HeyGen, Stripe, RevenueCat, AWS/GCP SDKs, or any other third-party service — and to **any implementation detail you are not certain of**, not just brand-new integrations.

**Before planning or writing code that touches a third-party API/SDK, or relies on non-obvious behavior of an unfamiliar library:**

1. Look up the current official API reference/docs for the exact endpoint, method, or SDK call being used — via `WebFetch`/`WebSearch`, or by making a live test call against the real API/sandbox when credentials are available (as was done to confirm the ElevenLabs `labels`/pagination shape above).
2. Confirm the actual response/request shape, required and optional parameters, defaults, pagination behavior, rate limits, and authentication requirements — do not infer these from memory or from how a similar-sounding API behaves elsewhere.
3. If a live credential is available in `.env`, prefer verifying behavior with a real request over trusting docs alone — docs can also be stale or incomplete (as seen with `voice_type` filter semantics needing to be empirically confirmed).
4. Only after this verification, propose the implementation plan. If clarification from the user is also needed (per "Clarification Before Implementation" above), ask after doing the lookup, not instead of it.
5. If official docs cannot be found or a live call cannot be made, say so explicitly and flag the assumption being made — do not silently proceed as if verified.

This applies even when the API/library seems familiar or "well known" — familiarity is exactly when outdated trained knowledge is most likely to go unchallenged.

### Cache Invalidation Rules

Any service method that **creates, updates, or deletes** a resource **must**:

1. Identify every cache key that could hold stale data for that resource (e.g. item key, list key, count key).
2. Call the cache delete/invalidate function for those keys **after** the DB write succeeds.
3. **Never** cache data that contains user-specific secrets or credentials (tokens, hashed passwords, API keys).
4. Wrap all cache operations in try/catch — a cache failure **must not** propagate an exception to the caller. Log the error and continue.

```typescript
// CORRECT pattern
async update(id: string, dto: UpdateDto) {
  const result = await this.db.db.update(...).where(...).returning();

  try {
    await this.cache.del(`resource:${id}`);
    await this.cache.del(`resource:list`);
  } catch (err) {
    this.logger.error('Cache invalidation failed', err);
  }

  return result[0];
}
```

