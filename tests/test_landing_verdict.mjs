// BF-landing-live: the landing leads with tomorrow's verdict, computed by the
// app's own loaders and brief code (web/landing/live-verdict.ts). Bundled with esbuild as
// tests/test_brief_lead.mjs does; the app's lead (Brief.tsx Verdict) is rendered from the same
// inputs, so the landing's word and sentence are compared with the app's, not with a copy.
// SC1952-04: rated for the boat and Boat limits saved on the device (the app's own reads of them), the
// reference boat when none is readable.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const HOUR = 3_600_000, PAGE = 'https://s.test/';
const REGION = await readFile(join(ROOT, 'dist/regions/morro-bay/region.json'), 'utf8');
const DAILY = {...montereyDaily, region_id: 'morro-bay'};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'landing-verdict-')), 'verdict.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/landing/live-verdict.ts';
      export {LiveVerdict} from './web/landing/Landing.tsx';
      export {Verdict, briefFrom, leadHour, dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
      export {coastReportFixture} from './e2e/coast-report-fixture.ts';
      export {briefVerdict} from './web/brief/verdict.ts';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {regionInfo, createRegionReader} from './web/app/App.tsx';
      export {hour, day, profile} from './web/state.ts';
      export {loadLimits, savedLimits} from './web/limits.ts';
      export {BOAT_MODEL_NOTE} from './web/boat-range.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

/** A synthetic /api/forecast answer for Morro Bay (values invented): wind rising by day, runs issued `ageH` hours before `now`. */
function forecastFeed(now, ageH = 6) {
  const start = Math.floor(now.getTime() / 86_400_000) * 86400 - 86400, issued = now.getTime() / 1000 - ageH * 3600;
  const time = Array.from({length: 9 * 24}, (_, i) => start + i * 3600), day = t => Math.floor((t - start) / 86400);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(t => typeof v === 'function' ? v(t) : v)]))}});
  const meta = {last_run_initialisation_time: issued, data_end_time: time.at(-1)};
  return {region_id: 'morro-bay', retrieved: now.getTime() - 20 * 60_000, requested_points: [['central', 35.36, -120.94], ['offshore-1-0', 35.3, -121.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [t => 4 + 3 * day(t), 'kn'], wind_gusts_10m: [t => 8 + 4 * day(t), 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [t => 2 + day(t), 'ft'], wave_period: [12, 's']}))}}};
}

/** A fetch answering region.json, the daily feed and the forecast; `missing` lists paths that answer 404. */
function feeds(now, {missing = [], ageH = 6, asked = []} = {}) {
  return async url => {
    const path = new URL(String(url), PAGE).pathname; asked.push(path);
    const body = missing.some(m => path.includes(m)) ? null : path.endsWith('/region.json') ? JSON.parse(REGION)
      : path === '/feeds/data/regions/morro-bay/latest.json' ? DAILY : path === '/api/forecast' ? forecastFeed(now, ageH) : null;
    return body ? {ok: true, status: 200, json: async () => body} : {ok: false, status: 404, json: async () => ({}), body: null};
  };
}

const BOAT_KEY = 'skippercast-boat-v1', LIMITS_KEY = 'skippercast-limits-v1';

/** A recording localStorage over `entries` (a Map, or 'throws' for a getter that throws); installed for `fn`, always removed. */
async function onDevice(entries, fn) {
  const reads = [], writes = [];
  const store = {getItem: k => { reads.push(k); if (entries === 'throws') throw new Error('storage denied'); return entries.get(k) ?? null; },
    setItem: (k, v) => writes.push(['set', k, v]), removeItem: k => writes.push(['remove', k]), clear: () => writes.push(['clear']), key: () => null, length: 0};
  const had = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {value: store, configurable: true, writable: true});
  try { return await fn({reads, writes}); } finally { if (had) Object.defineProperty(globalThis, 'localStorage', had); else delete globalThis.localStorage; }
}
const boatEnvelope = boat => JSON.stringify({schema_version: 1, boat});
const device = (boat, limits) => new Map([...(boat === undefined ? [] : [[BOAT_KEY, typeof boat === 'string' ? boat : boatEnvelope(boat)]]), ...(limits === undefined ? [] : [[LIMITS_KEY, typeof limits === 'string' ? limits : JSON.stringify(limits)]])]);

