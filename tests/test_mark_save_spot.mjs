// SC0022-05: "Save this spot" on the map mark card. The candidate is the mark's own name and position; the shared
// protected-area screen (SC0022-04: it must cover the point) answers before anything is sent; one POST for a clear
// place; every refusal and error is said in words; the card shows the action to a signed-in person only.
// Synthetic marks and areas only; the screen is the real initProtectedAreas over an offline answer.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {getRegion, setRegion} from '../dist/region.js';

const ROOT = new URL('..', import.meta.url).pathname;
const MORRO = JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8'));
setRegion(MORRO);

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-save-spot-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard, SaveSpotAction} from './web/app/MarkCard.tsx';
      export {SAVE_WORDS, boundName, saveMarkSpot, spotCandidate} from './web/saved-spots.ts';
      export {session} from './web/account.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

// A synthetic closure: a 0.01° square at (-121.0, 35.3) among eight far-away filler squares (the snapshot needs eight areas).
const CX = -121.0, CY = 35.3, HALF = 0.005, M_LAT = 111320, M_LON = 111320 * Math.cos(CY * Math.PI / 180);
const square = (x, y, d) => ({type: 'Polygon', coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]});
const area = (name, geometry) => ({type: 'Feature', properties: {NAME: name, FULLNAME: `${name} State Marine Reserve`, Type: 'SMR', CCR: 'Section 632(b)'}, geometry});
const areas = checkedAt => ({type: 'FeatureCollection', checked_at: checkedAt,
  features: [area('Synthetic Reef', square(CX, CY, HALF)), ...Array.from({length: 8}, (_, i) => area(`Filler ${i}`, square(-121.8 + i * 0.01, 35.8, 0.001)))]});
async function realScreen(checkedAt = new Date().toISOString()) {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => areas(checkedAt)});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}
const east = m => ({lat: CY, lon: CX + HALF + m / M_LON});
const loaded = screen => async id => ({state: 'loaded', region: id, screen});

const SIGNED_IN = Object.freeze({state: 'signed-in', name: null});
const mark = (lat, lon, over = {}) => ({id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'A reading', source: 'Source', basis: 'Basis', position: {latitude: lat, longitude: lon}, ...over});
const CLEAR = east(150);
const row = (spot, over = {}) => ({id: 'row-1', owner: 'x', ...spot, created_at: '2026-11-04T00:00:00Z', ...over});

/** A fetch that records every call and answers `answer(call)`; never the network. */
function spy(answer) {
  const calls = [];
  const fetchFn = async (url, init) => { calls.push({url: String(url), init}); return answer({url: String(url), init, n: calls.length}); };
  return {calls, fetchFn};
}
const reply = (status, body) => new Response(typeof body === 'string' ? body : JSON.stringify(body), {status, headers: {'Content-Type': 'application/json'}});
const created = ({init}) => reply(201, row(JSON.parse(init.body)));

async function setup(over = {}) {
  const {saveMarkSpot} = await components();
  const screen = over.screen ?? await realScreen();
  let who = over.session ?? SIGNED_IN, where = over.region ?? 'morro-bay';
  const refreshed = [];
  const run = (m, extra = {}) => saveMarkSpot(m, {session: () => who, region: () => where, loadScreen: loaded(screen), refresh: () => { refreshed.push(1); }, ...extra});
  return {run, refreshed, set: {session: s => { who = s; }, region: r => { where = r; }}, screen};
}

test('save_action_is_signed_in_only: absent while loading, offline, disabled or signed out; present with the privacy and cap words when signed in', async () => {
  const {SaveSpotAction, MarkCard, session, SAVE_WORDS, render, h} = await components();
  const m = mark(CLEAR.lat, CLEAR.lon);
  try {
    for (const s of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled'}, {state: 'signed-out'}]) {
      session.value = s;
      assert.equal(render(h(SaveSpotAction, {mark: m})), '', `${s.state}: nothing is drawn`);
      assert.doesNotMatch(render(h(MarkCard, {mark: m})), /Save this spot|Private to your account/, `${s.state}: not on the card`);
    }
    session.value = SIGNED_IN;
    const html = render(h(SaveSpotAction, {mark: m}));
    assert.match(html, />Save this spot<\/button>/);
    assert.ok(!/<button[^>]*disabled/.test(html), 'a clear candidate is enabled');
    assert.ok(html.includes(SAVE_WORDS.helper) && SAVE_WORDS.helper === 'Private to your account. You can keep up to 100 saved spots.');
    assert.match(html, /<p role="status"><\/p>/, 'a live status region');
    const card = render(h(MarkCard, {mark: m}));
    assert.ok(card.indexOf('Save this spot') > card.indexOf('app-mark-actions') && card.indexOf('Save this spot') < card.indexOf('app-mark-basis'), 'in the action row');
    // A mark that cannot be saved is disabled and says why, visibly.
    const ctx = render(h(SaveSpotAction, {mark: mark(35, -120, {id: 'geology:unit-1'})}));
    assert.match(ctx, /<button[^>]*disabled/);
    assert.ok(ctx.includes('This is map context, not a spot to save.'));
    session.value = {state: 'signed-out'};
    assert.equal(render(h(SaveSpotAction, {mark: m})), '', 'sign out removes it, with no payload or status left');
  } finally { session.value = {state: 'loading'}; }
});

