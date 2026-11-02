// BF-model-disagreement-plain: when NOAA and ECMWF are far apart in a day's
// morning window, the Conditions view says so in one sentence (web/model-disagreement.ts).
// Synthetic feeds, values invented.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {dayWord, disagreements, sentence, THRESHOLDS} from '../web/model-disagreement.ts';
import {VERDICT_WORD} from '../web/brief/verdict.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const TZ = 'America/Los_Angeles';
const NOW = new Date('2026-10-13T12:00:00Z'); // Tuesday 5 am PDT
const HOUR = 3600;
/** Epoch seconds of local hour `h` (PDT, UTC-7) on `date`. */
const pdt = (date, h) => Date.parse(`${date}T${String(h + 7).padStart(2, '0')}:00:00Z`) / 1000;

/** A parsed ConditionsForecast: both models read 10 kt and 3 ft unless `noaa(epoch)` / `ecmwf(epoch)` override {wind, sea}; `stale` ages those runs past 36 h. */
function forecast({now = NOW, start = '2026-10-13T07:00:00Z', length = 120, noaa = () => ({}), ecmwf = () => ({}), stale = []} = {}) {
  const times = Array.from({length}, (_, i) => Date.parse(start) / 1000 + i * HOUR);
  const series = cols => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(cols.map(([k, unit]) => [k, unit]))},
    hourly: {time: times, ...Object.fromEntries(cols.map(([k, , f]) => [k, times.map(f)]))}});
  const run = (id, cols) => ({id, issued: now.getTime() / 1000 - (stale.includes(id) ? 40 : 4) * HOUR, end: times.at(-1), data: series(cols)});
  const n = t => ({wind: 10, sea: 3, ...noaa(t)}), e = t => ({wind: 10, sea: 3, ...ecmwf(t)});
  const models = {
    gfs_global: run('gfs_global', [['wind_speed_10m', 'kn', t => n(t).wind], ['wind_gusts_10m', 'kn', t => n(t).wind + 3], ['wind_direction_10m', '°', () => 300]]),
    ncep_gfswave016: run('ncep_gfswave016', [['wave_height', 'ft', t => n(t).sea], ['wave_period', 's', () => 10]]),
    ecmwf_ifs025: run('ecmwf_ifs025', [['wind_speed_10m', 'kn', t => e(t).wind], ['wind_gusts_10m', 'kn', t => e(t).wind + 3]]),
    ecmwf_wam: run('ecmwf_wam', [['wave_height', 'ft', t => e(t).sea]]),
  };
  return {region: 'morro-bay', retrieved: now.getTime(), point: {id: 'morro-bay', lat: 35.37, lon: -120.9}, models};
}
/** Overrides at the listed epochs only. */
const at = map => t => map[t] ?? {};
const on = (date, hours, v) => Object.fromEntries(hours.map(h => [pdt(date, h), typeof v === 'function' ? v(h) : v]));

test('wind 8 vs 17 kt for three morning hours two days out: one item, the weekday, the largest gap\'s values', () => {
  const f = forecast({noaa: at(on('2026-10-15', [7, 8, 9], h => ({wind: {7: 9, 8: 8, 9: 10}[h]}))), ecmwf: at(on('2026-10-15', [7, 8, 9], h => ({wind: {7: 16, 8: 17, 9: 16}[h]})))});
  const items = disagreements(f, NOW, TZ);
  assert.deepEqual(items, [{date: '2026-10-15', quantity: 'wind', noaa: 8, ecmwf: 17, hours: 3}]);
  assert.equal(sentence(items[0], NOW, TZ), 'Models disagree about Thursday morning: wind 8 kt (NOAA) vs 17 kt (ECMWF). The score uses the rougher.');
  const tie = forecast({noaa: at(on('2026-10-14', [7, 9], h => ({wind: h === 7 ? 4 : 20}))), ecmwf: at(on('2026-10-14', [7, 9], h => ({wind: h === 7 ? 14 : 10})))});
  assert.deepEqual(disagreements(tie, NOW, TZ).map(d => [d.noaa, d.ecmwf]), [[4, 14]], 'equal gaps: the earliest hour');
});