/** The app's lead (Brief.tsx Verdict) for the same feeds at `now`, as word and limit sentence; `entries` is the device storage the app reads its boat and limits from. */
async function appLead(m, now, opts, entries = new Map()) {
  const fetchFn = feeds(now, opts), info = await m.createRegionReader(fetchFn)('morro-bay');
  m.regionInfo.value = info; m.dailyFeed.value = opts?.missing?.includes('latest.json') ? null : DAILY; m.hour.value = null; m.day.value = null; m.profile.value = 'boat';
  const f = await fetchFn('/api/forecast');
  m.regionalForecast.value = f.ok ? m.parseConditionsForecast(await f.json(), 'morro-bay', info.center) : null;
  try {
    return await onDevice(entries, () => {
      m.loadLimits();
      const html = m.render(m.h(m.Verdict, {now}));
      return {word: /<span class="app-verdict-word">([^<]*)</.exec(html)?.[1] ?? null, limit: /<p class="app-verdict-limit">([^<]*)</.exec(html)?.[1] ?? null};
    });
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.savedLimits.value = {}; }
}

/** The landing's verdict on `entries`, with the keys it read and every write it made. */
const landingOn = (m, entries, now = NOW, opts) => onDevice(entries, async ({reads, writes}) => ({v: await m.loadLandingVerdict(feeds(now, opts), now, PAGE), reads, writes}));

const NOW = new Date('2026-10-08T21:00:00Z'); // 2 pm PDT; tomorrow is 9 October

test('the landing shows the app lead\'s own word and sentence for tomorrow, and links to that day', async () => {
  const m = await load();
  for (const now of [NOW, new Date(NOW.getTime() + 24 * HOUR), new Date(NOW.getTime() + 48 * HOUR)]) {
    const v = await m.loadLandingVerdict(feeds(now), now, PAGE), app = await appLead(m, now);
    assert.ok(v && app.word, 'both answer');
    assert.notEqual(v.verdict, 'unknown', 'the fixture forecast rates the day');
    assert.equal(v.word, app.word, `${now.toISOString()}: same word as the app lead`);
    assert.equal(v.sentence, app.limit, `${now.toISOString()}: same sentence`);
    assert.equal(v.day, 'Tomorrow');
    assert.equal(v.place, 'Morro Bay & Avila');
    assert.equal(v.href, `/map?region=morro-bay&profile=boat&day=${v.date}`);
  }
  const v = await m.loadLandingVerdict(feeds(NOW), NOW, PAGE);
  assert.equal(v.date, '2026-10-09', 'the link names tomorrow');
  const html = m.render(m.h(m.LiveVerdict, {v}));
  assert.match(html, /reference 23 ft boat: <strong class="landing-verdict-word" data-verdict="\w+">/);
  assert.ok(html.includes('href="/map?region=morro-bay&amp;profile=boat&amp;day=2026-10-09"'));
});

test('a forecast 404 reads Unknown with its sentence, never a calmer word; a stale run holds as the app does', async () => {
  const m = await load();
  const v = await m.loadLandingVerdict(feeds(NOW, {missing: ['/api/forecast']}), NOW, PAGE);
  assert.equal(v?.verdict, 'unknown');
  assert.equal(v.word, 'Unknown');
  assert.ok(v.sentence.length > 0, 'Unknown says why');
  assert.match(m.render(m.h(m.LiveVerdict, {v})), /data-verdict="unknown">Unknown</);
  for (const ageH of [19, 30, 40]) {
    const held = await m.loadLandingVerdict(feeds(NOW, {ageH}), NOW, PAGE), app = await appLead(m, NOW, {ageH});
    assert.notEqual(held.verdict, 'comfortable', `${ageH} h old run: never Comfortable`);
    assert.deepEqual([held.word, held.sentence], [app.word, app.limit], `${ageH} h old run: the app's held word`);
  }
});

test('no region or no feeds: no verdict at all', async () => {
  const m = await load();
  assert.equal(await m.loadLandingVerdict(feeds(NOW, {missing: ['/region.json']}), NOW, PAGE), null);
  assert.equal(await m.loadLandingVerdict(feeds(NOW, {missing: ['latest.json']}), NOW, PAGE), null, 'daily and conditions feeds unreadable');
  assert.equal(await m.loadLandingVerdict(async () => { throw new TypeError('offline'); }, NOW, PAGE), null, 'a network failure');
});

