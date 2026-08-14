---
name: optimize-postgres-queries
description: "Analyze, validate, profile, and optimize PostgreSQL/Drizzle queries in this project — find N+1s, missing indexes, inefficient joins/sorts, bad pagination, and SELECT * usage, and (when asked) rewrite queries and generate migrations while preserving behavior. Use when the user asks to optimize/analyze/review database queries or performance for a feature, module, or the whole project (e.g. 'optimize queries for Authors', 'find N+1 queries', 'run EXPLAIN ANALYZE on Orders', 'verify indexes')."
argument-hint: "<feature-name-or-'all'> [--apply-fixes]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
---

<objective>
Analyze, validate, profile, and optimize PostgreSQL queries — both raw SQL and Drizzle-ORM-generated — for the requested scope in this NestJS/Fastify/Drizzle/PostgreSQL (DigitalOcean Managed) project.

Preserve existing application behavior exactly: never change business logic, never alter returned data shape, never introduce breaking changes. Only improve implementation and performance.

Scope: $ARGUMENTS (a feature/module name, or "all"/"project" for the entire codebase). If no scope is given, ask which feature/module to target, or confirm a full-project sweep.
</objective>

<context>
- NestJS monorepo: `apps/api` (Fastify, port 9000), `apps/realtime` (Fastify + Socket.io), `apps/workers` (BullMQ, no HTTP)
- ORM: Drizzle (not TypeORM/Prisma) — queries run through `db.db`, the raw drizzle instance from `DatabaseService` (`libs/shared/src/database/database.service.ts`)
- Schema: `libs/shared/src/database/schema/index.ts` — single source of truth for tables, columns, enums, and indexes
- Database: DigitalOcean Managed PostgreSQL. `DATABASE_URL` in `.env` is the only real target — never analyze against the local `loopscribe` Postgres instance, it does not reflect live schema/data (see project `CLAUDE.md`)
- Migrations: `npm run db:generate` (diff schema → SQL) then `npm run db:migrate` (apply). Registered via `migrations/meta/_journal.json`. **Never hand-write migration SQL files** — this project's CLAUDE.md treats that as a hard rule
- Pagination standard: cursor-based only (`cursor`/`limit`), never offset/page. Reference implementations: `apps/api/src/authors/authors.service.ts` (`listAuthors`), `apps/api/src/shows/shows.service.ts` (`listShows`)
- Caching: services that create/update/delete must invalidate relevant cache keys in a try/catch (see project CLAUDE.md "Cache Invalidation Rules") — factor this in when proposing changes near cached reads
- Controller/service separation: all query logic lives in `*.service.ts`, never in controllers

This project also occasionally shows patterns resembling TypeORM/Prisma repository or QueryBuilder style in comments or legacy code — recognize those idioms too, but all live query execution in this codebase goes through Drizzle.
</context>

<process>

## Step 1 — Resolve scope and discover queries

Determine target files based on `$ARGUMENTS`:

```bash
# Feature/module scope — locate controller, service, DTOs
find apps/api/src apps/realtime/src apps/workers/src -type f \( -name "*.service.ts" -o -name "*.controller.ts" -o -name "*.processor.ts" \) | xargs grep -l -i "<feature>" 2>/dev/null

# Full project scope — every file touching the DB
grep -rl "db\.db\.\|DatabaseService\|sql\`" apps/*/src libs/shared/src --include="*.ts"
```

Read every matched file fully. For each, extract every place a query is built or executed: `db.db.select(...)`, `db.db.insert(...)`, `db.db.update(...)`, `db.db.delete(...)`, `db.db.query.*`, `db.db.transaction(...)`, and any raw `sql\`...\`` template usage.

## Step 2 — Understand business logic before touching anything

For each query found, read the surrounding method fully — do not optimize a query in isolation. Understand:
- What the endpoint/job is for and who calls it
- What the exact return shape must remain (fields, types, ordering, pagination envelope)
- Whether results are cached anywhere (check for `this.cache` / `RedisModule` usage nearby)
- Whether the query runs inside a transaction with other writes

Never propose a change that alters the response shape, ordering semantics, or side effects unless the user explicitly asked for a behavior change.

## Step 3 — Static SQL/ORM inefficiency detection

For every extracted query, check against `references/detection-rules.md` for the full checklist (SELECT *, N+1, missing LIMIT, unnecessary DISTINCT, redundant subqueries, poor pagination, unnecessary locking, sequential-scan-prone filters, etc). Flag every match with file + line + method name.

