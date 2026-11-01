// SC-LAUNCH-3: the brief's lead answers "can I fish tomorrow, and is it legal". With no time
// chosen in the dock, the verdict (the existing web/brief/verdict.ts engine, unchanged) is the one
// for tomorrow's brief, and the lead says whether the selected target is legal on that day from
// web/regs.ts regulationState over the reviewed registry. A time chosen in the dock still wins.
// The brief modules are bundled with esbuild and rendered to strings, as tests/test_brief_view.mjs.
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
const TZ = 'America/Los_Angeles';
const INFO = {id: 'monterey-point-sur', name: 'Monterey', center: [36.62, -121.9], timezone: TZ};
const HOUR = 3_600_000;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'brief-lead-')), 'lead.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/brief/Brief.tsx';
      export {briefVerdict, VERDICT_WORD} from './web/brief/verdict.ts';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {Brief} from './web/app/Desktop.tsx';
      export {SheetBrief} from './web/app/Mobile.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {regsData} from './web/regs.ts';
      export {hour, day, species, profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** A synthetic /api/forecast answer (values invented): wind rising by day so each day rates differently, runs issued 6 h before `now`. */
function forecastFeed(now, region = INFO.id) {
  const start = Date.parse('2026-09-29T07:00:00Z') / 1000, issued = now.getTime() / 1000 - 6 * 3600;
  const time = Array.from({length: 16 * 24}, (_, i) => start + i * 3600);
  const day = t => Math.floor((t - start) / 86400);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(t => typeof v === 'function' ? v(t) : v)]))}});
  const meta = {last_run_initialisation_time: issued, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: now.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [t => 4 + 3 * day(t), 'kn'], wind_gusts_10m: [t => 8 + 4 * day(t), 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [t => 2 + day(t), 'ft'], wave_period: [12, 's']}))}}};
}

const tomorrowOf = (now, tz) => new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(now.getTime() + 24 * HOUR));
const windowSpan = html => /<span class="app-verdict-window ui-mono" data-day="(\d{4}-\d{2}-\d{2})">([^<]*)<\/span>/.exec(html);

test('SC-LAUNCH-3: with no time chosen the lead answers for tomorrow, from the existing verdict engine', async () => {
  const m = await load();
  const now = new Date('2026-10-08T21:00:00Z'); // 2 pm PDT Thursday 8 October
  m.regionInfo.value = INFO; m.dailyFeed.value = montereyDaily; m.hour.value = null; m.day.value = null;
  m.regionalForecast.value = m.parseConditionsForecast(forecastFeed(now), INFO.id, INFO.center);
  try {
    const html = m.render(m.h(m.Brief, {now}));
    const span = windowSpan(html);
    assert.ok(span, 'the lead names the day it answers for');
    assert.equal(span[1], '2026-10-09');
    assert.equal(span[1], tomorrowOf(now, TZ));
    assert.match(span[2], /^tomorrow, \d+ am–noon$/);
    // The lead is the verdict engine's own answer for tomorrow's brief, not a second calculation.
    const brief = m.briefFrom({info: INFO, feed: montereyDaily, coast: null, profile: 'boat', hour: m.leadHour(null, null, now, TZ)}, now);
    assert.equal(brief.date, '2026-10-09');
    const v = m.briefVerdict(brief, m.regionalForecast.value, now, TZ);
    assert.notEqual(v.verdict, 'unknown');
    assert.match(html, new RegExp(`<span class="app-verdict-word">${m.VERDICT_WORD[v.verdict]}</span>`));
    assert.ok(html.includes(`<p class="app-verdict-limit">${v.limit}`), 'the limit shown is tomorrow\'s limit');
    const today = m.briefVerdict(m.briefFrom({info: INFO, feed: montereyDaily, coast: null, profile: 'boat', hour: null}, now), m.regionalForecast.value, now, TZ);
    assert.notEqual(today.limit, v.limit, 'the fixture rates today and tomorrow differently, so the day is observable');
    // A time chosen in the dock still wins: the lead follows it.
    m.hour.value = '2026-10-08T22:00Z';
    const chosen = windowSpan(m.render(m.h(m.Brief, {now})));
    assert.equal(chosen[1], '2026-10-08');
    assert.match(chosen[2], /^today/);
    m.hour.value = null; m.day.value = '2026-10-11';
    assert.equal(windowSpan(m.render(m.h(m.Brief, {now})))[1], '2026-10-11', 'a link\'s ?day= names the lead\'s day');
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.hour.value = null; m.day.value = null; }
});

