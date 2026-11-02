import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {seasonYear} from '../web/season.ts';
const root = new URL('..', import.meta.url).pathname;
const region = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url))).region;
const committed = JSON.parse(readFileSync(new URL('../dist/data/regulations.json', import.meta.url)));
function data(year = 2026) {
  const d = structuredClone(committed);
  d.rules_review_status = 'reviewed';
  d.valid_from = `${year}-01-01`; d.valid_through = `${year}-12-31`;
  for (const p of Object.values(d.species)) p.windows = [{start: d.valid_from, end: d.valid_through}];
  return d;
}
const month = (d, m, species = 'lingcod', year = 2026) => seasonYear(d, species, region, year).months[m - 1];
test('committed dates never extrapolate earlier months or next year; December 31 is included', () => {
  const s = seasonYear(committed, 'lingcod', region, 2026);
  assert.equal(s.months.length, 12);
  assert.ok(s.months.slice(0, 9).every(m => m.state === 'not-reviewed'));
  assert.ok(s.months.slice(9).every(m => m.state === 'open'));
  assert.equal(s.revision, committed.reviewed_at);
  assert.ok(s.link.href.startsWith('https://wildlife.ca.gov/'));
  assert.ok(seasonYear(committed, 'lingcod', region, 2027).months.every(m => m.state === 'not-reviewed'));
  const d = data(); d.valid_from = '2026-09-21'; d.valid_through = '2026-09-21';
  assert.equal(month(d, 9).state, 'not-reviewed', '21st is reviewed, other days are not');
  d.valid_from = '2026-09-01'; d.valid_through = '2026-09-30';
  assert.equal(month(d, 9).state, 'open', 'both period endpoints are inclusive');
});
test('window edges, first open run, no open days, and all restriction states', () => {
  const d = data(), p = d.species.lingcod;
  p.windows = [{start: '2026-01-01', end: '2026-01-15'}];
  assert.equal(month(d, 1).label, 'Part open: 1–15');
  assert.equal(month(d, 1).state, 'part');
  assert.equal(month(d, 2).state, 'closed');
  p.windows.push({start: '2026-01-20', end: '2026-01-25'});
  assert.equal(month(d, 1).label, 'Part open: 1–15', 'first run, not the last or their union');
  p.windows = [{start: d.valid_from, end: d.valid_through, restriction: 'Synthetic limits'}];
  assert.equal(month(d, 1).state, 'limits'); assert.equal(month(d, 1).label, 'Open · limits');
  p.windows[0].requires_opening_review = true;
  assert.equal(month(d, 1).state, 'scheduled'); assert.equal(month(d, 1).label, 'Opener unconfirmed');
  p.windows[0].end = '2026-01-15';
  assert.equal(month(d, 1).label, 'Mixed', 'scheduled does not mean open');
  p.windows = [{start: d.valid_from, end: d.valid_through, geography: {kind: 'latitude-band', south: 34, north: 36, source_id: p.source_ids[0], note: 'Synthetic area'}}];
  assert.equal(month(d, 1).state, 'area'); assert.equal(month(d, 1).label, 'Choose fishing location');
  p.windows = [{start: d.valid_from, end: d.valid_through, start_at: '2026-01-01T08:00:00Z'}];
  assert.equal(month(d, 1).state, 'part', 'a timed opener is not all-day open');
});
test('reef uses the worse member each day, including geography and scheduled review', () => {
  const d = data(); d.species.rockfish.windows = [];
  assert.equal(month(d, 1, 'reef').state, 'closed');
  d.species.rockfish.windows = [{start: d.valid_from, end: d.valid_through, requires_opening_review: true}];
  assert.equal(month(d, 1, 'reef').state, 'scheduled');
  d.species.rockfish.windows[0] = {start: d.valid_from, end: d.valid_through, restriction: 'Synthetic limits'};
  assert.equal(month(d, 1, 'reef').state, 'limits');
  d.species.lingcod.windows = [];
  assert.equal(month(d, 1, 'reef').state, 'closed');
  d.species.rockfish.windows[0].geography = {kind: 'latitude-band', south: 34, north: 36, source_id: d.species.rockfish.source_ids[0], note: 'Synthetic area'};
  assert.equal(month(d, 1, 'reef').state, 'area');
});
test('mixed reviewed states with unreviewed days are mixed, not a fabricated closed month', () => {
  const d = data(); d.valid_from = '2026-01-10';
  d.species.lingcod.windows = [{start: '2026-01-10', end: '2026-01-15'}];
  assert.equal(month(d, 1).state, 'part'); assert.equal(month(d, 1).label, 'Part open: 10–15');
  for (const status of ['pending', 'changed', undefined]) {
    d.rules_review_status = status;
    assert.ok(seasonYear(d, 'lingcod', region, 2026).months.every(m => m.state === 'not-reviewed'));
  }
});
test('invalid registry, inherited or missing target, and invalid year fail closed', () => {
  for (const edit of [d => { delete d.checks; }, d => { d.valid_from = '2026-02-30'; }, d => { d.species.lingcod.windows[0].start = 'invalid'; }]) {
    const d = data(); edit(d); assert.equal(seasonYear(d, 'lingcod', region, 2026), null);
  }
  for (const id of ['missing', '__proto__', 'constructor', 'toString']) assert.equal(seasonYear(data(), id, region, 2026), null);
  assert.equal(seasonYear(null, 'lingcod', region, 2026), null);
  for (const y of [NaN, 2026.5, -1]) assert.equal(seasonYear(data(), 'lingcod', region, y), null);
});
test('leap day, final day, and civil dates across LA DST do not slip into UTC dates', () => {
  const d = data(2028); d.species.lingcod.windows = [{start: '2028-02-29', end: '2028-02-29'}];
  assert.equal(month(d, 2, 'lingcod', 2028).label, 'Part open: 29–29');
  d.species.lingcod.windows = [{start: '2028-12-31', end: '2028-12-31'}];
  assert.equal(month(d, 12, 'lingcod', 2028).label, 'Part open: 31–31');
  d.species.lingcod.windows = [{start: '2028-03-12', end: '2028-03-13'}];
  assert.equal(month(d, 3, 'lingcod', 2028).label, 'Part open: 12–13');
});
test('strip has twelve word-labelled cells, safe link and no promises; Conditions uses the region year and shown target', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'season-')), out = join(dir, 'render.mjs');
  try {
    await build({stdin: {resolveDir: root, loader: 'ts', contents: `
      export {SeasonStrip} from './web/app/SeasonStrip.tsx';
      export {Conditions} from './web/app/views/Conditions.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {regsData} from './web/regs.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href), d = data();
    const render = props => m.render(m.h(m.SeasonStrip, {data: d, species: 'lingcod', region, year: 2026, ...props}));
    const html = render({});
    assert.equal((html.match(/<li\b/g) ?? []).length, 12);
    assert.match(html, /aria-label="Lingcod season 2026"/);
    assert.equal((html.match(/<span>Open<\/span>/g) ?? []).length, 12);
    assert.match(html, /From the reviewed rules \(revision/); assert.match(html, /Not legal advice/);
    assert.doesNotMatch(html, /\b(?:best|hot|bite|guarantee)/i);
    assert.equal(render({data: null}), ''); assert.equal(render({species: 'constructor'}), '');
    d.sources[d.species.lingcod.source_ids[0]].url = 'https://example.com/untrusted';
    assert.doesNotMatch(render({}), /href="https:\/\/example.com/);
    m.state.configureStore({v2: true, storage: null});
    m.state.syncFromURL('https://s.test/map?region=morro-bay&view=conditions&target=lingcod');
    m.regionInfo.value = {id: 'morro-bay', timezone: 'America/Los_Angeles', rules: {...region, id: 'morro-bay'}}; m.regsData.value = {region: 'morro-bay', data: d};
    const view = () => m.render(m.h(m.Conditions, {now: new Date('2027-01-01T07:30:00Z')}));
    assert.match(view(), /aria-label="Lingcod season 2026"/, 'still December 31 in LA');
    m.state.syncFromURL('https://s.test/map?region=morro-bay&view=conditions&target=rockfish');
    assert.match(view(), /aria-label="Rockfish \/ rock cod season 2026"/);
    m.regsData.value = {region: 'other', data: d};
    assert.doesNotMatch(view(), /class="app-season"/); assert.match(view(), /Current CDFW ocean fishing rules/);
  } finally { await rm(dir, {recursive: true, force: true}); }
});
