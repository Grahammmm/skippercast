#!/usr/bin/env node
// Serve the built site for the browser tests (P4-09a): the real Worker and
// static assets under Wrangler's dev runtime (e2e/worker.mjs), with a local D1 migrated from drizzle/
// (accounts need it) and http://localhost:<port> allowed as an account origin.
// Run `pnpm build` first. Playwright starts this (playwright.config.ts).
//
// Public /feeds/ requests still use the Worker's upstream. Browser fixtures
// intercept forecast feeds and /api/om before the Worker receives them;
// blocking other browser origins alone does not block Worker-side requests.
import {spawn, spawnSync} from 'node:child_process';
import {existsSync, readdirSync, rmSync} from 'node:fs';
import {resolve} from 'node:path';

const root = resolve(import.meta.dirname, '..');
const port = process.env.E2E_PORT || '8787';
const WRANGLER = ['--yes', 'wrangler@4.142.0'];   // same pin as .github/workflows/deploy-cloudflare.yml
const config = resolve(root, 'wrangler.e2e.local.jsonc');
const state = resolve(root, '.wrangler/e2e-state');

if (!existsSync(resolve(root, 'dist/server/index.js'))) { console.error('Run `pnpm build` before the browser tests.'); process.exit(1); }
const run = (cmd, args) => { const r = spawnSync(cmd, args, {cwd: root, stdio: 'inherit'}); if (r.status !== 0) process.exit(r.status ?? 1); };
run(process.execPath, ['scripts/wrangler_config.mjs', '00000000-0000-0000-0000-000000000000', 'skippercast-feeds', config]);
rmSync(state, {recursive: true, force: true});   // every run starts with empty D1, R2 and caches
rmSync(resolve(root, '.wrangler/e2e-sql.json'), {force: true});   // and without the last run's SQL endpoint (e2e/worker.mjs)
run('npx', [...WRANGLER, 'd1', 'migrations', 'apply', 'DB', '--local', '--config', config, '--persist-to', state]);
// TA-W1: browser-test fixtures (e2e/seed/*.sql, in name order), loaded before the Worker starts so no spec writes to D1 under a running test.
for (const file of readdirSync(resolve(root, 'e2e/seed')).filter(name => name.endsWith('.sql')).sort())
  run('npx', [...WRANGLER, 'd1', 'execute', 'DB', '--local', '--config', config, '--persist-to', state, '--file', resolve(root, 'e2e/seed', file)]);
// #571, #579: the Worker runs in e2e/worker.mjs (Wrangler's programmatic API, under the same pin), which also serves the
// test-only SQL endpoint e2e/d1.ts uses, so no second workerd ever opens this state while the Worker runs.
const server = spawn('npx', ['--yes', '--package', WRANGLER[1], '--', process.execPath, resolve(root, 'e2e/worker.mjs'), config, state, port,
  `EXTRA_ORIGINS:http://localhost:${port}`,
  // TA-C3: the Text Advisor is on for the browser tests only (e2e/advisor-chat.spec.ts); deployed it stays off until the owner enables it.
  'TEXT_ADVISOR_ENABLED:true',
  // CF-31: the charter fleet's admin is on for the browser tests only (e2e/fleet-admin.spec.ts); deployed it stays off until the owner enables it.
  'FLEET_ENABLED:true'],
{cwd: root, stdio: 'inherit', env: {...process.env, WRANGLER_SEND_METRICS: 'false'}});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.kill(signal));
server.on('exit', code => process.exit(code ?? 0));
