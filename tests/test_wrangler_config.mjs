import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripJsonComments, deployConfig} from '../scripts/wrangler_config.mjs';

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
