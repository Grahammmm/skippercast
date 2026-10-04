import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {stripJsonComments, deployConfig, customDomains, features, advisorVars, ADVISOR_SECRETS} from '../scripts/wrangler_config.mjs';

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
    // A read that fails for any reason other than a missing object must never generate a new pair over the stored one.
    const outage = run({FAKE_R2_FAIL: 'Authentication error [code: 10000]'});
    assert.equal(outage.status, 1, outage.stdout + outage.stderr);
    assert.match(outage.stdout, /refusing to generate a new pair/);
    assert.equal((readFileSync(log, 'utf8').match(/r2 object put/g) || []).length, 1, 'no second put after a failed read');
    assert.equal(JSON.parse(readFileSync(join(dir, 'stored.json'), 'utf8')).VAPID_PUBLIC_KEY, stored.VAPID_PUBLIC_KEY, 'the stored pair is untouched');
    assert.doesNotMatch(first.stdout + second.stdout, new RegExp(stored.VAPID_PRIVATE_KEY.slice(0, 12)), 'the private key is never printed');
    const actions = run({GITHUB_ACTIONS: 'true'});
    assert.equal((actions.stdout.match(/::add-mask::/g) || []).length, 2, 'under Actions the pair is masked: ' + actions.stdout);
    const short = run({VAPID_PUBLIC_KEY: 'B'.repeat(86), VAPID_PRIVATE_KEY: 'k'.repeat(43)});
    assert.equal(short.status, 1);
    assert.match(short.stderr, /wrong length/);
    assert.doesNotMatch(readFileSync(log, 'utf8'), /d1 export|migrations apply|deploy --config/, 'nothing deployed on a bad pair');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

const ID = '12345678-1234-1234-1234-123456789abc';
const committed = () => readFileSync(new URL('../wrangler.jsonc', import.meta.url), 'utf8');
const ADVISOR_ENV = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_CHANNEL: 'twilio', ADVISOR_MODEL: ' claude-opus-5-5 ', ADVISOR_NUMBER: '',
  BLUEBUBBLES_PRIVATE_API: 'true', ENABLE_ADVISOR: 'true', PATH: '/usr/bin', OTHER_ADVISOR: 'x'};

test('advisor off: the deploy config is byte-identical to the config without the feature, whatever the environment holds', () => {
  const text = committed();
  // What deployConfig produced before ENABLE_ADVISOR existed: the committed file with the id, bucket and workers.dev filled in.
  const before = JSON.parse(stripJsonComments(text));
  before.d1_databases[0].database_id = ID; before.r2_buckets[0].bucket_name = 'skippercast-feeds'; before.workers_dev = true;
  const serialize = config => JSON.stringify(config, null, 2) + '\n';
  assert.equal(serialize(deployConfig(text, ID, 'skippercast-feeds')), serialize(before));
  assert.equal(serialize(deployConfig(text, ID, 'skippercast-feeds', '', {advisor: false, environ: ADVISOR_ENV})), serialize(before));
  assert.equal(serialize(deployConfig(text, ID, 'skippercast-feeds', '', {queues: true, environ: ADVISOR_ENV})),
    serialize(deployConfig(text, ID, 'skippercast-feeds', '', {queues: true})));
  for (const value of [undefined, '', 'false', '1', 'TRUE ']) assert.equal(features({ENABLE_ADVISOR: value}).advisor, value === 'TRUE ', String(value));
});

