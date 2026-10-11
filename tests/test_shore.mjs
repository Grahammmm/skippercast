// Shore runs, access points and guidance (FE-36, docs/plans/front-end/dev-plan.md):
// the priority and guidance (web/brief/shore.ts) and the Chart layer (web/map/shore.ts),
// read from the committed shore-habitat package and protected-area snapshot (offline).
// Synthetic clocks and one synthetic protected area stand in where the committed dates do not reach a case.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {CDFW_RULES_URL, RECHECK_WINDOW_MS, rankRuns, shoreGuidance, shoreReviewLines, shoreShown, shoreStatus} from '../web/brief/shore.ts';
import {assessScreen, CHECKING} from '../web/map/habitat.ts';
import {layerEntry} from '../web/map/layers.ts';
import {markScreen} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';
import {SEAFLOOR_CELLS} from '../web/map/seafloor.ts';
import {
  ACCESS_HIT, ACCESS_PIN, ACCESS_SOURCE, RUNS_HIT, RUNS_LINE, RUNS_SOURCE, createShore, insideAreas, runMark, shoreCollections, shoreOverlay, shoreState, shoreURL, shownRuns,
} from '../web/map/shore.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const PACKAGE = json('dist/regions/morro-bay/shore-habitat.geojson');
const REGION = json('dist/regions/morro-bay/region.json');
const SNAPSHOT = json(`dist/${REGION.assets.protected_areas}`);
const HOUR = 3_600_000;
const NOW = Date.parse('2026-10-09T18:00:00Z');
const iso = ms => new Date(ms).toISOString();
const sentinel = readPalette(name => `token(${name})`);
const flush = () => new Promise(resolve => setImmediate(resolve));
const screenAt = (areas, now) => assessScreen({areas, checkedAt: iso(now - HOUR), live: false, closures: undefined}, now);
const READY = screenAt(SNAPSHOT.features, NOW);
/** Every clock current for 30 days from `now`. */
const clocks = now => ({reviewExpiresAt: iso(now + 30 * 24 * HOUR), accessReviewedAt: iso(now - 24 * HOUR), accessReviewExpiresAt: iso(now + 30 * 24 * HOUR),
  legalReviewedAt: iso(now - 24 * HOUR), legalReviewExpiresAt: iso(now + 30 * 24 * HOUR), checkedAt: iso(now - 24 * HOUR)});

test('priority: Current, No surf model, Recheck soon, Hold and Blocked from the clocks, the protected-area check and the nearshore model', () => {
  const run = clocks(NOW);
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: [], conditions: true}).label, 'Current');
  assert.equal(shoreStatus(run, {now: NOW, inside: [], conditions: true}).priority, 3);
  assert.equal(shoreStatus(run, {now: NOW, inside: [], conditions: false}).label, 'No surf model');
  const soon = {...run, accessReviewExpiresAt: iso(NOW + RECHECK_WINDOW_MS - HOUR)};
  assert.deepEqual(shoreStatus(soon, {now: NOW, inside: [], conditions: true}), {priority: 1, label: 'Recheck soon', reasons: ['Access review ends within 24 h']});
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: null, conditions: true}), {priority: 0, label: 'Hold', reasons: ['Protected-area check not current']});
  assert.equal(shoreStatus({...run, accessReviewExpiresAt: 'not a date'}, {now: NOW, inside: [], conditions: true}).label, 'Hold', 'an unreadable clock holds');
  assert.equal(shoreShown(run, NOW), true);
  assert.equal(shoreShown({reviewExpiresAt: iso(NOW - 1)}, NOW), false, 'past its source review a run is not shown');
  const ranked = rankRuns([{name: 'B', status: {priority: 0}}, {name: 'C', status: {priority: 3}}, {name: 'A', status: {priority: 0}}]);
  assert.deepEqual(ranked.map(r => r.name), ['C', 'A', 'B']);
});

test('rules-review age alone does not set priority or claim all reviews are current', () => {
  const run = clocks(NOW);
  const expected = shoreStatus(run, {now: NOW, inside: [], conditions: true});
  for (const end of [iso(NOW - 30 * 24 * HOUR), iso(NOW), iso(NOW + HOUR), 'not a date']) {
    const dated = {...run, legalReviewExpiresAt: end};
    assert.deepEqual(shoreStatus(dated, {now: NOW, inside: [], conditions: true}), expected, end);
    assert.equal(shoreStatus(dated, {now: NOW, inside: [], conditions: false}).label, 'No surf model');
    assert.deepEqual(shoreStatus(dated, {now: NOW, inside: ['Synthetic SMR'], conditions: true}),
      {priority: 0, label: 'Blocked', reasons: ['Inside Synthetic SMR']});
    assert.equal(shoreStatus(dated, {now: NOW, inside: null, conditions: true}).label, 'Hold');
    assert.equal(shoreStatus({...dated, accessReviewExpiresAt: iso(NOW)}, {now: NOW, inside: [], conditions: true}).label, 'Hold');
    assert.equal(shoreStatus({...dated, reviewExpiresAt: iso(NOW)}, {now: NOW, inside: [], conditions: true}).label, 'Hold');
  }
  assert.match(expected.reasons[0], /^Access and source reviews current;/);
  assert.doesNotMatch(expected.reasons[0], /^Reviews current/);
});