test('a bound coast report enters the brief as in the app; a failed one leaves it regional', async () => {
  const m = await load();
  // The bridge admits a report by the real clock, so this test runs at the real time.
  const now = new Date(), body = m.coastReportFixture(now.getTime()), asked = [], real = globalThis.fetch;
  globalThis.fetch = async url => { asked.push(String(url)); return new Response(JSON.stringify(body)); };
  try {
    const v = await m.loadLandingVerdict(feeds(now), now, PAGE);
    assert.deepEqual(asked, ['/api/coast/report'], 'the report is read once, through the coast bridge');
    const info = await m.createRegionReader(feeds(now))('morro-bay'), f = m.parseConditionsForecast(forecastFeed(now), 'morro-bay', info.center);
    const brief = m.briefFrom({info, feed: DAILY, forecast: f, coast: {report: body, areaId: 'central'}, profile: 'boat', hour: m.leadHour(null, null, now, info.timezone), limits: null}, now);
    assert.equal(brief.basis, 'coast-report', 'Morro Bay binds the report (estero-bay → central)');
    const want = m.briefVerdict(brief, f, now, info.timezone);
    assert.deepEqual([v.verdict, v.sentence], [want.verdict, `${want.limit}${want.held ? ` ${want.held}` : ''}`], 'the coast-report brief\'s verdict');
    globalThis.fetch = async () => new Response('{}', {status: 503});
    const regional = await m.loadLandingVerdict(feeds(now), now, PAGE), app = await appLead(m, now);
    assert.deepEqual([regional.word, regional.sentence], [app.word, app.limit], 'report unavailable: the regional brief, as the app');
  } finally { globalThis.fetch = real; }
});

const SKIFF = {name: 'Wren', loa_ft: 17, layout: 'skiff', hull: 'flat'};
const CABIN = {name: 'Big Cabin', loa_ft: 32, displacement_lb: 12000, layout: 'pilothouse', hull: 'deep-v'};
/** The boat the heading names for a visitor with nothing saved. */
const REF_NAME = 'reference 23 ft boat';

test('a saved 17 ft skiff and a 32 ft cabin boat rate the same forecast as the app does, named, with the model note outside the reference range', async () => {
  const m = await load();
  const words = new Set();
  for (const boat of [SKIFF, CABIN]) {
    const entries = device(boat);
    const {v, writes} = await landingOn(m, entries), app = await appLead(m, NOW, undefined, entries);
    assert.ok(v && app.word, 'both answer');
    assert.deepEqual([v.word, v.sentence], [app.word, app.limit], `${boat.name}: the app's word and sentence`);
    assert.equal(v.boatName, boat.name);
    assert.equal(v.boatNote, m.BOAT_MODEL_NOTE, `${boat.loa_ft} ft is outside the reference range`);
    assert.deepEqual(writes, []);
    const html = m.render(m.h(m.LiveVerdict, {v}));
    assert.ok(html.includes(`near Morro Bay &amp; Avila, ${boat.name}: <strong`), 'the boat is named in the heading');
    assert.ok(!html.includes(REF_NAME), 'no reference label beside a saved boat');
    assert.ok(html.includes(`<p class="landing-verdict-note">${m.BOAT_MODEL_NOTE}</p>`), 'the model note is its own paragraph');
    words.add(`${v.word}|${v.sentence}`);
  }
  const ref = await landingOn(m, new Map());
  words.add(`${ref.v.word}|${ref.v.sentence}`);
  assert.ok(words.size >= 2, 'the saved boats rate the same forecast differently from each other or from the reference');
});

test('boat names: a saved name, "your <n> ft boat" for an automatic or missing name, a name-only boat, and markup stays text', async () => {
  const m = await load();
  const named = async boat => (await landingOn(m, device(boat))).v;
  assert.equal((await named({name: 'Wren', loa_ft: 23})).boatName, 'Wren');
  assert.equal((await named({name: '19 ft boat', loa_ft: 19})).boatName, 'your 19 ft boat', 'the automatic name counts as none');
  assert.equal((await named({loa_ft: 26.04})).boatName, 'your 26 ft boat');
  assert.equal((await named({name: 'Just a name'})).boatName, 'Just a name', 'a name-only boat keeps its name, rated at the reference length');
  assert.equal((await named({name: 'Just a name'})).boatNote, null, 'no length, no note');
  assert.equal((await named({loa_ft: 23})).boatNote, null, 'inside the reference range: no note');
  const evil = await named({name: '<script>alert(1)</script> & Co', loa_ft: 23});
  const html = m.render(m.h(m.LiveVerdict, {v: evil}));
  assert.ok(!html.includes('<script>'), 'the name is escaped');
  assert.ok(html.includes('&lt;script>alert(1)&lt;/script> &amp; Co: <strong'));
});

