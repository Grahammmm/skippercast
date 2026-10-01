#!/usr/bin/env node
// Serve the built site for the browser tests (P4-09a): the real Worker and
// static assets under `wrangler dev`, with a local D1 migrated from drizzle/
// (accounts need it) and http://localhost:<port> allowed as an account origin.
// Run `pnpm build` first. Playwright starts this (playwright.config.ts).
//
// Public data (/feeds/, /api/om) goes through the Worker to its upstream, the
// repository's raw GitHub branches, as in production; the tests block every
// other origin, so they never depend on NWS, NOAA or map tile servers.
import {spawn, spawnSync} from 'node:child_process';
import {existsSync, rmSync, mkdirSync, createWriteStream} from 'node:fs';
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
run('npx', [...WRANGLER, 'd1', 'migrations', 'apply', 'DB', '--local', '--config', config, '--persist-to', state]);
// Email sign-in links go to the Worker log (MAIL_TRANSPORT=log, localhost only),
// which is also written to test-results/worker.log for the email sign-in test to read.
mkdirSync(resolve(root, 'test-results'), {recursive: true});
const log = createWriteStream(resolve(root, 'test-results/worker.log'));
const server = spawn('npx', [...WRANGLER, 'dev', '--config', config, '--persist-to', state, '--ip', '127.0.0.1', '--port', port,
  '--var', `EXTRA_ORIGINS:http://localhost:${port}`, '--var', 'MAIL_TRANSPORT:log', '--show-interactive-dev-session=false', '--log-level', 'warn'],
{cwd: root, stdio: ['inherit', 'pipe', 'pipe'], env: {...process.env, WRANGLER_SEND_METRICS: 'false'}});
server.stdout.on('data', chunk => { process.stdout.write(chunk); log.write(chunk); });
server.stderr.on('data', chunk => { process.stderr.write(chunk); log.write(chunk); });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.kill(signal));
server.on('exit', code => process.exit(code ?? 0));
