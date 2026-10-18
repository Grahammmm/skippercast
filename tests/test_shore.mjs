// Shore runs, access points and guidance (FE-36, docs/plans/front-end/dev-plan.md):
// the priority and guidance (web/brief/shore.ts) and the Chart layer (web/map/shore.ts),
// read from the committed shore-habitat package and protected-area snapshot (offline).
// Synthetic clocks and one synthetic protected area stand in where the committed dates do not reach a case.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {BEACH_HEALTH_SOURCE, CDFW_RULES_URL, activeAlerts, beachNotices, rankRuns, shoreGuidance, shoreReviewLines, shoreShown, shoreStatus} from '../web/brief/shore.ts';
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
const NOW = Date.parse('2026-10-11T00:00:00Z');
const iso = ms => new Date(ms).toISOString();
const sentinel = readPalette(name => `token(${name})`);
const flush = () => new Promise(resolve => setImmediate(resolve));
const screenAt = (areas, now) => assessScreen({areas, checkedAt: iso(now - HOUR), live: false, closures: undefined}, now);
const READY = screenAt(SNAPSHOT.features, NOW);
/** Every clock current for 30 days from `now`. */
const clocks = now => ({reviewExpiresAt: iso(now + 30 * 24 * HOUR), accessReviewedAt: iso(now - 24 * HOUR), accessReviewExpiresAt: iso(now + 30 * 24 * HOUR),
  legalReviewedAt: iso(now - 24 * HOUR), legalReviewExpiresAt: iso(now + 30 * 24 * HOUR), checkedAt: iso(now - 24 * HOUR)});

test('priority: Current, No surf model, Hold and Blocked from protected areas and model coverage', () => {
  const run = clocks(NOW);
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: [], conditions: true}).label, 'Current');
  assert.equal(shoreStatus(run, {now: NOW, inside: [], conditions: true}).priority, 3);
  assert.equal(shoreStatus(run, {now: NOW, inside: [], conditions: false}).label, 'No surf model');
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: null, conditions: true}), {priority: 0, label: 'Hold', reasons: ['Protected-area check not current']});
  assert.equal(shoreShown(run, NOW), true);
  assert.equal(shoreShown({reviewExpiresAt: iso(NOW - 1)}, NOW), false, 'past its source review a run is not shown');
  const ranked = rankRuns([{name: 'B', status: {priority: 0}}, {name: 'C', status: {priority: 3}}, {name: 'A', status: {priority: 0}}]);
  assert.deepEqual(ranked.map(r => r.name), ['C', 'A', 'B']);
});

