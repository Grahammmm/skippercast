// BF-why-this-area: up to three dated one-line reasons per ranked area, from the records the ranker read, each with its source.
// reasonsFor is pure; the view test renders the real WhereToLook against the committed atlas. Offline.
import assert from 'node:assert/strict';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {assessScreen} from '../web/map/habitat.ts';
import {ranking} from '../web/ranking.ts';
import {MAX_REASONS, NO_REASONS, reasonsFor, targetEvidence} from '../web/area-reasons.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const ATLAS = read('data/atlas.json');
const DATA = {region: {...read('regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: ATLAS, survey: null, geology: null};
const NOW = Date.parse('2026-11-03T20:00:00Z');
const rec = (patch = {}) => ({area: 'A', kind: 'report', text: 'Reported lingcod nearby.', date: '2026-10-30', source: 'Landing report', ...patch});

test('the same syndicated report counts once: under two feed ids, two source names, or two copies of the same tuple', () => {
  const same = reasonsFor('A', [rec({id: 'r1', feed: 'feed-a', source: 'SoCalFishReports'}), rec({id: 'r1', feed: 'feed-b', source: 'socalfishreports.com'})], NOW);
  assert.equal(same.length, 1, 'one report id carried by two feeds under two spellings of its source');
  const tuple = reasonsFor('A', [rec({species: 'lingcod', feed: 'a', source: 'SoCalFishReports'}), rec({species: 'Lingcod', feed: 'b', source: 'socalfishreports.com'})], NOW);
  assert.equal(tuple.length, 1, 'no id: the (source, date, area, species) tuple decides');
  assert.equal(reasonsFor('A', [rec({id: 'r1'}), rec({id: 'r2'})], NOW).length, 1, 'distinct reports of one kind still show one reason per kind');
  const kinds = reasonsFor('A', [rec({id: 'r1', kind: 'a'}), rec({id: 'r2', kind: 'b'})], NOW);
  assert.equal(kinds.length, 2, 'different reports are different reasons');
  assert.equal(reasonsFor('A', [rec({source: 'One', kind: 'a'}), rec({source: 'Two', kind: 'b'})], NOW).length, 2, 'different sources without an id stay apart');
  assert.equal(reasonsFor('A', [rec({species: 'lingcod', kind: 'a'}), rec({species: 'rockfish', kind: 'b'})], NOW).length, 2, 'different species stay apart');
  assert.equal(reasonsFor('A', [rec({date: '2026-10-30', kind: 'a'}), rec({date: '2026-10-29', kind: 'b'})], NOW).length, 2, 'different dates stay apart');
});

test('the copy that stands never depends on feed order, and the copy with a link wins', () => {
  const a = rec({id: 'r1', source: 'Landing report', sourceURL: 'https://example.test/r1'}), b = rec({id: 'r1', source: 'Landing report'});
  assert.deepEqual(reasonsFor('A', [a, b], NOW), reasonsFor('A', [b, a], NOW));
  assert.equal(reasonsFor('A', [b, a], NOW)[0].sourceURL, 'https://example.test/r1');
});

test('otherwise identical copies choose the same canonical source link when feed order reverses', () => {
  const a = rec({id: 'r1', sourceURL: 'https://EXAMPLE.test:443/a'});
  const b = rec({id: 'r1', sourceURL: 'https://example.test/b'});
  const got = reasonsFor('A', [a, b], NOW);
  assert.deepEqual(reasonsFor('A', [b, a], NOW), got);
  assert.equal(got.length, 1);
  assert.equal(got[0].sourceURL, 'https://example.test/a');
});

test('four or more eligible reasons give exactly three, newest first, one per kind, the same whatever the input order', () => {
  const all = [rec({kind: 'survey', date: '2026-10-01', text: 'S', source: 'S1'}), rec({kind: 'screen', date: '2026-10-20', text: 'C', source: 'S2'}), rec({kind: 'report', date: '2026-10-30', text: 'R', source: 'S3'}),
    rec({kind: 'closure', date: '2026-10-10', text: 'L', source: 'S4'}), rec({kind: 'tide', date: '2026-10-20', text: 'T', source: 'S5'}), rec({kind: 'report', date: '2026-10-05', text: 'R older', source: 'S6'})];
  const got = reasonsFor('A', all, NOW);
  assert.equal(MAX_REASONS, 3);
  assert.deepEqual(got.map(r => r.text), ['R', 'C', 'T'], 'newest first; the 10-20 tie falls to the kind name; the older report of a kind is dropped');
  assert.deepEqual(got.map(r => r.date), ['2026-10-30', '2026-10-20', '2026-10-20']);
  for (const order of [[...all].reverse(), [...all.slice(3), ...all.slice(0, 3)], [all[4], all[0], all[5], all[2], all[1], all[3]]]) {
    assert.deepEqual(reasonsFor('A', order, NOW), got, 'deterministic on ties');
  }
  assert.equal(reasonsFor('A', all.slice(0, 2), NOW).length, 2, 'fewer than three shows fewer, with no filler');
});

test('a missing, malformed or future date is left out; a future date is never the newest', () => {
  for (const date of [undefined, null, '', 'yesterday', '2026-13-01', '2026-02-30', '2026-10-30x', '30/10/2026', NaN, {}, '2026-11-04', '2026-11-03T20:00:01Z', '2027', 2027, '1066-01-01']) {
    assert.deepEqual(reasonsFor('A', [rec({date})], NOW), [], `excluded: ${JSON.stringify(date)}`);
  }
  const got = reasonsFor('A', [rec({date: '2026-12-25', kind: 'a', text: 'future'}), rec({date: '2026-10-01', kind: 'b', text: 'past'})], NOW);
  assert.deepEqual(got.map(r => r.text), ['past']);
  assert.deepEqual(reasonsFor('A', [rec({date: '2026-11-03T19:59:59Z'})], NOW).map(r => r.date), ['2026-11-03'], 'a timestamp up to now counts, shown by its day');
  assert.deepEqual(reasonsFor('A', [rec({date: 2008})], NOW).map(r => r.date), ['2008'], 'a bare survey year is a usable date, shown as the year');
  for (const patch of [{text: ''}, {text: undefined}, {source: ''}, {source: 7}]) assert.deepEqual(reasonsFor('A', [rec(patch)], NOW), [], 'no text or no source is no reason');
});

test('an area absent from the evidence, or evidence that is not a list, is an empty list and never an error', () => {
  assert.deepEqual(reasonsFor('B', [rec()], NOW), []);
  for (const bad of [undefined, null, {}, 'x', 5, [null, undefined, 3, 'x']]) assert.deepEqual(reasonsFor('A', bad, NOW), []);
  assert.deepEqual(reasonsFor('', [rec({area: ''})], NOW), []);
  assert.deepEqual(reasonsFor('A', [rec({area: 'a'})], NOW), [], 'another area (even by case) never leaks in');
});

test('a source link is kept only when it is a plain https link; text and source stay raw for the view to render as text', () => {
  const link = url => reasonsFor('A', [rec({sourceURL: url})], NOW)[0].sourceURL;
  assert.equal(link('https://example.test/a'), 'https://example.test/a');
  for (const bad of ['javascript:alert(1)', 'http://example.test/', 'https://u:p@example.test/', 'data:text/html,x', '', null, 5, 'not a url']) assert.equal(link(bad), null, String(bad));
  const long = reasonsFor('A', [rec({text: `  ${'word '.repeat(80)}\n`})], NOW)[0].text;
  assert.ok(long.length <= 140 && long.endsWith('…') && !/\s{2}/.test(long), 'one line, bounded');
});

test('the reasons for an atlas mark and a published place come from the records the ranker read', () => {
  const mark = ATLAS.targets[0];
  const got = reasonsFor(mark.id, targetEvidence(mark, ATLAS, DATA.region.source_names), NOW);
  assert.deepEqual(got.map(r => r.date), [ATLAS.source_validation_date, String(mark.survey_year)], 'atlas check, then survey, newest first');
  assert.match(got[0].text, /^Passed the protected-area check with \d+ m clearance\.$/);
  assert.equal(got[1].text, mark.terrain_interpretation);
  assert.ok(got.every(r => r.source), 'every reason names its source');
  assert.equal(got[1].sourceURL, mark.source_url);
  const published = {id: 'reef-a', survey_year: 2008, source_url: 'https://example.test/s', terrain_interpretation: '12.0 m local relief; 2.0 ha reef footprint.', source_rights: [{credit: 'USGS'}]};
  assert.deepEqual(reasonsFor('reef-a', targetEvidence(published), NOW), [{text: published.terrain_interpretation, date: '2008', source: 'USGS', sourceURL: published.source_url}]);
  assert.deepEqual(reasonsFor('x', targetEvidence({id: 'x', source_id: 'S'}), NOW), [], 'no survey year and no check: nothing dated');
  assert.deepEqual(reasonsFor('x', targetEvidence({id: 'x', survey_year: 2008}), NOW), [], 'a record with no source name is not shown');
});

let view;
async function loadView() {
  if (view) return view;
  const out = join(await mkdtemp(join(tmpdir(), 'why-')), 'why.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {markData} from './web/map/marks.ts';
      export {reefPublication} from './web/ranking.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  view = await import(pathToFileURL(out).href);
  return view;
}
function browser(state, href) {
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(href);
}
const pick = (id, kind = 'spot') => ({id, kind, name: id, distance: '4.0 nm', depth: '~40–80 ft', fit: 'Fits lingcod habitat 3 of 3', reason: 'Terrain.', nm: 4, at: {latitude: 35.2, longitude: -120.9}, screen: {screened: true, inside: false, distanceM: null, name: null}});
const shown = (list, empty = '') => ({source: 'atlas', label: 'Survey reef atlas', basis: 'Basis.', picks: list, empty});

test('the view shows the selected area its dated reasons with sources, the explicit empty line without any, and nothing for other rows', async () => {
  const {WhereToLook, markData, state, render, h} = await loadView();
  const [a, b] = ATLAS.targets, bare = {...b, id: 'bare', survey_year: undefined, source_id: undefined, source_name: undefined, recorded_validation: undefined, qualification: undefined};
  markData.value = {...DATA, atlas: {...ATLAS, targets: [a, bare]}};
  browser(state, `https://s.test/map?region=morro-bay&spot=${a.id}`);
  const list = [pick(a.id), pick('bare'), pick('m-hab', 'habitat')];
  let html = render(h(WhereToLook, {ranking: shown(list)}));
  const [chunkA, chunkBare] = html.split('<li data-mark=').slice(1);
  assert.match(chunkA, /data-why="reasons"/);
  assert.equal((chunkA.match(/<li>/g) ?? []).length, 2);
  assert.ok(chunkA.includes(`<span class="ui-mono">${ATLAS.source_validation_date}</span>`) && chunkA.includes(`<span class="ui-mono">${a.survey_year}</span>`), 'each reason is dated');
  assert.match(chunkA, new RegExp(`<a href="${a.source_url.replace(/[.?]/g, '\\$&')}"[^>]*rel="noopener noreferrer"`), 'the source links out');
  assert.doesNotMatch(chunkBare, /data-why/, 'a row that is not selected shows no reasons');
  assert.equal((html.match(/data-why=/g) ?? []).length, 1);
  browser(state, 'https://s.test/map?region=morro-bay&spot=bare');
  html = render(h(WhereToLook, {ranking: shown(list)}));
  assert.ok(html.includes(`<p class="app-empty app-pick-why" data-why="none">${NO_REASONS}</p>`), 'a selected area with no dated evidence says so');
  assert.equal(NO_REASONS, 'No dated evidence for this area yet');
  browser(state, 'https://s.test/map?region=morro-bay&habitat=m-hab');
  html = render(h(WhereToLook, {ranking: shown(list)}));
  assert.ok(html.includes(NO_REASONS), 'a terrain-release place carries no dated record, so the empty line shows rather than filler');
  assert.doesNotMatch(html, /data-why="reasons"/);
  browser(state, 'https://s.test/map?region=morro-bay');
  assert.doesNotMatch(render(h(WhereToLook, {ranking: shown(list)})), /data-why/, 'nothing selected, nothing added');
  markData.value = null;
});

test('reason text and source names containing markup render as text', async () => {
  const {WhereToLook, markData, state, render, h} = await loadView();
  const evil = {...ATLAS.targets[0], id: 'evil', source_name: '<img src=x onerror=alert(1)>', terrain_interpretation: '<script>alert("x")</script> & <b>bold</b>', source_url: 'javascript:alert(1)'};
  markData.value = {...DATA, atlas: {...ATLAS, targets: [evil]}};
  browser(state, 'https://s.test/map?region=morro-bay&spot=evil');
  const html = render(h(WhereToLook, {ranking: shown([pick('evil')])}));
  assert.ok(html.includes('&lt;script>alert(&quot;x&quot;)&lt;/script> &amp; &lt;b>bold&lt;/b>'), 'the opening < of every tag is escaped, so none is a tag');
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)>'));
  const why = html.slice(html.indexOf('data-why'));
  assert.doesNotMatch(why, /<script|<img|<b>|javascript:|<a /, 'no tag, and an unsafe link is dropped');
  markData.value = null;
});

test('the ranked order is byte-identical, and the ranking does not read the reasons', async () => {
  const {WhereToLook, markData, state, render, h} = await loadView();
  const inputs = {region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, terrain: {state: 'unavailable'}, now: NOW, place: () => ({state: 'water'}),
    screen: assessScreen({areas: read('data/protected-areas.geojson').features, checkedAt: new Date(NOW).toISOString(), live: true}, NOW)};
  const before = JSON.stringify(ranking(inputs));
  const r = ranking(inputs);
  assert.ok(r.picks.length >= 2);
  markData.value = DATA;
  browser(state, `https://s.test/map?region=morro-bay&spot=${r.picks[0].id}`);
  const html = render(h(WhereToLook, {ranking: r}));
  assert.deepEqual([...html.matchAll(/data-mark="([^"]+)"/g)].map(m => m[1]), r.picks.map(p => p.id), 'the view lists the ranker\'s order');
  assert.equal(JSON.stringify(ranking(inputs)), before, 'ranking again, after reasons were computed, gives the same bytes');
  assert.equal(JSON.stringify(r), before);
  assert.doesNotMatch(await readFile(join(ROOT, 'web/ranking.ts'), 'utf8'), /area-reasons/);
  assert.doesNotMatch(await readFile(join(ROOT, 'web/area-reasons.ts'), 'utf8'), /\bfetch\b|\bimport\s/, 'pure: no source of its own');
  markData.value = null;
});
