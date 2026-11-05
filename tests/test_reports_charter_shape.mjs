// RF1510-18: a charter response that is valid JSON but malformed (null or
// missing grounds members, reports or species) refuses the charter section as
// a whole (null) and never rejects loadReports or discards the other sections.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = Date.parse('2026-10-08T19:00:00Z');

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'reports-shape-')), 'reports.mjs');
  await build({entryPoints: [join(ROOT, 'web/reports.ts')], bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent'});
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const rep = (over = {}) => ({date: '2026-09-10', boat: 'Boat A', species: ['lingcod'], source_url: 'https://reports.example/a', ...over});
const ground = (over = {}) => ({label: 'Fixture Reef', reported_ground: 'Fixture Reef', precision: 'Named landmark vicinity', reports: [rep()], ...over});
const doc = (...grounds) => ({audit_date: '2026-09-21', grounds});
const freeze = (v) => { if (v && typeof v === 'object') { Object.values(v).forEach(freeze); Object.freeze(v); } return v; };

test('valid charter data keeps matching, order, cap, source links and the broad-name exclusion', async () => {
  const {chartersFrom, CHARTER_LIMIT} = await load();
  const grounds = [ground({label: 'B tie'}), ground({label: 'A tie'}), ground({label: 'Newest', reports: [rep({date: '2026-09-20', boat: 'Boat B', source_url: 'http://plain.example/x'})]}),
    ground({label: 'Halibut', reports: [rep({species: ['halibut']})]}), ground({label: 'Empty', reports: []}),
    ...Array.from({length: CHARTER_LIMIT}, (_, i) => ground({label: `Extra ${i}`, reports: [rep({date: '2026-08-01'})]}))];
  const input = freeze(doc(...grounds));
  const c = chartersFrom(input, 'reef');
  assert.deepEqual(c.rows.slice(0, 3).map(r => [r.label, r.trips, r.boats, r.latest, r.sources.length]), [['Newest', 1, 1, '2026-09-20', 0], ['A tie', 1, 1, '2026-09-10', 1], ['B tie', 1, 1, '2026-09-10', 1]]);
  assert.equal(c.rows.length, CHARTER_LIMIT);
  assert.equal(c.more, 3);
  assert.equal(c.audit, '2026-09-21');
  assert.equal(chartersFrom(doc(), 'reef').rows.length, 0, 'empty grounds is a successful empty section');
  assert.equal(chartersFrom(doc(ground({reports: [rep({species: []})]})), 'reef').rows.length, 0, 'empty species is legal and invents no trips');
});

test('broad regional names stay excluded before their unused reports are inspected', async () => {
  const {chartersFrom} = await load();
  const c = chartersFrom(doc(ground({label: 'Broad', precision: 'Broad regional name', reports: null}), ground()), 'reef');
  assert.deepEqual(c.rows.map(r => r.label), ['Fixture Reef']);
});

const MALFORMED = {
  'null ground': () => [null],
  'primitive ground': () => ['x'],
  'array ground': () => [[]],
  'missing precision': () => [ground({precision: undefined})],
  'missing reports': () => [ground({reports: undefined})],
  'null reports': () => [ground({reports: null})],
  'non-array reports': () => [ground({reports: {}})],
  'null report': () => [ground({reports: [null]})],
  'primitive report': () => [ground({reports: ['r']})],
  'array report': () => [ground({reports: [[]]})],
  'missing species': () => [ground({reports: [rep({species: undefined})]})],
  'null species': () => [ground({reports: [rep({species: null})]})],
  'non-array species': () => [ground({reports: [rep({species: 'lingcod'})]})],
  'mixed-type species': () => [ground({reports: [rep({species: ['lingcod', 3]})]})],
  'wrong-type date': () => [ground({reports: [rep({date: 20260910})]})],
  'missing boat': () => [ground({reports: [rep({boat: undefined})]})],
  'wrong-type label': () => [ground({label: 5})],
  'wrong-type reported_ground': () => [ground({reported_ground: null})],
  'valid sibling plus malformed ground': () => [ground(), ground({label: 'Bad', reports: [rep({species: null})]})],
};

test('a malformed ground or report refuses the whole charter section without throwing', async () => {
  const {chartersFrom} = await load();
  for (const [name, make] of Object.entries(MALFORMED)) {
    const input = freeze(doc(...make()));
    assert.equal(chartersFrom(input, 'reef'), null, name);
  }
  assert.equal(chartersFrom(null, 'reef'), null);
  assert.equal(chartersFrom({audit_date: 5, grounds: []}, 'reef'), null);
  assert.equal(chartersFrom({audit_date: '2026-09-21'}, 'reef'), null);
  assert.equal(chartersFrom({audit_date: '2026-09-21', grounds: {}}, 'reef'), null);
});

const dailyFeed = () => ({schema_version: 1, region_id: 'morro-bay', generated_at: new Date(NOW - 3_600_000).toISOString(), health: {status: 'ok'}, catch_probability: null, bite_score: null, sources: {},
  reports: [{date: '2026-10-07', boat: 'Fixture Boat A', port: 'Morro Bay', source_url: 'https://reports.example/a', catches: [{species: 'lingcod', label: 'Lingcod', count: 6}]}]});

async function loadWith(charterBody, charterStatus = 200) {
  const {loadReports} = await load();
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => { throw new Error(`unexpected global network: ${url}`); };
  try {
    const fetchFn = async (url) => {
      const u = String(url);
      if (u.includes('/feeds/data/regions/morro-bay/')) return new Response(JSON.stringify(dailyFeed()));
      if (u === 'charters.json') return new Response(charterBody, {status: charterStatus});
      return new Response('no', {status: 503});
    };
    return await loadReports({region: 'morro-bay', species: 'reef', charters: 'charters.json', now: NOW}, fetchFn);
  } finally { globalThis.fetch = original; }
}

test('loadReports: every malformed charter case resolves with charters null and the other sections intact', async () => {
  const control = await loadWith('null');
  assert.equal(control.charters, null);
  assert.equal(control.evidence.trips, 1);
  assert.equal(control.evidence.rows.length, 1);
  for (const [name, make] of Object.entries(MALFORMED)) {
    const data = await loadWith(JSON.stringify(doc(...make())));
    assert.equal(data.charters, null, name);
    assert.ok(util.isDeepStrictEqual(data.evidence, control.evidence), `${name}: evidence unchanged`);
    assert.ok(util.isDeepStrictEqual(data.discussions, control.discussions), `${name}: discussions unchanged`);
    assert.ok(util.isDeepStrictEqual(data.watch, control.watch), `${name}: watch unchanged`);
  }
});

test('loadReports: valid charters still resolve; non-OK, invalid JSON keep their own null section', async () => {
  const ok = await loadWith(JSON.stringify(doc(ground())));
  assert.equal(ok.charters.rows.length, 1);
  assert.equal(ok.evidence.trips, 1);
  for (const [body, status] of [['no', 503], ['{not json', 200]]) {
    const data = await loadWith(body, status);
    assert.equal(data.charters, null);
    assert.equal(data.evidence.trips, 1);
  }
});
