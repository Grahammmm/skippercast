import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {stripJsonComments, deployConfig, customDomains} from '../scripts/wrangler_config.mjs';

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
