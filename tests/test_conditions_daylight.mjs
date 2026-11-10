// SC2252-08: Conditions shows the dock day's sunrise and sunset under Tide events for every profile, in the region zone,
// from the brief's own sunrise/sunset fields and the Run line's clock; the pair is unavailable as a whole, never half.
// The real Conditions view and the real currentBrief run over the synthetic Monterey daily fixture.
// A non-Pacific process zone catches any clock or date read in the device zone instead of the region's.
process.env.TZ = 'Asia/Kolkata';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'conditions-daylight-')), 'bundle.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {daylightText} from './web/conditions-daylight.ts';
    export {clock} from './web/brief/clock.ts';
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {currentBrief, dailyFeed} from './web/brief/Brief.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {cruiseSpeed} from './web/limits.ts';
    export {configureStore, region, profile, hour, day} from './web/state.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
});
const v = await import(pathToFileURL(out).href);

const LA = 'America/Los_Angeles';
const norm = s => s?.replace(/[\u202f\u00a0]/g, ' ') ?? s;   // ICU's narrow no-break space before am/pm
const text = (brief, day, lang = 'en', tz = LA) => norm(v.daylightText(brief, day, tz, lang));
const NONE = {en: 'Sunrise and sunset unavailable', es: 'Amanecer y atardecer no disponibles'};
const OCT8 = {date: '2026-10-08', sunrise: '2026-10-08T14:08:57.156Z', sunset: '2026-10-09T01:40:36.795Z'};

test('pair_text_en_es_and_zone_names', () => {
  assert.equal(text(OCT8, '2026-10-08'), 'Sunrise 7:08 am · sunset 6:40 pm PDT');
  assert.equal(text(OCT8, '2026-10-08', 'es'), 'Amanecer 7:08 · atardecer 18:40 PDT', 'Spanish clocks as Run formats them, the region label kept');
  // The same instants written with another offset are the same regional clocks.
  assert.equal(text({...OCT8, sunrise: '2026-10-08T07:08:57-07:00', sunset: '2026-10-09T07:10:36+05:30'}, '2026-10-08'), 'Sunrise 7:08 am · sunset 6:40 pm PDT');
  // A whole hour drops ':00' exactly as the Run line does.
  assert.equal(text({date: '2026-10-08', sunrise: '2026-10-08T14:00:00Z', sunset: '2026-10-09T01:00:00Z'}, '2026-10-08'), 'Sunrise 7 am · sunset 6 pm PDT');
  // Another region's zone, not the process zone: a non-Pacific region and a sunset on the next UTC date.
  assert.equal(text({date: '2026-10-08', sunrise: '2026-10-08T11:05:00Z', sunset: '2026-10-08T22:41:00Z'}, '2026-10-08', 'en', 'America/New_York'), 'Sunrise 7:05 am · sunset 6:41 pm EDT');
  // Two zone names for one day (synthetic: a pair across a fall-back): each clock carries its own.
  assert.equal(text({date: '2026-11-01', sunrise: '2026-11-01T08:30:00Z', sunset: '2026-11-01T09:30:00Z'}, '2026-11-01'), 'Sunrise 1:30 am PDT · sunset 1:30 am PST');
  assert.equal(text({date: '2026-11-01', sunrise: '2026-11-01T08:30:00Z', sunset: '2026-11-01T09:30:00Z'}, '2026-11-01', 'es'), 'Amanecer 1:30 PDT · atardecer 1:30 PST');
  // The Run line's clock is the same shared formatter, unchanged.
  assert.deepEqual(['2026-10-08T15:00:00Z', '2026-10-08T15:25:00Z'].map(iso => norm(v.clock(iso, LA))), ['8 am', '8:25 am']);
  assert.equal(v.clock('2026-10-08T15:25:00Z', LA, 'es'), '8:25');
});

