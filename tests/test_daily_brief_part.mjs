// SC2222-02: /api/daily?part=brief holds only what the brief (web/brief/Brief.tsx briefFrom) and the
// station pins (web/map/station-model.ts stationPins) read: buoys, tides, advisories, chlorophyll,
// landing reports and names. No model, grid, boundary or regulation data. The offline pack saves it.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';import {tmpdir} from 'node:os';
import {join} from 'node:path';import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {stationPins} from '../web/map/station-model.ts';
import {DAILY_PARTS as PACK_PARTS, packRequests} from '../dist/offline-core.js';
import catalog from '../catalog/station-locations.json' with {type: 'json'};
import monterey from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
Object.assign(globalThis, {DEPLOYMENT: read('../deployments/production.json'), SHELLS: {}, BUILD_ID: 'b1'});
const {default: worker} = await import('../server/index.ts');
const {DAILY_PARTS, dailyPartOf, validDailyFeed} = await import('../server/routes/public.ts');

const REGION = read('../regions/monterey-point-sur/region.json');
const NOW = new Date('2026-10-08T21:00:00Z'), INFO = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: 'America/Los_Angeles'};
const big = n => Array.from({length: n}, (_, i) => ({lat: 36 + i / 1e4, lon: -122, value: i}));
// The Monterey fixture plus one source of every other kind the collector writes, and the top-level fields.
const everyKind = {...structuredClone(monterey), health: {ok: 3, failed: 1}, landing_names: ['Monterey', 'Moss Landing'],
  reports: [...monterey.reports, {date: '2026-10-08', port: 'Moss Landing', boat: 'Fixture Heron'}],
  regulations: {reviewed_at: '2026-10-01', checks: big(50)}, catch_probability: null, bite_score: null};
