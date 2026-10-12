// Shared by the admin specs: run SQL against the local D1 the Playwright dev server uses.
//
// #571, #579: the SQL goes through the one running Worker process. e2e/worker.mjs serves a test-only
// endpoint (127.0.0.1, an ephemeral port, a per-run bearer token, both in .wrangler/e2e-sql.json) that
// runs it on the running workerd's own D1 binding. Spawning `wrangler d1 execute --local` instead opened
// a second workerd on the same SQLite files, which raced the dev server: SQLITE_BUSY on either side and
// "Network connection lost" on the Worker's own requests.
import {existsSync, readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {setTimeout as sleep} from 'node:timers/promises';

const SQL_FILE = resolve(import.meta.dirname, '..', '.wrangler/e2e-sql.json');
const WAIT_MS = 30_000;

/** The endpoint's address and token; e2e/worker.mjs writes them just after the Worker is ready, so wait briefly for them. */
async function endpoint(): Promise<{url: string; token: string}> {
  for (const end = Date.now() + WAIT_MS; ; await sleep(200)) {
    if (existsSync(SQL_FILE)) {
      try { return JSON.parse(readFileSync(SQL_FILE, 'utf8')) as {url: string; token: string}; } catch { /* half written */ }
    }
    if (Date.now() > end) throw Error(`${SQL_FILE} is missing: is e2e/serve.mjs (e2e/worker.mjs) running?`);
  }
}

/** Run SQL (one or more statements, applied as one batch) against the local D1 the dev server uses; the rows of the last statement. */
export async function d1(sql: string): Promise<Record<string, unknown>[]> {
  const {url, token} = await endpoint();
  const res = await fetch(url, {method: 'POST', headers: {authorization: `Bearer ${token}`, 'content-type': 'application/json'}, body: JSON.stringify({sql})});
  const body = await res.json() as {results?: Record<string, unknown>[]; error?: string};
  if (!res.ok) throw Error(`d1 failed (${res.status}): ${body.error ?? 'no reason'}\nSQL: ${sql.slice(0, 500)}`);
  return body.results ?? [];
}
