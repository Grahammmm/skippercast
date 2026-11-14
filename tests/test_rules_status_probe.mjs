// SC2184-06: the hourly rules-card alarm (scripts/rules_status_probe.mjs). CI was green while every species read
// "Check rules". The probe runs the app's own `loadRegs` and `regulationState` against a site (here a fixture
// site: the frozen FE-61 registry, as tests/test_regs_retry.mjs builds it) and fails when ANY species
// in the selected region is unknown for want of rules. A crash fails too. No external network: fixture fetches only.
import assert from 'node:assert/strict';
import {execFile, spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createServer} from 'node:http';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {BLANK_EXIT, isBlank, probe} from '../scripts/rules_status_probe.mjs';

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
function site(regs, region = REGION) {
  const files = {
    '/regions/index.json': {schema_version: 1, default_region: REGION.id, regions: [{id: REGION.id, config: `regions/${REGION.id}/region.json`}, {id: region.id, config: 'custom/region.json'}]},
    [`/regions/${REGION.id}/region.json`]: REGION,
    '/custom/region.json': region,
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

test('a reviewed registry: every species has a season status, so no alarm', async () => {
  const r = await probe(BASE, site(registry()), NOW);
  const known = r.species.filter(s => s.status !== 'unknown');
  assert.ok(known.some(s => s.status === 'open'), `one species is open: ${JSON.stringify(r.species.map(s => [s.species, s.status]))}`);
  assert.equal(r.blank, false);
  assert.ok(r.species.every(s => !s.blank));
});

test('one unknown species fails even while other species still have statuses', async () => {
  const regs = registry();
  const profile = regs.species[REGION.species.find(id => id !== 'reef')];
  const source = profile.source_ids[0];
  regs.sources['fixture-species-only'] = structuredClone(regs.sources[source]);
  regs.checks['fixture-species-only'] = {...regs.checks[source], status: 'changed'};
  profile.source_ids.push('fixture-species-only');
  const r = await probe(BASE, site(regs), NOW);
  assert.ok(r.species.some(s => s.blank));
  assert.ok(r.species.some(s => !s.blank));
  assert.equal(r.blank, true);
});

test('a season that requires choosing a location is not missing a status', () => {
  assert.equal(isBlank({status: 'unknown', labelId: 'rules.label.chooseLocation'}), false);
  assert.equal(isBlank({status: 'unknown', labelId: 'rules.label.unknown'}), true);
});

test('a listed non-default region uses its config path and can pass with reviewed rules', async () => {
  const region = {...REGION, id: 'fixture-other-coast', species: [REGION.species[0]]};
  const r = await probe(BASE, site(registry(), region), NOW, region.id);
  const defaultResult = await probe(BASE, site(registry()), NOW);
  assert.equal(r.region, region.id);
  assert.deepEqual(r.species, defaultResult.species.filter(s => region.species.includes(s.species)));
  assert.equal(r.blank, false);
});

const stage1 = ['morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon', 'big-sur-coast', 'monterey-point-sur', 'point-arguello-conception'];
const index = JSON.parse(readFileSync(new URL('../dist/regions/index.json', import.meta.url)));
const regions = stage1.map(id => JSON.parse(readFileSync(new URL(`../dist/regions/${id}/region.json`, import.meta.url))));

function regionalSite() {
  const files = {'/regions/index.json': index};
  for (const region of regions) files[`/${index.regions.find(r => r.id === region.id).config}`] = region;
  return files;
}

test('all six Stage 1 regions use their own species and rule requests, not the default region', async () => {
  const files = regionalSite();
  for (const region of regions) {
    const requests = [];
    const r = await probe(BASE, async url => {
      const path = new URL(url).pathname;
      requests.push(path);
      return files[path] ? Response.json(files[path]) : new Response('', {status: 404});
    }, NOW, region.id);
    assert.equal(r.region, region.id);
    assert.deepEqual(r.species.map(s => s.species), region.species);
    assert.ok(r.species.every(s => s.status === 'unknown'));
    assert.equal(r.blank, true);
    assert.ok(requests.includes(`/regions/${region.id}/regulations-startup.json`));
    if (region.id !== index.default_region) assert.ok(!requests.includes(`/regions/${index.default_region}/region.json`));
  }
});

test('unknown region is rejected without silently probing the default', async () => {
  const requests = [];
  await assert.rejects(probe(BASE, async url => {
    requests.push(new URL(url).pathname);
    return Response.json(index);
  }, NOW, 'not-a-region'), /not listed/);
  assert.deepEqual(requests, ['/regions/index.json']);
});

test('CLI selects a non-default region and exits 3 for missing statuses', async t => {
  const files = regionalSite();
  const server = createServer((req, res) => {
    const body = files[req.url];
    res.writeHead(body ? 200 : 404, {'Content-Type': 'application/json'});
    res.end(JSON.stringify(body ?? {}));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const region = regions[1];
  const script = fileURLToPath(new URL('../scripts/rules_status_probe.mjs', import.meta.url));
  const run = await promisify(execFile)(process.execPath, [script, '--region', region.id, '--base', `http://127.0.0.1:${server.address().port}`], {timeout: 60000}).catch(e => e);
  assert.equal(run.code, BLANK_EXIT);
  const lines = run.stdout.trim().split('\n');
  assert.equal(lines[0], `region: ${region.id}`);
  assert.deepEqual(lines.slice(1, -1).map(line => line.split(':')[0]), region.species);
  assert.ok(lines.slice(1, -1).every(line => line.includes(': unknown (')));
  assert.equal(lines.at(-1), 'rules-card-blank');
});

test('CLI rejects missing, duplicate and misspelled options without fetching', () => {
  const script = fileURLToPath(new URL('../scripts/rules_status_probe.mjs', import.meta.url));
  for (const args of [['--region'], ['--region', '--base', BASE], ['--base'], ['--regoin', 'morro-bay'], ['--region', 'morro-bay', '--region', 'big-sur-coast']]) {
    const run = spawnSync(process.execPath, [script, ...args], {encoding: 'utf8', timeout: 60000});
    assert.equal(run.status, 1, JSON.stringify(args));
    assert.ok(run.stdout.includes('probe crashed: TypeError'));
    assert.ok(!run.stdout.includes('rules-card-ok'));
  }
});

test('a probe that cannot read the site throws, and the command line reports blank', async () => {
  await assert.rejects(probe(BASE, async () => { throw new TypeError('fetch failed'); }, NOW));
  const script = fileURLToPath(new URL('../scripts/rules_status_probe.mjs', import.meta.url));
  const run = spawnSync(process.execPath, [script, '--base', 'http://127.0.0.1:1'], {encoding: 'utf8', timeout: 60000});
  assert.notEqual(run.status, 0, 'only exit 0 is healthy');
  assert.ok(run.stdout.includes('rules-card-blank'), run.stdout);
  assert.notEqual(BLANK_EXIT, 0);
});
