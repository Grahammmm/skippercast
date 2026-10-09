// The reef marks' run-time screen (#489): v1 checks every atlas mark again in the browser
// against the current protected-area boundaries and the region's closures, and withholds a
// mark inside one, or every mark while that check is unavailable or more than 36 hours old
// (dist/protected-areas.js). v2 keeps that rule in web/map/habitat.ts and loads its inputs in
// web/map/marks.ts. Offline: the region files are the committed dist/ copies; the live ds582
// query and the Worker's /api/daily answer from fixtures built here, with synthetic squares
// (an invented reserve or groundfish exclusion area) drawn around chosen marks.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {validDailyPart as v1DailyPart} from '../dist/daily-feed.js';
import {MPA_QUERY, initProtectedAreas, validMPAs} from '../dist/protected-areas.js';
import {acceptsFeed as v1Accepts, getRegion, setRegion} from '../dist/region.js';
import {
  CHECKING, SCREEN_MAX_AGE_MS, SCREEN_NOTES, acceptsFeed, assessScreen, closureCheckedAt, freshCheck, validDailyPart, withheld, withheldCard,
} from '../web/map/habitat.ts';
import {MARKS_SOURCE, SELECTION_SOURCE} from '../web/map/layers.ts';
import {createMarks, markNote, markScreen, markSources, spotCard} from '../web/map/marks.ts';
import {CDFW_MPA_PAGE, MPA_SERVICE, NOAA_GEA_PAGE, loadMpas, mpaQuery, validMpas} from '../web/map/mpa.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const PAGE = 'https://s.test/map';
const HOUR = 3600000;
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const MORRO = read('regions/morro-bay/region.json'), ATLAS = read('data/atlas.json'), MPAS = read('data/protected-areas.geojson');
const SOCAL = read('regions/southern-california/region.json'), SOCAL_ATLAS = read('regions/southern-california/atlas.json');
const SOCAL_MPAS = read('regions/southern-california/protected-areas.geojson'), GEAS = read('regions/southern-california/groundfish-exclusions.geojson');
const iso = ms => new Date(ms).toISOString();
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
/** Words that would read a mark as cleared to fish. */
const VERDICT = /\b(?:allowed|permitted|legal to|you may|you can|open to fishing|clear of|safe to)\b/i;

// Synthetic areas: a square around a mark, or one with a corner exactly on it (v1 counts boundary contact as inside).
const square = ({longitude: x, latitude: y}, d = 0.001) => ({type: 'Polygon', coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]});
const corner = ({longitude: x, latitude: y}, d = 0.001) => ({type: 'Polygon', coordinates: [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]]});
const reserve = (geometry, NAME = 'Test Reef') => ({type: 'Feature', properties: {NAME: `${NAME} SMR`, FULLNAME: `${NAME} State Marine Reserve`, Type: 'SMR', CCR: 'Section 632(b)'}, geometry});
const exclusion = (geometry, NAME = 'Test Bank') => ({type: 'Feature', properties: {NAME, FULLNAME: `${NAME} Groundfish Exclusion Area`, Type: 'GEA', CCR: 'NOAA groundfish closure'}, geometry});
const withAreas = (collection, ...extra) => ({...collection, features: [...collection.features, ...extra]});

const ok = body => ({ok: true, status: 200, json: async () => body});
const down = status => ({ok: false, status, json: async () => ({})});
/**
 * The site and the services the screen asks, offline: dist/ files (`patch` replaces some by path), the live ds582 query
 * (`live`: its answer, null when it fails, or a function of the query area) and the Worker's daily parts (`daily`:
 * part → record; a missing part answers 503).
 */
function site({live = null, daily = {}, patch = {}} = {}) {
  return async url => {
    const at = new URL(String(url), PAGE);
    if (at.origin + at.pathname === MPA_SERVICE) {
      const answer = typeof live === 'function' ? live(at.searchParams.get('geometry')) : live;
      return answer ? ok(answer) : down(503);
    }
    if (at.pathname === '/api/daily') {
      const part = at.searchParams.get('part');
      return part in daily ? ok({schema_version: 1, region_id: at.searchParams.get('region'), part, generated_at: iso(Date.now()),
        catch_probability: null, bite_score: null, sources: {[part]: daily[part]}}) : down(503);
    }
    const path = at.pathname.slice(1);
    if (path in patch) return ok(patch[path]);
    return existsSync(new URL(`../dist/${path}`, import.meta.url)) ? ok(read(path)) : down(404);
  };
}
const record = (hoursAgo, data, status = 'ok') => ({status, data_retrieved_at: iso(Date.now() - hoursAgo * HOUR), data});

