// The mark card's regulations line (FE-54, docs/plans/front-end/dev-plan.md; design § 6, § 9, § 12):
// web/regs.ts restates dist/regulations.js's state and "rules at a glance" row with the region passed
// in; these tests pin it to v1's output over frozen FE-61 registry and region inputs with
// fresh synthetic source checks, as tests/test_regulations.mjs builds it, plus synthetic edits for an
// opening time, a latitude band and a depth line), including #396's guard against inherited ids, and
// render the card's line. web/regs.ts runs by type stripping; the card is bundled with esbuild.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {createHash} from 'node:crypto';
import {CDFW_OCEAN, loadRegs, officialURL, regsData, regulationState, ruleProfile, ruleSummary, validRegulations, verifiedText} from '../web/regs.ts';

const ROOT = new URL('..', import.meta.url).pathname;
// Both inputs affect the historical digests: species/order, rules, source ids/URLs,
// jurisdiction, timezone and authority hosts must not follow generated dist data.
const fixtureBytes = readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url));
const fixture = JSON.parse(fixtureBytes);
const MORRO = fixture.region;
const ORIGINAL = fixture.regulations;
test('the frozen v1 oracle inputs retain their reviewed identity', () => {
  assert.equal(createHash('sha256').update(fixtureBytes).digest('hex'),
    '5c170912135231fa42aab6918694e8947fa08dd2287ce3caf45a05d0e46ecda3');
  assert.equal(fixture.provenance.commit, 'db50a71da352c2b06c3e736067a1677be17328c7');
});
const NOW = Date.parse('2026-09-21T18:00:00Z');
const HOUR = 3600000;
function data(at = NOW) {
  const d = structuredClone(ORIGINAL);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
/** Synthetic windows v1 supports that the frozen registry does not use. */
function edited(at = NOW) {
  const d = data(at), band = d.species.salmon.source_ids[0];
  d.species.salmon.windows = [{start: '2026-09-21', end: '2026-09-30', start_at: '2026-09-21T05:00:00-07:00'}];
  d.species.halibut.windows = [{start: '2026-01-01', end: '2026-12-31', geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: band, note: 'Synthetic band.'}}];
  d.species.halibut.source_ids = [band, ...d.species.halibut.source_ids.filter(s => s !== band)];
  d.species.lingcod.windows = [{start: '2026-04-01', end: '2026-12-31', access: 'shoreward-50fm'}];
  d.species.bluefin.windows = [{start: '2026-01-01', end: '2026-12-31', restriction: 'Synthetic restriction text.'}];
  return d;
}
const IDS = [...Object.keys(ORIGINAL.species), 'reef'];
const INHERITED = ['constructor', 'toString', '__proto__', 'hasOwnProperty', '', 'unsupported-target'];
const fields = s => ({status: s.status, label: s.label, today: s.today, reason: s.reason, issues: s.issues});
// FE-61 deleted dist/regulations.js with the v1 shell. Its output over these cases is
// pinned by digest (state fields and row, in loop order), computed from v1 before the deletion.
// SP-RULES-STATUS departs from v1 on purpose in exactly 50 grid rows: an unknown state with fresh,
// reviewed checks (outside the rule period, or a latitude-band season with no location) no longer
// carries `verified`; that date moves to `checked`. Every state field is still v1's. v1's own grid
// digest was 2a00529fc1145ddaf4d3b74ee98130a4ccb7274b3f579e7301e7eba85a2d2a7b.
const V1_DIGEST = {grid: 'e48a0a7730896a7b4fae6a4000d565c264a0361778a397889ff72c7e2e4a5cdc', evidence: '9845ca291ad962d581d162241d51f0cd41dcf147405a061ea8fd05806235586b'};
const digest = rows => createHash('sha256').update(JSON.stringify(rows)).digest('hex');

test('state and row equal dist/regulations.js for every species, date and trip hour', () => {
  assert.ok(validRegulations(data(), MORRO), 'the frozen registry passes for Morro Bay');
  const dates = ['2026-09-21T18:00:00Z', '2026-09-21T11:00:00Z', '2026-09-21T13:00:00Z', '2026-10-01T06:59:00Z', '2026-10-01T07:00:00Z', '2026-11-07T08:00:00Z', '2027-01-01T08:00:00Z'];
  const rows = [];
  for (const build of [data, edited]) {
    for (const when of dates) {
      const at = Date.parse(when), d = build(at);
      for (const id of [...IDS, ...INHERITED]) {
        for (const [tripDate, tripInstant] of [[null, null], ['2026-09-21', null], ['2026-09-21', Date.parse('2026-09-21T11:30:00Z')], ['2026-09-21', Date.parse('2026-09-21T13:00:00Z')], ['2026-12-31', null]]) {
          const mine = regulationState(d, id, MORRO, at, tripDate, tripInstant);
          rows.push([fields(mine), ruleSummary(d, id, mine, MORRO)]);
        }
      }
    }
  }
  assert.equal(rows.length, 980);
  assert.equal(digest(rows), V1_DIGEST.grid);
});