test('unavailable_is_a_pair', () => {
  const day = '2026-10-08';
  const cases = [
    ['no brief', null], ['undefined brief', undefined],
    ['no sunrise', {...OCT8, sunrise: null}], ['no sunset', {...OCT8, sunset: null}], ['neither', {...OCT8, sunrise: null, sunset: null}],
    ['brief for another day', {...OCT8, date: '2026-10-09'}],
    ['reversed', {...OCT8, sunrise: OCT8.sunset, sunset: OCT8.sunrise}], ['equal', {...OCT8, sunset: OCT8.sunrise}],
    ['sunrise on the day before', {...OCT8, sunrise: '2026-10-07T14:08:00Z'}], ['sunset on the day after', {...OCT8, sunset: '2026-10-09T08:00:00Z'}],
  ];
  for (const bad of ['', '   ', 'soon', '2026-10-08', '2026-10-08T14:08:57', '2026-10-08 14:08', '2026-02-30T14:00:00Z', '2026-10-08T25:00:00Z', '+275761-01-01T00:00:00Z', 42])
    cases.push([`sunrise ${String(bad)}`, {...OCT8, sunrise: bad}], [`sunset ${String(bad)}`, {...OCT8, sunset: bad}]);
  for (const [name, brief] of cases) for (const lang of ['en', 'es']) {
    assert.doesNotThrow(() => v.daylightText(brief, day, LA, lang), name);
    assert.equal(v.daylightText(brief, day, LA, lang), NONE[lang], `${name} (${lang})`);
  }
});

// ---- the actual view over the actual model
const NOW = new Date('2026-10-08T21:00:00Z');   // Thu Oct 8, 2 pm PDT
const FIXTURE = readFileSync(join(ROOT, 'tests/fixtures/brief/monterey-daily.json'), 'utf8');
const INFO = {id: 'monterey-point-sur', name: 'Monterey', timezone: LA, center: [36.62, -121.9]};
v.configureStore({v2: true, storage: null});
function setFeed({noTides = false, profile = 'boat', info = INFO} = {}) {
  const daily = JSON.parse(FIXTURE);
  if (noTides) for (const s of Object.values(daily.sources)) if (s.kind === 'prediction') s.data.predictions = [];
  v.region.value = info.id; v.profile.value = profile; v.hour.value = null; v.day.value = null; v.regionInfo.value = info; v.dailyFeed.value = daily;
  v.cruiseSpeed.value = null;
}
const render = (now = NOW, lang = 'en') => { v.language.value = lang; const html = norm(v.render(v.h(v.Conditions, {now}))); v.language.value = 'en'; return html; };
const lines = html => [...html.matchAll(/<p class="app-conditions-daylight">(.*?)<\/p>/gs)].map(m => m[1]);
const line = (now = NOW, lang = 'en') => { const all = lines(render(now, lang)); assert.equal(all.length, 1, 'exactly one daylight line'); return all[0]; };

test('all_profiles_without_run', () => {
  for (const profile of ['boat', 'shore', 'spear', 'kayak']) {
    setFeed({noTides: true, profile});
    const brief = v.currentBrief(NOW);
    assert.equal(brief.tideEvents.length, 0, 'no tide predictions');
    assert.equal(brief.date, '2026-10-08');
    const html = render(), [sun] = lines(html);
    assert.equal(lines(html).length, 1, profile);
    assert.equal(sun, `Sunrise ${norm(v.clock(brief.sunrise, LA))} · sunset ${norm(v.clock(brief.sunset, LA))} PDT`, profile);
    assert.equal(sun, 'Sunrise 7:08 am · sunset 6:40 pm PDT', profile);
    // Under Tide events (after the empty state), before the moon and Before you go.
    const at = html.indexOf('app-conditions-daylight');
    assert.ok(html.indexOf('No tide predictions for') < at && at < html.indexOf('app-conditions-moon') && at < html.indexOf('app-conditions-notes'), profile);
    assert.ok(!html.includes('app-run'), 'no Run line on Conditions');
  }
  // With tide events the line follows the list.
  setFeed({profile: 'shore'});
  const html = render();
  assert.ok(html.indexOf('</ul>', html.indexOf('app-conditions-tides')) < html.indexOf('app-conditions-daylight'));
});

