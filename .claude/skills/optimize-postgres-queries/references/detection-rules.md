# Detection Rules

Checklist to apply to every discovered query. Each item lists what to look for in Drizzle/TypeScript source and, where relevant, in an `EXPLAIN` plan.

## SQL / ORM inefficiencies

- **SELECT \***: `db.db.select()` or `db.db.query.<table>.findMany()` with no column projection on a table with many/large columns (e.g. `jsonb`, `text`, `vector`). Fix: explicit `.select({ col1: table.col1, ... })` or Drizzle's column-picking query API.
- **Missing LIMIT**: any list query without `.limit(...)` — including internal helper queries, not just public endpoints.
- **Unnecessary DISTINCT**: `DISTINCT` used to paper over a fan-out join instead of fixing the join/aggregation.
- **Redundant subqueries**: the same subquery/derived value computed more than once in one statement or across sequential statements — candidate for a CTE or a single joined query.
- **Sequential queries for related data**: N+1 pattern — a list query followed by a per-row query inside a loop or `Promise.all(items.map(...))`. Fix: single query with `leftJoin`/`innerJoin`, or a batched `WHERE id IN (...)` query.
- **Repeated identical queries**: the same exact query executed multiple times per request (e.g. once per branch of an if/else, or refetched after every write in the same request when the write already returns the row via `.returning()`).
- **Unnecessary locking**: `FOR UPDATE`/`FOR SHARE` or explicit transaction where a simple read or single-statement write would do; long-held transactions spanning I/O or external calls.
- **Poor pagination**: any `page`/`offset`-based pagination — this project mandates cursor-based only (`cursor`+`limit`, encoded `(sortField, id)` tuple, `nextCursor`/`hasNextPage` envelope). Also flag pagination missing a stable tiebreaker column (e.g. `ORDER BY createdAt DESC` alone without `, id DESC` — ties can duplicate/skip rows across pages).
- **Expensive sorts**: `ORDER BY` on a column with no supporting index, especially combined with `LIMIT` (should be an index-driven top-N, not a full sort).
- **Unnecessary joins**: joining a table only to discard its columns (dead join), or joining when an `EXISTS`/subquery would avoid fan-out entirely.
- **Missing composite/covering index opportunities**: a query filters on col A and sorts on col B, or filters on (A, B) together — check whether a composite index in the correct order exists.

## EXPLAIN plan red flags

- **Seq Scan** on a table beyond a few hundred rows where a `WHERE`/`JOIN` column has no index.
- **Estimated rows vs. actual rows** differing by an order of magnitude — stale statistics; recommend `ANALYZE <table>` (recommendation only, never run automatically).
- **Nested Loop** with a high row count on the outer side and no index on the inner side's join key.
- **Sort** node with a large `Sort Method: external merge` (spilling to disk) — usually means `work_mem` pressure or a missing index that would avoid the sort entirely.
- **Hash Join** building a hash table from an unexpectedly large relation — check if a filter could be pushed down earlier.
- High **Buffers: shared read** relative to **shared hit** — indicates cold cache / disk I/O; may justify a covering index to keep hot data in fewer pages.

## NestJS / Drizzle-specific

- Query logic embedded in a controller method instead of the service (architecture rule violation, also usually correlates with untested query paths).
- Cache reads that don't check a cache key before hitting the DB for expensive/hot queries.
- Missing cache invalidation after a create/update/delete that affects a cached list/item (see project CLAUDE.md "Cache Invalidation Rules") — flag as a correctness bug even outside pure performance scope.
- Multi-table writes not wrapped in `db.db.transaction()`.