test('candidate_uses_only_the_selected_mark_point: every positioned family, and none of the hidden, context or invalid ones', async () => {
  const {spotCandidate, boundName, SAVE_WORDS} = await components();
  for (const id of ['spot:SC26-001', 'survey:rock-1', 'habitat:reef:r1', 'reading:35.30000,-121.00000', 'trip:1', 'coastline:x', 'mpa:thing']) {
    assert.deepEqual(spotCandidate(mark(35.3, -121.0, {id, basis: 'B', source: 'S', rules: 'R', reading: 'secret reading'})), {name: 'Synthetic mark', lat: 35.3, lon: -121.0, note: null}, id);
  }
  assert.deepEqual(Object.keys(spotCandidate(mark(35.3, -121.0))).sort(), ['lat', 'lon', 'name', 'note'], 'no basis, source or rules fields');
  assert.deepEqual(spotCandidate(mark(0, 0)), {name: 'Synthetic mark', lat: 0, lon: 0, note: null}, 'zero is a position');
  for (const id of ['geology:u', 'charter:c', 'fleet:f']) assert.equal(spotCandidate(mark(35.3, -121.0, {id})).message, SAVE_WORDS.context, id);
  assert.equal(spotCandidate(mark(35.3, -121.0, {withheld: true, reading: 'This mark is inside a protected area.'})).message, 'This mark is inside a protected area. Not saved.');
  assert.equal(spotCandidate({id: 'spot:x', name: 'W', kind: '', reading: '', source: '', basis: '', withheld: true, position: {latitude: 35.3, longitude: -121.0}}).message, 'Not saved.');
  const w = spotCandidate(mark(35.31234, -121.04321, {withheld: true, reading: 'Withheld.'}));
  assert.ok(!JSON.stringify(w).includes('35.31234') && !JSON.stringify(w).includes('121.04321'), 'a withheld point is never revealed');
  const none = {id: 'habitat:x', name: 'N', kind: '', reading: '', source: '', basis: ''};
  for (const m of [none, {...none, position: {latitude: NaN, longitude: -121}}, {...none, position: {latitude: 35, longitude: Infinity}}, {...none, position: {latitude: 90.1, longitude: 0}},
    {...none, position: {latitude: 35, longitude: 180}}, {...none, position: {latitude: 35, longitude: -180.5}}, {...none, position: {latitude: '35', longitude: -121}}, {...none, id: 'spot:35.3,-121.0'}]) {
    assert.equal(spotCandidate(m).message, SAVE_WORDS.noPosition, JSON.stringify(m.position));
  }
  assert.equal(boundName('x'.repeat(100)).length, 80);
  assert.equal(boundName('é'.repeat(79) + '🐟'), 'é'.repeat(79), 'never half of a surrogate pair');
  assert.equal(boundName('é'.repeat(78) + '🐟'), 'é'.repeat(78) + '🐟');
  assert.equal(spotCandidate(mark(35.3, -121.0, {name: 'n'.repeat(79) + '🐟'})).name, 'n'.repeat(79));
});