test('stale, changed, unreviewed and out-of-period evidence withholds open exactly as v1 does', () => {
  const rows = [];
  for (const edit of [
    d => { d.checks['rules-salmon'].status = 'changed'; }, d => { delete d.checks['rules-groundfish']; }, d => { d.checks['rules-salmon'].source_status = 'retained'; },
    d => { d.sources['rules-salmon'].approved_content_sha256 = null; }, d => { d.checks['rules-salmon'].data_retrieved_at = '2026-09-19T00:00:00Z'; },
    d => { d.rules_review_status = 'pending'; }, d => { d.valid_through = '2026-09-20'; }, d => { d.schema_version = 2; },
  ]) {
    const d = data(); edit(d);
    for (const id of IDS) {
      const mine = regulationState(d, id, MORRO, NOW);
      rows.push([fields(mine), ruleSummary(d, id, mine, MORRO)]);
    }
  }
  assert.equal(digest(rows), V1_DIGEST.evidence);
});

test('#396: an inherited or unsupported target never borrows a record; the row links CDFW', () => {
  const d = data();
  for (const id of INHERITED) {
    assert.equal(ruleProfile(d, id, MORRO), null, id);
    const state = regulationState(d, id, MORRO, NOW), row = ruleSummary(d, id, state, MORRO);
    assert.equal(state.status, 'unknown', id);
    assert.deepEqual([row.bag, row.size, row.depth, row.verified, row.link], [[], [], null, null, CDFW_OCEAN], id);
  }
  const inherited = Object.create({borrowed: d.species.lingcod});
  Object.assign(inherited, d.species);
  assert.equal(regulationState({...d, species: inherited}, 'borrowed', MORRO, NOW).status, 'unknown');
});

test('every link is an official page: the region\'s authority hosts over https, else CDFW', () => {
  for (const [value, v1] of [['https://wildlife.ca.gov/x', 'https://wildlife.ca.gov/x'], ['http://wildlife.ca.gov/x', CDFW_OCEAN], ['https://user@wildlife.ca.gov/x', CDFW_OCEAN],
    ['https://example.com/x', CDFW_OCEAN], ['not a url', CDFW_OCEAN], ['https://www.ecfr.gov/y', 'https://www.ecfr.gov/y']])
    assert.equal(officialURL(value, MORRO), v1, value);
  const d = data();
  for (const id of IDS) assert.ok(MORRO.regulatory_authority_hosts.includes(new URL(ruleSummary(d, id, regulationState(d, id, MORRO, NOW), MORRO).link).hostname), id);
  assert.equal(ruleSummary(null, 'lingcod', regulationState(null, 'lingcod', MORRO, NOW), MORRO).link, CDFW_OCEAN, 'nothing loaded: CDFW\'s page');
});

test('loads the region\'s file, then the daily checks when as recent; another jurisdiction is refused', async () => {
  const committed = data(NOW - 48 * HOUR), daily = data(NOW);
  const answers = {'data/regulations.json': committed, '/api/daily?region=morro-bay&part=regulations': {schema_version: 1, part: 'regulations', region_id: 'morro-bay', generated_at: new Date(NOW).toISOString(), catch_probability: null, bite_score: null, regulations: daily}};
  const urls = [];
  const fetchFn = async url => { urls.push(url); return url in answers ? Response.json(answers[url]) : new Response('', {status: 404}); };
  regsData.value = null;
  await loadRegs(MORRO, fetchFn);
  assert.equal(urls[0], 'data/regulations.json');
  assert.equal(regsData.value?.region, 'morro-bay');
  assert.equal(regsData.value.data.checks['rules-groundfish'].data_retrieved_at, daily.checks['rules-groundfish'].data_retrieved_at, 'the daily checks replace the committed ones');
  regsData.value = null;
  await loadRegs({...MORRO, id: 'other', jurisdiction_id: 'california-other'}, fetchFn);
  assert.equal(regsData.value, null, 'a registry naming another jurisdiction never shows');
});

test('the card\'s line shows v1\'s row: status, bag, size, check date and the official link', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'regs-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RulesLine} from './web/app/MarkCard.tsx';
      export {markData} from './web/map/marks.ts';
      export {regsData} from './web/regs.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&target=reef');
  const d = data(Date.now());
  m.markData.value = {region: {...MORRO, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  m.regsData.value = {region: 'morro-bay', data: d};
  const mark = {id: 'spot:x', name: 'x', kind: 'Reef mark', reading: '', source: '', basis: ''};
  const html = m.render(m.h(m.RulesLine, {mark}));
  const row = ruleSummary(d, 'reef', regulationState(d, 'reef', MORRO, Date.now()), MORRO);
  const text = html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
  for (const part of [row.label, ...row.bag, ...row.size, verifiedText(row), row.linkLabel]) assert.ok(text.includes(part), `${part} in ${text}`);
  assert.match(html, new RegExp(`<a href="${row.link.replace(/[.?]/g, '\\$&')}" target="_blank" rel="noopener"`), 'the official link');
  assert.match(html, /aria-label="Rules at a glance: Lingcod &amp; rockfish"/);
  assert.doesNotMatch(text, /\b(?:hotspot|chance|odds|probab\w*|bite|guarantee\w*|you should|we recommend)\b/i, 'no advice or promise');
  for (const id of ['mpa:x', 'coastline:x', 'ais:x']) assert.equal(m.render(m.h(m.RulesLine, {mark: {...mark, id}})), '', `${id}: no rules line`);
  assert.equal(m.render(m.h(m.RulesLine, {mark: {...mark, withheld: true}})), '', 'a withheld mark keeps its own words');
  m.state.syncFromURL('https://s.test/map?region=morro-bay&target=constructor');
  assert.match(m.render(m.h(m.RulesLine, {mark})), /Check rules.*Official CDFW rules/s, '#396 in the card');
});