test('a marine alert or a county beach-health notice holds a run, as the original Fish rules do (#422)', () => {
  const run = clocks(NOW);
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: [], conditions: true, alerts: ['Small Craft Advisory']}),
    {priority: 0, label: 'Hold', reasons: ['Marine alert: Small Craft Advisory']});
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: [], conditions: false, notices: ['Synthetic Beach']}),
    {priority: 0, label: 'Hold', reasons: ['Beach-health notice: Synthetic Beach']});
  assert.deepEqual(shoreStatus(run, {now: NOW, inside: null, conditions: true, alerts: ['Gale Warning'], notices: ['Synthetic Beach']}).reasons,
    ['Protected-area check not current', 'Marine alert: Gale Warning', 'Beach-health notice: Synthetic Beach'], 'every hold reason is said');
  assert.equal(shoreStatus(run, {now: NOW, inside: ['Synthetic SMR'], conditions: true, alerts: ['Gale Warning']}).label, 'Blocked', 'Blocked still wins');
  assert.equal(shoreStatus(run, {now: NOW, inside: [], conditions: true, alerts: [], notices: []}).label, 'Current');

  const alert = (o = {}) => ({event: 'Small Craft Advisory', effective: iso(NOW - HOUR), expires: iso(NOW + HOUR), ...o});
  assert.equal(activeAlerts([alert()], 'a1', NOW).length, 1, 'in effect now, any area');
  assert.equal(activeAlerts([alert({areaIds: ['a1']})], 'a1', NOW).length, 1);
  assert.equal(activeAlerts([alert({areaIds: ['a2']})], 'a1', NOW).length, 0, 'another area');
  assert.equal(activeAlerts([alert({expires: iso(NOW - 1)})], 'a1', NOW).length, 0, 'expired');
  assert.equal(activeAlerts([alert({effective: iso(NOW + 23 * HOUR), expires: null})], 'a1', NOW).length, 1, 'starts within a day');
  assert.equal(activeAlerts([alert({effective: iso(NOW + 25 * HOUR)})], 'a1', NOW).length, 0, 'starts later');
  assert.equal(activeAlerts([alert({effective: 'not a date', expires: 'not a date'})], 'a1', NOW).length, 1, 'bad clocks count as in effect');

  const source = (o = {}) => ({id: BEACH_HEALTH_SOURCE, outcome: 'ok', fetchedAt: iso(NOW - HOUR), ...o});
  const beach = (status, areaId = 'a1') => ({areaId, name: `Beach ${status}`, status, url: 'https://example.org/beach'});
  const report = (o = {}) => ({sources: [source()], waterQuality: [beach('Advisory'), beach('Beach Open'), beach('Closed', 'a2'), beach('Warning')], ...o});
  assert.deepEqual(beachNotices(report(), 'a1', NOW).map(b => b.name), ['Beach Advisory', 'Beach Warning'], 'notices only, this area only');
  assert.deepEqual(beachNotices(report({sources: [source({fetchedAt: iso(NOW - 4 * HOUR)})]}), 'a1', NOW), [], 'a stale county source says nothing');
  assert.deepEqual(beachNotices(report({sources: [source({outcome: 'error'})]}), 'a1', NOW), []);
  assert.deepEqual(beachNotices(report({sources: []}), 'a1', NOW), []);
});

test('the Chart holds the runs of an area under a marine alert or beach notice', () => {
  const plain = shownRuns(PACKAGE, READY, null, NOW).find(r => r.status.label !== 'Blocked');
  assert.ok(plain, 'an unblocked run');
  const area = plain.run.properties.areaId;
  const base = {alerts: [], sources: [{id: BEACH_HEALTH_SOURCE, outcome: 'ok', fetchedAt: iso(NOW - HOUR)}], waterQuality: [], nearshore: []};
  const held = (report) => shownRuns(PACKAGE, READY, report, NOW).find(r => r.run.id === plain.run.id).status;
  assert.equal(held(base).label, 'No surf model');
  assert.deepEqual(held({...base, alerts: [{event: 'Gale Warning', effective: null, expires: iso(NOW + HOUR), areaIds: [area]}]}),
    {priority: 0, label: 'Hold', reasons: ['Marine alert: Gale Warning']});
  assert.deepEqual(held({...base, waterQuality: [{areaId: area, name: 'Synthetic Beach', status: 'Closed', url: 'https://example.org/b'}]}),
    {priority: 0, label: 'Hold', reasons: ['Beach-health notice: Synthetic Beach']});
  const card = runMark(shownRuns(PACKAGE, READY, {...base, alerts: [{event: 'Gale Warning', effective: null, expires: null}]}, NOW).find(r => r.run.id === plain.run.id), 'surfperch', NOW);
  assert.match(card.kind, /· Hold$/);
  assert.match(card.reading, /^Marine alert: Gale Warning\./, 'the card says why');
});

