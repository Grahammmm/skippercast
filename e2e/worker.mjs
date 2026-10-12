#!/usr/bin/env node
// The browser tests' one Worker process (#571, #579). e2e/serve.mjs prepares the
// config and the migrated, seeded D1 state, then runs this file under
// `npx --package wrangler@<pin>`, which puts that Wrangler's bin directory on PATH.
//
// It starts the Worker with Wrangler's programmatic API (the same as `wrangler dev`)
// and serves a test-only SQL endpoint from THIS Node process, on an ephemeral
// 127.0.0.1 port, that runs statements through the running workerd's own D1
// binding (Miniflare getD1Database). e2e/d1.ts calls it instead of spawning
// `wrangler d1 execute --local`, which opened a second workerd on the same SQLite
// files and raced the dev server (SQLITE_BUSY, "Network connection lost").
// Nothing in the Worker (server/) knows about the endpoint; it needs the bearer
// token written, with its address, to .wrangler/e2e-sql.json.
//
// Arguments: <wrangler config> <persist dir> <port> [NAME:value vars...]
import {randomBytes} from 'node:crypto';
import {existsSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:http';
import {delimiter, join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const PIN = '4.142.0';
const [config, persist, port, ...vars] = process.argv.slice(2);
const root = resolve(import.meta.dirname, '..');
const SQL_FILE = resolve(root, '.wrangler/e2e-sql.json');   // e2e/d1.ts reads it; e2e/serve.mjs removes it before each run

/** The pinned Wrangler that `npx --package` installed: its package sits next to the .bin directory on PATH. */
function wranglerEntry() {
  for (const bin of (process.env.PATH ?? '').split(delimiter)) {
    const pkg = join(bin, '..', 'wrangler', 'package.json');
    if (existsSync(join(bin, 'wrangler')) && existsSync(pkg) && JSON.parse(readFileSync(pkg, 'utf8')).version === PIN)
      return join(bin, '..', 'wrangler', 'wrangler-dist', 'cli.js');
  }
  throw Error(`wrangler@${PIN} not on PATH: run this through \`npx --yes --package wrangler@${PIN} -- node e2e/worker.mjs\``);
}

const wrangler = await import(pathToFileURL(wranglerEntry()).href);
const bindings = Object.fromEntries(vars.map(v => {
  const at = v.indexOf(':');
  return [v.slice(0, at), {type: 'plain_text', value: v.slice(at + 1)}];
}));
// A runtime that never comes up (a port clash, a bad bundle) would otherwise hang until Playwright's webServer timeout.
const startup = setTimeout(() => { console.error('e2e/worker.mjs: the Worker did not start within 90 s'); process.exit(1); }, 90_000);
const worker = await wrangler.unstable_startWorker({
  config,
  bindings,
  // No watching: the built bundle, assets and config never change during a test run, and a reload would drop
  // requests in flight and replace the runtime the SQL endpoint uses.
  dev: {server: {hostname: '127.0.0.1', port: Number(port)}, persist, watch: false, inspector: false, remote: false, liveReload: false, logLevel: 'warn'},
});
// `ready` is the proxy; a first request through it waits for the Worker's own runtime (Miniflare) to load.
await worker.ready;
await (await worker.fetch(`http://127.0.0.1:${port}/api/health`)).arrayBuffer();
worker.raw.on('reloadComplete', () => console.error('e2e/worker.mjs: the Worker reloaded during the run'));
/** The running Worker's D1, looked up per request: a stub from before a reload would be poisoned. */
async function database() {
  const mf = worker.raw.runtimes.find(r => r.mf)?.mf;
  if (!mf) throw Error('the local runtime has no Miniflare instance');
  return mf.getD1Database('DB');
}
await database();
clearTimeout(startup);

// POST {sql}: every statement of the script in one D1 batch (a transaction); the rows of the last one.
const token = randomBytes(24).toString('hex');
const sqlServer = createServer(async (req, res) => {
  const reply = (status, body) => { res.writeHead(status, {'content-type': 'application/json'}); res.end(JSON.stringify(body)); };
  if (req.method !== 'POST' || req.url !== '/sql' || req.headers.authorization !== `Bearer ${token}`) return reply(404, {error: 'Not found'});
  try {
    let body = '';
    for await (const chunk of req) body += chunk;
    const statements = wrangler.unstable_splitSqlQuery(String(JSON.parse(body).sql ?? '')).filter(s => s.trim());
    if (!statements.length) return reply(400, {error: 'no SQL'});
    const db = await database();
    const results = await db.batch(statements.map(s => db.prepare(s)));
    reply(200, {results: results.at(-1)?.results ?? []});
  } catch (e) {
    reply(500, {error: e instanceof Error ? e.message : String(e)});
  }
});
await new Promise(ok => sqlServer.listen(0, '127.0.0.1', ok));
writeFileSync(SQL_FILE, JSON.stringify({url: `http://127.0.0.1:${sqlServer.address().port}/sql`, token}));

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  sqlServer.close();
  rmSync(SQL_FILE, {force: true});
  await worker.dispose().catch(() => {});
  process.exit(0);
}
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(signal, close);