/**
 * v1's screen over the same answers: initProtectedAreas and its startup refresh, with a fake Leaflet and status line.
 * v1 reads its active region on every check, so `region` stays active until the caller restores Morro Bay.
 */
async function v1Screen(region, fetchFn) {
  const saved = {fetch: globalThis.fetch, L: globalThis.L, document: globalThis.document};
  setRegion(region);
  globalThis.fetch = fetchFn;
  globalThis.L = {layerGroup: () => ({addTo() { return this; }, clearLayers() {}}), geoJSON: () => ({bindTooltip() { return this; }, bindPopup() { return this; }, addTo() { return this; }})};
  globalThis.document = {getElementById: () => ({textContent: '', classList: {toggle() {}}}), dispatchEvent() {}};
  try {
    const screen = await initProtectedAreas({createPane: () => ({style: {}}), getZoom: () => 10}, () => {});
    await screen.refresh();
    return screen;
  } finally {
    Object.assign(globalThis, saved);
  }
}

/** The v2 page at `region` with its marks loaded. */
async function v2Marks(region, fetchFn, options = {}) {
  const href = `${PAGE}?region=${region}&target=reef`;
  globalThis.location = {href};
  globalThis.history = {state: null, pushState(_s, _t, url) { location.href = url; }, replaceState(_s, _t, url) { location.href = url; }};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  const marks = createMarks({fetchFn, page: () => PAGE, resolver: async () => ({resolveHabitatSelection: async () => null}), ...options});
  await settle();
  return marks;
}

/** Runs both screens over one fixture; returns the marks v1 withholds after checking v2 withholds exactly those. */
async function parity(region, atlas, answers) {
  const v1 = await v1Screen(region, site(answers));
  const marks = await v2Marks(region.id, site(answers));
  try {
    assert.equal(getRegion().id, region.id, 'v1 checks against its active region');
    assert.equal(markScreen.value.status === 'ready', v1.ready(), `${region.id}: ready`);
    for (const t of atlas.targets) assert.equal(!withheld(t, markScreen.value), v1.pointAllowed(t), `${region.id} ${t.id}`);
    return atlas.targets.filter(t => !v1.pointAllowed(t)).map(t => t.id);
  } finally { marks.destroy(); setRegion(MORRO); }
}

test('the rules v2 restates are v1\'s: the live query, the snapshot count, the daily feed part and the region check', () => {
  assert.equal(mpaQuery(MORRO.mpa.bounds), MPA_QUERY, 'v1 evaluates its query for the default region, Morro Bay');
  for (const data of [MPAS, {...MPAS, features: MPAS.features.slice(0, 7)}, {...MPAS, exceededTransferLimit: true}, null, {error: {code: 400}}]) {
    assert.equal(validMpas(data, MORRO.mpa.minimum_features), validMPAs(data));
  }
  assert.equal(validMpas(MPAS, undefined), false, 'no minimum, nothing passes (as v1)');
  const part = {schema_version: 1, region_id: 'morro-bay', part: 'mpa-boundaries', generated_at: '2026-10-09T00:00:00Z', catch_probability: null, bite_score: null, sources: {}};
  const variants = [part, {...part, region_id: undefined}, {...part, region_id: 'big-sur-coast'}, {...part, part: 'regulations'}, {...part, sources: []},
    {...part, generated_at: 'soon'}, {...part, bite_score: 0}, {...part, schema_version: 2}, null];
  for (const region of [MORRO, SOCAL]) {
    for (const [i, d] of variants.entries()) {
      assert.equal(validDailyPart(d, 'mpa-boundaries', region.id), v1DailyPart(d, 'mpa-boundaries', region), `${region.id} variant ${i}`);
      assert.equal(acceptsFeed(d, region.id), v1Accepts(d, region), `${region.id} variant ${i}`);
    }
  }
});