test('review dates never set guidance priority or imply current reviews', () => {
  const run = clocks(NOW);
  const expected = {priority: 3, label: 'Current', reasons: ['Protected-area check current; a fresh nearshore model sample covers this area']};
  for (const field of ['accessReviewExpiresAt', 'legalReviewExpiresAt', 'reviewExpiresAt']) {
    for (const end of [iso(NOW - 30 * 24 * HOUR), iso(NOW), iso(NOW + HOUR), 'not a date']) {
      const dated = {...run, [field]: end};
      assert.deepEqual(shoreStatus(dated, {now: NOW, inside: [], conditions: true}), expected, field + end);
      assert.equal(shoreStatus(dated, {now: NOW, inside: [], conditions: false}).label, 'No surf model');
      assert.deepEqual(shoreStatus(dated, {now: NOW, inside: ['Synthetic SMR'], conditions: true}),
        {priority: 0, label: 'Blocked', reasons: ['Inside Synthetic SMR']});
      assert.deepEqual(shoreStatus(dated, {now: NOW, inside: null, conditions: true}),
        {priority: 0, label: 'Hold', reasons: ['Protected-area check not current']});
    }
  }
  const allExpired = {...run, accessReviewExpiresAt: iso(NOW - HOUR), legalReviewExpiresAt: iso(NOW - HOUR), reviewExpiresAt: iso(NOW - HOUR)};
  assert.deepEqual(shoreStatus(allExpired, {now: NOW, inside: [], conditions: true}), expected);
  assert.doesNotMatch(expected.reasons[0], /reviews current/i);
});

test('committed expired access and rules dates remain visible without blanket Hold', () => {
  const runs = shownRuns(PACKAGE, READY, null, NOW);
  assert.equal(runs.length, PACKAGE.features.length);
  const unblocked = runs.filter(r => r.status.label !== 'Blocked');
  assert.ok(unblocked.length > 0);
  for (const r of unblocked) {
    assert.ok(Date.parse(r.run.properties.legalReviewExpiresAt) < NOW);
    assert.ok(Date.parse(r.run.properties.accessReviewExpiresAt) < NOW);
    assert.equal(r.status.label, 'No surf model', r.name);
    const card = runMark(r, 'surfperch', NOW);
    assert.match(card.reading, /rules checked Oct 2, 2026, review expired Oct 3, 2026/);
    assert.match(card.basis, /check the current CDFW rules/);
    assert.match(card.basis, /Review dates remain historical context/);
    assert.match(card.reading, /Access checked Oct 2, 2026, review expired Oct 9, 2026/);
    assert.match(card.basis, /Ranking does not establish legal permission/);
    assert.doesNotMatch(card.basis, /held when a review expires/);
  }
});

test('Accept 1: access expiry does not hold guidance; source publication visibility stays enforced', () => {
  const access = Date.parse(PACKAGE.features[0].properties.accessReviewExpiresAt);
  for (const now of [access - 2 * HOUR, access, access + HOUR]) {
    const runs = shownRuns(PACKAGE, screenAt(SNAPSHOT.features, now), null, now);
    assert.equal(runs.length, PACKAGE.features.length);
    for (const r of runs) assert.ok(['No surf model', 'Blocked'].includes(r.status.label), r.name);
  }
  const late = Date.parse(PACKAGE.features[0].properties.reviewExpiresAt) + HOUR;
  assert.deepEqual(shownRuns(PACKAGE, screenAt(SNAPSHOT.features, late), null, late), [], 'source publication visibility remains separate from guidance priority');
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
  const card = runMark(r, 'surfperch', NOW);
  assert.match(card.kind, /^Shore run · (No surf model|Blocked)$/);
  assert.match(card.reading, /Access checked .+, review (until|expired) .+ · rules checked .+ · source review until/);
  assert.equal(shoreReviewLines(r.run.properties).includes('Oct'), true);
  // P5: a lapsed access or rules review says expired instead of a past "review until" date.
  const clocks = {accessReviewedAt: '2026-10-03T02:48:10Z', accessReviewExpiresAt: '2026-10-10T02:48:10Z', legalReviewedAt: '2026-10-03T02:43:19Z',
    legalReviewExpiresAt: '2026-10-04T02:43:19Z', reviewExpiresAt: '2026-11-02T02:48:10Z'};
  assert.equal(shoreReviewLines(clocks, Date.parse('2026-10-12T13:00:00Z')),
    'Access checked Oct 2, 2026, review expired Oct 9, 2026 · rules checked Oct 2, 2026, review expired Oct 3, 2026 · source review until Nov 1, 2026');
  assert.match(shoreReviewLines(clocks, Date.parse('2026-10-03T12:00:00Z')), /review until Oct 9, 2026 · rules checked Oct 2, 2026, review until Oct 3/);
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
