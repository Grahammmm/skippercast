// BF-one-answer: the app leads with one answer - can I fish tomorrow, and is it legal - read from the
// verdict the brief already computes (web/brief/verdict.ts) and the rules card's state (web/regs.ts),
// above the map. Bundled with esbuild and rendered to strings, as tests/test_brief_lead.mjs does; the
// answer is compared with what verdict.ts returns for the same state, never with a copy of its text.
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
const HOUR = 3_600_000;
const NOW = new Date('2026-09-30T16:00:00Z'); // 9 am PDT; tomorrow is 1 October

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'first-answer-')), 'fa.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {App, FirstAnswerLine, regionInfo} from './web/app/App.tsx';
      export {firstAnswer} from './web/first-answer.ts';
      export {briefFrom, currentVerdict, leadBrief, leadDate, dailyFeed, regionalForecast} from './web/brief/Brief.tsx';
      export {briefVerdict} from './web/brief/verdict.ts';
      export {parseConditionsForecast} from './web/conditions.ts';
      export {regsData} from './web/regs.ts';
      export {hour, day, species, profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  return (mod = await import(pathToFileURL(out).href));
}

/** The frozen FE-61 registry with fresh synthetic source checks, as tests/test_brief_lead.mjs builds it; `reviewed` false leaves it unreviewed (due). */
async function registry(reviewed = true) {
  const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(NOW.getTime() - HOUR).toISOString();
  d.rules_review_status = reviewed ? 'reviewed' : 'draft';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: NOW.toISOString()};
  }
  return {region: fixture.region, data: d};
}

/** A synthetic forecast feed; wind of `wind` kn all through, ending `days` days after 29 September. */
function forecastFeed(region, wind, days = 16) {
  const start = Date.parse('2026-09-29T07:00:00Z') / 1000, time = Array.from({length: days * 24}, (_, i) => start + i * 3600);
  const series = values => ({utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(values).map(([k, [, u]]) => [k, u]))},
    hourly: {time, ...Object.fromEntries(Object.entries(values).map(([k, [v]]) => [k, time.map(() => v)]))}});
  const meta = {last_run_initialisation_time: NOW.getTime() / 1000 - 6 * 3600, data_end_time: time.at(-1)};
  return {region_id: region, retrieved: NOW.getTime() - 20 * 60_000, requested_points: [['monterey-bay', 36.7, -121.95], ['offshore-0-0', 36.5, -122.25]],
    models: {gfs_global: {meta, data: [0, 1].map(() => series({wind_speed_10m: [wind, 'kn'], wind_gusts_10m: [wind + 4, 'kn'], wind_direction_10m: [300, '°'], temperature_2m: [60, '°F'], cloud_cover: [30, '%']}))},
      ncep_gfswave016: {meta, data: [0, 1].map(() => series({wave_height: [wind > 20 ? 14 : 2, 'ft'], wave_period: [12, 's']}))}}};
}

async function setup(m, {wind = 5, days = 16, feed = true, forecast = true, rules = true, reviewed = true} = {}) {
  const {region, data} = await registry(reviewed);
  const info = {id: region.id, name: region.name, center: region.map.center, timezone: region.timezone, ...rules ? {rules: region} : {}};
  m.regionInfo.value = info; m.dailyFeed.value = feed ? {...montereyDaily, region_id: region.id} : null;
  m.regionalForecast.value = forecast ? m.parseConditionsForecast(forecastFeed(region.id, wind, days), region.id, region.map.center) : null;
  m.regsData.value = rules ? {region: region.id, data} : null; m.species.value = 'salmon'; m.profile.value = 'boat'; m.hour.value = null; m.day.value = null;
  return info;
}
const reset = m => { m.regionInfo.value = null; m.dailyFeed.value = null; m.regionalForecast.value = null; m.regsData.value = null; m.species.value = null; m.hour.value = null; m.day.value = null; };
const lineOf = html => /<h2 class="app-first-answer-line">(.*?)<\/h2>/.exec(html)?.[1];
const fishableOf = html => /data-fishable="(\w+)"/.exec(html)?.[1];

test('the answer line precedes the map container, and its answer is the verdict engine\'s own for tomorrow', async () => {
  const m = await load();
  await setup(m);
  try {
    const html = m.render(m.h(m.App, {now: NOW}));
    assert.ok(html.indexOf('app-first-answer-line') > 0, 'the answer renders');
    assert.ok(html.indexOf('app-first-answer-line') < html.indexOf('class="app-stage"'), 'the answer line precedes the map container');
    assert.ok(html.indexOf('class="app-stage"') > 0, 'the map stays');
    assert.ok(html.indexOf('class="app-brief"') > html.indexOf('app-first-answer-line'), 'the measured detail stays, one step behind');
    const brief = m.leadBrief(NOW), v = m.currentVerdict(brief, NOW);
    assert.equal(brief.date, '2026-10-01');
    const a = m.firstAnswer({verdict: v, rules: m.regionInfo.value.rules, regs: m.regsData.value.data, target: 'salmon', date: brief.date, day: 'tomorrow', now: NOW, profile: 'boat', chosen: true});
    assert.equal(a.fishable, {comfortable: 'yes', marginal: 'marginal', rough: 'no', unknown: 'unknown'}[v.verdict]);
    assert.equal(fishableOf(html), a.fishable);
    assert.ok(html.includes(`<p class="app-first-answer-reason">${v.limit}${v.held ? ` ${v.held}` : ''}</p>`), 'the reason is the verdict\'s own sentence');
    assert.notEqual(v.verdict, 'unknown');
  } finally { reset(m); }
});

