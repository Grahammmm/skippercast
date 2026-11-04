// BF-rules-freshness: a rules card says in words when the daily source check last confirmed the row, and links the
// official page. web/regs.ts `freshnessLabel` reads the registry's own checks (data_retrieved_at, max_age_hours).
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {CDFW_OCEAN, freshnessLabel, regulationState, ruleSummary} from '../web/regs.ts';

const ROOT = new URL('..', import.meta.url).pathname, fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const REGION = fixture.region, HOUR = 3600000, NOW = Date.parse('2026-09-21T18:00:00Z');
const PAGE = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary';

/** The frozen registry with every source checked at `at`, reviewed an hour before. */
function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const label = (d, species = 'halibut', now = NOW) => freshnessLabel(d, species, regulationState(d, species, REGION, now), REGION, now);

test('checked today, yesterday, never and past the max age read as four distinct labels', () => {
  assert.deepEqual(label(data(NOW - HOUR)), {text: 'Checked today', state: 'checked-today'});
  assert.deepEqual(label(data(NOW - 20 * HOUR)), {text: 'Checked Sep 20', state: 'checked-earlier'});
  const none = data(); delete none.checks['rules-central'].data_retrieved_at;
  assert.deepEqual(label(none), {text: 'Check date unknown', state: 'unknown'});
  assert.deepEqual(label(data(NOW - 37 * HOUR)), {text: 'Check overdue - open the official page', state: 'stale'});
  assert.equal(new Set([label(data(NOW - HOUR)), label(data(NOW - 20 * HOUR)), label(none), label(data(NOW - 37 * HOUR))].map(l => l.text)).size, 4);
});

test('the registry\'s own max_age_hours sets "overdue", never looser than 36 h', () => {
  const short = data(NOW - 13 * HOUR); short.max_age_hours = 12;
  assert.equal(label(short).state, 'stale');
  const loose = data(NOW - 40 * HOUR); loose.max_age_hours = 72;
  assert.equal(label(loose).state, 'stale', 'a looser registry value still ends at 36 h');
});

test('an unparseable, absent or future check time reads unknown, never checked today', () => {
  for (const at of ['not a date', null, undefined, '', new Date(NOW + 30 * 60000).toISOString(), new Date(NOW + 5 * 24 * HOUR).toISOString()]) {
    const d = data(); d.checks['rules-central'].data_retrieved_at = at;
    assert.deepEqual(label(d), {text: 'Check date unknown', state: 'unknown'}, String(at));
  }
  for (const d of [null, undefined, {}, {...data(), checks: null}]) assert.equal(label(d).state, 'unknown');
});

test('the oldest of a target\'s sources is the date shown, so one fresh source cannot vouch for a stale one', () => {
  const d = data(NOW - HOUR);
  d.checks['rules-gear'].data_retrieved_at = new Date(NOW - 30 * HOUR).toISOString();
  assert.equal(label(d).text, 'Checked Sep 20');
  const missing = data(NOW - HOUR); delete missing.checks['rules-gear'];
  assert.equal(label(missing).state, 'unknown');
  const reef = data(NOW - HOUR); reef.checks['rules-groundfish'].data_retrieved_at = new Date(NOW - 30 * HOUR).toISOString();
  assert.equal(label(reef, 'reef').text, 'Checked Sep 20');
});

test('a rule that reads unknown keeps "Check rules" and gets no line saying a check confirmed it', () => {
  const pending = data(NOW - HOUR); pending.rules_review_status = 'pending';
  const s = regulationState(pending, 'halibut', REGION, NOW);
  assert.equal(s.status, 'unknown');
  assert.equal(ruleSummary(pending, 'halibut', s, REGION).label, 'Check rules');
  assert.deepEqual(label(pending), {text: 'Check date unknown', state: 'unknown'});
  const changed = data(NOW - HOUR); changed.checks['rules-central'].status = 'changed';
  const outside = data(NOW - HOUR); outside.valid_through = '2026-09-01';
  for (const d of [changed, outside]) assert.equal(label(d).state, 'unknown');
});

