import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {stripJsonComments, deployConfig, customDomains, features} from '../scripts/wrangler_config.mjs';

test('comment stripping leaves // and /* inside strings alone', () => {
  const text = '{\n  // a comment\n  "url": "https://example.com/a//b", /* block */ "glob": "x/*y*/z",\n  "n": 1, // trailing\n}';
  assert.deepEqual(JSON.parse(stripJsonComments(text)), {url: 'https://example.com/a//b', glob: 'x/*y*/z', n: 1});
  assert.deepEqual(JSON.parse(stripJsonComments('{"q": "say \\"//hi\\""}')), {q: 'say "//hi"'});
});

test('the committed wrangler.jsonc becomes a valid deploy config', () => {
  const text = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8');
  const config = deployConfig(text, '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds');
  assert.equal(config.d1_databases[0].database_id, '12345678-1234-1234-1234-123456789abc');
  assert.equal(config.r2_buckets[0].bucket_name, 'skippercast-feeds');
  assert.equal(config.main, 'dist/server/index.js');
  assert.throws(() => deployConfig(text, 'not-an-id', 'skippercast-feeds'));
  assert.throws(() => deployConfig(text, '12345678-1234-1234-1234-123456789abc', 'Bad_Bucket'));
});

test('without CUSTOM_DOMAINS the deploy config is workers.dev only', () => {
  const text = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8');
  for (const domains of [undefined, '', ' , ']) {
    const config = deployConfig(text, '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', domains);
    assert.equal(config.routes, undefined);
    assert.equal(config.workers_dev, true);
  }
});

test('CUSTOM_DOMAINS becomes custom-domain routes and keeps workers.dev on', () => {
  const text = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8');
  const config = deployConfig(text, '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', 'skippercast.com, www.skippercast.com,skippercast.com');
  assert.deepEqual(config.routes, [
    {pattern: 'skippercast.com', custom_domain: true},
    {pattern: 'www.skippercast.com', custom_domain: true},
  ]);
  assert.equal(config.workers_dev, true, 'the workers.dev staging URL keeps working');
  assert.deepEqual(customDomains('SkipperCast.com'), ['skippercast.com']);
  for (const bad of ['https://skippercast.com', 'skippercast.com/*', '*.skippercast.com', 'skippercast.com:443', 'localhost', 'a b.com'])
    assert.throws(() => deployConfig(text, '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', bad), /custom domain/, bad);
});