test('advisor on: the private media bucket, the advisor queue pair and the advisor vars are added', () => {
  const config = deployConfig(committed(), ID, 'skippercast-feeds', '', {advisor: true, environ: ADVISOR_ENV});
  assert.deepEqual(config.r2_buckets, [{binding: 'FEEDS', bucket_name: 'skippercast-feeds'}, {binding: 'ADVISOR_MEDIA', bucket_name: 'skippercast-advisor-media'}]);
  assert.deepEqual(config.queues.producers, [{queue: 'skippercast-advisor', binding: 'ADVISOR_QUEUE'}]);
  assert.deepEqual(config.queues.consumers, [
    {queue: 'skippercast-advisor', max_batch_size: 10, max_batch_timeout: 5, max_retries: 3, max_concurrency: 2, retry_delay: 20, dead_letter_queue: 'skippercast-advisor-dlq'},
    {queue: 'skippercast-advisor-dlq', max_batch_size: 25, max_batch_timeout: 30, max_retries: 0, max_concurrency: 1},
  ]);
  // Existing vars stay; advisor vars are trimmed, empty ones left out, unrelated keys ignored.
  assert.deepEqual(config.vars, {IDENTITY_PROVIDER: 'skippercast', BOAT_LOOKUP_ENABLED: 'true', BOAT_LOOKUP_GLOBAL_DAILY_LIMIT: '500',
    ADVISOR_CHANNEL: 'twilio', ADVISOR_MODEL: 'claude-opus-5-5', BLUEBUBBLES_PRIVATE_API: 'true', TEXT_ADVISOR_ENABLED: 'true'});
  // Without advisor vars in the environment only the bindings change.
  assert.deepEqual(deployConfig(committed(), ID, 'skippercast-feeds', '', {advisor: true}).vars, JSON.parse(stripJsonComments(committed())).vars);
  const env = readFileSync(new URL('../server/env.ts', import.meta.url), 'utf8');
  for (const binding of ['ADVISOR_MEDIA', 'ADVISOR_QUEUE', ...Object.keys(config.vars)]) assert.match(env, new RegExp(`^\\s+${binding}\\?:`, 'm'), `server/env.ts declares ${binding}`);
});

test('trip and advisor queues together: producers and consumers are concatenated, trip first', () => {
  const config = deployConfig(committed(), ID, 'skippercast-feeds', '', {queues: true, advisor: true});
  assert.deepEqual(config.queues.producers.map(p => p.binding), ['TRIP_QUEUE', 'ADVISOR_QUEUE']);
  assert.deepEqual(config.queues.consumers.map(c => c.queue), ['skippercast-trip-checks', 'skippercast-trip-checks-dlq', 'skippercast-advisor', 'skippercast-advisor-dlq']);
  // The exported constants are never mutated by a build.
  assert.equal(deployConfig(committed(), ID, 'skippercast-feeds', '', {queues: true}).queues.producers.length, 1);
});

test('a secret named as a deploy variable is refused, never copied into vars', () => {
  for (const key of ['ADVISOR_WEBHOOK_TOKEN', 'ADVISOR_PHONE_KEY'])
    assert.throws(() => deployConfig(committed(), ID, 'skippercast-feeds', '', {advisor: true, environ: {[key]: 'secret-value'}}), new RegExp(key));
  // Non-advisor secret names are not vars candidates at all, so they are simply ignored.
  assert.deepEqual(advisorVars({ANTHROPIC_API_KEY: 'k', TWILIO_AUTH_TOKEN: 't', META_IG_TOKEN: 'm'}), {});
  assert.ok(ADVISOR_SECRETS.has('ADVISOR_WEBHOOK_TOKEN') && ADVISOR_SECRETS.has('ADVISOR_PHONE_KEY'));
  // Even an empty secret-named variable is refused: its presence is the mistake.
  assert.throws(() => advisorVars({ADVISOR_PHONE_KEY: ''}), /ADVISOR_PHONE_KEY/);
});