test('committed expired rules dates remain visible without blanket Hold', () => {
  const runs = shownRuns(PACKAGE, READY, null, NOW);
  assert.equal(runs.length, PACKAGE.features.length);
  const unblocked = runs.filter(r => r.status.label !== 'Blocked');
  assert.ok(unblocked.length > 0);
  for (const r of unblocked) {
    assert.ok(Date.parse(r.run.properties.legalReviewExpiresAt) < NOW);
    assert.ok(['Recheck soon', 'No surf model'].includes(r.status.label), r.name);
    const card = runMark(r, 'surfperch');
    assert.match(card.reading, /rules checked Oct 2, 2026, review until Oct 3, 2026/);
    assert.match(card.basis, /check the current CDFW rules/);
    assert.match(card.basis, /Rules-review dates are context only/);
    assert.match(card.basis, /Ranking does not establish legal permission/);
    assert.doesNotMatch(card.basis, /held when a review expires/);
  }
});

test('Accept 1: an expired access review drops the run to "Hold"', () => {
  const pkg = PACKAGE;
  const access = Date.parse(PACKAGE.features[0].properties.accessReviewExpiresAt);
  const before = shownRuns(pkg, screenAt(SNAPSHOT.features, access - 2 * HOUR), null, access - 2 * HOUR);
  assert.ok(before.length > 0);
  for (const r of before) assert.ok(['Recheck soon', 'Blocked'].includes(r.status.label), `${r.name} is not held before its access review ends`);
  const after = shownRuns(pkg, screenAt(SNAPSHOT.features, access + HOUR), null, access + HOUR);
  const held = after.filter(r => r.status.label !== 'Blocked');
  assert.ok(held.length > 0);
  for (const r of held) {
    assert.equal(r.status.label, 'Hold', r.name);
    assert.equal(r.status.priority, 0);
    assert.ok(r.status.reasons.includes('Access review expired'));
  }
  // Past the source review the run is not drawn at all.
  const late = Date.parse(PACKAGE.features[0].properties.reviewExpiresAt) + HOUR;
  assert.deepEqual(shownRuns(pkg, screenAt(SNAPSHOT.features, late), null, late), []);
});

test('Accept 2: a run inside a protected area is blocked and loses its access pins', () => {
  const pkg = PACKAGE;
  const target = pkg.features[0], [lon, lat] = target.geometry.coordinates[0][0];
  const d = 0.002, box = {type: 'Feature', properties: {NAME: 'Synthetic SMR'}, geometry: {type: 'Polygon', coordinates: [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]]}};
  const screen = screenAt([box], NOW);
  assert.deepEqual(insideAreas(target, screen), ['Synthetic SMR']);
  assert.equal(insideAreas(target, CHECKING), null, 'no answer while the check is not current');
  const runs = shownRuns(pkg, screen, null, NOW);
  const blocked = runs.find(r => r.run.id === target.id);
  assert.deepEqual(blocked.status, {priority: 0, label: 'Blocked', reasons: ['Inside Synthetic SMR']});
  const {access, runs: lines} = shoreCollections(runs);
  assert.equal(access.features.filter(f => f.properties.id === target.id).length, 0, 'no access pin on a blocked run');
  assert.ok(access.features.length > 0, 'the other runs keep theirs');
  assert.equal(lines.features.find(f => f.properties.id === target.id).properties.held, 1, 'drawn muted');
  assert.doesNotMatch(runMark(blocked, 'surfperch').reading, /Public access/);
});

test('a protected access point blocks a run even with an expired rules review', () => {
  const target = PACKAGE.features[0];
  const [lon, lat] = target.properties.access[0].coordinates;
  const d = 0.00001;
  const box = {type: 'Feature', properties: {NAME: 'Synthetic access restriction'}, geometry: {type: 'Polygon',
    coordinates: [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]]}};
  const screen = screenAt([box], NOW);
  assert.deepEqual(insideAreas({...target, properties: {...target.properties, access: []}}, screen), [], 'line is outside');
  assert.deepEqual(insideAreas(target, screen), ['Synthetic access restriction']);
  const runs = shownRuns(PACKAGE, screen, null, NOW);
  const blocked = runs.find(r => r.run.id === target.id);
  assert.equal(blocked.status.label, 'Blocked');
  assert.equal(shoreCollections(runs).access.features.filter(f => f.properties.id === target.id).length, 0);
});