## Step 4 — Runtime performance analysis (EXPLAIN ANALYZE)

For queries where a real execution plan would meaningfully inform the decision (anything filtering, joining, sorting, or aggregating on non-trivial tables), get the actual SQL Drizzle would emit and run it through `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` against the real database.

Use `scripts/explain-query.js` — it connects via `DATABASE_URL` from `.env` (DigitalOcean managed Postgres) exactly as required by this project's testing rules, and never against the local Postgres instance:

```bash
node .claude/skills/optimize-postgres-queries/scripts/explain-query.js "<SQL with literal or representative parameter values>"
```

Interpret the returned plan per `references/explain-plan-guide.md`: sequential vs. index scans, nested loop vs. hash/merge join, sort methods, estimated vs. actual row counts, cost, timing, and buffer/I/O behavior. A large estimated/actual row mismatch usually means stale statistics — recommend `ANALYZE <table>` (never `VACUUM ANALYZE` automatically, only as a recommendation).

If `pg_stat_statements` is available, use it to find real repeated/slow queries in production traffic:

```bash
node .claude/skills/optimize-postgres-queries/scripts/explain-query.js --stat-statements
```

## Step 5 — Cross-reference indexes against schema

Read `libs/shared/src/database/schema/index.ts` for the tables involved. For every column used in a `WHERE`, `ORDER BY`, `JOIN ON`, or cursor comparison, verify a Drizzle `index(...)` / `uniqueIndex(...)` exists covering it (check both single-column and, where the query filters+sorts together, composite coverage in the correct column order).

Recommend (do not add automatically unless asked):
- Missing single-column or composite indexes, with the exact Drizzle schema snippet
- Partial indexes where a query always filters on a fixed condition (e.g. `WHERE deleted_at IS NULL`)
- Covering indexes when a query could become index-only
- Removal candidates only when clearly duplicate/redundant — always justify, never remove automatically

## Step 6 — Apply fixes (only if requested, or `--apply-fixes` passed in `$ARGUMENTS`)

When asked to fix/optimize/rewrite (not just analyze/review/find):
- Rewrite the query/service method in place, preserving the method signature and return shape
- Prefer a single joined Drizzle query over sequential queries for related data (classic N+1 fix)
- Convert offset pagination to cursor pagination per the project standard if found
- Add `.limit(...)` where missing and appropriate
- Wrap multi-table writes in `db.db.transaction()` if not already
- Add narrow column projections (`.select({ ... })`) instead of implicit `SELECT *`
- For index additions: update `libs/shared/src/database/schema/index.ts`, then run `npm run db:generate` followed by `npm run db:migrate` — **never** hand-write the migration SQL file
- Add a one-line comment only if the fix encodes a non-obvious constraint; otherwise no comment
- After each file edit, note the specific reason performance improves (used in the report)

Never perform, in this or any mode: dropping data, deleting indexes without justification, destructive migrations, automatic schema changes beyond what was explicitly requested, business logic changes, or breaking API changes. Schema changes are always proposed first unless the user explicitly said to implement them.

## Step 7 — Verify

Per this project's verification rules:
- Run `npm run build:api` (and `build:workers`/`build:realtime` if touched) to confirm no compile errors
- Start the affected service and confirm no startup errors
- Re-run `EXPLAIN ANALYZE` on the optimized query and compare cost/timing/rows against the "before" plan captured in Step 4
- Exercise the affected endpoint/job to confirm the response shape and success/error behavior are unchanged

## Step 8 — Produce the report

Write the report to stdout (or to `docs/query-optimization/<scope>-<YYYY-MM-DD>.md` if the user asked to save it) using the structure in `references/report-template.md`:

- **Summary** — files analyzed, queries analyzed, queries optimized, indexes recommended, estimated improvement
- **Findings** — per issue: file, method, original query, problem, EXPLAIN ANALYZE findings, root cause, optimized query, expected benefit
- **Changes Made** — every code modification actually applied
- **Remaining Recommendations** — improvements that need developer/schema approval before being applied (e.g. new indexes, migrations)

</process>

<safety>
Never: drop data, delete indexes without explicit justification, write destructive migrations, change schema automatically without being asked, change business logic, or introduce breaking API changes. Schema/migration changes are proposed first and only implemented when explicitly instructed. Never hand-write migration `.sql` files — always `db:generate` → `db:migrate`. Never run analysis against the local `loopscribe` Postgres database — always use `DATABASE_URL` from `.env`.
</safety>
