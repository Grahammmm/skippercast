// In-memory D1 for advisor tests: node:sqlite with every committed migration
// applied in journal order, behind the subset of the D1 API the Worker uses
// (prepare/bind/first/all/run, batch as one transaction). Same adapter as
// tests/test_accounts.mjs, with RETURNING support in first(). Not a test file
// itself (no test_ prefix), so `node --test tests/test_*.mjs` does not run it.
import {readFileSync} from 'node:fs';

let DatabaseSync = null, reason = '';
try { ({DatabaseSync} = await import('node:sqlite')); } catch (e) { reason = `node:sqlite is unavailable in Node ${process.version} (${e.code || e.message}); needs Node 22.13+`; }
/** null when node:sqlite works, else why the database tests skip. */
export const sqliteUnavailable = DatabaseSync ? null : reason;

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8');
export const journal = () => JSON.parse(read('../drizzle/meta/_journal.json'));
export const migrationSql = tag => read(`../drizzle/${tag}.sql`);

/** {sql, db}: the raw DatabaseSync for assertions and the D1-shaped adapter for code under test. */
export function advisorDatabase() {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...journal().entries].sort((a, b) => a.idx - b.idx)) sql.exec(migrationSql(tag));
  const db = {
    prepare(query) {
      let args = []; const statement = sql.prepare(query);
      return {
        bind(...a) { args = a; return this; },
        async first() { return statement.get(...args) || null; },
        async all() { return {results: statement.all(...args)}; },
        async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; },
      };
    },
    async batch(queries) {
      sql.exec('BEGIN');
      try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; }
      catch (e) { sql.exec('ROLLBACK'); throw e; }
    },
  };
  return {sql, db};
}

/** A minimal R2 bucket: put/list(prefix, cursor, limit)/delete(keys). */
export function fakeBucket(keys = []) {
  const store = new Set(keys);
  return {
    store,
    async list({prefix = '', cursor, limit = 1000} = {}) {
      const all = [...store].filter(k => k.startsWith(prefix)).sort(), start = cursor ? Number(cursor) : 0;
      const page = all.slice(start, start + limit), truncated = start + limit < all.length;
      return {objects: page.map(key => ({key})), truncated, cursor: truncated ? String(start + limit) : undefined};
    },
    async delete(k) { for (const key of [].concat(k)) store.delete(key); },
  };
}
