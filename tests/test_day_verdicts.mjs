// SC2252-06: each day chip says its day's verdict (web/app/day-verdicts.ts). The word is the brief's own
// currentBrief/currentVerdict answer at the dock's hour on that day, from the feeds already loaded, so every
// chip must read exactly what the brief reads once that day is chosen. Synthetic feeds only; fetch is trapped.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const TZ = 'America/Los_Angeles';
const ID = 'monterey-point-sur';
/** Thursday 2026-10-08, 5 am Pacific: the alert check (12:00Z) is fresh, the forecast runs five days (Thu–Mon). */
const NOW = new Date('2026-10-08T12:00:00Z');
const DAILY = JSON.parse(readFileSync(new URL('./fixtures/brief/monterey-daily.json', import.meta.url), 'utf8'));
const WORDS = {en: {comfortable: 'Comfortable', marginal: 'Marginal', rough: 'Rough', unknown: 'Unknown'}, es: {comfortable: 'Cómodo', marginal: 'Marginal', rough: 'Agitado', unknown: 'Desconocido'}};

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'day-verdicts-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {dayVerdicts, withVerdicts} from './web/app/day-verdicts.ts';
      export {TimeDock, dayOptions, dockState, selectDay, selectHour, localParts} from './web/app/TimeDock.tsx';
      export {HourEdge} from './web/app/Mobile.tsx';
      export {Verdict, currentBrief, currentVerdict, leadBrief, dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
      export {regionInfo} from './web/app/region-info.ts';
      export {dockTime, horizonDays} from './web/hour.ts';
      export {boatSaved} from './web/boat-entry.ts';
      export {savedLimits} from './web/limits.ts';
      export {BOAT_KEY} from './dist/boat-handling.js';
      export {language} from './web/i18n.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {admitBriefFixture} from './tests/helpers/settled-brief.ts';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k)}; };
let fetches = 0;
globalThis.fetch = async () => { fetches++; throw new Error('day verdicts must not read the network'); };

/** A synthetic forecast for `id`: one wind per local day from Thursday (5 kn calm, 16 kn marginal, 30 kn rough), `days` days long. */
function forecast(id, winds = [5, 16, 30, 5, 5], issued = NOW.getTime() / 1000 - 4 * 3600) {
  const start = Date.parse('2026-10-08T07:00:00Z') / 1000, time = Array.from({length: winds.length * 24}, (_, i) => start + i * 3600);
  const base = {wind_direction_10m: [300, '°'], wave_height: [2, 'ft'], wave_period: [10, 's'], wind_wave_height: [0.3, 'ft'], wind_wave_period: [4, 's'], swell_wave_height: [1.8, 'ft'],
    swell_wave_period: [10, 's'], swell_wave_direction: [300, '°'], secondary_swell_wave_height: [0.1, 'ft'], secondary_swell_wave_direction: [180, '°'], wind_speed_10m: [0, 'kn'], wind_gusts_10m: [0, 'kn']};
  const value = (k, t) => { const w = winds[Math.floor((t - start) / 86400)]; return k === 'wind_speed_10m' ? w : k === 'wind_gusts_10m' ? Math.round(w * 1.3) : base[k][0]; };
  const run = keys => ({issued, end: time.at(-1), data: {utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(k => [k, base[k][1]]))}, hourly: {time, ...Object.fromEntries(keys.map(k => [k, time.map(t => value(k, t))]))}}});
  return {region: id, retrieved: NOW.getTime(), point: {id, lat: 36.62, lon: -121.9}, models: {gfs_global: run(['wind_speed_10m', 'wind_gusts_10m', 'wind_direction_10m']), ecmwf_ifs025: run(['wind_speed_10m', 'wind_gusts_10m']),
    ncep_gfswave016: run(Object.keys(base).filter(k => !k.startsWith('wind_') || k.startsWith('wind_wave'))), ecmwf_wam: run(['wave_height'])}};
}
/** The daily feed with `alerts` in its advisory check, checked `checkedAt`. */
function daily({alerts = [], checkedAt = '2026-10-08T12:00:00Z', status = 'ok', region = ID} = {}) {
  const d = structuredClone(DAILY);
  d.region_id = region;
  Object.assign(d.sources['alerts-PZZ535'], {checked_at: checkedAt, status, data: {alerts}});
  return d;
}