test('the CLI reads ENABLE_ADVISOR and the advisor vars from the environment', () => {
  const dir = mkdtempSync(join(tmpdir(), 'wrangler-config-')), out = join(dir, 'w.json'), cwd = fileURLToPath(new URL('..', import.meta.url));
  try {
    const on = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', ID, 'skippercast-feeds', out, ''], {cwd, encoding: 'utf8',
      env: {...process.env, ENABLE_ADVISOR: 'true', ENABLE_QUEUES: '', TEXT_ADVISOR_ENABLED: 'true', ADVISOR_CHANNEL: 'twilio'}});
    assert.equal(on.status, 0, on.stderr);
    assert.match(on.stdout, /with advisor/);
    const config = JSON.parse(readFileSync(out, 'utf8'));
    assert.equal(config.vars.TEXT_ADVISOR_ENABLED, 'true'); assert.equal(config.vars.ADVISOR_CHANNEL, 'twilio');
    assert.equal(config.queues.producers[0].binding, 'ADVISOR_QUEUE');
    const off = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', ID, 'skippercast-feeds', out, ''], {cwd, encoding: 'utf8',
      env: {...process.env, ENABLE_ADVISOR: '', ENABLE_QUEUES: '', TEXT_ADVISOR_ENABLED: 'true'}});
    assert.equal(off.status, 0, off.stderr);
    assert.equal(JSON.parse(readFileSync(out, 'utf8')).vars.TEXT_ADVISOR_ENABLED, undefined, 'vars are copied only with ENABLE_ADVISOR');
    const secret = spawnSync(process.execPath, ['scripts/wrangler_config.mjs', ID, 'skippercast-feeds', out, ''], {cwd, encoding: 'utf8',
      env: {...process.env, ENABLE_ADVISOR: 'true', ADVISOR_WEBHOOK_TOKEN: 'leak-me'}});
    assert.notEqual(secret.status, 0);
    assert.match(secret.stderr, /ADVISOR_WEBHOOK_TOKEN is a secret/);
    assert.doesNotMatch(secret.stderr + secret.stdout, /leak-me/);
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('the deploy script creates the advisor bucket and queues only with ENABLE_ADVISOR, before the config that binds them', () => {
  const script = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  const block = script.indexOf('if [ "${ENABLE_ADVISOR:-}" = "true" ]'), generate = script.indexOf('node scripts/wrangler_config.mjs');
  assert.ok(block > 0 && block < generate, 'the advisor block runs before the deploy config is written');
  const body = script.slice(block, script.indexOf('\nfi\n', block));
  assert.match(body, /r2 bucket create skippercast-advisor-media/);
  assert.match(body, /grep -qi "already exist"/, 'an existing bucket is success');
  assert.match(body, /for queue in skippercast-advisor-dlq skippercast-advisor; do/, 'the dead-letter queue is created first');
  assert.match(body, /queues info "\$queue"/);
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  for (const name of ['ENABLE_ADVISOR', 'TEXT_ADVISOR_ENABLED', 'ADVISOR_CHANNEL', 'ADVISOR_REPLIES_ENABLED', 'ADVISOR_SOCIAL_ENABLED', 'ADVISOR_INBOX_ENABLED',
    'ADVISOR_NUMBER', 'ADVISOR_PUBLIC_BASE', 'ADVISOR_REGION_DEFAULT', 'ADVISOR_MODEL', 'ADVISOR_VISION_MODEL', 'ADVISOR_VISION_PROVIDERS',
    'ADVISOR_DAILY_MESSAGES_PER_CONTACT', 'ADVISOR_DAILY_LLM_PER_CONTACT', 'ADVISOR_GLOBAL_DAILY_LLM', 'ADVISOR_GLOBAL_DAILY_VISION',
    'ADVISOR_AUTO_PUBLISH_AFTER', 'ADVISOR_ADMIN_CONTACT_ID', 'ADVISOR_INBOX_PUBLIC_REPLIES', 'BLUEBUBBLES_PRIVATE_API'])
    assert.match(workflow, new RegExp(`^ {10}${name}: \\$\\{\\{ vars\\.${name} \\}\\}$`, 'm'), name);
  for (const secret of ADVISOR_SECRETS) assert.doesNotMatch(workflow, new RegExp(`\\b${secret}: \\$\\{\\{ vars\\.`), `${secret} is never a variable`);
});