test('a snapshot that fails to load fails the closures the region names', async () => {
  const noSnapshot = url => (String(url).endsWith('protected-areas.geojson') ? down(503) : site()(url));
  assert.equal((await loadMpas('southern-california', noSnapshot, PAGE)).screen.closures, null);
  assert.equal((await loadMpas('morro-bay', noSnapshot, PAGE)).screen.closures, undefined, 'none named, none failed');
  assert.equal((await loadMpas('southern-california', async () => down(503), PAGE)).screen.closures, undefined, 'unknown before region.json loads');
});

test('a check counts for 36 hours and from 5 minutes ahead; the screen says why it withholds', () => {
  const now = Date.parse('2026-10-09T12:00:00Z');
  assert.equal(freshCheck(iso(now - SCREEN_MAX_AGE_MS), now), true);
  assert.equal(freshCheck(iso(now - SCREEN_MAX_AGE_MS - 1), now), false);
  assert.equal(freshCheck(iso(now + 5 * 60000), now), true);
  assert.equal(freshCheck(iso(now + 5 * 60000 + 1), now), false, 'a check from the future is no check');
  assert.equal(freshCheck(null, now), false);
  assert.equal(assessScreen(null, now), CHECKING);
  assert.equal(CHECKING.note, 'Checking protected areas before showing fishing spots…');

  const live = {areas: MPAS.features, checkedAt: iso(now - HOUR), live: true};
  const ready = assessScreen(live, now);
  assert.equal(ready.status, 'ready');
  assert.equal(ready.note, 'Reef marks inside protected areas are withheld · boundaries checked this session');
  assert.equal(ready.source, 'CDFW ds582 checked this session');
  assert.equal(ready.until, now - HOUR + SCREEN_MAX_AGE_MS, 'goes stale when the check passes 36 hours');
  assert.equal(ready.boundaries.length, MPAS.features.length);
  const snapshot = assessScreen({...live, live: false}, now);
  assert.equal(snapshot.note, 'Reef marks inside protected areas are withheld · boundary snapshot 2026-10-09');
  const stale = assessScreen({...live, checkedAt: iso(now - 37 * HOUR)}, now);
  assert.deepEqual([stale.status, stale.note, stale.boundaries], ['stale', SCREEN_NOTES.stale, []]);
  assert.equal(SCREEN_NOTES.stale, 'Boundary check stale; fishing targets withheld', 'v1\'s words');
  const none = assessScreen({areas: null, checkedAt: null, live: false}, now);
  assert.deepEqual([none.status, none.note, none.source], ['unavailable', 'Protected-area check unavailable · fishing spots withheld', 'CDFW ds582 check unavailable']);

  // The region's closures, where it names any, need their own current check.
  const closures = {areas: GEAS.features, checkedAt: iso(now - 2 * HOUR), sha256: GEAS.source_sha256};
  const both = assessScreen({...live, closures}, now);
  assert.equal(both.note, 'Reef marks inside protected areas or groundfish exclusions are withheld · boundaries checked this session');
  assert.equal(both.boundaries.length, MPAS.features.length + GEAS.features.length);
  assert.ok(both.boundaries.filter(b => b.federal).length === GEAS.features.length, 'the NOAA areas are federal');
  assert.equal(both.until, now - 2 * HOUR + SCREEN_MAX_AGE_MS, 'the older check decides');
  assert.equal(assessScreen({...live, closures: null}, now).status, 'stale', 'closures named but failed: withheld');
  const old = assessScreen({...live, closures: {...closures, checkedAt: iso(now - 40 * HOUR)}}, now);
  assert.deepEqual([old.status, old.source], ['stale', `CDFW ds582 checked this session · NOAA closures checked ${iso(now - 40 * HOUR).slice(0, 10)}`]);

  // v1's closure refresh: the daily check of NOAA's file renews the time while its hash matches, a changed file voids it.
  const at = '2026-10-09T10:00:00Z';
  assert.equal(closureCheckedAt(closures, {status: 'ok', data_retrieved_at: at, data: {sha256: GEAS.source_sha256}}), at);
  assert.equal(closureCheckedAt(closures, {status: 'ok', data_retrieved_at: at, data: {sha256: 'f'.repeat(64)}}), null);
  assert.equal(closureCheckedAt(closures, {status: 'retained', data_retrieved_at: at, data: {sha256: GEAS.source_sha256}}), closures.checkedAt);
  assert.equal(closureCheckedAt(closures, null), closures.checkedAt);
  assert.equal(closureCheckedAt({...closures, sha256: null}, {status: 'ok', data_retrieved_at: at, data: {}}), null, 'no hash, no renewal');
  for (const s of [CHECKING, ready, both, stale, none, old]) assert.doesNotMatch(`${s.note} ${s.source}`, VERDICT);
});