test('refused_or_unchecked_mark_never_posts: inside, boundary, within 70 m, outside coverage, a missing or stale or wrong-region or unbounded screen', async () => {
  const {SAVE_WORDS} = await components();
  const {run} = await setup(), api = spy(created);
  const refuse = async (m, words, label, extra = {}) => {
    const r = await run(m, {fetchFn: api.fetchFn, ...extra});
    assert.deepEqual(r, {state: 'refused', message: words}, label);
  };
  assert.equal(SAVE_WORDS.notChecked, 'Protected areas not checked for this spot. Not saved.');
  await refuse(mark(CY, CX), 'Inside a protected area. Not saved.', 'inside');
  await refuse(mark(CY, CX + HALF), 'Inside a protected area. Not saved.', 'on the boundary');
  await refuse(mark(east(30).lat, east(30).lon), 'Within 70 m of a protected area. Not saved.', '30 m outside');
  await refuse(mark(east(60).lat, east(60).lon), SAVE_WORDS.margin, '60 m outside');
  await refuse(mark(36.5, -120.0), SAVE_WORDS.notChecked, 'outside the covered area');
  await refuse(mark(35.3, -120.55 - 30 / M_LON), SAVE_WORDS.notChecked, '30 m inside the raw query edge (the search halo is not covered)');
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a failed screen', {loadScreen: async () => ({state: 'failed'})});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a screen not started', {loadScreen: async () => ({state: 'idle'})});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a screen that throws', {loadScreen: async () => { throw new Error('boom'); }});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a screen loaded for another region', {loadScreen: async () => ({state: 'loaded', region: 'other-region', screen: await realScreen()})});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a legacy screen with no coverage method', {loadScreen: async id => ({state: 'loaded', region: id, screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true}})});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'a stale screen (older than 36 hours)', {loadScreen: loaded(await realScreen(new Date(Date.now() - 40 * 3600000).toISOString()))});
  await refuse(mark(CLEAR.lat, CLEAR.lon), SAVE_WORDS.notChecked, 'no region', {region: () => null});
  assert.equal(api.calls.length, 0, 'no refusal wrote anything');
  assert.ok(getRegion().id === 'morro-bay');
});

test('clear_mark_posts_once_and_confirms_private_row: the captured name, position and a null note to the one route', async () => {
  const {run, refreshed} = await setup(), api = spy(created);
  const r = await run(mark(CLEAR.lat, CLEAR.lon, {name: 'Synthetic mark 🐟', basis: 'PRIVATE-BASIS', rules: 'PRIVATE-RULES'}), {fetchFn: api.fetchFn});
  assert.deepEqual(r, {state: 'saved', message: 'Saved to your spots'});
  assert.equal(api.calls.length, 1);
  const [{url, init}] = api.calls;
  assert.equal(url, '/api/spots');
  assert.deepEqual(Object.keys(init).sort(), ['body', 'credentials', 'headers', 'method', 'signal']);
  assert.equal(init.method, 'POST'); assert.equal(init.credentials, 'same-origin'); assert.deepEqual(init.headers, {'Content-Type': 'application/json'});
  assert.ok(init.signal instanceof AbortSignal, 'a timeout');
  assert.deepEqual(JSON.parse(init.body), {name: 'Synthetic mark 🐟', lat: CLEAR.lat, lon: CLEAR.lon, note: null});
  assert.ok(!/PRIVATE/.test(init.body));
  assert.equal(refreshed.length, 0);
  // The point just beyond 70 m (80 m) is clear; 0 °N 0 °E would be outside coverage, not a refusal of the words.
  assert.equal((await run(mark(east(80).lat, east(80).lon), {fetchFn: spy(created).fetchFn})).state, 'saved');
});

test('save_errors_are_words_not_raw_payload: 401, the cap, validation, 403/429/500, bad JSON, timeout; never retried, never echoed', async () => {
  const {SAVE_WORDS} = await components();
  const SECRET = 'SECRET-SERVER-TEXT <b>x</b>';
  const m = mark(CLEAR.lat, CLEAR.lon);
  const outcome = async (answer, label) => {
    const s = await setup(), api = spy(answer), r = await s.run(m, {fetchFn: api.fetchFn});
    assert.equal(api.calls.length, 1, `${label}: never retried`);
    assert.ok(!JSON.stringify(r).includes('SECRET'), `${label}: no raw server text`);
    return {r, refreshed: s.refreshed.length};
  };
  let o = await outcome(() => reply(401, {error: SECRET}), '401');
  assert.deepEqual(o, {r: {state: 'failed', message: 'Sign in again to save this spot.'}, refreshed: 1});
  o = await outcome(() => reply(400, {error: 'you can keep at most 100 saved spots; remove one first'}), 'cap');
  assert.deepEqual(o.r, {state: 'failed', message: 'You can keep up to 100 saved spots. Remove one in Account before saving another.'});
  o = await outcome(() => reply(400, {error: `coordinates_out_of_range: ${SECRET}`}), 'validation');
  assert.deepEqual(o.r, {state: 'failed', message: 'This spot could not be saved. Check its name and position.'});
  o = await outcome(() => reply(400, 'not json'), 'validation with a bad body');
  assert.equal(o.r.message, SAVE_WORDS.invalid);
  for (const status of [403, 429, 500, 503, 200, 202, 204]) {
    o = await outcome(() => reply(status, {error: SECRET}), String(status));
    assert.deepEqual(o.r, {state: 'failed', message: 'Could not confirm this spot was saved. Check Saved spots in Account before trying again.'}, String(status));
    assert.equal(o.refreshed, 0);
  }
  // A 201 that is not this candidate's row is not a confirmation.
  const good = ({init}) => row(JSON.parse(init.body));
  for (const [label, answer] of [['bad JSON', () => reply(201, 'nope')], ['no id', a => reply(201, {...good(a), id: undefined})], ['empty id', a => reply(201, {...good(a), id: ''})],
    ['another position', a => reply(201, {...good(a), lat: good(a).lat + 0.001})], ['another name', a => reply(201, {...good(a), name: 'Other'})], ['an array', () => reply(201, [])], ['null', () => reply(201, 'null')]]) {
    assert.equal((await outcome(answer, label)).r.message, SAVE_WORDS.uncertain, label);
  }
  o = await outcome(() => { throw new TypeError(SECRET); }, 'network error');
  assert.equal(o.r.message, SAVE_WORDS.uncertain);
  o = await outcome(() => { throw new DOMException(SECRET, 'TimeoutError'); }, 'timeout');
  assert.equal(o.r.message, SAVE_WORDS.uncertain);
});

