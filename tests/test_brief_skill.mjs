// SCFEAT-SKILL-1: measured forecast skill beside the brief's model-disagreement line. Synthetic scorecards only.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {readFile} from 'node:fs/promises';
import {skillLead, skillSummary, skillLine} from '../web/brief/skill.ts';

const NOW = Date.parse('2026-11-05T12:00:00Z');
const row = (over = {}) => ({port: 'morro-bay', station: '46215', variable: 'wind_speed_10m', lead_hours: 24, window_days: 30, n: 50, within: 41, enough: true, tolerance: 't', ...over});
const file = (scores, over = {}) => ({schema_version: 1, generated_at: '2026-11-04T03:00:00Z', minimum: {valid_times: 30}, ports: [{id: 'morro-bay', name: 'Morro Bay'}], scores, ...over});

test('a measured figure carries its sample, window, buoy and publish date', () => {
  const s = skillSummary(file([row(), row({variable: 'wave_height', n: 40, within: 30})]), 'morro-bay', NOW);
  assert.equal(s.state, 'known');
  assert.deepEqual(s.parts.map(p => [p.variable, p.pct, p.within, p.n, p.station, p.window]), [['wind', 82, 41, 50, '46215', 30], ['seas', 75, 30, 40, '46215', 30]]);
  assert.equal(s.published, '2026-11-04');
  const line = skillLine(s, 'en');
  assert.match(line, /last 30 days/); assert.match(line, /wind 82% \(41 of 50 checked, buoy 46215\)/); assert.match(line, /2026-11-04/); assert.match(line, /Not for navigation/);
});

test('too little history says UNKNOWN with no percentage', () => {
  for (const scores of [[row({enough: false, within: null, n: 0})], [row({n: 10, within: 9})], [row({port: 'other'})], []]) {
    const s = skillSummary(file(scores), 'morro-bay', NOW);
    assert.equal(s.state, 'unknown');
    const line = skillLine(s, 'en');
    assert.match(line, /UNKNOWN/); assert.doesNotMatch(line, /%/);
  }
});

test('falls back to the 7-day window only when 30 days is not enough, and never mixes 48 h leads in', () => {
  const s = skillSummary(file([row({enough: false, within: null, n: 0}), row({window_days: 7, n: 31, within: 31}), row({lead_hours: 48, n: 99, within: 1})]), 'morro-bay', NOW);
  assert.equal(s.parts[0].window, 7); assert.equal(s.parts[0].pct, 100); assert.equal(s.parts.length, 1);
});

test('an unreadable, future-dated or stale scorecard is UNKNOWN, never a figure', () => {
  for (const bad of [null, {}, file([row()], {schema_version: 2}), file([row()], {generated_at: '2026-11-20T00:00:00Z'}), file([row()], {generated_at: '2026-10-01T00:00:00Z'}), file([row()], {minimum: {}})]) {
    const s = skillSummary(bad, 'morro-bay', NOW);
    assert.equal(s.state, 'unknown'); assert.doesNotMatch(skillLine(s, 'en'), /%/);
  }
});

test('Spanish line keeps UNKNOWN and not-for-navigation', () => {
  assert.match(skillLine(skillSummary(file([row()]), 'morro-bay', NOW), 'es'), /No apto para navegar/);
  assert.match(skillLine(skillSummary(file([]), 'morro-bay', NOW), 'es'), /DESCONOCIDO/);
});

test('the real published scorecard reads without error', async () => {
  const real = JSON.parse(await readFile(new URL('../dist/data/forecast-skill.json', import.meta.url), 'utf8'));
  const s = skillSummary(real, 'morro-bay', Date.parse(real.generated_at) + 3600_000);
  assert.ok(['known', 'unknown'].includes(s.state));
});

