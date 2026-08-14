#!/usr/bin/env node
/**
 * Runs EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) — or a pg_stat_statements
 * summary — against the real DigitalOcean-managed Postgres database referenced by
 * DATABASE_URL in .env. Never targets the local `loopscribe` Postgres instance.
 *
 * Usage:
 *   node explain-query.js "SELECT * FROM shows WHERE channel_id = '...' ORDER BY created_at DESC LIMIT 20"
 *   node explain-query.js --stat-statements [limit]
 *
 * This script is read-only by construction: it only ever issues EXPLAIN or a
 * SELECT against pg_stat_statements. It never mutates data or schema.
 */

const path = require('path');
require('dotenv').config({ path: path.resolve(process.cwd(), '.env') });

const postgres = require(path.resolve(process.cwd(), 'node_modules/postgres'));

async function main() {
  const args = process.argv.slice(2);

  if (!process.env.DATABASE_URL) {
    console.error('DATABASE_URL not found in .env — refusing to run against an unknown database.');
    process.exit(1);
  }

  const sql = postgres(process.env.DATABASE_URL, { ssl: 'require' });

  try {
    if (args[0] === '--stat-statements') {
      const limit = Number(args[1]) || 20;
      const rows = await sql`
        SELECT
          calls,
          round(total_exec_time::numeric, 2) AS total_exec_ms,
          round(mean_exec_time::numeric, 2) AS mean_exec_ms,
          rows,
          query
        FROM pg_stat_statements
        WHERE query NOT ILIKE '%pg_stat_statements%'
        ORDER BY total_exec_time DESC
        LIMIT ${limit}
      `;
      console.log(JSON.stringify(rows, null, 2));
      return;
    }

    const query = args[0];
    if (!query) {
      console.error('Usage: node explain-query.js "<SQL>"  |  node explain-query.js --stat-statements [limit]');
      process.exit(1);
    }

    const trimmed = query.trim().toUpperCase();
    if (!trimmed.startsWith('SELECT') && !trimmed.startsWith('WITH')) {
      console.error('Refusing to EXPLAIN a non read-only statement. Only SELECT/WITH queries are supported.');
      process.exit(1);
    }

    const result = await sql.unsafe(
      `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON) ${query}`,
    );
    console.log(JSON.stringify(result[0]['QUERY PLAN'], null, 2));
  } catch (err) {
    console.error('Query failed:', err.message);
    process.exit(1);
  } finally {
    await sql.end();
  }
}

main();
