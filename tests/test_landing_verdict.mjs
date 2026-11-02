// BF-landing-live: the landing leads with tomorrow's verdict for the reference boat, computed by the
// app's own loaders and brief code (web/landing/live-verdict.ts). Bundled with esbuild as
// tests/test_brief_lead.mjs does; the app's lead (Brief.tsx Verdict) is rendered from the same
// inputs, so the landing's word and sentence are compared with the app's, not with a copy.
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

/** The app's lead (Brief.tsx Verdict) for the same feeds at `now`, as word and limit sentence. */
async function appLead(m, now, opts) {
  const fetchFn = feeds(now, opts), info = await m.createRegionReader(fetchFn)('morro-bay');
  m.regionInfo.value = info; m.dailyFeed.value = opts?.missing?.includes('latest.json') ? null : DAILY; m.hour.value = null; m.day.value = null; m.profile.value = 'boat';
  const f = await fetchFn('/api/forecast');
  m.regionalForecast.value = f.ok ? m.parseConditionsForecast(await f.json(), 'morro-bay', info.center) : null;
  try {
    const html = m.render(m.h(m.Verdict, {now}));
    return {word: /<span class="app-verdict-word">([^<]*)</.exec(html)?.[1] ?? null, limit: /<p class="app-verdict-limit">([^<]*)</.exec(html)?.[1] ?? null};
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; }
}

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

test('a saved profile and limits are ignored and storage is never written', async () => {
  const m = await load();
  const plain = await m.loadLandingVerdict(feeds(NOW), NOW, PAGE);
  const store = new Map([['skippercast-profile-v1', 'kayak'], ['skippercast-limits-v1', JSON.stringify({boat: {wind_knots: 1, gust_knots: 2, sea_feet: 0.5}})]]), writes = [];
  globalThis.localStorage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => writes.push([k, v]), removeItem: k => writes.push([k]), clear: () => writes.push(['clear']), key: () => null, length: store.size};
  try {
    const v = await m.loadLandingVerdict(feeds(NOW), NOW, PAGE);
    assert.deepEqual([v.word, v.sentence, v.href], [plain.word, plain.sentence, plain.href], 'the reference boat, not the saved limits');
    assert.match(m.render(m.h(m.LiveVerdict, {v})), /reference 23 ft boat/);
    assert.deepEqual(writes, [], 'no storage write');
  } finally { delete globalThis.localStorage; }
});

test('the verdict modules are not in the landing\'s entry chunk: main.tsx imports them dynamically', async () => {
  const result = await build({entryPoints: [join(ROOT, 'web/landing/main.tsx')], bundle: true, splitting: true, format: 'esm', platform: 'browser', outdir: join(await mkdtemp(join(tmpdir(), 'landing-chunks-')), 'out'),
    write: false, metafile: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, external: ['*.css']});
  const outputs = Object.values(result.metafile.outputs), entry = outputs.find(o => o.entryPoint?.endsWith('web/landing/main.tsx'));
  const inputs = Object.keys(entry.inputs);
  for (const mod of ['web/landing/live-verdict.ts', 'web/brief/verdict.ts', 'web/brief/Brief.tsx', 'web/app/App.tsx']) assert.ok(!inputs.includes(mod), `${mod} is not in the entry chunk`);
  assert.ok(outputs.some(o => o !== entry && Object.keys(o.inputs).includes('web/landing/live-verdict.ts')), 'live-verdict.ts is its own lazy chunk');
});