test('thresholds: 6 kt for 2 hours counts, 5.9 kt does not, one hour does not, 2.0 ft seas count', () => {
  assert.deepEqual(THRESHOLDS, {windKt: 6, seaFt: 2, hours: 2});
  assert.ok(Object.isFrozen(THRESHOLDS));
  const wind = (gap, hours) => disagreements(forecast({ecmwf: at(on('2026-10-13', hours, {wind: 10 + gap}))}), NOW, TZ);
  assert.equal(wind(6, [8, 9]).length, 1);
  assert.equal(wind(5.9, [8, 9]).length, 0);
  assert.equal(wind(6, [8]).length, 0);
  const seas = (a, b) => disagreements(forecast({noaa: at(on('2026-10-13', [8, 10], {sea: a})), ecmwf: at(on('2026-10-13', [8, 10], {sea: b}))}), NOW, TZ);
  assert.deepEqual(seas(3, 5), [{date: '2026-10-13', quantity: 'seas', noaa: 3, ecmwf: 5, hours: 2}]);
  assert.equal(seas(3.3, 1.3).length, 1, 'a 2.0 ft gap that floating point reads as 1.9999… still counts');
  assert.equal(seas(3, 4.9).length, 0);
  assert.equal(sentence(seas(3, 5)[0], NOW, TZ), 'Models disagree about today morning: seas 3 ft (NOAA) vs 5 ft (ECMWF). The score uses the rougher.');
});

test('only 6 am to noon counts, in local hours across a daylight-saving change', () => {
  const wind = (date, hours) => disagreements(forecast({ecmwf: at(on(date, hours, {wind: 20}))}), NOW, TZ);
  assert.equal(wind('2026-10-14', [12, 13, 14]).length, 0, 'afternoon');
  assert.equal(wind('2026-10-14', [3, 4, 5]).length, 0, 'before 6 am');
  assert.equal(wind('2026-10-14', [5, 6]).length, 0, '5 am is outside');
  assert.equal(wind('2026-10-14', [11, 12]).length, 0, 'noon is outside');
  assert.equal(wind('2026-10-14', [6, 11]).length, 1);
  // 2026-11-01: clocks fall back at 2 am, so 6 am PST is 14:00Z (13:00Z would be 6 am under PDT).
  const now = new Date('2026-10-31T19:00:00Z'), dst = hoursZ => disagreements(forecast({now, start: '2026-10-31T07:00:00Z', length: 72,
    ecmwf: at(Object.fromEntries(hoursZ.map(h => [Date.parse(`2026-11-01T${h}:00:00Z`) / 1000, {wind: 20}])))}), now, TZ);
  assert.deepEqual(dst(['13', '14']), [], '5 am and 6 am PST: one hour in the window');
  assert.deepEqual(dst(['14', '15']).map(d => d.date), ['2026-11-01']);
  assert.deepEqual(dst(['19', '20']), [], '11 am and noon PST');
  assert.match(sentence(dst(['14', '15'])[0], now, TZ), /^Models disagree about tomorrow morning: wind 10 kt \(NOAA\) vs 20 kt \(ECMWF\)\./);
});

test('wind and seas both apart on one day: one item, the larger gap relative to its threshold', () => {
  const both = (windB, seaB) => disagreements(forecast({ecmwf: at(on('2026-10-14', [7, 8], {wind: windB, sea: seaB}))}), NOW, TZ);
  assert.deepEqual(both(17, 6).map(d => [d.quantity, d.noaa, d.ecmwf]), [['seas', 3, 6]], 'seas 3 ft / 2 beats wind 7 kt / 6');
  assert.deepEqual(both(22, 5).map(d => [d.quantity, d.noaa, d.ecmwf]), [['wind', 10, 22]], 'wind 12 kt / 6 beats seas 2 ft / 2');
});

