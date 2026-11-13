// SC2184-06: the hourly rules-card alarm (scripts/rules_status_probe.mjs). CI was green while every species read
// "Check rules". The probe runs the app's own `loadRegs` and `regulationState` against a site (here a fixture
// site: the frozen FE-61 registry, as tests/test_regs_retry.mjs builds it) and is blank only when EVERY species
// in the default region is unknown for want of rules. A crash counts as blank. No network: every fetch is a fixture.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {BLANK_EXIT, probe} from '../scripts/rules_status_probe.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const REGION = fixture.region;
const NOW = Date.parse('2026-09-21T18:00:00Z');
const BASE = 'https://site.test';

/** The frozen registry, reviewed an hour before `at`, every source checked unchanged at `at`. */
function registry(at = NOW, review = 'reviewed') {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - 3600000).toISOString();
  d.rules_review_status = review;
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
/** A fixture site: the region directory plus the registry (null: the registry is not served). */
function site(regs) {
  const files = {
    '/regions/index.json': {schema_version: 1, default_region: REGION.id, regions: [{id: REGION.id, config: `regions/${REGION.id}/region.json`}]},
    [`/regions/${REGION.id}/region.json`]: REGION,
  };
  if (regs) files['/data/regulations.json'] = regs;
  return async url => {
    const body = files[new URL(url).pathname];
    return body === undefined ? new Response('', {status: 404}) : Response.json(body);
  };
}

test('every species reads Check rules (registry not reviewed): the card is blank', async () => {
  const r = await probe(BASE, site(registry(NOW, 'draft')), NOW);
  assert.equal(r.region, REGION.id);
  assert.deepEqual(r.species.map(s => s.species), REGION.species);
  assert.ok(r.species.every(s => s.status === 'unknown' && s.label === 'Check rules'), 'all unknown');
  assert.equal(r.blank, true);
});

test('no registry served at all: the card is blank', async () => {
  const r = await probe(BASE, site(null), NOW);
  assert.equal(r.blank, true);
});

test('a reviewed registry: at least one species has a season status, so no alarm', async () => {
  const r = await probe(BASE, site(registry()), NOW);
  const known = r.species.filter(s => s.status !== 'unknown');
  assert.ok(known.some(s => s.status === 'open'), `one species is open: ${JSON.stringify(r.species.map(s => [s.species, s.status]))}`);
  assert.equal(r.blank, false);
});

test('a probe that cannot read the site throws, and the command line reports blank', async () => {
  await assert.rejects(probe(BASE, async () => { throw new TypeError('fetch failed'); }, NOW));
  const script = fileURLToPath(new URL('../scripts/rules_status_probe.mjs', import.meta.url));
  const run = spawnSync(process.execPath, [script, '--base', 'http://127.0.0.1:1'], {encoding: 'utf8', timeout: 60000});
  assert.notEqual(run.status, 0, 'only exit 0 is healthy');
  assert.ok(run.stdout.includes('rules-card-blank'), run.stdout);
  assert.notEqual(BLANK_EXIT, 0);
});