test('parity with v1\'s screen: the same answers withhold the same marks', async t => {
  t.mock.method(console, 'warn', () => {});
  const [first, other] = [ATLAS.targets.find(x => x.id === 'SC26-001'), ATLAS.targets[40]];
  // A live check that finds a new reserve over one mark and another touching a second mark's position.
  assert.deepEqual(await parity(MORRO, ATLAS, {live: withAreas(MPAS, reserve(square(first)), reserve(corner(other), 'Corner'))}), [first.id, other.id].sort());
  // Without the live query, the daily feed's boundary record decides while it is current.
  assert.deepEqual(await parity(MORRO, ATLAS, {daily: {'mpa-boundaries': record(2, {geojson: MPAS})}}), []);
  const all = ATLAS.targets.map(x => x.id);
  assert.deepEqual(await parity(MORRO, ATLAS, {daily: {'mpa-boundaries': record(40, {geojson: MPAS})}}), all, 'a 40-hour-old record withholds every mark');
  assert.deepEqual(await parity(MORRO, ATLAS, {daily: {'mpa-boundaries': record(2, {geojson: MPAS}, 'retained')}}), all, 'only a fresh "ok" record counts');
  assert.deepEqual(await parity(MORRO, ATLAS, {daily: {'mpa-boundaries': {status: 'ok', data: {geojson: MPAS}}}}), all, 'a record without its retrieval time is no check');
  assert.deepEqual(await parity(MORRO, ATLAS, {}), all, 'no check at all: the committed snapshot is weeks old');
  // Southern California also names NOAA's groundfish exclusion areas.
  const mark = SOCAL_ATLAS.targets[0], closures = withAreas(GEAS, exclusion(square(mark)));
  const answers = check => ({live: SOCAL_MPAS, daily: {'additional-closures': check}, patch: {[SOCAL.assets.closures]: closures}});
  assert.deepEqual(await parity(SOCAL, SOCAL_ATLAS, answers(record(1, {sha256: GEAS.source_sha256}))), [mark.id]);
  const allSocal = SOCAL_ATLAS.targets.map(x => x.id);
  assert.deepEqual(await parity(SOCAL, SOCAL_ATLAS, answers(record(1, {sha256: 'f'.repeat(64)}))), allSocal, 'NOAA changed the file: every mark withheld');
  assert.deepEqual(await parity(SOCAL, SOCAL_ATLAS, {live: SOCAL_MPAS}), allSocal, 'no closure check: the file\'s own time is weeks old');
});

