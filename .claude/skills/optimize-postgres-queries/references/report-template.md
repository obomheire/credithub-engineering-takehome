# Optimization Report Template

Use this exact structure when producing the end-of-session report.

```markdown
# Query Optimization Report — <scope>

## Summary

- Files analyzed: <n>
- Queries analyzed: <n>
- Queries optimized: <n>
- Indexes recommended: <n>
- Estimated performance improvement: <qualitative/quantitative summary>

## Findings

### 1. <short title>

- **File**: `path/to/file.ts`
- **Method**: `methodName`
- **Original query**:
  ```ts
  // or raw SQL
  ```
- **Problem**: <which detection rule this violates>
- **EXPLAIN ANALYZE findings**: <key metrics — scan type, rows est vs actual, timing, buffers>
- **Root cause**: <why this happens — missing index, N+1 loop, offset pagination, etc.>
- **Optimized query**:
  ```ts
  ```
- **Expected benefit**: <e.g. "Seq Scan (avg 340ms, 120k rows) → Index Scan (avg 4ms)">

<!-- repeat per finding -->

## Changes Made

- `path/to/file.ts` — <one-line description of the edit and why>

## Remaining Recommendations

- <e.g. "Add composite index on (channel_id, created_at) to shows table — requires db:generate + db:migrate, not applied automatically">
```

Keep every finding traceable: file + method + before/after query + measured or reasoned justification. Do not report a "finding" without at least a root cause and an optimized alternative, even if the fix wasn't applied.