test('no readable boat rates and names the reference boat: none, corrupt, wrong version, null/scalar/array/missing boat, unavailable or throwing storage', async () => {
  const m = await load();
  const plain = (await landingOn(m, new Map())).v, app = await appLead(m, NOW);
  assert.deepEqual([plain.word, plain.sentence], [app.word, app.limit], 'nothing saved: as the app');
  assert.equal(plain.boatName, REF_NAME);
  assert.equal(plain.boatNote, null);
  const bad = {
    'corrupt JSON': device('{not json'), 'wrong schema version': device(JSON.stringify({schema_version: 2, boat: SKIFF})),
    'null boat': device(null), 'scalar boat': device(5), 'string boat': device('"Wren"'), 'array boat': device([SKIFF]),
    'envelope without a boat': device(JSON.stringify({schema_version: 1})), 'bare scalar value': device('7'),
  };
  for (const [what, entries] of Object.entries(bad)) {
    const {v, writes} = await landingOn(m, entries);
    assert.deepEqual([v.word, v.sentence, v.boatName, v.boatNote ?? null], [plain.word, plain.sentence, REF_NAME, null], what);
    assert.deepEqual(writes, [], what);
  }
  const thrown = await landingOn(m, 'throws');
  assert.deepEqual([thrown.v.word, thrown.v.sentence, thrown.v.boatName], [plain.word, plain.sentence, REF_NAME], 'a throwing getter');
  const gone = await m.loadLandingVerdict(feeds(NOW), NOW, PAGE);   // no localStorage at all (this process has none)
  assert.deepEqual([gone.word, gone.boatName], [plain.word, REF_NAME], 'storage unavailable');
});

test('the Boat comfort limits saved on the device rate as /map does; a bad limits key keeps the boat and a bad boat keeps the limits', async () => {
  const m = await load();
  const cases = {
    strict: {boat: {wind: 4, gust: 6, seas: 1}}, loose: {boat: {wind: 20, gust: 25, seas: 8}}, clamped: {boat: {wind: 99, gust: 1, seas: 0}},
    partial: {boat: {wind: 6}}, 'string numbers': {boat: {wind: '7', gust: '9', seas: '2'}},
    malformed: '{oops', 'not an object': '[1,2]', 'default limits': {boat: {wind: 10, gust: 15, seas: 4}}, 'other profile only': {kayak: {wind: 4, gust: 6, seas: 1}, shore: {wind: 4, gust: 6, seas: 1}},
  };
  const seen = new Set();
  for (const boat of [undefined, SKIFF, CABIN]) for (const [what, limits] of Object.entries(cases)) {
    const entries = device(boat, limits);
    const {v, writes} = await landingOn(m, entries), app = await appLead(m, NOW, undefined, entries);
    assert.deepEqual([v.word, v.sentence], [app.word, app.limit], `${boat?.name ?? 'no boat'} with ${what} limits: same word and sentence as /map`);
    assert.equal(v.boatName, boat?.name ?? REF_NAME);
    assert.deepEqual(writes, []);
    seen.add(v.sentence);
  }
  assert.ok(seen.size > 1, 'the saved boats change what the landing says (limits shape the brief window, not the comfort word)');
  // Non-Boat limits never change the Boat answer.
  const base = (await landingOn(m, device(SKIFF))).v, other = (await landingOn(m, device(SKIFF, cases['other profile only']))).v;
  assert.deepEqual([other.word, other.sentence], [base.word, base.sentence], 'kayak and shore limits do not rate the Boat verdict');
  // Each key is read on its own.
  const strictOnly = (await landingOn(m, device(undefined, cases.strict))).v, both = (await landingOn(m, device(SKIFF, cases.strict))).v;
  assert.equal(both.boatName, 'Wren');
  assert.equal(strictOnly.boatName, REF_NAME, 'limits without a boat still apply to the reference boat');
  const badLimits = (await landingOn(m, device(SKIFF, '{oops'))).v;
  assert.deepEqual([badLimits.word, badLimits.sentence, badLimits.boatName], [base.word, base.sentence, 'Wren'], 'an unreadable limits key does not discard the boat');
  const badBoat = (await landingOn(m, device('{oops', cases.strict))).v, refStrict = (await landingOn(m, device(undefined, cases.strict))).v;
  assert.deepEqual([badBoat.word, badBoat.sentence, badBoat.boatName], [refStrict.word, refStrict.sentence, REF_NAME], 'an unreadable boat does not discard the limits');
});

