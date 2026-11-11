// SC2252-07: each marine alert under Conditions → Before you go says when it starts and ends, in the region
// zone, with its headline as the accessible description. The real Conditions view and the real currentBrief
// run over the synthetic Monterey daily fixture; only its advisory rows are replaced.
// A non-Pacific process zone catches any clock read in the device zone instead of the region's.
process.env.TZ = 'Asia/Kolkata';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'alert-times-')), 'bundle.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {alertTimeSpan} from './web/alert-time.ts';
    export {Conditions} from './web/app/views/Conditions.tsx';
    export {currentBrief, dailyFeed} from './web/brief/Brief.tsx';
    export {regionInfo} from './web/app/App.tsx';
    export {configureStore, region, profile, hour} from './web/state.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string';
    export {h, Fragment} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
});
const v = await import(pathToFileURL(out).href);

const LA = 'America/Los_Angeles';
const norm = s => s?.replace(/[\u202f\u00a0]/g, ' ') ?? s;   // ICU's narrow no-break space before AM/PM
const span = (a, b, lang = 'en', tz = LA) => norm(v.alertTimeSpan(a, b, tz, lang));

test('both_end_only_start_only_neither_en_es', () => {
  const start = '2026-10-08T20:00:00Z', end = '2026-10-09T04:00:00Z';
  assert.equal(span(start, end), 'from Thu, Oct 8, 1:00 PM PDT to Thu, Oct 8, 9:00 PM PDT');
  assert.equal(span(null, end), 'until Thu, Oct 8, 9:00 PM PDT');
  assert.equal(span(start, null), 'from Thu, Oct 8, 1:00 PM PDT');
  assert.equal(span(null, null), null);
  const es = [span(start, end, 'es'), span(null, end, 'es'), span(start, null, 'es')];
  assert.match(es[0], /^desde .*\b13:00 PDT hasta .*\b21:00 PDT$/);
  assert.match(es[1], /^hasta .*\b21:00 PDT$/);
  assert.match(es[2], /^desde .*\b13:00 PDT$/);
  assert.ok(es.every(s => /\b8\b/.test(s) && !/GMT|from|until| to /.test(s)), es.join(' | '));
  assert.equal(span(null, null, 'es'), null);
  // Unreadable clocks are no clock at all: never epoch zero, now, the device zone or a rolled-over date.
  const bad = [null, undefined, '', '   ', 'soon', 'null', '2026-10-08', '2026-10-08T20:00:00', '2026-10-08 20:00', '2026-02-30T10:00:00Z',
    '2026-10-08T25:00:00Z', '2026-10-08T20:00:00+25:00', '+275761-01-01T00:00:00Z', '275760-09-14T00:00:00Z', 'T20:00:00Z', 42];
  for (const x of bad) {
    assert.doesNotThrow(() => v.alertTimeSpan(x, x, LA, 'en'));
    assert.equal(v.alertTimeSpan(x, x, LA, 'en'), null, `no span for ${String(x)}`);
    assert.equal(v.alertTimeSpan(x, x, LA, 'es'), null);
    // A valid sibling clock survives the unreadable one, with no dangling separator or placeholder.
    assert.equal(span(x, end), 'until Thu, Oct 8, 9:00 PM PDT');
    assert.equal(span(start, x), 'from Thu, Oct 8, 1:00 PM PDT');
  }
  assert.ok(!/1970|\{|undefined|NaN|Invalid/.test(bad.map(x => span(x, end) + span(start, x)).join()));
  // The same instant written with another offset (or padding) is the same regional time.
  assert.equal(span('2026-10-08T13:00:00-07:00', '2026-10-09T09:30:00+05:30'), span(start, end));
  assert.equal(span(' 2026-10-08T20:00:00.000Z ', null), span(start, null));
});

test('cross_midnight_and_dst_endpoint_zones', () => {
  // An ordinary night: 11 pm Thursday to 2 am Friday.
  assert.equal(span('2026-10-09T06:00:00Z', '2026-10-09T09:00:00Z'), 'from Thu, Oct 8, 11:00 PM PDT to Fri, Oct 9, 2:00 AM PDT');
  // Spring forward on 2026-03-08: each end has its own zone name.
  assert.equal(span('2026-03-08T09:30:00Z', '2026-03-08T10:30:00Z'), 'from Sun, Mar 8, 1:30 AM PST to Sun, Mar 8, 3:30 AM PDT');
  assert.equal(span('2026-03-07T20:00:00Z', '2026-03-09T05:00:00Z'), 'from Sat, Mar 7, 12:00 PM PST to Sun, Mar 8, 10:00 PM PDT');
  // Fall back on 2026-11-01: the repeated 1:30 is two distinct instants, told apart by the zone.
  const first = '2026-11-01T08:30:00Z', second = '2026-11-01T09:30:00Z';
  assert.equal(span(first, second), 'from Sun, Nov 1, 1:30 AM PDT to Sun, Nov 1, 1:30 AM PST');
  assert.notEqual(span(null, first), span(null, second));
  assert.equal(span('2026-10-31T19:00:00Z', '2026-11-02T05:00:00Z'), 'from Sat, Oct 31, 12:00 PM PDT to Sun, Nov 1, 9:00 PM PST');
  assert.match(span(first, second, 'es'), /^desde .*1:30 PDT hasta .*1:30 PST$/);
  // The region zone, not the process zone (Asia/Kolkata here).
  assert.equal(span(first, null, 'en', 'America/New_York'), 'from Sun, Nov 1, 3:30 AM EST');
});

// ---- the actual view over the actual model
const NOW = new Date('2026-10-08T21:00:00Z');
const FIXTURE = readFileSync(join(ROOT, 'tests/fixtures/brief/monterey-daily.json'), 'utf8');
const INFO = {id: 'monterey-point-sur', name: 'Monterey', timezone: LA, center: [36.62, -121.9]};
v.configureStore({v2: true, storage: null});
function setAlerts(alerts, info = INFO) {
  const daily = JSON.parse(FIXTURE);
  for (const s of Object.values(daily.sources)) if (s.kind === 'advisory') s.data.alerts = alerts;
  v.region.value = info.id; v.profile.value = 'boat'; v.hour.value = null; v.regionInfo.value = info; v.dailyFeed.value = daily;
}
const notes = html => html.match(/<ul class="app-conditions-notes">(.*?)<\/ul>/s)[1];
const items = html => [...notes(html).matchAll(/<li(?: aria-describedby="([^"]*)")?><a href="https:\/\/api\.weather\.gov\/alerts\/active\/zone\/PZZ535"[^>]*>(.*?)<\/a>(.*?)<\/li>/gs)]
  .map(m => ({describedby: m[1] ?? null, anchor: m[0].match(/<a [^>]*>/)[0], event: m[2], rest: m[3]}));
const render = (now = NOW, lang = 'en') => { v.language.value = lang; const html = norm(v.render(v.h(v.Conditions, {now}))); v.language.value = 'en'; return html; };
const text = s => s.replace(/<[^>]+>/g, '');

const MEMBERS = [
  {id: 'a-both', event: 'Small Craft Advisory', headline: 'Small Craft Advisory until 9 PM', effective: '2026-10-08T20:00:00Z', ends: '2026-10-09T04:00:00Z', expires: '2026-10-09T06:00:00Z'},
  {id: 'b-bad-start', event: 'Gale Warning', headline: 'Gale', effective: 'soon', expires: '2026-10-09T10:00:00Z'},
  {id: 'c-gone', event: 'Expired Advisory', headline: 'Over', effective: '2026-10-07T20:00:00Z', expires: '2026-10-08T04:00:00Z'},
  {id: 'd-both-bad', event: 'Hazardous Seas Warning', headline: 'Seas', effective: 'later', ends: 'bad'},
  {id: 'e-saturday', event: 'Beach Hazards Statement', headline: 'Saturday', effective: '2026-10-10T08:00:00Z', expires: '2026-10-10T20:00:00Z'},
];

test('actual_conditions_preserves_alert_membership', () => {
  setAlerts(structuredClone(MEMBERS));
  const before = JSON.stringify(v.dailyFeed.value);
  const brief = v.currentBrief(NOW);
  // The model already maps ends over expires; unreadable clocks are kept conservatively by relevantAlerts.
  assert.ok(isDeepStrictEqual(brief.alerts.map(a => [a.id, a.effective, a.expires]),
    [['a-both', '2026-10-08T20:00:00Z', '2026-10-09T04:00:00Z'], ['b-bad-start', 'soon', '2026-10-09T10:00:00Z'], ['d-both-bad', 'later', 'bad']]), JSON.stringify(brief.alerts));
  const rows = items(render());
  assert.ok(isDeepStrictEqual(rows.map(r => r.event), brief.alerts.map(a => a.event)), JSON.stringify(rows));
  assert.equal(text(rows[0].rest), ' · from Thu, Oct 8, 1:00 PM PDT to Thu, Oct 8, 9:00 PM PDT' + 'Small Craft Advisory until 9 PM');
  assert.equal(text(rows[1].rest), ' · until Fri, Oct 9, 3:00 AM PDT' + 'Gale');
  assert.equal(text(rows[2].rest), 'Seas', 'an alert with no readable clock is still listed, with no span');
  assert.equal(JSON.stringify(v.dailyFeed.value), before, 'the feed is not mutated');
  // Choosing Saturday (the dock's hour) gives that day's alerts, still in the model's order.
  v.hour.value = '2026-10-10T19:00Z';
  const saturday = v.currentBrief(NOW);
  assert.ok(isDeepStrictEqual(items(render()).map(r => r.event), saturday.alerts.map(a => a.event)));
  assert.ok(saturday.alerts.some(a => a.id === 'e-saturday') && !saturday.alerts.some(a => a.id === 'a-both'));
  assert.match(text(items(render()).find(r => r.event === 'Beach Hazards Statement').rest), /^ · from Sat, Oct 10, 1:00 AM PDT to Sat, Oct 10, 1:00 PM PDT/);
  v.hour.value = null;
});

test('headlines_are_resolving_accessible_descriptions', () => {
  setAlerts([
    {id: 'urn:oid:2.49.0.1.840.0.x;1', event: 'Small Craft Advisory', headline: 'First <b>bold</b> & "quoted"', effective: '2026-10-08T20:00:00Z', expires: '2026-10-09T04:00:00Z'},
    {id: 'urn:oid:2.49.0.1.840.0.x;2', event: 'Small Craft Advisory', headline: 'Second headline', effective: null, expires: '2026-10-09T08:00:00Z'},
    {id: 'id with spaces#3', event: '<script>alert(1)</script>', headline: '   ', expires: '2026-10-09T08:00:00Z'},
  ]);
  const html = render(), rows = items(html);
  assert.equal(rows.length, 3);
  assert.ok(!/<b>|<script>/.test(notes(html)), 'markup-like published text stays text');
  const decode = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;|&#34;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
  assert.equal(decode(rows[2].event), '<script>alert(1)</script>');
  const heads = ['First <b>bold</b> & "quoted"', 'Second headline'];
  const ids = rows.slice(0, 2).map((r, i) => {
    assert.ok(r.describedby, 'the item is described');
    assert.ok(r.anchor.includes(` aria-describedby="${r.describedby}"`), 'the source link is described too');
    assert.ok(!/tabindex|title=|aria-label/.test(r.anchor), 'the link keeps its own name and focus');
    assert.ok(!r.describedby.includes('urn') && !r.describedby.includes('oid'), 'ids are not built from provider ids');
    const target = [...html.matchAll(new RegExp(`<span id="${r.describedby}" class="app-visually-hidden">(.*?)</span>`, 'g'))];
    assert.equal(target.length, 1, 'the description id resolves exactly once');
    assert.equal(decode(target[0][1]), heads[i]);
    return r.describedby;
  });
  assert.notEqual(ids[0], ids[1]);
  assert.equal(rows[2].describedby, null, 'a blank headline gives no description');
  assert.ok(!rows[2].anchor.includes('aria-describedby') && !rows[2].rest.includes('app-visually-hidden'));
  assert.equal(text(rows[2].rest), ' · until Fri, Oct 9, 1:00 AM PDT');
  // Two mounted views share no description id.
  const both = norm(v.render(v.h(v.Fragment, null, v.h(v.Conditions, {now: NOW}), v.h(v.Conditions, {now: NOW}))));
  const all = [...both.matchAll(/<span id="([^"]+)" class="app-visually-hidden">/g)].map(m => m[1]);
  assert.equal(all.length, 4);
  assert.equal(new Set(all).size, 4, all.join());
  for (const id of all) assert.equal(both.split(`aria-describedby="${id}"`).length - 1, 2, 'item and link point at it');
});

test('language_and_region_redraw', () => {
  const alert = {id: 'x', event: 'Small Craft Advisory', headline: 'Synthetic headline', effective: '2026-10-08T20:00:00Z', expires: '2026-10-09T04:00:00Z'};
  setAlerts([alert]);
  const en = items(render(NOW, 'en'))[0], es = items(render(NOW, 'es'))[0], back = items(render(NOW, 'en'))[0];
  assert.match(text(es.rest), /^ · desde .*13:00 PDT hasta .*21:00 PDT/);
  assert.ok(text(es.rest).endsWith('Synthetic headline') && es.event === en.event && es.anchor === en.anchor, 'event, headline and link stay as published');
  assert.ok(isDeepStrictEqual(back, en), 'back to English gives the English line again');
  // Another region's zone redraws the same alert in that zone.
  setAlerts([alert], {...INFO, timezone: 'America/New_York'});
  assert.equal(text(items(render())[0].rest), ' · from Thu, Oct 8, 4:00 PM EDT to Fri, Oct 9, 12:00 AM EDT' + 'Synthetic headline');
  // With no alerts the notes list is the old one: the caveat, the rules and the plan link, with the moon and tides above it.
  setAlerts([]);
  const html = render();
  assert.equal(items(html).length, 0);
  assert.ok(!html.includes('aria-describedby') && !html.includes('app-visually-hidden'));
  assert.ok(html.indexOf('app-conditions-tides') < html.indexOf('app-conditions-moon') && html.indexOf('app-conditions-moon') < html.indexOf('app-conditions-notes'));
  v.dailyFeed.value = null;
  assert.equal(items(render()).length, 0, 'no brief, no alert lines');
});
