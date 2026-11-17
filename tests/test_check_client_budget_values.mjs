// Offline fixtures: an explicit invalid JS/CSS bundle ceiling fails; an omitted one stays optional.
import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {gzipSync} from 'node:zlib';
import {precacheManifest} from '../scripts/precache.mjs';

const CHECK = new URL('../scripts/check_client.mjs', import.meta.url).pathname;
const APP = 'assets/app.0123456789.js';
const LANDING = 'assets/landing.0123456789.js';
const CODE = 'export const x = ' + JSON.stringify(Array.from({length: 40}, (_, i) => `v${i}`)) + ';';
const SIZE = gzipSync(Buffer.from(CODE), {level: 9}).length;

async function run(t, budgetText, env = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'client-budget-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  await mkdir(join(dir, '.vite'), {recursive: true});
  await mkdir(join(dir, 'assets'));
  await writeFile(join(dir, APP), CODE);
  await writeFile(join(dir, LANDING), 'export {};');
  await writeFile(join(dir, '.vite/manifest.json'), JSON.stringify({'app.html': {file: APP, isEntry: true}, 'landing.html': {file: LANDING, isEntry: true}}));
  for (const [p, f] of [['app', APP], ['landing', LANDING]]) await writeFile(join(dir, `${p}.fixture.html`), `<script type="module" src="/${f}"></script>`);
  await writeFile(join(dir, '.assetsignore'), '.vite\n');
  await writeFile(join(dir, 'sw.js'), "const BUILD = 'fixture';");
  await writeFile(join(dir, 'precache.json'), JSON.stringify(await precacheManifest(dir, 'fixture')));
  const budget = join(dir, 'budget.json');
  await writeFile(budget, budgetText);
  const r = spawnSync(process.execPath, [CHECK, dir, dir, budget], {encoding: 'utf8', env: {...process.env, ...env}});
  assert.ifError(r.error);
  return {status: r.status, output: r.stdout + r.stderr, dir};
}
const page = body => `{"bundles": {"app.html": ${body}}}`;

for (const kind of ['js', 'css']) {
  const key = `${kind}_gzip_max`;
  for (const [label, value] of [['string', '"1"'], ['null', 'null'], ['true', 'true'], ['false', 'false'],
    ['object', '{}'], ['array', '[1]'], ['negative', '-1'], ['overflow', '1e400']]) {
    test(`explicit_invalid_bundle_ceiling_is_not_disabled: ${key} ${label}`, async t => {
      const r = await run(t, page(`{"${key}": ${value}}`));
      assert.equal(r.status, 1, r.output);
      assert.ok(r.output.includes(`app.html: ${key} must be a finite number >= 0`), r.output);
      assert.ok(!/TypeError/.test(r.output) && !r.output.includes('Client check passed'), r.output);
    });
  }
}

test('partial_budget_dimensions_remain_optional', async t => {
  for (const body of ['{"js_gzip_max": 100000}', '{"css_gzip_max": 100000}', '{}']) {
    const r = await run(t, page(body));
    assert.equal(r.status, 0, r.output);
    assert.ok(r.output.includes('Client check passed'), r.output);
  }
});

test('numeric_ceiling_is_inclusive', async t => {
  assert.equal((await run(t, page(`{"js_gzip_max": ${SIZE}}`))).status, 0);
  const over = await run(t, page(`{"js_gzip_max": ${SIZE - 1}}`));
  assert.equal(over.status, 1, over.output);
  assert.ok(/initial JavaScript \d+ B gzipped exceeds its budget of/.test(over.output), over.output);
  assert.equal((await run(t, page('{"css_gzip_max": 0}'))).status, 0);
  assert.equal((await run(t, page('{"js_gzip_max": 100000.5}'))).status, 0);
});

test('healthy_manifest_and_measurements_unchanged', async t => {
  const out = join(await mkdtemp(join(tmpdir(), 'client-measured-')), 'm.json');
  t.after(() => rm(join(out, '..'), {recursive: true, force: true}));
  const r = await run(t, page('{"js_gzip_max": 100000, "css_gzip_max": 100}'), {BUDGET_MEASUREMENTS_OUT: out});
  assert.equal(r.status, 0, r.output);
  const {readFile} = await import('node:fs/promises');
  assert.equal(JSON.parse(await readFile(out, 'utf8')).bundles['app.html'].js, SIZE);
});
