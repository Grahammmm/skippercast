// RF2115-8: the Boat Run's clocks use the zone of the region the app is in (zone() in web/app/region-info.ts),
// never the timezone of region metadata that belongs to another region. Real RunLine, synthetic metadata
// (no published file or region added): UTC is the contrast, since every real region is Pacific.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {entranceFor} from '../packages/coast/src/bar-conditions.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const WINDOW = {start: '2026-10-12T14:00:00.000Z', end: '2026-10-12T19:00:00.000Z', label: 'Lower wind & offshore seas', confidence: 'Low', reasons: [], wind: 8, gust: 12, wave: 3, period: 10};
const brief = (over = {}) => ({profile: 'boat', windows: [WINDOW], alerts: [], missing: [], tiles: [{id: 'wind', state: 'fresh'}], limits: {custom: false}, ...over});
const pick = {id: 'a', kind: 'spot', name: 'Reef a', distance: '7.4 nm', nm: 7.4, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.'};
const RANKING = {source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [pick], empty: '', harbor: 'Morro Bay'};
const NOW = new Date('2026-10-12T12:00:00Z');
const PACIFIC = 'America/Los_Angeles';
const PACIFIC_TIMES = 'Leave 7 am · there 7:25 am · turn back 11:35 am · in by 12 pm · window 7 am–12 pm';
const UTC_TIMES = 'Leave 2 pm · there 2:25 pm · turn back 6:35 pm · in by 7 pm · window 2 pm–7 pm';
const info = (id, timezone) => ({id, name: id, center: [35.34, -120.965], timezone});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'run-zone-')), 'run.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RunLine} from './web/brief/Run.tsx';
      export {regionInfo, currentRegionInfo, zone} from './web/app/region-info.ts';
      export {region, profile, selection, species} from './web/state.ts';
      export {language} from './web/i18n.ts';
      export {cruiseSpeed, wantedHours} from './web/limits.ts';
      export {regsData} from './web/regs.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** Set the app's region and the retained metadata, render the real RunLine, and read its clock paragraph and zone(). */
async function setup() {
  const m = await load();
  const saved = {region: m.region.value, info: m.regionInfo.value, profile: m.profile.value, speed: m.cruiseSpeed.value, selection: m.selection.value};
  m.profile.value = 'boat'; m.selection.value = null; m.cruiseSpeed.value = 20;
  const show = (regionId, meta, props = {}, now = NOW) => {
    m.region.value = regionId; m.regionInfo.value = meta;
    const html = m.render(m.h(m.RunLine, {brief: brief(props.brief), ranking: RANKING, now}));
    return {html, times: html.match(/<p class="app-run-times ui-mono">(.*?)<\/p>/)?.[1] ?? null, zone: m.zone()};
  };
  const restore = () => {
    m.region.value = saved.region; m.regionInfo.value = saved.info; m.profile.value = saved.profile;
    m.cruiseSpeed.value = saved.speed; m.selection.value = saved.selection; m.language.value = 'en';
  };
  return {m, show, restore};
}

test('run_other_region_zone_is_ignored: metadata for another region does not set the clocks', async () => {
  const {show, restore} = await setup();
  try {
    const control = show('morro-bay', null);
    assert.equal(control.zone, PACIFIC);
    assert.ok(control.times?.startsWith(PACIFIC_TIMES), control.times);
    const other = show('morro-bay', info('cambria-san-simeon', 'UTC'));
    assert.equal(other.zone, PACIFIC, 'zone() ignores the other region');
    assert.ok(other.times?.startsWith(PACIFIC_TIMES), `Run clocks follow zone(): ${other.times}`);
    assert.equal(other.html, control.html, 'the whole line is what the no-metadata control renders');
  } finally { restore(); }
});

test('run_matching_zone_remains_effective: the active region\'s own metadata still sets the zone', async () => {
  const {show, restore} = await setup();
  try {
    const utc = show('morro-bay', info('morro-bay', 'UTC'));
    assert.equal(utc.zone, 'UTC');
    assert.ok(utc.times?.startsWith(UTC_TIMES), utc.times);
    const pacific = show('morro-bay', info('morro-bay', PACIFIC));
    assert.ok(pacific.times?.startsWith(PACIFIC_TIMES), pacific.times);
  } finally { restore(); }
});

test('run_zone_changes_are_render_local: each render reads the current matching metadata', async () => {
  const {show, restore} = await setup();
  try {
    const seq = [['morro-bay', null, PACIFIC_TIMES], ['morro-bay', info('cambria-san-simeon', 'UTC'), PACIFIC_TIMES],
      ['morro-bay', info('morro-bay', 'UTC'), UTC_TIMES], ['morro-bay', info('morro-bay', PACIFIC), PACIFIC_TIMES],
      ['morro-bay', info('morro-bay', 'UTC'), UTC_TIMES], ['morro-bay', null, PACIFIC_TIMES]];
    for (const [id, meta, want] of seq) {
      const r = show(id, meta);
      assert.ok(r.times?.startsWith(want), `${JSON.stringify(meta)}: ${r.times}`);
    }
  } finally { restore(); }
});