test('a mark inside a closure is hidden; a link to it says why and links NOAA\'s page', async t => {
  t.mock.method(console, 'warn', () => {});
  const [mark, kept] = SOCAL_ATLAS.targets;
  const fetchFn = site({live: SOCAL_MPAS, daily: {'additional-closures': record(1, {sha256: GEAS.source_sha256})},
    patch: {[SOCAL.assets.closures]: withAreas(GEAS, exclusion(square(mark)))}});
  const marks = await v2Marks('southern-california', fetchFn);
  const shown = markSources[MARKS_SOURCE].value.features.map(f => f.properties.id);
  assert.ok(!shown.includes(mark.id), 'the mark inside the closure is not drawn');
  assert.ok(shown.includes(kept.id), 'the others are');
  assert.equal(markNote.value, 'Reef marks inside protected areas or groundfish exclusions are withheld · boundaries checked this session');

  setParams({spot: mark.id});
  const card = spotCard.value;
  assert.equal(card.name, 'Reef mark withheld');
  assert.equal(card.reading, 'Inside Test Bank Groundfish Exclusion Area');
  assert.equal(card.rules, 'NOAA groundfish closure. SkipperCast excludes all target species here as a conservative planning rule. Federal regulations control over this supplemental map.');
  assert.deepEqual(card.regulations, {href: NOAA_GEA_PAGE, label: 'NOAA groundfish closed areas'});
  assert.match(card.source, /^CDFW ds582 checked this session · NOAA closures checked \d{4}-\d{2}-\d{2}$/);
  assert.deepEqual(markSources[SELECTION_SOURCE].value.features, [], 'a withheld mark is never outlined');
  assert.doesNotMatch(`${card.kind} ${card.reading}`, /\d+\.\d{3}/, 'never its position');
  setParams({spot: kept.id});
  assert.match(spotCard.value.rules, /^Screened against protected areas with \d+ m clearance/, 'a mark that shows keeps its own card');
  assert.equal(markSources[SELECTION_SOURCE].value.features.length, 1);
  marks.destroy();

  // A mark inside a state reserve reads v1's protected-area words and links CDFW.
  const first = ATLAS.targets.find(x => x.id === 'SC26-001');
  const morro = await v2Marks('morro-bay', site({live: withAreas(MPAS, reserve(square(first)))}));
  setParams({spot: first.id});
  assert.equal(spotCard.value.reading, 'Inside Test Reef State Marine Reserve');
  assert.equal(spotCard.value.rules, 'SkipperCast withholds fishing targets in all mapped protected areas, including conservation areas that allow some activities. Consult the exact official rules.');
  assert.deepEqual(spotCard.value.regulations, {href: CDFW_MPA_PAGE, label: 'CDFW marine protected areas'});
  assert.doesNotMatch(Object.values(spotCard.value).join(' '), VERDICT);
  morro.destroy();
  const checking = withheldCard(first, withheld(first, CHECKING), CHECKING);
  assert.deepEqual([checking.name, checking.reading, checking.source], ['Checking reef mark', 'Checking protected areas before showing fishing spots…', 'CDFW ds582 check in progress']);
});

test('stale closure input hides every mark and says why; a region change checks again', async t => {
  t.mock.method(console, 'warn', () => {});
  const live = area => (area === SOCAL.mpa.bounds.join(',') ? SOCAL_MPAS : null);
  const changed = await v2Marks('southern-california', site({live, daily: {'additional-closures': record(1, {sha256: 'f'.repeat(64)})}}));
  assert.equal(markScreen.value.status, 'stale');
  assert.deepEqual(markSources[MARKS_SOURCE].value.features, [], 'NOAA changed its file since the published closures: nothing shows');
  assert.equal(markNote.value, 'Boundary check stale; fishing targets withheld');
  setParams({spot: SOCAL_ATLAS.targets[0].id});
  assert.equal(spotCard.value.reading, 'Boundary check stale; fishing targets withheld');
  assert.equal(spotCard.value.source, 'CDFW ds582 checked this session · NOAA closures check unavailable');
  assert.equal(spotCard.value.rules, 'Check current rules and boundaries before you fish.');
  assert.equal(spotCard.value.regulations.href, CDFW_MPA_PAGE);
  setParams({region: 'morro-bay', spot: null});
  assert.equal(markScreen.value, CHECKING, 'a new region starts checking at once');
  assert.deepEqual(markSources[MARKS_SOURCE].value.features, []);
  await settle();
  assert.equal(markScreen.value.status, 'stale', 'no check came back, and the committed snapshot is weeks old');
  assert.equal(markNote.value, 'Boundary check stale; fishing targets withheld');
  assert.equal(markScreen.value.source, 'CDFW ds582 checked 2026-09-21');
  changed.destroy();

  // No boundaries at all: the check is unavailable.
  const none = await v2Marks('morro-bay', site({patch: {[MORRO.assets.protected_areas]: {type: 'FeatureCollection', features: []}}}));
  assert.deepEqual([markScreen.value.status, markNote.value], ['unavailable', 'Protected-area check unavailable · fishing spots withheld']);
  none.destroy();
  assert.equal(markScreen.value, CHECKING);

  // A region whose atlas has no marks for the target says nothing about them.
  const cambria = await v2Marks('cambria-san-simeon', site());
  assert.equal(markNote.value, '');
  cambria.destroy();
});

