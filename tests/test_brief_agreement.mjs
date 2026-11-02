// Synthetic dual-model feeds; values invented. Goldens captured from unchanged main.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile, mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {boatVerdict, profileVerdict} from '../web/brief/verdict.ts';
export const TZ = 'America/Los_Angeles', NOW = new Date('2026-10-13T12:00:00Z');
const TIMES = Array.from({length: 4}, (_, i) => Date.parse('2026-10-13T15:00:00Z') / 1000 + i * 3600);
export const brief = (over = {}) => ({profile: 'boat', date: '2026-10-13', sunrise: '2026-10-13T14:10:00Z', sunset: null, alerts: [], missing: [], bar: null, ...over});
export function forecast({wind = 6, other = wind, sea = 2.5, wam = sea, age = 4, drop = [], partial = false} = {}) {
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.keys(values).map(k => [k, k.includes('period') ? 's' : k.includes('direction') ? '°' : k.includes('height') ? 'ft' : 'kn']))},
    hourly: {time: TIMES, ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, Array.isArray(v) ? v : TIMES.map(() => v)]))}});
  const run = data => ({issued: NOW.getTime() / 1000 - age * 3600, end: TIMES.at(-1), data: series(data)});
  const models = {gfs_global: run({wind_speed_10m: wind, wind_gusts_10m: wind + 3, wind_direction_10m: 315}),
    ncep_gfswave016: run({wave_height: sea, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4, swell_wave_height: 2, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200}),
    ecmwf_ifs025: run({wind_speed_10m: other, wind_gusts_10m: wind + 3}), ecmwf_wam: run({wave_height: partial ? [wam, wam, null, null] : wam})};
  for (const id of drop) delete models[id];
  return {region: 'synthetic', retrieved: NOW.getTime(), point: {id: 'synthetic', lat: 36, lon: -122}, models};
}
export const generated = i => forecast({wind: 3 + i % 25, other: 2 + i % 19, sea: 1 + i % 8, wam: 1 + i % 6, age: i % 3 ? 4 : 20, drop: i % 7 ? [] : ['ecmwf_ifs025']});
export const numbers = v => [v.verdict, v.limit, v.held, v.window, v.score];