test('the card shows review dates, method guidance and the official rules link, and never promises fish', () => {
  const [r] = shownRuns(PACKAGE, READY, null, NOW);
  const card = runMark(r, 'surfperch');
  assert.match(card.kind, /^Shore run · (No surf model|Recheck soon|Blocked)$/);
  assert.match(card.reading, /Access checked .+, review until .+ · rules checked .+ · source review until/);
  assert.equal(shoreReviewLines(r.run.properties).includes('Oct'), true);
  assert.deepEqual(card.regulations, {href: CDFW_RULES_URL, label: 'Official CDFW regional rules'});
  for (const target of ['surfperch', 'halibut', 'lingcod']) {
    const text = [shoreGuidance(target).text, runMark(r, target).basis].join(' ');
    assert.match(text, /Fish presence is unverified/);
    assert.doesNotMatch(text, /hot ?spot|probab|bite|guarantee|will catch|best spot|%/i, target);
  }
  assert.match(shoreGuidance('halibut').text, /size and bag limits apply/);
});

test('the overlay: a soft --amber run tinted by priority, muted on hold, and pins with 44 px targets', () => {
  const o = shoreOverlay(sentinel, shoreCollections(shownRuns(PACKAGE, READY, null, NOW)));
  assert.deepEqual(o.layers.map(l => l.id), [RUNS_HIT, RUNS_LINE, ACCESS_HIT, ACCESS_PIN]);
  assert.deepEqual(Object.keys(o.sources), [RUNS_SOURCE, ACCESS_SOURCE]);
  const line = o.layers.find(l => l.id === RUNS_LINE).paint;
  assert.deepEqual(line['line-color'], ['case', ['==', ['get', 'held'], 1], 'token(muted)', 'token(amber)']);
  assert.ok(line['line-opacity'].includes(0.6));
  assert.equal(o.layers.find(l => l.id === ACCESS_HIT).paint['circle-radius'], 22);
  assert.equal(o.layers.find(l => l.id === RUNS_HIT).paint['line-width'] >= 22, true);
  const entry = layerEntry('shore-runs');
  assert.deepEqual(entry.presentations, ['chart']);
  assert.deepEqual(entry.sources, [RUNS_SOURCE, ACCESS_SOURCE]);
  assert.equal(entry.gate, 'profile = shore');
});

test('Accept 3: visible only with profile=shore', async t => {
  globalThis.location = {href: 'https://s.test/map?region=morro-bay&profile=boat'};
  configureStore({v2: true, storage: null});
  syncFromURL(location.href);
  const asked = [], calls = [];
  const fetchFn = async url => { const path = new URL(url).pathname.slice(1); asked.push(path); return {ok: true, json: async () => json(`dist/${path}`)}; };
  const engine = signal({setOverlay: (layer, o, before) => calls.push(['overlay', layer, o && o.layers.map(l => l.id), before ?? null]),
    setData: (id, data) => calls.push(['data', id, data.features.length])});
  markScreen.value = READY;
  const shore = createShore({engine, fetchFn, page: () => location.href, palette: () => sentinel, now: () => NOW, report: signal(null)});
  t.after(() => { shore.destroy(); markScreen.value = CHECKING; });
  await flush(); await flush();
  assert.deepEqual(asked, [], 'Boat never loads shore runs');
  assert.equal(calls.some(c => c[2]), false, 'and draws none');
  syncFromURL('https://s.test/map?region=morro-bay&profile=shore');
  await flush(); await flush();
  assert.deepEqual(asked, [shoreURL('morro-bay')]);
  assert.deepEqual(calls.find(c => c[0] === 'overlay' && c[2]), ['overlay', 'shore-runs', [RUNS_HIT, RUNS_LINE, ACCESS_HIT, ACCESS_PIN], SEAFLOOR_CELLS]);
  assert.equal(shoreState.value.drawn, PACKAGE.features.length);
  const id = PACKAGE.features[0].id;
  assert.equal(shore.pick.mark(RUNS_HIT, {id}).id, `shore:${id}`);
  syncFromURL('https://s.test/map?region=morro-bay&profile=spear');
  await flush();
  assert.deepEqual(calls.at(-1), ['overlay', 'shore-runs', null, null]);
  assert.equal(shoreState.value.drawn, 0);
  assert.equal(shore.pick.mark(RUNS_HIT, {id}), null);
});