test('the brief shows the skill line under the model line, UNKNOWN on thin history, nothing while loading', async () => {
  const {mkdtemp} = await import('node:fs/promises'), {tmpdir} = await import('node:os'), {join} = await import('node:path'), {pathToFileURL} = await import('node:url');
  const {build} = await import('esbuild'), {rendererPlugins} = await import('./helpers/esbuild-url.mjs');
  const out = join(await mkdtemp(join(tmpdir(), 'skill-')), 'view.mjs');
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export * from './web/brief/Brief.tsx';
    export {skillFile} from './web/brief/skill.ts';
    export {regionInfo} from './web/app/App.tsx';
    export {profile, hour, day} from './web/state.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, platform: 'node', format: 'esm', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  const m = await import(pathToFileURL(out).href), TZ = 'America/Los_Angeles';
  const T0 = Date.parse('2026-10-13T15:00:00Z') / 1000, TIMES = Array.from({length: 80}, (_, i) => T0 + i * 3600), issued = Date.parse('2026-10-13T12:00:00Z') / 1000 - 4 * 3600;
  const series = v => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.keys(v).map(k => [k, k.includes('period') ? 's' : k.includes('direction') ? '°' : k.includes('height') ? 'ft' : 'kn']))},
    hourly: {time: TIMES, ...Object.fromEntries(Object.entries(v).map(([k, x]) => [k, TIMES.map(() => x)]))}});
  const run = data => ({issued, end: TIMES.at(-1), data: series(data)});
  const forecast = {region: 'synthetic', retrieved: Date.parse('2026-10-13T12:00:00Z'), point: {id: 'synthetic', lat: 36, lon: -122}, models: {
    gfs_global: run({wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315}),
    ncep_gfswave016: run({wave_height: 2.5, wave_period: 11, wind_wave_height: 0.3, wind_wave_period: 4, swell_wave_height: 2, swell_wave_period: 11, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200}),
    ecmwf_ifs025: run({wind_speed_10m: 4, wind_gusts_10m: 9}), ecmwf_wam: run({wave_height: 2.1})}};
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', center: [36, -122], timezone: TZ};
  m.dailyFeed.value = {schema_version: 1, region_id: 'morro-bay', sources: {}};
  m.hour.value = '2026-10-13T15:00Z'; m.profile.value = 'boat'; m.day.value = null; m.regionalForecast.value = forecast;
  const html = () => m.render(m.h(m.Verdict, {now: new Date('2026-10-13T12:00:00Z')}));
  m.skillFile.value = undefined; assert.doesNotMatch(html(), /app-verdict-skill/);
  m.skillFile.value = file([row()], {generated_at: '2026-10-12T03:00:00Z'});
  const ok = html(); assert.match(ok, /data-skill="known"[^>]*>Forecast skill 24 h ahead, last 30 days: wind 82%/);
  assert.ok(ok.indexOf('app-verdict-models') < ok.indexOf('app-verdict-skill'));
  assert.match(ok, /app-verdict-skill[^<]*<a href="\/skill">Scorecard<\/a><\/p>/);
  m.skillFile.value = file([], {generated_at: '2026-10-12T03:00:00Z'});
  assert.match(html(), /data-skill="unknown"[^>]*>Forecast skill 24 h ahead: UNKNOWN[^<]*<a href="\/skill">Scorecard<\/a>/);
  // SC1407-11: the dock's chosen hour sets the lead (measured from now), and the link shows in every state and language.
  m.skillFile.value = file([row(), row({lead_hours: 48, within: 35}), row({lead_hours: 72, within: 20})], {generated_at: '2026-10-12T03:00:00Z'});
  for (const [hour, lead, pct] of [['2026-10-14T15:00Z', 48, 70], ['2026-10-15T15:00Z', 72, 40]]) {
    m.hour.value = hour;
    assert.match(html(), new RegExp(`data-skill="known"[^>]*>Forecast skill ${lead} h ahead, last 30 days: wind ${pct}%[^<]*<a href="/skill">Scorecard</a>`));
  }
  m.hour.value = '2026-10-16T15:00Z';
  const far = html(); assert.match(far, /data-skill="unavailable"[^>]*>Forecast skill: UNKNOWN\. No measured skill is published 72 h or more ahead[^<]*<a href="\/skill">Scorecard<\/a>/);
  assert.doesNotMatch(far.slice(far.indexOf('app-verdict-skill')), /\d+%/);
  m.language.value = 'es'; m.hour.value = '2026-10-14T15:00Z';
  assert.match(html(), /Acierto del pronóstico a 48 h, últimos 30 días: viento 70%[^<]*<a href="\/skill">Tabla de aciertos<\/a>/);
  m.language.value = 'en';
});