const GOLDENS = [["marginal","Wind to 3 kt and seas to 1 ft through noon.","Held at Marginal: forecast detail is partial; the forecast run is 20 h old.","8 am\u2013noon",6.9],["comfortable","Wind to 4 kt and seas to 2 ft through noon.",null,"8 am\u2013noon",9.7],["comfortable","Wind to 5 kt and seas to 3 ft through noon.",null,"8 am\u2013noon",8.8],["marginal","Wind to 6 kt and seas to 4 ft through noon.","Held at Marginal: the forecast run is 20 h old.","8 am\u2013noon",8],["comfortable","Wind to 7 kt and seas to 5 ft through noon.",null,"8 am\u2013noon",7.1],["marginal","6 ft seas at 11 s at 8 am.",null,"8 am\u2013noon",6.3],["marginal","7 ft seas at 11 s at 8 am.",null,"8 am\u2013noon",5.4],["marginal","8 ft seas at 11 s at 8 am.",null,"8 am\u2013noon",4.6],["comfortable","Wind to 11 kt and seas to 3 ft through noon.",null,"8 am\u2013noon",7.3],["marginal","12 kt wind gusting 15 at 8 am.",null,"8 am\u2013noon",6.7],["marginal","13 kt wind gusting 16 at 8 am, with 5 ft seas.",null,"8 am\u2013noon",6],["marginal","14 kt wind gusting 17 at 8 am, with 6 ft seas.",null,"8 am\u2013noon",5.4],["marginal","15 kt wind gusting 18 at 8 am, with 5 ft seas at 11 s.",null,"8 am\u2013noon",5.4],["marginal","16 kt wind gusting 19 at 8 am, with 6 ft seas at 11 s.",null,"8 am\u2013noon",4.7],["marginal","17 kt wind gusting 20 at 8 am, with 7 ft seas at 11 s.",null,"8 am\u2013noon",4.1],["rough","8 ft seas at 11 s at 8 am, with 18 kt wind gusting 21.",null,"8 am\u2013noon",3.4],["marginal","19 kt wind gusting 22 at 8 am, with 5 ft seas.",null,"8 am\u2013noon",4.1],["rough","20 kt wind gusting 23 at 8 am, with 6 ft seas.",null,"8 am\u2013noon",3.5],["marginal","21 kt wind gusting 24 at 8 am.",null,"8 am\u2013noon",4.1],["rough","22 kt wind gusting 25 at 8 am.",null,"8 am\u2013noon",3.5],["rough","23 kt wind gusting 26 at 8 am, with 5 ft seas at 11 s.",null,"8 am\u2013noon",2.8],["rough","24 kt wind gusting 27 at 8 am, with 6 ft seas at 11 s.",null,"8 am\u2013noon",2.2],["rough","25 kt wind gusting 28 at 8 am, with 7 ft seas at 11 s.",null,"8 am\u2013noon",1.5],["rough","26 kt wind gusting 29 at 8 am, with 8 ft seas at 11 s.",null,"8 am\u2013noon",0.9],["rough","27 kt wind gusting 30 at 8 am.",null,"8 am\u2013noon",2.6],["marginal","Wind to 8 kt and seas to 2 ft through noon.","Held at Marginal: forecast detail is partial.","8 am\u2013noon",6.9],["marginal","Wind to 9 kt and seas to 3 ft through noon.","Held at Marginal: forecast detail is partial.","8 am\u2013noon",6.9],["marginal","Wind to 10 kt and seas to 4 ft through noon.","Held at Marginal: forecast detail is partial; the forecast run is 20 h old.","8 am\u2013noon",6.9],["marginal","Wind to 6 kt and seas to 5 ft through noon.","Held at Marginal: forecast detail is partial.","8 am\u2013noon",6.9],["marginal","6 ft seas at 11 s at 8 am.",null,"8 am\u2013noon",5.9],["marginal","7 ft seas at 11 s at 8 am, with 13 kt wind.",null,"8 am\u2013noon",5.1],["marginal","8 ft seas at 11 s at 8 am, with 14 kt wind.",null,"8 am\u2013noon",4.2],["marginal","15 kt wind at 8 am.",null,"8 am\u2013noon",6.5],["marginal","16 kt wind at 8 am.",null,"8 am\u2013noon",5.9],["marginal","17 kt wind at 8 am, with 5 ft seas.",null,"8 am\u2013noon",5.2],["marginal","6 ft seas at 8 am, with 13 kt wind gusting 16.",null,"8 am\u2013noon",5.6],["marginal","19 kt wind at 8 am, with 5 ft seas at 11 s.",null,"8 am\u2013noon",4.6],["marginal","20 kt wind at 8 am, with 6 ft seas at 11 s.",null,"8 am\u2013noon",4],["marginal","7 ft seas at 11 s at 8 am, with 16 kt wind gusting 19.",null,"8 am\u2013noon",4.4],["rough","8 ft seas at 11 s at 8 am, with 17 kt wind gusting 20.",null,"8 am\u2013noon",3.6],["marginal","18 kt wind gusting 21 at 8 am, with 5 ft seas.",null,"8 am\u2013noon",4.4],["rough","19 kt wind gusting 22 at 8 am, with 6 ft seas.",null,"8 am\u2013noon",3.8],["marginal","20 kt wind gusting 23 at 8 am.",null,"8 am\u2013noon",4.4],["rough","21 kt wind gusting 24 at 8 am.",null,"8 am\u2013noon",3.8],["rough","22 kt wind gusting 25 at 8 am, with 5 ft seas at 11 s.",null,"8 am\u2013noon",3.1],["rough","23 kt wind gusting 26 at 8 am, with 6 ft seas at 11 s.",null,"8 am\u2013noon",2.5],["rough","24 kt wind gusting 27 at 8 am, with 7 ft seas at 11 s.",null,"8 am\u2013noon",1.9],["rough","25 kt wind gusting 28 at 8 am, with 8 ft seas at 11 s.",null,"8 am\u2013noon",1.2],["rough","26 kt wind gusting 29 at 8 am.",null,"8 am\u2013noon",3],["rough","27 kt wind gusting 30 at 8 am.",null,"8 am\u2013noon",2.5]];