test('the landing reads only the boat and Boat limits keys, writes nothing, and puts neither in a request', async () => {
  const m = await load();
  const entries = device(SKIFF, {boat: {wind: 5, gust: 8, seas: 1.5}});
  entries.set('skippercast-profile-v1', 'kayak'); entries.set('skippercast-cruise-v1', '22'); entries.set('skippercast-reach-v1', '{}'); entries.set('skippercast-layers-v1', '[]');
  const asked = [];
  const {v, reads, writes} = await onDevice(entries, async ({reads, writes}) => ({v: await m.loadLandingVerdict(async url => { asked.push(String(url)); return feeds(NOW)(url); }, NOW, PAGE), reads, writes}));
  assert.equal(v.boatName, 'Wren');
  assert.deepEqual([...new Set(reads)].sort(), [BOAT_KEY, LIMITS_KEY].sort(), 'only the boat and limits keys are read');
  assert.deepEqual(writes, [], 'no set, remove or clear');
  assert.ok(asked.length >= 3, 'the readings were asked for');
  for (const url of asked) assert.ok(!/Wren|wind=|gust|seas|loa/.test(decodeURIComponent(url)), `no boat detail in ${url}`);
});

test('missing forecast, stale run, missing feeds keep their behaviour with a saved boat; the name implies no fresh data', async () => {
  const m = await load();
  const entries = device(SKIFF, {boat: {wind: 6, gust: 9, seas: 2}});
  const unknown = (await landingOn(m, entries, NOW, {missing: ['/api/forecast']})).v;
  assert.equal(unknown.verdict, 'unknown');
  assert.equal(unknown.boatName, 'Wren');
  assert.match(m.render(m.h(m.LiveVerdict, {v: unknown})), /near Morro Bay &amp; Avila, Wren: <strong class="landing-verdict-word" data-verdict="unknown">Unknown</);
  for (const ageH of [19, 30, 40]) {
    const {v} = await landingOn(m, entries, NOW, {ageH}), app = await appLead(m, NOW, {ageH}, entries);
    assert.notEqual(v.verdict, 'comfortable', `${ageH} h old run: never Comfortable`);
    assert.deepEqual([v.word, v.sentence], [app.word, app.limit], `${ageH} h old run: the app's held word for the saved boat`);
  }
  for (const missing of [['/region.json'], ['latest.json']]) assert.equal((await landingOn(m, entries, NOW, {missing})).v, null, `${missing}: no verdict`);
});

test('the verdict modules are not in the landing\'s entry chunk: main.tsx imports them dynamically', async () => {
  const result = await build({entryPoints: [join(ROOT, 'web/landing/main.tsx')], bundle: true, splitting: true, format: 'esm', platform: 'browser', outdir: join(await mkdtemp(join(tmpdir(), 'landing-chunks-')), 'out'),
    write: false, metafile: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, external: ['*.css']});
  const outputs = Object.values(result.metafile.outputs), entry = outputs.find(o => o.entryPoint?.endsWith('web/landing/main.tsx'));
  const inputs = Object.keys(entry.inputs);
  for (const mod of ['web/landing/live-verdict.ts', 'web/brief/verdict.ts', 'web/brief/Brief.tsx', 'web/app/App.tsx']) assert.ok(!inputs.includes(mod), `${mod} is not in the entry chunk`);
  assert.ok(outputs.some(o => o !== entry && Object.keys(o.inputs).includes('web/landing/live-verdict.ts')), 'live-verdict.ts is its own lazy chunk');
});