Object.assign(everyKind.sources, {
  'buoy-46092': {...structuredClone(monterey.sources['buoy-46042']), id: 'buoy-46092', data: {...monterey.sources['buoy-46042'].data, station: '46092'}},
  chlorophyll: {id: 'chlorophyll', name: 'NOAA chlorophyll', kind: 'satellite', url: 'https://example.test/chl', status: 'ok', checked_at: '2026-10-08T12:00:00Z',
    data: {sample_at: '2026-10-07T12:00:00Z', samples: [{chlorophyll: 2.5, latitude: 36.62, longitude: -121.9}, {chlorophyll: 3.5, latitude: 36.63, longitude: -121.91}]}},
  'model-gfs': {id: 'model-gfs', kind: 'model', status: 'ok', data: {grid: big(2000)}},
  'sst-grid': {id: 'sst-grid', kind: 'grid', status: 'ok', data: {cells: big(2000)}},
  'sst-satellite': {id: 'sst-satellite', kind: 'satellite', status: 'ok', data: {cells: big(500)}},
  'mpa-boundaries': {id: 'mpa-boundaries', kind: 'boundaries', status: 'ok', data: {geojson: {features: big(2000)}}},
  'additional-closures': {id: 'additional-closures', kind: 'boundaries', status: 'ok', data: {features: big(200)}},
  regulations: {id: 'regulations', kind: 'advisory', status: 'ok', data: {alerts: []}},
});
let briefFrom;
async function loadBrief() {
  if (briefFrom) return briefFrom;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-part-')), 'brief.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `export {briefFrom} from './web/brief/Brief.tsx';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return (briefFrom = (await import(pathToFileURL(out).href)).briefFrom);
}
const brief = (fn, feed, hour = null) => fn({info: INFO, feed, coast: null, profile: 'boat', hour}, NOW);
const pins = feed => stationPins({region: REGION, catalog, feed, now: NOW, at: NOW});
const viaJSON = value => JSON.parse(JSON.stringify(value));

test('the brief and station pins built from the brief part equal those built from the whole feed', async () => {
  const fn = await loadBrief();
  for (const [name, feed] of [['monterey', monterey], ['every kind', everyKind]]) {
    const part = viaJSON(dailyPartOf(feed, 'brief'));
    for (const hour of [null, '2026-10-09T15:00:00.000Z']) {
      const whole = brief(fn, feed, hour);
      assert.ok(whole, `${name}: the whole feed builds a brief`);
      assert.deepEqual(brief(fn, part, hour), whole, `${name}: brief at ${hour}`);
    }
    assert.notDeepEqual(pins(feed), pins(null), `${name}: the pins read the feed`);
    assert.deepEqual(pins(part), pins(feed), `${name}: station pins`);
  }
  assert.equal(brief(fn, viaJSON(dailyPartOf(everyKind, 'brief'))).fleet?.count, 3, 'landing reports and names reach the brief');
});

test('the brief part holds no model, grid, boundary or regulation data, and is a small share of the feed', () => {
  const part = dailyPartOf(everyKind, 'brief');
  assert.deepEqual(Object.keys(part.sources), ['buoy-46042', 'tides', 'alerts-PZZ535', 'buoy-46092', 'chlorophyll'], 'feed order is kept');
  for (const [key, source] of Object.entries(part.sources)) {
    assert.ok(['observation', 'prediction', 'advisory'].includes(source.kind) || key === 'tides' || key === 'chlorophyll', key);
    assert.deepEqual(source, everyKind.sources[key], `${key} is kept whole`);
  }
  for (const gone of ['model-gfs', 'sst-grid', 'sst-satellite', 'mpa-boundaries', 'additional-closures', 'regulations']) assert.equal(gone in part.sources, false, gone);
  assert.equal('regulations' in part, false);
  assert.deepEqual([part.part, part.reports, part.landing_names, part.health], ['brief', everyKind.reports, everyKind.landing_names, everyKind.health]);
  assert.ok(JSON.stringify(part).length < 0.25 * JSON.stringify(everyKind).length, 'under 25 % of the whole feed');
  assert.ok(validDailyFeed(viaJSON(part), 'monterey-point-sur'), 'the part is itself a valid daily feed');
});

test('a feed without chlorophyll, tides or landing names gives a part without them that the client still accepts', () => {
  const feed = structuredClone(everyKind);
  delete feed.sources.chlorophyll; delete feed.sources.tides; delete feed.landing_names; delete feed.reports;
  const part = viaJSON(dailyPartOf(feed, 'brief'));
  assert.equal('chlorophyll' in part.sources, false);assert.equal('tides' in part.sources, false);assert.equal('landing_names' in part, false);
  assert.deepEqual(part.reports, []);
  // Brief.tsx readFeed's identity check.
  assert.ok(part.schema_version === 1 && part.region_id === 'monterey-point-sur' && !!part.sources && typeof part.sources === 'object');
});
const ctx = () => { const pending = []; return {waitUntil: p => pending.push(p), settle: () => Promise.all(pending)}; };
const get = path => new Request('https://skippercast.com' + path, {headers: {'cf-connecting-ip': '203.0.113.9'}});
async function withEdge(feed, fn) {
  const entries = new Map(), originalCaches = globalThis.caches, originalFetch = globalThis.fetch, state = {reads: 0, entries};
  globalThis.caches = {default: {async put(r, res) { entries.set(r.url, {status: res.status, headers: [...res.headers], body: await res.text()}); },
    async match(r) { const e = entries.get(r.url); return e && new Response(e.body, {status: e.status, headers: e.headers}); }}, async open() { throw Error('no'); }};
  globalThis.fetch = async () => { state.reads++; return Response.json(feed); };
  try { return await fn(state); } finally { globalThis.caches = originalCaches; globalThis.fetch = originalFetch; }
}
const morro = {...structuredClone(everyKind), region_id: 'morro-bay'};

test('?part=brief caches its three siblings, and a sibling caches the brief: one feed read answers all four', async () => {
  for (const first of ['brief', 'regulations']) await withEdge(morro, async state => {
    const c = ctx(), r = await worker.fetch(get(`/api/daily?region=morro-bay&part=${first}`), {}, c);await c.settle();
    assert.equal(r.status, 200);assert.equal(r.headers.get('X-SC-Cache'), 'miss');assert.equal(state.entries.size, 4);
    for (const p of DAILY_PARTS) {
      const hit = await worker.fetch(get(`/api/daily?part=${p}&region=morro-bay&x=1`), {}, ctx());
      assert.equal(hit.headers.get('X-SC-Cache'), 'hit', p);
      assert.deepEqual(await hit.json(), viaJSON(dailyPartOf(morro, p)), p);
    }
    assert.equal(state.reads, 1, 'one feed read answers every part');
  });
});

test('unknown part is 400, unknown region 404, and an invalid feed fails before any part is cached', async () => {
  await withEdge(morro, async state => {
    assert.equal((await worker.fetch(get('/api/daily?region=morro-bay&part=briefs'), {}, ctx())).status, 400);
    assert.equal((await worker.fetch(get('/api/daily?region=nowhere&part=brief'), {}, ctx())).status, 404);
    assert.equal(state.reads, 0);
  });
  await withEdge({...morro, catch_probability: 0.4}, async state => {
    for (let i = 0; i < 2; i++) assert.notEqual((await worker.fetch(get('/api/daily?region=morro-bay&part=brief'), {}, ctx())).status, 200);
    assert.equal(state.reads, 2);assert.equal(state.entries.size, 0);
  });
});

test('the offline pack saves the brief part once, and server and pack list the same parts', () => {
  assert.deepEqual(PACK_PARTS, [...DAILY_PARTS]);
  const origin = 'https://skippercast.com', urls = packRequests({origin, region: globalThis.REGIONS['morro-bay']});
  assert.equal(urls.filter(u => u === `${origin}/api/daily?region=morro-bay&part=brief`).length, 1);
});