test('late_save_cannot_answer_another_card_or_account: a sign out, another account or another region before the write sends nothing', async () => {
  const {SAVE_WORDS} = await components();
  const m = mark(CLEAR.lat, CLEAR.lon);
  let s = await setup(), api = spy(created);
  let r = await s.run(m, {fetchFn: api.fetchFn, loadScreen: async id => { s.set.session({state: 'signed-out'}); return loaded(s.screen)(id); }});
  assert.deepEqual(r, {state: 'failed', message: SAVE_WORDS.signIn}); assert.equal(api.calls.length, 0, 'signed out while the screen loaded');
  s = await setup(); api = spy(created);
  r = await s.run(m, {fetchFn: api.fetchFn, loadScreen: async id => { s.set.session({state: 'signed-in', name: 'Someone else'}); return loaded(s.screen)(id); }});
  assert.deepEqual(r, {state: 'failed', message: SAVE_WORDS.changed}); assert.equal(api.calls.length, 0, 'another account while the screen loaded');
  s = await setup(); api = spy(created);
  r = await s.run(m, {fetchFn: api.fetchFn, loadScreen: async id => { s.set.region('santa-cruz-monterey-bay'); return loaded(s.screen)(id); }});
  assert.equal(r.state, 'refused'); assert.equal(api.calls.length, 0, 'region switched while the screen loaded');
  s = await setup(); api = spy(created);
  r = await s.run(m, {fetchFn: api.fetchFn, session: () => ({state: 'signed-out'})});
  assert.deepEqual(r, {state: 'failed', message: SAVE_WORDS.signIn}); assert.equal(api.calls.length, 0, 'signed out at the start: the screen is not even asked');
  // Two marks, one after the other: each is its own write of its own point (the id alone never decides).
  s = await setup(); api = spy(created);
  await s.run(mark(CLEAR.lat, CLEAR.lon), {fetchFn: api.fetchFn});
  await s.run(mark(east(200).lat, east(200).lon), {fetchFn: api.fetchFn});
  assert.deepEqual(api.calls.map(c => JSON.parse(c.init.body).lon), [CLEAR.lon, east(200).lon]);
});

test('save_spot_preserves_address_and_privacy: the save code has no address, history, share, storage, console, error-reporting or measurement path', async () => {
  const strip = text => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '');
  const own = strip(readFileSync(new URL('../web/saved-spots.ts', import.meta.url), 'utf8'));
  const card = readFileSync(new URL('../web/app/MarkCard.tsx', import.meta.url), 'utf8');
  const action = strip(card.slice(card.indexOf('export function SaveSpotAction'), card.indexOf('export function MarkCard(')));
  const FORBIDDEN = /\b(?:navigate|setParams|withParams|history|location|localStorage|sessionStorage|indexedDB|caches|console|reportError|telemetry|analytics|track|measure\w*|beacon|sendBeacon|innerHTML|dangerouslySetInnerHTML|share|navigator|clipboard|selection|camera|chartMark|terrainPick)\b/;
  for (const [label, text] of [['web/saved-spots.ts', own], ['SaveSpotAction', action]]) assert.doesNotMatch(text, FORBIDDEN, `${label} reaches no forbidden channel`);
  assert.match(own, /fetchFn\('\/api\/spots'/, 'the one write');
  assert.ok(!/api\/spots|saved_spots|routes\/spots/.test(card), 'the card calls the module and names no route or table');
  assert.doesNotMatch(action, /note/i, 'no note field on the card');
});