test('SC-LAUNCH-3: the mobile sheet heads its lead with the lead\'s own day, at peek and full', async () => {
  const m = await load();
  const now = new Date('2026-10-08T21:00:00Z'); // 2 pm PDT Thursday 8 October
  m.regionInfo.value = INFO; m.dailyFeed.value = montereyDaily; m.hour.value = null; m.day.value = null;
  m.regionalForecast.value = m.parseConditionsForecast(forecastFeed(now), INFO.id, INFO.center);
  const eyebrows = html => [...html.matchAll(/<span class="ui-eyebrow">([^<]*)<\/span>/g)].map(x => [x[1], x.index]);
  try {
    for (const detent of ['peek', 'full']) {
      const html = m.render(m.h(m.SheetBrief, {now, detent}));
      const lead = html.indexOf('class="app-verdict"'), heads = eyebrows(html);
      assert.ok(lead > 0, `${detent}: the lead renders`);
      assert.match(windowSpan(html)[2], /^tomorrow, /, `${detent}: the lead answers for tomorrow`);
      const before = heads.filter(([, i]) => i < lead).map(([t]) => t);
      assert.deepEqual(before, ['Tomorrow'], `${detent}: the only heading above the lead names its day`);
      // The dock's day still heads the evidence, below the lead and before the tiles.
      const dock = heads.find(([t]) => t === 'Today · 2 pm');
      assert.ok(dock && dock[1] > lead && dock[1] < html.indexOf('class="ui-tile"'), `${detent}: the dock heading introduces the dock-day evidence`);
    }
    // An explicit hour today: one heading, the dock's, and the lead agrees with it.
    m.hour.value = '2026-10-08T22:00Z';
    for (const detent of ['peek', 'full']) {
      const html = m.render(m.h(m.SheetBrief, {now, detent}));
      const lead = html.indexOf('class="app-verdict"');
      assert.deepEqual(eyebrows(html).filter(([, i]) => i < lead).map(([t]) => t), ['Today · 3 pm'], `${detent}: the chosen hour heads the lead`);
      assert.match(windowSpan(html)[2], /^today/);
      assert.equal(eyebrows(html).filter(([t]) => t.startsWith('Today')).length, 1, `${detent}: no second dock heading`);
    }
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.hour.value = null; m.day.value = null; }
});

/** The frozen FE-61 registry with fresh synthetic source checks, as tests/test_regs_wrapper.mjs builds it. */
async function registry(now) {
  const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(now.getTime() - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: now.toISOString()};
  }
  return {region: fixture.region, data: d};
}

test('SC-LAUNCH-3: the lead says the selected target is closed on the day it answers for, from regulationState', async () => {
  const m = await load();
  // 9 am PDT 30 September: the registry's Chinook salmon window ends today, so tomorrow is closed.
  const now = new Date('2026-09-30T16:00:00Z');
  const {region: morro, data} = await registry(now);
  const info = {id: morro.id, name: morro.name, center: morro.map.center, timezone: morro.timezone, rules: morro};
  m.regionInfo.value = info; m.dailyFeed.value = {...montereyDaily, region_id: morro.id};
  m.regsData.value = {region: morro.id, data}; m.species.value = 'salmon'; m.profile.value = 'boat'; m.hour.value = null; m.day.value = null;
  try {
    const html = m.render(m.h(m.Brief, {now}));
    const rules = /<p class="app-verdict-rules" data-status="(\w+)">(.*?)<\/p>/.exec(html);
    assert.ok(rules, 'the lead carries the target\'s legality line');
    assert.equal(rules[1], 'closed');
    assert.match(rules[2], /Closed/);
    assert.match(rules[2], /Chinook salmon/);
    assert.match(rules[2], /tomorrow/);
    assert.ok(html.indexOf('app-verdict-rules') < html.indexOf('class="ui-tile"'), 'legality leads, before the evidence');
    // The same target today, chosen in the dock, is open: the line reads the lead's own day.
    m.hour.value = '2026-09-30T17:00Z';
    assert.match(m.render(m.h(m.Brief, {now})), /<p class="app-verdict-rules" data-status="open">/);
    // Before the registry loads it says to check the rules, never open.
    m.hour.value = null; m.regsData.value = null;
    assert.match(m.render(m.h(m.Brief, {now})), /<p class="app-verdict-rules" data-status="unknown">/);
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regsData.value = null; m.species.value = null; m.hour.value = null; }
});