/** A clean shell at NOW over the mixed week, Boat profile, no saved boat or limits, English. */
function setup(m, {profile = 'boat', feed = daily(), fc = forecast(ID)} = {}) {
  globalThis.location = {href: `${ORIGIN}?region=${ID}&profile=${profile}`};
  globalThis.history = {state: null, pushState: () => {}, replaceState: (_s, _t, url) => { globalThis.location.href = new URL(url, ORIGIN).href; }};
  globalThis.localStorage = memory();
  m.state.configureStore({v2: true, storage: memory()});
  m.state.syncFromURL(location.href);
  m.regionInfo.value = {id: ID, name: 'Monterey', center: [36.62, -121.9], timezone: TZ};
  m.dailyFeed.value = feed; m.regionalForecast.value = fc;
  m.savedLimits.value = {}; m.language.value = 'en';
  m.admitBriefFixture();
}

/** The verdict the brief shows once day `d` is chosen from the dock as it stands. */
function chosen(m, d) {
  m.selectDay(NOW, TZ, d, m.dockState(NOW, TZ));
  const html = m.render(m.h(m.Verdict, {now: NOW})), shown = /data-verdict="(\w+)"/.exec(html)?.[1] ?? 'unknown';
  const v = m.currentVerdict(m.leadBrief(NOW), NOW);
  assert.equal(shown, v?.verdict ?? 'unknown', 'the rendered brief and its verdict agree');
  return {verdict: shown, held: v?.held ?? null, limit: v?.limit ?? null};
}
/** Chip word for every option equals the brief's verdict once that day is chosen; returns the words by day. */
function parity(m, label) {
  const answers = m.dayVerdicts(NOW, TZ).value, words = {};
  for (const o of m.dayOptions(NOW, TZ, null)) {
    const a = answers.get(o.value), b = chosen(m, o.value);
    assert.ok(util.isDeepStrictEqual({verdict: a.verdict, held: a.held, limit: a.limit}, b), `${label} ${o.value}: chip ${JSON.stringify(a)} vs brief ${JSON.stringify(b)}`);
    assert.equal(m.withVerdicts([o], answers, 'en')[0].label, `${o.label} · ${WORDS.en[b.verdict]}`);
    words[o.value] = a.verdict;
  }
  return words;
}

test('mixed_week_every_chip_matches_chosen_brief: every chip, every profile, before and after scrubbing the hour', async () => {
  const m = await load();
  for (const profile of ['boat', 'shore', 'spear', 'kayak']) {
    setup(m, {profile});
    const words = parity(m, profile);
    // Scrub to 9 pm on Friday first, then choose each day again: the day-window answer does not move with the hour.
    m.selectHour(NOW, TZ, Date.parse('2026-10-10T04:00:00Z'));
    assert.ok(util.isDeepStrictEqual(parity(m, `${profile} scrubbed`), words), `${profile}: same words after scrubbing`);
    if (profile === 'boat') assert.ok(util.isDeepStrictEqual(Object.values(words), ['comfortable', 'marginal', 'rough', 'comfortable', 'comfortable', 'unknown', 'unknown', 'unknown']), JSON.stringify(words));
  }
  assert.equal(fetches, 0);
});

test('thin_alert_and_stale_evidence_never_improves: an alert day reads Rough, a missing alert check holds, a stale run reads Unknown', async () => {
  const m = await load();
  // A Small Craft Advisory over Sunday only: Sunday turns Rough, Monday stays Comfortable.
  setup(m, {feed: daily({alerts: [{id: 'a1', event: 'Small Craft Advisory', effective: '2026-10-11T07:00:00Z', ends: '2026-10-12T07:00:00Z'}]})});
  let words = parity(m, 'alert');
  assert.equal(words['2026-10-11'], 'rough');
  assert.equal(words['2026-10-12'], 'comfortable');
  // An alert running past the forecast's end: the engine's own precedence, which is never Comfortable.
  setup(m, {feed: daily({alerts: [{id: 'a2', event: 'Gale Warning', effective: '2026-10-12T07:00:00Z', ends: '2026-10-15T07:00:00Z'}]})});
  words = parity(m, 'alert past the forecast');
  for (const d of ['2026-10-12', '2026-10-13', '2026-10-14']) assert.notEqual(words[d], 'comfortable', d);
  // The alert check 6 h old, then failed: no day reads Comfortable and the held sentence travels with the word.
  for (const feed of [daily({checkedAt: '2026-10-08T06:00:00Z'}), daily({status: 'error'})]) {
    setup(m, {feed});
    words = parity(m, 'alert check missing');
    assert.ok(!Object.values(words).includes('comfortable'), JSON.stringify(words));
    assert.ok(m.dayVerdicts(NOW, TZ).value.get('2026-10-08').held, 'Today is held, not cleared');
  }
  // A forecast run 40 h old is not usable: every day reads Unknown, as the brief does.
  setup(m, {fc: forecast(ID, undefined, NOW.getTime() / 1000 - 40 * 3600)});
  words = parity(m, 'stale run');
  assert.ok(Object.values(words).every(w => w === 'unknown'), JSON.stringify(words));
  assert.equal(fetches, 0);
});