test('the link is always an official page: http, credentials and foreign hosts fall back to CDFW', () => {
  const link = url => {
    const d = data(); d.sources['rules-groundfish'].url = url; d.checks['rules-groundfish'].url = url;
    return ruleSummary(d, 'reef', regulationState(d, 'reef', REGION, NOW), REGION).link;
  };
  assert.equal(link(PAGE), PAGE);
  for (const bad of ['http://wildlife.ca.gov/Fishing/Ocean', 'https://user:pw@wildlife.ca.gov/Fishing/Ocean', 'https://evil.example/Fishing/Ocean', 'javascript:alert(1)'])
    assert.equal(link(bad), CDFW_OCEAN, bad);
});

let ui;
async function load() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'rules-fresh-')), 'ui.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {RulesLine} from './web/app/MarkCard.tsx';
    export {TargetRules} from './web/app/PlanView.tsx';
    export {markData} from './web/map/marks.ts';
    export {regionInfo} from './web/app/App.tsx';
    export {regsData} from './web/regs.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return ui = await import(pathToFileURL(out).href);
}
const MARK = {id: 'spot:x', name: 'x', kind: 'Reef mark', reading: '', source: '', basis: ''};
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
async function card(d, target = 'reef') {
  const m = await load();
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL(`https://s.test/map?region=morro-bay&target=${target}`);
  m.markData.value = {region: {...REGION, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  m.regsData.value = {region: 'morro-bay', data: d};
  return m.render(m.h(m.RulesLine, {mark: MARK}));
}

test('the mark card renders the label beside an official link in every case', async t => {
  await load();
  // Keep the check and render on the same Pacific day, even near midnight.
  t.mock.timers.enable({apis: ['Date'], now: NOW});
  const now = Date.now();
  const none = data(now - HOUR); delete none.checks['rules-groundfish'].data_retrieved_at;
  const cases = [[data(now - HOUR), 'Checked today'], [data(now - 30 * HOUR), /^Checked [A-Z][a-z]{2} \d{1,2}$/], [none, 'Check date unknown'], [data(now - 40 * HOUR), 'Check overdue - open the official page']];
  for (const [d, expected] of cases) {
    const html = await card(d), shown = html.match(/class="app-mark-regs-fresh[^"]*" data-state="([^"]+)">([^<]+)</);
    assert.ok(shown, html);
    if (expected instanceof RegExp) assert.match(shown[2], expected); else assert.equal(shown[2], expected);
    const href = html.match(/<a href="([^"]+)" target="_blank" rel="noopener" aria-label="Official groundfish rules[^"]*">Official groundfish rules<\/a>/)?.[1];
    assert.ok(href, 'the official link is always present');
    assert.ok(REGION.regulatory_authority_hosts.includes(new URL(href.replace(/&amp;/g, '&')).hostname), href);
  }
  assert.match(await card(data(now - 40 * HOUR)), /Check rules/, 'a stale rule keeps "Check rules"');
  assert.doesNotMatch(text(await card(data(now - 40 * HOUR))), /Checked today|Verified/);
});

test('a link label with markup renders as text', async () => {
  const d = data(Date.now() - HOUR); d.species.salmon.name = '<img src=x onerror=alert(1)>';
  const html = await card(d, 'salmon');
  assert.doesNotMatch(html, /<img/);
  assert.match(html, />Official &lt;img src=x onerror=alert\(1\)> rules</);
  assert.match(html, /app-mark-regs-fresh/);
});

test('the plan view\'s rules card shows the same label and official link', async () => {
  const m = await load(), d = data(NOW - HOUR);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&profile=boat&view=plan&target=reef');
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles', center: [35, -121], rules: REGION};
  m.regsData.value = {region: 'morro-bay', data: d};
  const html = m.render(m.h(m.TargetRules, {now: new Date(NOW)}));
  assert.match(html, /app-plan-rules-fresh" data-state="checked-today">Checked today</);
  assert.match(html, /href="https:\/\/wildlife\.ca\.gov[^"]*"[^>]*>Official groundfish rules</);
  d.checks['rules-groundfish'].data_retrieved_at = new Date(NOW - 40 * HOUR).toISOString();
  assert.match(m.render(m.h(m.TargetRules, {now: new Date(NOW)})), /data-state="stale">Check overdue - open the official page</);
  m.regsData.value = null;
  assert.match(m.render(m.h(m.TargetRules, {now: new Date(NOW)})), /data-state="unknown">Check date unknown</);
});