test('run_no_active_region_uses_default: no active region never borrows metadata; no Run for no brief or other profiles', async () => {
  const {m, show, restore} = await setup();
  try {
    const none = show(null, info('morro-bay', 'UTC'));
    assert.equal(none.zone, PACIFIC);
    assert.ok(none.times?.startsWith(PACIFIC_TIMES), none.times);
    m.region.value = 'morro-bay'; m.regionInfo.value = info('morro-bay', 'UTC');
    assert.equal(m.render(m.h(m.RunLine, {brief: null, ranking: RANKING, now: NOW})), '');
    m.profile.value = 'shore';
    assert.equal(m.render(m.h(m.RunLine, {brief: brief({profile: 'shore'}), ranking: RANKING, now: NOW})), '');
  } finally { restore(); }
});

test('run_all_clock_surfaces_share_context: daylight, entrance, fishing hours and the date key follow one zone', async () => {
  const {m, show, restore} = await setup();
  const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
  const rules = fixture.region, d = structuredClone(fixture.regulations);
  d.reviewed_at = NOW.toISOString(); d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: source.approved_content_sha256, data_retrieved_at: d.reviewed_at};
  }
  // The Pacific calendar day of this window is 2026-10-12 (8 pm PDT); its UTC day is 2026-10-13, the day lingcod opens.
  d.species.lingcod.windows = [{start: '2026-10-13', end: '2026-10-31', start_at: '2026-10-13T08:00:00-07:00'}];
  const late = {...WINDOW, start: '2026-10-13T03:00:00.000Z', end: '2026-10-13T06:00:00.000Z'};
  const HOUR = 3600000, t0 = Date.parse('2026-10-12T14:00:00Z');
  const hours = [0, 1, 2].map(i => ({at: new Date(t0 + i * HOUR).toISOString(), band: 'No bar flag', tide: {stage: 'flood', midEbb: false, fraction: 0.5},
    swell: {heightFt: 1, periodS: 10, basis: 'offshore', longPeriodS: null}, windAgainst: false, reasons: []}));
  const props = {brief: {windows: [late], sunrise: '2026-10-12T06:52:00-07:00', sunset: '2026-10-12T17:21:00-07:00', bar: {entrance: entranceFor('morro-bay', 'morro-bay'), hours}}};
  m.species.value = 'lingcod'; m.wantedHours.value = 2; m.regsData.value = {region: rules.id, data: d};
  try {
    const withRules = meta => ({...meta, rules}), at = now => new Date(now);
    const mismatched = show(rules.id, withRules(info('cambria-san-simeon', 'UTC')), props, at('2026-10-12T12:00:00Z'));
    const control = show(rules.id, withRules(info(rules.id, PACIFIC)), props, at('2026-10-12T12:00:00Z'));
    assert.match(control.html, /Daylight 6:52 am–5:21 pm/);
    assert.match(control.html, /app-run-entrance/);
    assert.match(control.html, /is closed that day/, 'the Pacific date key 2026-10-12 is before the season opens');
    for (const surface of [/Daylight [^<]*/, /<p class="app-run-entrance">.*?<\/p>/, /<p class="app-run-hours".*?<\/p>/]) {
      assert.equal(mismatched.html.match(surface)?.[0], control.html.match(surface)?.[0], `${surface} follows zone() with other-region metadata`);
    }
    const matching = show(rules.id, withRules(info(rules.id, 'UTC')), props, at('2026-10-12T12:00:00Z'));
    assert.match(matching.html, /Daylight 1:52 pm–12:21 am/, 'matching metadata moves the daylight clock');
    assert.doesNotMatch(matching.html, /is closed that day/, 'and the date key: the UTC day 2026-10-13 is open');
    assert.notEqual(matching.html.match(/<p class="app-run-entrance">.*?<\/p>/)?.[0], control.html.match(/<p class="app-run-entrance">.*?<\/p>/)?.[0], 'and the entrance clock');
  } finally { m.species.value = null; m.wantedHours.value = null; m.regsData.value = null; restore(); }
});

test('run_language_and_dst_compatibility: Spanish keeps the same default clocks; fixed instants across fall-back follow the formatter', async () => {
  const {m, show, restore} = await setup();
  try {
    m.language.value = 'es';
    const es = show('morro-bay', info('cambria-san-simeon', 'UTC'));
    const base = show('morro-bay', null);
    assert.equal(es.html, base.html, 'Spanish with other-region metadata equals Spanish with none');
    m.language.value = 'en';
    // Pacific falls back on 2026-11-01: 8 am PST is 16:00Z, the same wall-clock hour as 8 am PDT is 15:00Z.
    const fall = {...WINDOW, start: '2026-11-01T16:00:00.000Z', end: '2026-11-01T21:00:00.000Z'};
    const r = show('morro-bay', info('cambria-san-simeon', 'UTC'), {brief: {windows: [fall]}}, new Date('2026-11-01T12:00:00Z'));
    assert.match(r.times ?? '', /^Leave 8 am · there 8:25 am · turn back 12:35 pm · in by 1 pm · window 8 am–1 pm/);
  } finally { restore(); }
});