test('yes, marginal, no and unknown each render a distinct line, and unknown never reads as a yes', async () => {
  const m = await load();
  const lines = {};
  try {
    for (const [name, opts] of Object.entries({marginal: {wind: 5}, no: {wind: 30}, unknown: {forecast: false}})) {
      await setup(m, opts);
      const html = m.render(m.h(m.FirstAnswerLine, {now: NOW})), v = m.currentVerdict(m.leadBrief(NOW), NOW);
      lines[name] = lineOf(html);
      assert.equal(fishableOf(html), {comfortable: 'yes', marginal: 'marginal', rough: 'no', unknown: 'unknown'}[v?.verdict ?? 'unknown'], name);
      assert.equal(fishableOf(html), name, `${name}: the fixture produces the verdict it names`);
    }
    // The pipeline holds a clear day at Marginal here (partial detail, no alert check), so a Comfortable verdict is passed straight in.
    const clear = {verdict: 'comfortable', limit: 'Wind to 5 kt and seas to 2 ft through noon.', held: null, window: '8 am-noon', score: 9, basis: 'comfort-score', agreement: null};
    lines.yes = m.firstAnswer({verdict: clear, rules: null, regs: null, target: 'lingcod', date: '2026-10-01', day: 'tomorrow', now: NOW, profile: 'boat', chosen: true}).line;
    assert.equal(new Set(Object.values(lines)).size, 4, 'four distinct lines');
    assert.match(lines.yes, /^Yes/);
    assert.doesNotMatch(lines.unknown, /\byes\b|fishable|comfortable/i, 'unknown is not phrased as a yes');
    assert.match(lines.unknown, /not known/i);
  } finally { reset(m); }
});

test('a missing feed reads unknown with the map still rendered; one missing feed still paints the line', async () => {
  const m = await load();
  try {
    await setup(m, {feed: false, forecast: false});
    const none = m.render(m.h(m.App, {now: NOW}));
    assert.equal(fishableOf(none), 'unknown');
    assert.ok(none.indexOf('app-first-answer-line') < none.indexOf('class="app-stage"'), 'the map is rendered behind the line');
    await setup(m, {forecast: false});   // the daily feed alone: no forecast for the window
    const half = m.render(m.h(m.App, {now: NOW}));
    assert.equal(fishableOf(half), 'unknown');
    assert.ok(lineOf(half) && half.includes('class="app-stage"'));
    await setup(m, {feed: false});       // the forecast alone
    assert.equal(fishableOf(m.render(m.h(m.FirstAnswerLine, {now: NOW}))), 'unknown');
  } finally { reset(m); }
});

test('tomorrow past the forecast\'s data_end_time is unknown, not a guess', async () => {
  const m = await load();
  try {
    await setup(m, {days: 2});           // the model ends on 30 September; tomorrow is 1 October
    const html = m.render(m.h(m.FirstAnswerLine, {now: NOW}));
    assert.equal(fishableOf(html), 'unknown');
    assert.ok(html.includes(m.currentVerdict(m.leadBrief(NOW), NOW).limit), 'the reason is the verdict engine\'s own');
  } finally { reset(m); }
});

test('rules unavailable or due for review are named as such and quote no numbers', async () => {
  const m = await load();
  try {
    const note = html => /<p class="app-first-answer-rules">(.*?) <a /.exec(html)[1];
    await setup(m, {rules: false});
    const unavailable = note(m.render(m.h(m.FirstAnswerLine, {now: NOW})));
    assert.match(unavailable, /^Rules unavailable/);
    await setup(m, {reviewed: false});
    const due = note(m.render(m.h(m.FirstAnswerLine, {now: NOW})));
    assert.match(due, /^Rules due for review/);
    await setup(m);
    const reviewed = note(m.render(m.h(m.FirstAnswerLine, {now: NOW})));
    assert.match(reviewed, /^Rules reviewed \(Closed\)/, 'the salmon season ends today, so tomorrow reads closed');
    for (const text of [unavailable, due, reviewed]) assert.doesNotMatch(text, /\d/, 'no bag, size or depth numbers');
    assert.match(m.render(m.h(m.FirstAnswerLine, {now: NOW})), /<a href="https:[^"]*" target="_blank"/, 'a pointer to the official rules');
  } finally { reset(m); }
});

test('with no profile chosen the line states which profile it assumed; a chosen one does not', async () => {
  const m = await load();
  try {
    await setup(m);
    m.profile.value = 'kayak';
    const html = m.render(m.h(m.FirstAnswerLine, {now: NOW}));   // no address or storage names a profile under test
    assert.match(lineOf(html), /Assuming the Kayak profile/);
    const brief = m.leadBrief(NOW);
    const base = {verdict: m.currentVerdict(brief, NOW), rules: null, regs: null, target: 'lingcod', date: brief.date, day: 'tomorrow', now: NOW, profile: 'shore'};
    assert.match(m.firstAnswer({...base, chosen: false}).line, /Assuming the Shore profile/);
    assert.doesNotMatch(m.firstAnswer({...base, chosen: true}).line, /Assuming/);
    assert.equal(m.firstAnswer({...base, chosen: true, verdict: null}).fishable, 'unknown', 'no verdict at all is unknown');
  } finally { reset(m); }
});