test('the CLI passes the fourth argument through as custom domains', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wrangler-config-')), out = join(dir, 'w.json');
  try {
    const run = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', out, 'skippercast.com,www.skippercast.com'], {cwd: fileURLToPath(new URL('..', import.meta.url)), encoding: 'utf8'});
    assert.equal(run.status, 0, run.stderr);
    assert.deepEqual(JSON.parse(readFileSync(out, 'utf8')).routes.map(r => r.pattern), ['skippercast.com', 'www.skippercast.com']);
    const plain = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', out, ''], {cwd: fileURLToPath(new URL('..', import.meta.url)), encoding: 'utf8'});
    assert.equal(plain.status, 0, plain.stderr);assert.equal(JSON.parse(readFileSync(out, 'utf8')).routes, undefined);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('queues are added only when ENABLE_QUEUES is "true" (any case), and their binding is typed in Env', () => {
  const text = readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8'), id = '12345678-1234-1234-1234-123456789abc';
  for (const value of [undefined, '', 'false', '1', 'yes', 'TRUE ']) assert.equal(features({ENABLE_QUEUES: value}).queues, value === 'TRUE ', String(value));
  assert.equal(deployConfig(text, id, 'skippercast-feeds').queues, undefined, 'off by default');
  assert.equal(JSON.parse(stripJsonComments(text)).queues, undefined, 'the committed config never binds queues itself');
  const config = deployConfig(text, id, 'skippercast-feeds', '', {queues: true});
  assert.deepEqual(config.queues.producers, [{queue: 'skippercast-trip-checks', binding: 'TRIP_QUEUE'}]);
  const [main, dlq] = config.queues.consumers;
  assert.equal(main.queue, 'skippercast-trip-checks');
  assert.equal(main.dead_letter_queue, 'skippercast-trip-checks-dlq');
  assert.equal(main.max_batch_size, 25);
  assert.equal(main.max_retries, 3);
  assert.equal(dlq.queue, 'skippercast-trip-checks-dlq');
  const env = readFileSync(new URL('../server/env.ts', import.meta.url), 'utf8');
  for (const {binding} of config.queues.producers) assert.match(env, new RegExp(`^\\s+${binding}\\?:`, 'm'), `server/env.ts declares ${binding}`);
});

test('the CLI reads ENABLE_QUEUES from the environment', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wrangler-config-')), out = join(dir, 'w.json'), cwd = fileURLToPath(new URL('..', import.meta.url));
  try {
    const on = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', out, ''], {cwd, encoding: 'utf8', env: {...process.env, ENABLE_QUEUES: 'true'}});
    assert.equal(on.status, 0, on.stderr);
    assert.match(on.stdout, /with queues/);
    assert.equal(JSON.parse(readFileSync(out, 'utf8')).queues.producers[0].binding, 'TRIP_QUEUE');
    const off = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', '12345678-1234-1234-1234-123456789abc', 'skippercast-feeds', out, ''], {cwd, encoding: 'utf8', env: {...process.env, ENABLE_QUEUES: ''}});
    assert.equal(off.status, 0, off.stderr);
    assert.equal(JSON.parse(readFileSync(out, 'utf8')).queues, undefined);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('the deploy script creates the queues only when enabled, before the config that binds them', () => {
  const script = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  const create = script.indexOf('queues create'), generate = script.indexOf('node scripts/wrangler_config.mjs');
  assert.ok(create > 0 && create < generate, 'queues exist before the Worker is deployed with their bindings');
  assert.match(script, /if \[ "\$\{ENABLE_QUEUES:-\}" = "true" \]/);
  assert.match(script, /queues info "\$queue"/, 'an existing queue is left alone');
  assert.ok(script.indexOf('skippercast-trip-checks-dlq') < script.indexOf('skippercast-trip-checks;'), 'the dead-letter queue is created first');
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  assert.match(workflow, /ENABLE_QUEUES: \$\{\{ vars\.ENABLE_QUEUES \}\}/);
});

test('the deploy script takes the VAPID pair from the backup bucket, generating it once, and refuses a malformed pair', () => {
  const dir = mkdtempSync(join(tmpdir(), 'deploy-'));
  try {
    const log = join(dir, 'npx.log');
    // tests/fixtures/fake-wrangler.sh stands in for npx: it logs every call, keeps one stored
    // object for `r2 object get/put`, and returns no D1 databases so the run stops after the key check.
    writeFileSync(join(dir, 'npx'), '#!/bin/sh\nexec "' + fileURLToPath(new URL('./fixtures/fake-wrangler.sh', import.meta.url)) + '" "$@"\n', {mode: 0o755});
    const script = fileURLToPath(new URL('../scripts/cloudflare_deploy.sh', import.meta.url));
    const run = keys => spawnSync('bash', [script], {cwd: dir, encoding: 'utf8',
      env: {PATH: `${dir}:${process.env.PATH}`, HOME: dir, CLOUDFLARE_API_TOKEN: 't', CLOUDFLARE_ACCOUNT_ID: 'a', FAKE_LOG: log, FAKE_STORE: join(dir, 'stored.json'), ...keys}});
    const first = run({});
    assert.match(first.stdout, /generated and saved to r2:\/\/skippercast-backups\/secrets\/vapid\.json/, first.stderr);
    assert.ok(readFileSync(join(dir, 'npx.log'), 'utf8').includes('d1 list'), 'the key step completed and the deploy went on: ' + first.stderr);
    const stored = JSON.parse(readFileSync(join(dir, 'stored.json'), 'utf8'));
    assert.equal(stored.VAPID_PUBLIC_KEY.length, 87); assert.equal(stored.VAPID_PRIVATE_KEY.length, 43);
    assert.throws(() => readFileSync(join(dir, 'var', 'vapid.json')), /ENOENT/, 'the pair never stays on disk');
    const second = run({});
    assert.match(second.stdout, /read from r2:/);
    assert.equal(JSON.parse(readFileSync(join(dir, 'stored.json'), 'utf8')).VAPID_PUBLIC_KEY, stored.VAPID_PUBLIC_KEY, 'the same pair is reused');
    assert.equal((readFileSync(log, 'utf8').match(/r2 object put/g) || []).length, 1, 'generated exactly once');
    const short = run({VAPID_PUBLIC_KEY: 'B'.repeat(86), VAPID_PRIVATE_KEY: 'k'.repeat(43)});
    assert.equal(short.status, 1);
    assert.match(short.stderr, /wrong length/);
    assert.doesNotMatch(readFileSync(log, 'utf8'), /d1 export|migrations apply|deploy --config/, 'nothing deployed on a bad pair');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