test('forecast_end_and_external_selected_day: days past the forecast, no feed, another region and an outside chip read Unknown', async () => {
  const m = await load();
  setup(m);
  const labels = m.withVerdicts(m.dayOptions(NOW, TZ, '2026-10-20'), m.dayVerdicts(NOW, TZ).value, 'en').map(o => o.label);
  assert.ok(util.isDeepStrictEqual(labels, ['Today · Comfortable', 'Fri · Marginal', 'Sat · Rough', 'Sun · Comfortable', 'Mon · Comfortable', 'Tue · Unknown', 'Wed · Unknown', 'Thu 15 · Unknown', '10-20 · Unknown']), JSON.stringify(labels));
  assert.equal(new Set(m.dayOptions(NOW, TZ, null).map(o => o.value)).size, 8, 'the repeated weekday keeps its own day key');
  for (const [name, patch] of [['no daily feed', {feed: null}], ['no forecast', {fc: null}], ['wrong-region feed', {feed: daily({region: 'elsewhere'})}], ['wrong-region forecast', {fc: forecast('elsewhere')}]]) {
    setup(m, patch);
    const words = parity(m, name);
    assert.ok(Object.values(words).every(w => w === 'unknown'), `${name}: ${JSON.stringify(words)}`);
  }
});

test('profile_boat_limits_and_sources_invalidate: each change re-reads the days and still matches the brief', async () => {
  const m = await load();
  setup(m);
  let evaluated = 0;
  const p = m.dayVerdicts(NOW, TZ, {onEvaluate: () => evaluated++});
  const words = () => Object.fromEntries([...p.value].map(([d, a]) => [d, a.verdict]));
  const check = (label, change) => {
    const before = evaluated;
    change();
    if (label.startsWith('fresh ') || label === 'region switch') m.admitBriefFixture(); // SC1722-02: a changed fixture source is admitted as a new terminal snapshot
    const now = words();
    assert.equal(evaluated, before + 8, `${label}: the eight days are read again`);
    assert.ok(util.isDeepStrictEqual(now, parity(m, label)), `${label}: equals the brief`);
    return now;
  };
  words();
  check('profile', () => { m.state.setParams({profile: 'spear'}); });
  check('profile back', () => { m.state.setParams({profile: 'boat'}); });
  // A 17 ft flat skiff saved in this browser re-rates the week; clearing it restores the reference boat's words.
  const reference = words();
  const skiff = check('boat saved', () => { localStorage.setItem(m.BOAT_KEY, JSON.stringify({schema_version: 1, boat: {name: '', loa_ft: 17, hull: 'flat', layout: 'skiff'}})); m.boatSaved.value++; });
  assert.ok(!util.isDeepStrictEqual(skiff, reference), 'the skiff reads a rougher week');
  assert.ok(util.isDeepStrictEqual(check('boat cleared', () => { localStorage.removeItem(m.BOAT_KEY); m.boatSaved.value++; }), reference));
  check('own limits', () => { m.savedLimits.value = {boat: {wind: 6, gust: 8, seas: 1, period: 12}}; });
  check('limits reset', () => { m.savedLimits.value = {}; });
  check('fresh forecast', () => { m.regionalForecast.value = forecast(ID, [30, 30, 5, 5, 5]); });
  check('fresh daily', () => { m.dailyFeed.value = daily({alerts: [{id: 'a3', event: 'Small Craft Advisory', effective: '2026-10-09T07:00:00Z', ends: '2026-10-10T07:00:00Z'}]}); });
  const gone = check('region switch', () => { m.state.setParams({region: 'elsewhere'}); m.regionInfo.value = {id: 'elsewhere', name: 'Elsewhere', center: [34, -119], timezone: TZ}; });
  assert.ok(Object.values(gone).every(w => w === 'unknown'), 'the old region\'s answers are withdrawn');
  check('language', () => { m.language.value = 'es'; });
  m.language.value = 'en';
});