test('missing_feed_and_missing_value_render_unavailable', () => {
  setFeed();
  v.dailyFeed.value = null;
  assert.equal(line(), NONE.en, 'before the feed arrives');
  assert.equal(line(NOW, 'es'), NONE.es);
  // A polar day: astro gives no sunrise or sunset that belongs to the date.
  setFeed({info: {...INFO, center: [78.2, 15.6]}});
  v.hour.value = '2026-06-21T12:00Z';
  const polar = v.currentBrief(NOW);
  assert.ok(!polar || !polar.sunrise || !polar.sunset, 'fixture really lacks one event');
  assert.equal(line(), NONE.en);
});

test('dock_day_not_lead_or_now', () => {
  setFeed();
  const today = line();
  assert.equal(today, 'Sunrise 7:08 am · sunset 6:40 pm PDT');
  // A day-only link to Saturday with no hour: the line is Saturday's, while currentBrief(now) stays on today.
  v.day.value = '2026-10-10';
  assert.equal(v.currentBrief(NOW).date, '2026-10-08');
  assert.equal(line(), 'Sunrise 7:10 am · sunset 6:37 pm PDT');
  // An explicit hour wins over a conflicting day.
  v.hour.value = '2026-10-09T19:00Z';
  const friday = line();
  assert.equal(friday, 'Sunrise 7:09 am · sunset 6:39 pm PDT');
  // Scrubbing within the same regional day keeps the two events.
  for (const h of ['2026-10-09T08:00Z', '2026-10-09T15:00Z', '2026-10-10T06:00Z']) { v.hour.value = h; assert.equal(line(), friday, h); }
  v.hour.value = null; v.day.value = null;
  // 03:00 UTC on Oct 9 is still Oct 8 in the region: the regional day, not the UTC date.
  assert.equal(line(new Date('2026-10-09T03:00:00Z')), today);
  // Changing the loaded feed redraws the line.
  v.dailyFeed.value = null;
  assert.equal(line(), NONE.en);
});

test('dst_change_days', () => {
  setFeed();
  // Fall back: the evening before (11 pm PDT Oct 31), Sunday chosen; both events are after 2 am, so PST.
  v.hour.value = '2026-11-01T20:00Z';
  const fall = v.currentBrief(new Date('2026-11-01T06:00:00Z'));
  assert.equal(fall.date, '2026-11-01');
  assert.equal(line(new Date('2026-11-01T06:00:00Z')), 'Sunrise 6:31 am · sunset 5:10 pm PST');
  // Spring forward: just after midnight PST on Mar 8, the day chosen; sunrise and sunset are PDT.
  v.hour.value = '2026-03-08T20:00Z';
  assert.equal(line(new Date('2026-03-08T08:30:00Z')), 'Sunrise 7:28 am · sunset 7:08 pm PDT');
  assert.equal(line(new Date('2026-03-08T08:30:00Z'), 'es'), 'Amanecer 7:28 · atardecer 19:08 PDT');
  v.hour.value = null;
});

test('language_redraw_and_no_duplicate', () => {
  setFeed();
  const en = line(NOW, 'en'), es = line(NOW, 'es'), back = line(NOW, 'en');
  assert.equal(es, 'Amanecer 7:08 · atardecer 18:40 PDT');
  assert.equal(back, en);
  const html = render();
  for (let i = 0; i < 3; i++) assert.equal(render(), html, 'a redraw renders the same single line');
  assert.ok(html.indexOf('app-conditions-moon') < html.indexOf('app-conditions-notes'), 'moon and notes stay in order');
});
