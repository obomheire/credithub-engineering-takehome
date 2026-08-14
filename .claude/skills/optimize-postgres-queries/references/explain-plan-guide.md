# Interpreting EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)

## Node types

| Node | Meaning | When it's a problem |
|---|---|---|
| Seq Scan | Full table scan | Table is large and a selective `WHERE`/`JOIN` column has no index |
| Index Scan | Index used, then heap fetch per match | Fine; if `rows` returned is large relative to table size, an index may not help much |
| Bitmap Index Scan / Bitmap Heap Scan | Index used to build a bitmap, then batched heap fetch | Normal for medium-selectivity filters; frequent recheck conditions (`Rows Removed by Filter` high) suggest the index doesn't fully match the predicate |
| Index Only Scan | Satisfied entirely from the index (no heap fetch) | Best case — if you see a regular Index Scan where all needed columns are in the WHERE/SELECT list, consider a covering index |
| Nested Loop | Outer rows drive repeated inner lookups | Fine when outer set is small and inner side is indexed; expensive when outer set is large and inner lookup isn't indexed (effectively an N+1 inside SQL) |
| Hash Join | Build hash table from one side, probe with the other | Watch `Hash Buckets`/batch spill in verbose output — spilling to disk means `work_mem` is too small or the built side is too large |
| Merge Join | Both sides sorted then merged | Efficient only if inputs are already sorted (e.g. via an index) — an explicit `Sort` feeding it may be avoidable with the right index |
| Sort | Explicit sort node | Check `Sort Method`: `quicksort` (fine, in-memory) vs `external merge` (spilled to disk — expensive) |
| Aggregate / HashAggregate | Grouping/aggregation | `HashAggregate` with high `Peak Memory Usage` on a huge group count can be slow; consider whether the aggregation can be pushed down or precomputed |

## Key metrics to compare (planned vs actual)

- **rows** (estimated) vs **actual rows**: large mismatch → stale table statistics → recommend `ANALYZE <table>` (never auto-run).
- **cost**: relative planner estimate; only meaningful for comparing plans of the same query, not across queries.
- **actual time**: wall-clock ms per node (`startup..total`), multiplied by `loops` for nodes executed more than once (e.g. inner side of a Nested Loop) — this is the real cost, not the raw per-loop number.
- **Buffers: shared hit** (found in cache) vs **shared read** (disk I/O) vs **shared dirtied/written**: high `shared read` relative to `hit` means cold cache; recurring hot queries with high `shared read` are prime covering-index candidates.
- **Rows Removed by Filter**: high count means the index/scan is fetching far more rows than needed before filtering — signals a missing or non-selective index.
- **Planning Time** vs **Execution Time**: if planning dominates, it's usually not a data/index problem — likely too many partitions/statistics targets, not something to fix via query rewrite.

## Decision guide

1. Seq Scan + large table + selective filter → add index on filter column(s).
2. Sort (external merge) feeding a `LIMIT` → add an index matching `ORDER BY` (and `WHERE`, if combined) so the planner can do an Index Scan top-N instead of sorting everything.
3. Nested Loop with unindexed inner side and large outer row count → add index on the inner join key, or restructure as a Hash Join by ensuring both sides have adequate stats.
4. Estimated vs actual rows off by 10x+ → recommend `ANALYZE`, re-run EXPLAIN afterward before concluding an index is needed.
5. High `shared read`, low `shared hit`, query runs frequently → consider a covering index or application-level caching (per project cache-invalidation rules) rather than a bigger index alone.