test('a stale ECMWF run gives no item on any day and no sentence of agreement', () => {
  const apart = on('2026-10-13', [7, 8, 9], {wind: 30, sea: 9});
  for (const stale of [['ecmwf_ifs025', 'ecmwf_wam'], ['ecmwf_ifs025'], ['gfs_global', 'ncep_gfswave016']]) {
    const f = forecast({ecmwf: at(apart), stale: [...stale]});
    const items = disagreements(f, NOW, TZ);
    if (stale.length === 2) assert.deepEqual(items, [], stale.join());
    else assert.deepEqual(items.map(d => d.quantity), ['seas'], 'the wave runs still compare');
    assert.ok(items.every(d => !/agree\b|same/i.test(sentence(d, NOW, TZ).replace('disagree', ''))));
  }
});

test('non-finite or string samples are skipped hours, not zeros', () => {
  const bad = [NaN, 'x', Infinity, null];
  for (const v of bad) {
    const f = forecast({noaa: at(on('2026-10-13', [7, 8], {wind: 9})), ecmwf: at(on('2026-10-13', [7, 8], {wind: v}))});
    assert.deepEqual(disagreements(f, NOW, TZ), [], String(v));
  }
  const f = forecast({ecmwf: at({...on('2026-10-13', [7, 8], {wind: 20}), ...on('2026-10-13', [9], {wind: NaN})})});
  assert.deepEqual(disagreements(f, NOW, TZ).map(d => d.hours), [2]);
});

test('three days by default; today, tomorrow, then the weekday', () => {
  const dates = ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16'];
  const f = forecast({ecmwf: at(Object.assign({}, ...dates.map(d => on(d, [7, 8], {wind: 20}))))});
  const items = disagreements(f, NOW, TZ);
  assert.deepEqual(items.map(d => d.date), dates.slice(0, 3));
  assert.deepEqual(items.map(d => sentence(d, NOW, TZ).split(' morning')[0]), ['Models disagree about today', 'Models disagree about tomorrow', 'Models disagree about Thursday']);
  assert.equal(disagreements(f, NOW, TZ, 4).length, 4);
  for (const d of items) assert.doesNotMatch(sentence(d, NOW, TZ), new RegExp(`\\b(?:safe|calm|${Object.values(VERDICT_WORD).join('|')})\\b`, 'i'));
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'disagree-')), 'disagree.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {leadDayText, regionalForecast} from './web/brief/Brief.tsx';
      export {Conditions} from './web/app/views/Conditions.tsx';
      export {region} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

test('dayWord follows the brief\'s leadDayText: today and tomorrow match, later days name the same weekday', async () => {
  const {leadDayText} = await load();
  const now = new Date('2026-10-14T06:30:00Z'); // 11:30 pm PDT on the 13th
  for (const date of ['2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-19']) {
    const lead = leadDayText(date, now, TZ), word = dayWord(date, now, TZ);
    if (['today', 'tomorrow'].includes(lead)) assert.equal(word, lead, date);
    else assert.equal(word.slice(0, 3), lead.slice(0, 3), date);
  }
  assert.deepEqual(['2026-10-13', '2026-10-14'].map(d => dayWord(d, now, TZ)), ['today', 'tomorrow']);
});

test('the Conditions view lists one line per item under its heading, and nothing when the models agree', async () => {
  const {Conditions, regionalForecast, region, render, h} = await load();
  region.value = 'morro-bay';
  regionalForecast.value = forecast({ecmwf: at(on('2026-10-14', [7, 8], {wind: 20}))});
  const html = render(h(Conditions, {now: NOW}));
  assert.match(html, /<\/header><link rel="stylesheet" href="[^"]*model-disagreement\.css[^"]*"\/?><ul class="app-conditions-disagree" aria-label="Model disagreement"><li>Models disagree about tomorrow morning: wind 10 kt \(NOAA\) vs 20 kt \(ECMWF\)\. The score uses the rougher\.<\/li><\/ul>/);
  regionalForecast.value = forecast();
  assert.doesNotMatch(render(h(Conditions, {now: NOW})), /app-conditions-disagree|model-disagreement|disagree/);
  regionalForecast.value = forecast({ecmwf: at(on('2026-10-14', [7, 8], {wind: 20})), stale: ['ecmwf_ifs025', 'ecmwf_wam']});
  assert.doesNotMatch(render(h(Conditions, {now: NOW})), /disagree|agree/i);
  region.value = null; regionalForecast.value = null;
});