import {modelAgreement} from '../web/brief/agreement.ts';
const row = (ms, wind = 2, sea = 0.4) => ({ms, hour: {wind: 0, other_wind: wind, sea: 0, other_sea: sea}});
test('raw boundaries, missing and zero readings, empty rows and normalized worst-hour ties', () => {
  for (const [w, s, state] of [[4, 1, 'agree'], [4.1, 1, 'differ'], [4, 1.1, 'differ'], [0.1 + 0.2, 0, 'agree'], [4.01, 0, 'differ']]) assert.equal(modelAgreement([row(1, w, s)]).state, state);
  assert.equal(modelAgreement([]).state, 'none');
  for (const missing of [null, undefined, NaN, Infinity]) for (const field of ['wind', 'other_wind', 'sea', 'other_sea']) {
    const r = row(1); r.hour[field] = missing;
    assert.equal(modelAgreement([r]).state, 'one-model');
    assert.equal(modelAgreement([r, row(2)]).state, 'partial');
  }
  assert.equal(modelAgreement([row(1, 0, 0)]).state, 'agree');
  const rows = [row(1, 8, 0), row(2, 0, 2), row(3, 2, 0.4)];
  const a = modelAgreement(rows);
  assert.deepEqual(modelAgreement([rows[2], rows[1], rows[0], row(1, 99, 99)]), a);
  assert.equal(a.worst.ms, 1); assert.equal(a.differing, 2); assert.deepEqual(a.gap, {wind: 8, sea: 2});
});
test('calm but differing and rough but agreeing do not collapse into one output', () => {
  const f = forecast({other: [6, 1, 6, 6]});
  const a = boatVerdict(brief(), f, NOW, TZ), b = boatVerdict(brief(), forecast(), NOW, TZ);
  assert.equal(a.verdict, 'comfortable'); assert.equal(a.agreement.state, 'differ');
  assert.deepEqual(numbers(a), numbers(b));
  const rough = boatVerdict(brief(), forecast({wind: 30}), NOW, TZ);
  assert.equal(rough.verdict, 'rough'); assert.equal(rough.agreement.state, 'agree');
});
test('50 unchanged-main goldens preserve verdict, limit, held, window and score', () => {
  for (let i = 0; i < 50; i++) assert.deepEqual(numbers(boatVerdict(brief(), generated(i), NOW, TZ)), GOLDENS[i], `feed ${i}`);
});
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'agreement-')), 'view.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export * from './web/brief/Brief.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {profile, hour, day} from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  mod = await import(pathToFileURL(out).href); return mod;
}
test('Brief view templates, disclosure, missing/expired/stale suppression and region supersession', async () => {
  const m = await load();
  m.regionInfo.value = {id: 'synthetic', name: 'Synthetic', center: [36, -122], timezone: TZ};
  m.dailyFeed.value = {schema_version: 1, region_id: 'synthetic', sources: {}};
  m.hour.value = '2026-10-13T15:00Z'; m.profile.value = 'boat'; m.day.value = null;
  const render = f => { m.regionalForecast.value = f; return m.render(m.h(m.Verdict, {now: NOW})); };
  const text = html => /data-agreement="[^"]+">([^<]*)/.exec(html)?.[1] ?? '';
  const states = [];
  try {
    let html = render(forecast({other: 4, wam: 2.1})); states.push(html);
    assert.equal(text(html), 'Models agree through noon: wind within 2 kn, seas within 0.4 ft.');
    assert.ok(html.indexOf('app-verdict-limit') < html.indexOf('app-verdict-models'));
    html = render(forecast({other: [6, 1, 6, 6]})); states.push(html);
    assert.equal(text(html), 'Models differ at 9 am: wind 5 kn apart, seas 0 ft apart.');
    assert.match(html, /<details class="app-verdict-models-detail"><summary>Model readings<\/summary>NOAA 6 kn, ECMWF 1 kn; NOAA 2.5 ft, ECMWF 2.5 ft\.<\/details>/);
    assert.match(render(forecast({other: 1})), /\(4 of 4 hours\)/);
    html = render(forecast({partial: true})); states.push(html);
    assert.equal(text(html), 'Models compared for 2 of 4 hours; they agree on those.');
    html = render(forecast({drop: ['ecmwf_ifs025']})); states.push(html);
    assert.equal(text(html), 'One model only for this window.');
    for (const opts of [{}, {partial: true}, {other: 1}, {drop: ['ecmwf_ifs025']}]) {
      render(forecast({...opts, age: 4}));
      const old = forecast({...opts, age: 20}); html = render(old);
      assert.ok(!/data-agreement="(?:agree|partial)"/.test(html));
      if (opts.other) assert.match(html, /data-agreement="differ"/);
      assert.match(boatVerdict(brief(), old, NOW, TZ).held, /20 h old/);
    }
    const expired = forecast(); expired.models.ecmwf_ifs025.issued = NOW.getTime() / 1000 - 37 * 3600;
    assert.equal(text(render(expired)), 'One model only for this window.');
    assert.equal(text(render(null)), ''); assert.equal(boatVerdict(brief(), null, NOW, TZ).agreement, null);
    const blank = row(1); Object.keys(blank.hour).forEach(k => blank.hour[k] = null);
    assert.equal(modelAgreement([blank]).state, 'one-model');
    for (const p of ['shore', 'spear', 'kayak']) {
      m.profile.value = p; assert.equal(profileVerdict(brief({profile: p}), NOW, TZ).agreement, null);
      assert.equal(text(render(forecast())), '');
    }
    m.profile.value = 'boat'; render(forecast({other: 1}));
    m.regionInfo.value = {id: 'next-region', timezone: TZ, center: [35, -121]};
    const pending = [];
    const request = m.ensureRegionalForecast('next-region', null, () => new Promise(resolve => pending.push(resolve)), 'https://example.test/');
    assert.equal(text(m.render(m.h(m.Verdict, {now: NOW}))), '', 'previous region is cleared while loading');
    const newer = m.ensureRegionalForecast('newest-region', null, async () => ({ok: false}), 'https://example.test/');
    await newer; pending[0]({ok: false}); await request;
    assert.equal(text(m.render(m.h(m.Verdict, {now: NOW}))), '', 'superseded result cannot restore an old line');
    for (const html of states) {
      assert.doesNotMatch(text(html), /confiden|probab|likel|chance|odds|bite|\bgo\b|\b(high|low|moderate)\b|%/i);
      assert.doesNotMatch(html.replace(/<details class="app-verdict-models-detail">.*?<\/details>/g, ''), /GFS|ECMWF/);
    }
    const source = await readFile(new URL('../web/brief/agreement.ts', import.meta.url), 'utf8');
    assert.doesNotMatch(source, /confiden|probab|likel|chance|odds|bite|\b(high|low|moderate)\b|%/i);
  } finally { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.hour.value = null; m.profile.value = 'boat'; }
});

import {createHash} from 'node:crypto';
// Re-pinned for BF-stale-never-calmer: RUN_STALE_MS/RUN_MAX_MS read score.ts FORECAST_AGE (same 18 h/36 h) and a run over 1 h ahead is unusable.
test('verdict source outside agreement additions is unchanged', async () => {
  const source = await readFile(new URL('../web/brief/verdict.ts', import.meta.url), 'utf8');
  const stripped = source.replace(/, agreement: (?:staleAgreement \? null : agreement|null)/g, '').split('\n').filter(line => !/agreement|Agreement/.test(line)).join('\n');
  assert.equal(createHash('sha256').update(stripped).digest('hex'), '2ab09202dab98f44fa491c59aa4e476131bf415591a635f282147957f8cf477f');
});
