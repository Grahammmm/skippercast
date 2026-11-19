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
import {feedBucket} from './fixtures/feed-bucket.mjs';
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
let briefModule;
async function loadBrief() {
  if (briefModule) return briefModule;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-part-')), 'brief.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {briefFrom, BriefLinks} from './web/brief/Brief.tsx';
    export {EvidenceSection} from './web/app/views/Reports.tsx';
    export {evidenceFrom} from './web/reports.ts';
    export {language, prepareCatalogue} from './web/i18n.ts';
    export {h} from 'preact'; export {render} from 'preact-render-to-string';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return (briefModule = await import(pathToFileURL(out).href));
}
const brief = (fn, feed, hour = null) => fn({info: INFO, feed, coast: null, profile: 'boat', hour}, NOW);
const pins = feed => stationPins({region: REGION, catalog, feed, now: NOW, at: NOW});
const viaJSON = value => JSON.parse(JSON.stringify(value));

test('the brief and station pins built from the brief part equal those built from the whole feed', async () => {
  const {briefFrom: fn} = await loadBrief();
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

// The old projection dropped the publisher's flag (leaving either silence or a misleading count).
test('charter outage reaches the Brief and Reports without a boat count; verified zero stays distinct', async () => {
  const {briefFrom, BriefLinks, evidenceFrom, EvidenceSection, h, render, language, prepareCatalogue} = await loadBrief();
  const fresh = {...everyKind, generated_at: NOW.toISOString(), reports: [], sources: {...everyKind.sources}};
  for (let day = 1; day <= 7; day++) fresh.sources[`catches-2026-10-0${day}`] = {kind: 'charter-reports', status: 'ok', data_retrieved_at: fresh.generated_at};
  const briefHTML = feed => render(h(BriefLinks, {brief: brief(briefFrom, feed)}));
  const evidence = feed => evidenceFrom(feed, INFO.id, 'lingcod', NOW.getTime());
  const reportsHTML = feed => render(h(EvidenceSection, {evidence: evidence(feed)}));
  const freshPart = viaJSON(dailyPartOf(fresh, 'brief'));
  assert.equal('charter_reports' in freshPart, false);
  assert.equal(evidence(fresh)?.reasonKind, 'none', 'seven checked pages and no reported trips');
  assert.match(reportsHTML(fresh), /0 boats/);
  assert.doesNotMatch(briefHTML(freshPart), /Not available|\d+ boats?/i, 'the Brief has no positive report line for an empty sample');

  const trip = {date: '2026-10-07', port: 'Monterey', boat: 'Fixture Tern', catches: [{species: 'lingcod', count: 1}]};
  assert.match(briefHTML(viaJSON(dailyPartOf({...fresh, reports: [trip]}, 'brief'))), /1 boat reported/);
  assert.equal(evidence({...fresh, reports: [trip]})?.boats, 1, 'the retained fixture would otherwise count');
  for (const [reports, last_source_day] of [[[], null], [[trip], '2026-10-07']]) {
    const feed = {...fresh, reports, charter_reports: {status: 'not_available', last_source_day, reason: 'source_stale', extra: 'fixture-only'}};
    const part = viaJSON(dailyPartOf(feed, 'brief'));
    assert.deepEqual(part.charter_reports, {status: 'not_available', last_source_day});
    for (const sibling of DAILY_PARTS.filter(p => p !== 'brief')) assert.equal('charter_reports' in dailyPartOf(feed, sibling), false);
    for (const html of [briefHTML(part), briefHTML(feed), reportsHTML(feed)]) {
      assert.match(html, /Not available\./);
      if (last_source_day) assert.match(html, /Oct 7, 2026/);
      else assert.match(html, /not updated recently/);
      assert.doesNotMatch(html, /\b\d+\s+boats?\b|Fixture Tern/);
    }
  }
  await prepareCatalogue('es');
  language.value = 'es';
  try {
    const feed = {...fresh, reports: [trip], charter_reports: {status: 'not_available', last_source_day: trip.date}};
    for (const html of [briefHTML(viaJSON(dailyPartOf(feed, 'brief'))), reportsHTML(feed)]) {
      assert.match(html, /No disponible\./);
      assert.doesNotMatch(html, /\b\d+\s+(?:boats?|barcos?)\b/);
    }
  } finally { language.value = 'en'; }
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
const FEED_ENV = {FEEDS: feedBucket()};   // published feeds come only from R2
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
    const c = ctx(), r = await worker.fetch(get(`/api/daily?region=morro-bay&part=${first}`), FEED_ENV, c);await c.settle();
    assert.equal(r.status, 200);assert.equal(r.headers.get('X-SC-Cache'), 'miss');assert.equal(state.entries.size, 4);
    for (const p of DAILY_PARTS) {
      const hit = await worker.fetch(get(`/api/daily?part=${p}&region=morro-bay&x=1`), FEED_ENV, ctx());
      assert.equal(hit.headers.get('X-SC-Cache'), 'hit', p);
      assert.deepEqual(await hit.json(), viaJSON(dailyPartOf(morro, p)), p);
    }
    assert.equal(state.reads, 1, 'one feed read answers every part');
  });
});

test('unknown part is 400, unknown region 404, and an invalid feed fails before any part is cached', async () => {
  await withEdge(morro, async state => {
    assert.equal((await worker.fetch(get('/api/daily?region=morro-bay&part=briefs'), FEED_ENV, ctx())).status, 400);
    assert.equal((await worker.fetch(get('/api/daily?region=nowhere&part=brief'), FEED_ENV, ctx())).status, 404);
    assert.equal(state.reads, 0);
  });
  await withEdge({...morro, catch_probability: 0.4}, async state => {
    for (let i = 0; i < 2; i++) assert.notEqual((await worker.fetch(get('/api/daily?region=morro-bay&part=brief'), FEED_ENV, ctx())).status, 200);
    assert.equal(state.reads, 2);assert.equal(state.entries.size, 0);
  });
});

test('the offline pack saves the brief part once, and server and pack list the same parts', () => {
  assert.deepEqual(PACK_PARTS, [...DAILY_PARTS]);
  const origin = 'https://skippercast.com', urls = packRequests({origin, region: globalThis.REGIONS['morro-bay']});
  assert.equal(urls.filter(u => u === `${origin}/api/daily?region=morro-bay&part=brief`).length, 1);
});