test('scrub_and_play_reuse_day_cache_without_requests: hour and day changes never re-read the days', async () => {
  const m = await load();
  setup(m);
  fetches = 0;
  let evaluated = 0;
  const p = m.dayVerdicts(NOW, TZ, {onEvaluate: () => evaluated++});
  const first = p.value;
  assert.equal(evaluated, 8);
  for (const d of m.horizonDays(NOW, TZ)) for (const at of d.hours) { m.selectHour(NOW, TZ, at); assert.equal(p.value, first); }
  for (const o of m.dayOptions(NOW, TZ, null)) { m.selectDay(NOW, TZ, o.value, m.dockState(NOW, TZ)); assert.equal(p.value, first); }
  m.state.day.value = '2026-10-20'; m.state.hour.value = null; assert.equal(p.value, first);
  assert.equal(evaluated, 8, 'scrubbing, playing and choosing days reuse the answers');
  // A new clock is a new projection; the old one is left to the collector with its consumer.
  const later = m.dayVerdicts(new Date(NOW.getTime() + 3_600_000), TZ, {onEvaluate: () => evaluated++});
  void later.value;
  assert.equal(evaluated, 16);
  assert.equal(fetches, 0);
});

test('en_es_visible_and_accessible_both_surfaces: the word is the chip text on desktop and phone, in both languages', async () => {
  const m = await load();
  setup(m);
  const chips = html => [...html.match(/aria-label="(?:Day|Día)"[^>]*>(.*?)<\/div>/s)[1].matchAll(/<button\b([^>]*)>(?:<svg.*?<\/svg>)?([^<]+)<\/button>/gs)].map(b => ({text: b[2], pressed: /aria-pressed="true"/.test(b[1]), labelled: /aria-label=/.test(b[1])}));
  const values = m.dayOptions(NOW, TZ, null).map(o => o.value);
  const expected = lang => m.withVerdicts(m.dayOptions(NOW, TZ, null, lang), m.dayVerdicts(NOW, TZ).value, lang).map(o => o.label);
  for (const Surface of [m.TimeDock, m.HourEdge]) {
    const en = m.render(m.h(Surface, {now: NOW}));
    for (const lang of ['en', 'es', 'en']) {
      m.language.value = lang;
      const html = m.render(m.h(Surface, {now: NOW})), got = chips(html);
      assert.ok(util.isDeepStrictEqual(got.map(c => c.text), expected(lang)), `${lang}: ${JSON.stringify(got)}`);
      assert.ok(got[0].pressed && got.slice(1).every(c => !c.pressed), 'today stays pressed');
      assert.ok(got.every(c => !c.labelled), 'no aria-label masks the word');
      assert.ok(got.every((c, i) => c.text.endsWith(WORDS[lang][m.dayVerdicts(NOW, TZ).value.get(values[i]).verdict])));
      if (lang === 'en') assert.equal(html, en, 'English restores byte for byte');
    }
    assert.ok(util.isDeepStrictEqual(chips(en).slice(0, 3).map(c => c.text), ['Today · Comfortable', 'Fri · Marginal', 'Sat · Rough']));
  }
  m.language.value = 'es';
  assert.ok(util.isDeepStrictEqual(expected('es').slice(0, 3), ['Hoy · Cómodo', 'vie · Marginal', 'sáb · Agitado']), JSON.stringify(expected('es')));
  m.language.value = 'en';
  assert.ok(util.isDeepStrictEqual(m.withVerdicts(m.dayOptions(NOW, TZ, null), m.dayVerdicts(NOW, TZ).value, 'en').map(o => o.value), values), 'values are unchanged');
});

test('dst_and_clock_rollover: one answer per real local day, each read at an hour on that day', async () => {
  const m = await load();
  setup(m);
  for (const [iso, tz] of [['2026-10-30T20:00:00Z', TZ], ['2026-03-06T20:00:00Z', TZ], ['2026-10-30T20:00:00Z', 'Pacific/Honolulu'], ['2026-10-31T06:30:00Z', TZ]]) {
    const now = new Date(iso), days = m.horizonDays(now, tz), answers = m.dayVerdicts(now, tz).value;
    assert.ok(util.isDeepStrictEqual([...answers.keys()], days.map(d => d.day)), `${iso} ${tz}`);
    for (const d of days) {
      const a = answers.get(d.day);
      assert.equal(m.localParts(new Date(a.at), tz).day, d.day, `${d.day} is read on its own day`);
      assert.ok(d.hours.includes(Date.parse(a.at)), `${d.day} is read at one of its horizon hours`);
      assert.equal(a.at, m.state.hourParam(m.dockTime(d.day, null, now, tz, days).at / 1000));
    }
  }
});