test('a current screen goes stale when its check passes 36 hours, and the marks go with it', async t => {
  t.mock.method(console, 'warn', () => {});
  let clock = Date.now();
  t.mock.timers.enable({apis: ['setTimeout']});
  const marks = await v2Marks('morro-bay', site({daily: {'mpa-boundaries': record(35, {geojson: MPAS})}}), {now: () => clock});
  assert.equal(markScreen.value.status, 'ready');
  assert.ok(markSources[MARKS_SOURCE].value.features.length > 0);
  assert.equal(markNote.value, `Reef marks inside protected areas are withheld · boundary snapshot ${iso(clock - 35 * HOUR).slice(0, 10)}`);
  clock += HOUR + 1000;
  t.mock.timers.tick(HOUR + 1000);
  assert.equal(markScreen.value.status, 'stale');
  assert.deepEqual(markSources[MARKS_SOURCE].value.features, []);
  marks.destroy();
});

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'screen-')), 'screen.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MpaRow} from './web/app/Legend.tsx';
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {markData, markScreen} from './web/map/marks.ts';
      export {assessScreen} from './web/map/habitat.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

test('the legend row stays one line while marks show; a withheld screen adds its own line; a withheld card offers no trip', async () => {
  const {MpaRow, MarkCard, markData, markScreen: screen, assessScreen: assess, state, render, h} = await components();
  state.configureStore({v2: true, storage: null});
  state.syncFromURL(`${PAGE}?region=morro-bay&target=reef&spot=${ATLAS.targets[0].id}`);
  markData.value = {region: MORRO, atlas: ATLAS, survey: null, geology: null};
  // Current: the screen's line sits in the row's basis, so the row keeps its height (one .app-mpa-note at most).
  screen.value = assess({areas: MPAS.features, checkedAt: iso(Date.now() - HOUR), live: true}, Date.now());
  const ready = render(h(MpaRow, {}));
  assert.match(ready, /<div class="ui-popover-body">.*<p data-reason="marks">Reef marks inside protected areas are withheld · boundaries checked this session<\/p><\/div><\/details>/s);
  assert.doesNotMatch(ready, /app-mpa-marks/);
  assert.match(render(h(MarkCard, {})), /<div class="app-mark-actions"><button type="button" class="ui-button ui-button--ghost ui-button--sm">(?:(?!<\/button>).)*(?:Add to trip|Save research reference)<\/button>/s, 'a mark that shows joins a trip');
  // Stale: a visible line of its own, outside .app-mpa-note.
  screen.value = assess({areas: MPAS.features, checkedAt: iso(Date.now() - 40 * HOUR), live: false}, Date.now());
  const stale = render(h(MpaRow, {}));
  assert.match(stale, /<p class="app-mpa-marks" data-reason="marks">Boundary check stale; fishing targets withheld<\/p>/);
  assert.equal(stale.match(/data-reason="marks"/g).length, 1);
  assert.doesNotMatch(stale, /class="app-mpa-note" data-reason/);
  const card = render(h(MarkCard, {}));
  assert.match(card, /<h2 tabindex="-1">Reef mark withheld<\/h2>/);
  assert.match(card, /<button disabled type="button" class="ui-button ui-button--ghost ui-button--sm">(?:(?!<\/button>).)*Add to trip<\/button>/s, 'no trip for a withheld mark');
  assert.match(card, /<button disabled type="button" class="ui-button ui-button--ghost ui-button--sm">(?:(?!<\/button>).)*GPX<\/button>/s);
  assert.match(card, new RegExp(`<a class="ui-button ui-button--ghost ui-button--sm" href="${CDFW_MPA_PAGE}" target="_blank" rel="noopener" aria-label="Regulations: CDFW marine protected areas \\(official page, opens in a new tab\\)">`));
  markData.value = {region: MORRO, atlas: {...ATLAS, targets: []}, survey: null, geology: null};
  assert.doesNotMatch(render(h(MpaRow, {})), /data-reason="marks"/, 'no marks, no line');
  markData.value = null;
});