const H = 3_600_000, M = 60_000;
const leads = file([row(), row({lead_hours: 48, within: 35}), row({lead_hours: 72, within: 20})]);

test('the lead uses the publisher\'s half-open buckets: exactly 24 h is 48 h ahead, exactly 72 h has no score', () => {
  const cases = [[0, 24], [24 * H - M, 24], [24 * H, 48], [24 * H + M, 48], [48 * H - M, 48], [48 * H, 72], [48 * H + M, 72], [72 * H - M, 72], [72 * H, null], [72 * H + M, null], [200 * H, null]];
  const pct = {24: 82, 48: 70, 72: 40};
  for (const [delta, lead] of cases) {
    assert.equal(skillLead(NOW + delta, NOW), lead, `delta ${delta / M} min`);
    const s = skillSummary(leads, 'morro-bay', NOW, NOW + delta);
    if (lead === null) { assert.ok(util.isDeepStrictEqual(s, {state: 'unavailable', reason: 'range'}), `delta ${delta / M} min`); continue; }
    assert.equal(s.state, 'known'); assert.equal(s.lead, lead); assert.equal(s.parts[0].pct, pct[lead]);
    assert.match(skillLine(s, 'en'), new RegExp(`^Forecast skill ${lead} h ahead, last 30 days: wind ${pct[lead]}%`));
    assert.match(skillLine(s, 'es'), new RegExp(`^Acierto del pronóstico a ${lead} h,`));
  }
  assert.equal(skillLead(NaN, NOW), null); assert.equal(skillLead(Infinity, NOW), null); assert.equal(skillLead(NOW - 2 * H, NOW), null);
  for (const at of [NaN, NOW - 2 * H]) assert.equal(skillSummary(leads, 'morro-bay', NOW, at).reason, 'invalid');
  assert.equal(skillSummary(leads, 'morro-bay', NOW).lead, 24, 'without a chosen hour the lead is 24 h, as before');
});

test('a lead with too few pairs says not enough history, never borrowing the 24 h figure', () => {
  for (const thin of [[], [row({lead_hours: 48, n: 10, within: 9})], [row({lead_hours: 48, enough: false, within: null, n: 0})]]) {
    const s = skillSummary(file([row(), row({window_days: 7}), ...thin]), 'morro-bay', NOW, NOW + 30 * H);
    assert.equal(s.state, 'unknown'); assert.equal(s.lead, 48);
    const line = skillLine(s, 'en');
    assert.match(line, /^Forecast skill 48 h ahead: UNKNOWN\. Not enough buoy history yet/); assert.doesNotMatch(line, /%/);
    assert.match(skillLine(s, 'es'), /^Acierto del pronóstico a 48 h: DESCONOCIDO\. Aún no hay suficiente historial/);
  }
  const s = skillSummary(file([row(), row({lead_hours: 48, window_days: 7, n: 31, within: 31})]), 'morro-bay', NOW, NOW + 30 * H);
  assert.equal(s.lead, 48); assert.equal(s.parts[0].window, 7); assert.equal(s.parts[0].pct, 100);
});

test('past 72 h the line says no skill is measured that far ahead, with no figure, in both languages', () => {
  const s = skillSummary(leads, 'morro-bay', NOW, NOW + 80 * H);
  assert.match(skillLine(s, 'en'), /No measured skill is published 72 h or more ahead\. Not for navigation\./);
  assert.match(skillLine(s, 'es'), /No se publica acierto medido a 72 h o más\. No apto para navegar\./);
  for (const lang of ['en', 'es']) assert.doesNotMatch(skillLine(s, lang), /%|publi[a-z]+ 20/);
  assert.match(skillLine(skillSummary(leads, 'morro-bay', NOW, NOW - 2 * H), 'en'), /^Forecast skill: UNKNOWN for this hour\. Not for navigation\.$/);
});
