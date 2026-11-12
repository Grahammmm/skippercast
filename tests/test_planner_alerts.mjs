// SC1822-04: a signed-in planner saves its plan with a private trip alert. Offline: the production planner model and component,
// fixture settings, a bounded screen, an injected clock and request, and the emitted body run through the server's own validateTrip.
import assert from 'node:assert/strict';
import test, {after, mock} from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugin} from './helpers/esbuild-url.mjs';
import {draftKey} from '../dist/trip-export.js';
import {geometryCoveredByBounds} from '../dist/geo-screen.js';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {validateTrip} = await import('../server/trips.ts');

const hookStub = {name: 'hook-stub', setup: b => {
  b.onResolve({filter: /^preact\/hooks$/}, a => a.importer.endsWith('web/app/Planner.tsx') ? {path: 'hooks', namespace: 'hook-stub'} : null);
  b.onLoad({filter: /.*/, namespace: 'hook-stub'}, () => ({contents: 'export const useEffect = (fn, deps) => { (globalThis.__plannerEffects ??= []).push(fn); };', loader: 'js'}));
}};
const dir = await mkdtemp(join(tmpdir(), 'planner-alerts-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {Planner} from './web/app/Planner.tsx';
    export {createPlanner} from './web/planner.ts';
    export {session} from './web/account.ts';
    export {launchPoints} from './web/launches.ts'; export {cruiseSpeed} from './web/limits.ts';
    export {region as stateRegion} from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, hookStub]});
const m = await import(pathToFileURL(out).href);

const traffic = [], realFetch = globalThis.fetch;
globalThis.fetch = (...a) => { traffic.push(a); throw Error('no network in this test'); };
after(async () => { globalThis.fetch = realFetch; m.session.value = {state: 'loading'}; m.stateRegion.value = null; m.launchPoints.value = null; m.cruiseSpeed.value = null; await rm(dir, {recursive: true, force: true}); });

const NOW = new Date('2026-10-12T18:00:00Z'); // 11:00 Pacific, 2026-10-12
const REGION = {...globalThis.REGIONS['morro-bay'], mpa: {bounds: [-125, 30, -115, 40]}};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -122, getEast: () => -120, getNorth: () => 36, getSouth: () => 34, contains: () => true})};
const NOTE = 'PRIVNOTE-7f3a', OWNER = 'OWNERMARK-9c1d';
const layers = {waypoints: true, outlines: false, alignments: false, exclusions: false};
const wp = (id, name, lat, lon) => ({id, name, category: 'reef', latitude: lat, longitude: lon});
const FIRST = wp('user:11111111-1111-4111-8111-111111111111', 'North Reef', 35.46, -120.95), SECOND = wp('user:habitat-reef-r1', 'Second Reef', 35.3, -120.9);
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
const SETTINGS = {profile: 'boat', ownBoatLimits: false, limits: {wind: 12, gust: 18, seas: 4}, factors: {sea: 1, wind: 1, custom: false}, boat: null};
const LEGS = stops => ({legs: stops.slice(1).map((s, i) => ({from: stops[i].name, to: s.name, nm: 2.5, runMin: 10, basis: 'straight'})), skipped: []});

function makeScreen(over = {}) {
  const s = {bounds: [-122, 34, -120, 36], live: true, throws: false, ...over};
  return Object.assign(s, {ready: () => s.live, exportExclusions: () => s.live ? {checked_at: new Date().toISOString(), features: []} : null, pointAllowed: () => s.live, geometryAllowed: () => s.live,
    coversGeometry: g => { if (s.throws) throw Error('coverage unavailable'); return geometryCoveredByBounds(g, s.bounds); }});
}
const ok = (status, body) => Promise.resolve({ok: status >= 200 && status < 300, status, json: async () => body});
function harness({points = [FIRST, SECOND], ids = points.map(p => p.id), screen = makeScreen(), date = '2026-10-13', reply, state = {state: 'signed-in', name: 'Sam'}, settings = SETTINGS, launchId, region = REGION, species} = {}) {
  const calls = [], stored = {ids, userWaypoints: points, rankedPlan: null, name: 'Mine', date, avoidScope: 'map', layers, ...(launchId ? {launchId} : {})};
  const store = new Map([[draftKey(region.id), JSON.stringify(stored)]]);
  m.stateRegion.value = region.id; m.session.value = state;
  const alertFetch = (url, init) => { calls.push({url, init, body: JSON.parse(init.body)}); return reply ? reply(calls.length) : ok(201, {id: 'trip-1'}); };
  const planner = m.createPlanner({atlas: {targets: [], areas: [], drifts: []}, screen, region, map: MAP, getVisible: () => [], storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }},
    now: () => NOW, landWater: async () => () => ({state: 'water'}), loadPorts: async () => ({ports: []}), emit() {}, alertFetch, alertSettings: () => settings, nav: {open() {}, showMap() {}, conditions() {}}});
  if (species) planner.filters.value = {...planner.filters.value, species};
  planner.setAlertOpen(true);
  return {planner, calls, store, screen, save: () => planner.saveAlert(LEGS), preview: () => planner.alertPreview(LEGS)};
}

test('planner_alert_body_maps_ids_drops_notes_and_validates', async () => {
  m.launchPoints.value = {region: REGION.id, points: [{id: 'ramp.1', name: 'Ramp <b>One</b>', latitude: 35.37, longitude: -120.86}]};
  const h = harness({launchId: 'ramp.1', points: [FIRST, SECOND, wp('user:unchecked', 'Not checked', 35.4, -120.9)], ids: [FIRST.id, SECOND.id]});
  await h.save(); await settle();
  assert.equal(h.calls.length, 1); const {url, init, body} = h.calls[0];
  assert.deepEqual([url, init.method, init.credentials, init.cache, init.headers['Content-Type']], ['/api/trips', 'POST', 'same-origin', 'no-store', 'application/json']);
  assert.deepEqual(body.plan.spots.map(s => [s.id, s.order, s.notes, s.depth_ft]), [['stop-1', 0, '', null], ['stop-2', 1, '', null], ['stop-3', 2, '', null]]);
  assert.deepEqual(body.plan.spots.map(s => s.name), ['North Reef', 'Second Reef', 'Launch · Ramp <b>One</b>']);
  assert.equal(body.launch_point, 'stop-3'); assert.ok(!JSON.stringify(body).includes('Not checked'), 'an unchecked waypoint is not sent');
  assert.deepEqual([body.date, body.point, body.species, body.targets, body.status, body.start_hour, body.end_hour, body.boat], ['2026-10-13', 'north', 'reef', ['reef'], 'planned', 7, 13, null]);
  assert.deepEqual([body.wind_limit, body.gust_limit, body.sea_limit], [8, 12, 3], 'reference boat limits as the alerts form starts');
  assert.deepEqual(body.plan.window, {depart: '07:00', return_by: '13:00', hours: [7, 8, 9, 10, 11, 12]}); assert.deepEqual(body.plan.exports, []);
  assert.deepEqual(body.plan.legs.map(l => [l.from, l.to, l.nm, l.minutes]), [['North Reef', 'Second Reef', 2.5, 10], ['Second Reef', 'Launch · Ramp <b>One</b>', 2.5, 10]]);
  assert.ok(!JSON.stringify(body).includes('user:'), 'no source id travels');
  // The server's own validator accepts the body exactly as sent, with the same clock.
  const v = validateTrip(JSON.parse(JSON.stringify(body)), NOW.getTime());
  assert.deepEqual([v.plan.spots.length, v.launch_point, v.targets, v.point], [3, 'stop-3', ['reef'], 'north']);
  assert.match(h.planner.alertStatus.value, /^Trip saved with this plan\./);
  assert.deepEqual(h.planner.draft.value.ids, [FIRST.id, SECOND.id], 'the browser draft is untouched'); assert.deepEqual(traffic, []);
  h.planner.dispose(); m.launchPoints.value = null;
});

test('planner_alert_private_note_never_enters_trip', async () => {
  // A saved spot (with a private note on the server's row) joins as an ordinary waypoint; only its name and position can be sent.
  const spot = {id: '00000000-0000-4000-8000-000000000001', owner: OWNER, name: 'Saved Spot', lat: 35.4, lon: -120.9, note: NOTE};
  const h = harness({points: [], ids: []});
  const syntheticDraft = {...h.planner.draft.value, userWaypoints: [{...wp('user:note-1', 'Has note', spot.lat, spot.lon), notes: NOTE, note: NOTE, owner: OWNER}], ids: ['user:note-1']};
  h.planner.draft.value = syntheticDraft; // as if a malicious or stale source record carried extra fields
  await h.save(); await settle();
  assert.equal(h.calls.length, 1);
  const text = JSON.stringify(h.calls[0].body);
  assert.ok(!text.includes(NOTE) && !text.includes(OWNER), 'no note or owner in the body'); assert.equal(h.calls[0].body.plan.spots[0].notes, '');
  assert.ok(![...h.store.values()].join('').includes(NOTE)); h.planner.dispose();
});

test('planner_alert_date_uses_region_calendar', async () => {
  for (const [date, allowed] of [['2026-10-12', true], ['2026-10-19', true], ['2026-10-11', false], ['2026-10-20', false], ['', false], ['2026-02-30', false], ['10/13/2026', false]]) {
    const h = harness(); h.planner.edit({date}); await h.save(); await settle();
    assert.equal(h.calls.length, allowed ? 1 : 0, `${date || 'empty'}: ${allowed ? 'sent' : 'not sent'}`);
    if (!allowed) { assert.equal(h.planner.alertStatus.value, 'Choose a fishing date from today to seven days ahead in this region to save alerts.'); const p = h.preview(); assert.equal(p.ok, false); assert.equal(p.message, h.planner.alertStatus.value); }
    h.planner.dispose();
  }
});

test('planner_alert_refuses_whole_unsafe_unresolved_or_oversized_plan', async () => {
  const refuse = async (label, h, message) => { await h.save(); await settle(); assert.equal(h.calls.length, 0, `${label}: nothing sent`); assert.equal(h.planner.alertStatus.value, message, label); h.planner.dispose(); };
  const SCREEN = 'A selected stop is inside, near, or not checked against protected areas. Review the plan before saving alerts.';
  await refuse('uncovered stop', harness({points: [FIRST, wp('user:far', 'Far', 36.5, -118)]}), SCREEN);
  await refuse('screen without coverage', harness({screen: {...makeScreen(), coversGeometry: undefined}}), SCREEN);
  await refuse('screen that throws', harness({screen: makeScreen({throws: true})}), SCREEN);
  const elsewhere = harness(); m.stateRegion.value = 'other-coast'; await elsewhere.save(); await settle(); assert.equal(elsewhere.calls.length, 0, 'the app is in another region: nothing sent'); elsewhere.planner.dispose();
  await refuse('no stop', harness({points: [], ids: []}), 'Select at least one stop to save alerts.');
  const many = Array.from({length: 13}, (_, i) => wp(`user:s${i}`, `S${i}`, 35.3 + i / 100, -120.9));
  await refuse('13 stops', harness({points: many}), 'Trip alerts can save up to 12 stops, including the launch. Uncheck stops before saving.');
  const twelve = harness({points: many.slice(0, 12)}); await twelve.save(); await settle(); assert.equal(twelve.calls.length, 1, '12 stops are sent whole'); assert.equal(twelve.calls[0].body.plan.spots.length, 12); twelve.planner.dispose();
  const unresolved = harness(); unresolved.planner.toggleSpot('user:gone', true);
  await refuse('unresolved checked id', unresolved, 'Some selected stops are unavailable. Review your plan before saving alerts.');
  const bad = harness(); bad.planner.dispose(); // disposed: no work
  await bad.save(); assert.equal(bad.calls.length, 0);
  // A leg with no cruise speed (null minutes) is refused, never sent as zero.
  const noSpeed = harness(); await noSpeed.planner.saveAlert(stops => ({legs: [{from: 'a', to: 'b', nm: 1, runMin: null, basis: 'straight'}], skipped: []}));
  assert.equal(noSpeed.calls.length, 0); assert.equal(noSpeed.planner.alertStatus.value, 'Set a valid cruise speed and review the leg distances before saving alerts.'); noSpeed.planner.dispose();
  const skipped = harness(); await skipped.planner.saveAlert(stops => ({legs: [], skipped: ['x']})); assert.equal(skipped.calls.length, 0); skipped.planner.dispose();
  // A pending restore or changed filters keep the export gates: no alert either.
  const pending = harness(); pending.planner.restorePending.value = true; await pending.save(); assert.equal(pending.calls.length, 0); assert.match(pending.planner.alertStatus.value, /needs current reef data/); pending.planner.dispose();
  assert.deepEqual(traffic, []);
});

test('planner_alert_area_target_and_defaults', async () => {
  // The nearest forecast point to the first non-launch stop, not the launch or a later stop.
  const south = wp('user:south', 'South', 35.2, -120.9), north = wp('user:north', 'North', 35.46, -120.95);
  const a = harness({points: [south, north]}); await a.save(); await settle(); assert.equal(a.calls[0].body.point, 'south', `first stop picks its nearest point (${REGION.forecast_points.map(p => p.id)})`); a.planner.dispose();
  const b = harness({points: [north, south]}); await b.save(); await settle(); assert.equal(b.calls[0].body.point, 'north'); assert.match(b.preview().preview.area, /./); b.planner.dispose();
  // Lingcod and rockfish are saved under the region's Reef group, said in the preview; an unlisted target is refused.
  const l = harness({species: 'lingcod'}); assert.equal(l.preview().preview.groupNote, 'This region groups lingcod and rockfish alerts under Reef.'); await l.save(); await settle();
  assert.deepEqual([l.calls[0].body.species, l.calls[0].body.targets], ['reef', ['reef']]); l.planner.dispose();
  const noReef = harness({region: {...REGION, species: ['halibut']}, species: 'rockfish'}); await noReef.save(); assert.equal(noReef.calls.length, 0);
  assert.equal(noReef.planner.alertStatus.value, 'This region does not offer alerts for the plan’s target.'); noReef.planner.dispose();
  // Limits: non-Boat from the profile's limits and no boat; Boat with own limits unscaled; a saved boat scales and travels.
  const shore = harness({settings: {...SETTINGS, profile: 'shore', limits: {wind: 10, gust: 15, seas: 2}}}); await shore.save(); await settle();
  assert.deepEqual([shore.calls[0].body.wind_limit, shore.calls[0].body.gust_limit, shore.calls[0].body.sea_limit, shore.calls[0].body.boat], [10, 15, 2, null]); shore.planner.dispose();
  const own = harness({settings: {...SETTINGS, ownBoatLimits: true, limits: {wind: 14, gust: 20, seas: 5}, factors: {sea: 2, wind: 1.5, custom: true, chopPeriod: 5}, boat: {name: 'Mine'}}}); await own.save(); await settle();
  assert.deepEqual([own.calls[0].body.wind_limit, own.calls[0].body.sea_limit, own.calls[0].body.boat.name], [14, 5, 'Mine']); own.planner.dispose();
  const saved = harness({settings: {...SETTINGS, factors: {sea: 2, wind: 1.5, custom: true, chopPeriod: 5}, boat: {name: 'Big'}}}); await saved.save(); await settle();
  assert.deepEqual([saved.calls[0].body.wind_limit, saved.calls[0].body.sea_limit, saved.calls[0].body.boat], [12, 6, {name: 'Big', sea: 2, wind: 1.5, chop_period: 5}]); saved.planner.dispose();
});

test('planner_alert_post_refusals_are_words_and_never_retried', async () => {
  const words = [[409, {error: 'Limit of 20 active trips'}, 'You already have 20 active trips. Delete an upcoming trip in Saved-trip alerts before saving another.'],
    [400, {error: 'invalid spot id'}, 'This trip could not be saved. Check its date, area, targets and limits, then try again.'],
    [401, {}, 'Sign in again to save trip alerts.'], [403, {}, 'Sign in again to save trip alerts.'],
    [500, {error: 'SECRET-SERVER-TEXT'}, 'Could not confirm this trip was saved. Check Saved-trip alerts before trying again.'],
    [201, {}, 'Could not confirm this trip was saved. Check Saved-trip alerts before trying again.'],
    [201, {id: ''}, 'Could not confirm this trip was saved. Check Saved-trip alerts before trying again.']];
  for (const [status, body, message] of words) {
    const h = harness({reply: () => ok(status, body)}); await h.save(); await settle();
    assert.equal(h.calls.length, 1, `${status}: one request, no retry`); assert.equal(h.planner.alertStatus.value, message, String(status)); assert.ok(!h.planner.alertStatus.value.includes('SECRET'));
    assert.equal(h.planner.alertSaved.value, '', `${status}: not marked saved`); h.planner.dispose();
  }
  for (const [label, reply] of [['network', () => Promise.reject(new TypeError('offline'))], ['non-JSON', () => Promise.resolve({ok: true, status: 201, json: async () => { throw SyntaxError('x'); }})]]) {
    const h = harness({reply}); await h.save(); await settle(); assert.equal(h.calls.length, 1, label);
    assert.equal(h.planner.alertStatus.value, 'Could not confirm this trip was saved. Check Saved-trip alerts before trying again.', label); h.planner.dispose();
  }
  // A request that never answers is aborted after 20 seconds and said as unconfirmed.
  mock.timers.enable({apis: ['setTimeout']});
  try {
    const h = harness({reply: () => new Promise(() => {})}); const run = h.save(); await settle();
    assert.equal(h.planner.alertBusy.value, true); mock.timers.tick(20000); await settle(); await Promise.race([run, settle()]);
    assert.equal(h.calls[0].init.signal.aborted, true); h.planner.dispose();
  } finally { mock.timers.reset(); }
  // Double click: one request while pending; the same successful snapshot is not saved twice, an edit allows another save.
  let release; const gate = new Promise(r => { release = r; });
  const h = harness({reply: () => gate.then(() => ok(201, {id: 't'}))}); const first = h.save(); const second = h.save(); await settle();
  assert.equal(h.calls.length, 1, 'double click is one POST'); release(); await first; await second; await settle();
  assert.equal(h.planner.alertSaved.value !== '', true); await h.save(); assert.equal(h.calls.length, 1); assert.match(h.planner.alertStatus.value, /already saved/);
  h.planner.edit({date: '2026-10-14'}); await h.save(); await settle(); assert.equal(h.calls.length, 2); assert.equal(h.calls[1].body.date, '2026-10-14'); h.planner.dispose();
});

test('planner_alert_session_and_revision_lifecycle: signed out is unchanged and nothing is sent without a click', async () => {
  globalThis.document = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}};
  try {
    for (const state of [{state: 'loading'}, {state: 'offline'}, {state: 'disabled'}, {state: 'signed-out'}]) {
      const h = harness({state}); await h.save(); await settle();
      assert.equal(h.calls.length, 0, state.state); assert.equal(h.preview(), null);
      const html = m.render(m.h(m.Planner, {model: h.planner, open: true}));
      assert.ok(!html.includes('Alert me for this trip') && !html.includes('planner-alert'), `${state.state}: no section`);
      assert.ok(html.includes('Separate from your account’s trip alerts.'), `${state.state}: existing wording`); h.planner.dispose();
    }
    m.cruiseSpeed.value = 20;
    const h = harness(); await settle(); assert.equal(h.calls.length, 0, 'opening and rendering send nothing');
    const html = m.render(m.h(m.Planner, {model: h.planner, open: true}));
    assert.ok(html.includes('id="planner-save-alert"') && html.includes('Alert me for this trip') && html.includes('Nearest to the first stop; alerts assess this area, not conditions at every stop.'));
    assert.ok(html.includes('Saved in this browser. Alert me for this trip saves a separate snapshot to your account.') && !html.includes('Separate from your account’s trip alerts.'));
    assert.equal(h.calls.length, 0); h.planner.dispose();
    // A change while the gates run, a sign-out, closing or disposal means no request and no late answer.
    for (const [label, disturb] of [['edit', h2 => h2.planner.toggleSpot(SECOND.id, false)], ['sign-out', () => { m.session.value = {state: 'signed-out'}; }], ['close', h2 => h2.planner.setAlertOpen(false)], ['dispose', h2 => h2.planner.dispose()]]) {
      const h2 = harness(); const run = h2.save(); disturb(h2); await run; await settle();
      assert.equal(h2.calls.length, 0, `${label}: nothing sent`); h2.planner.dispose();
    }
    let release; const gate = new Promise(r => { release = r; });
    const late = harness({reply: () => gate.then(() => ok(201, {id: 't'}))}); const run = late.save(); await settle(); assert.equal(late.calls.length, 1);
    late.planner.setAlertOpen(false); release(); await run; await settle();
    assert.equal(late.planner.alertStatus.value, '', 'a late answer after close paints nothing'); assert.equal(late.planner.alertSaved.value, ''); late.planner.dispose();
  } finally { delete globalThis.document; }
});

test('planner_alert_guide_and_snapshot_copy', () => {
  const doc = readFileSync(new URL('../docs/web-app.md', import.meta.url), 'utf8');
  const plan = doc.split('\n').find(l => l.startsWith('- **Trip plan and GPX.**')), alerts = doc.split('\n').find(l => l.startsWith('- **Saved-trip alerts.**'));
  assert.ok(plan.includes('The plan is saved per region in this browser.') && plan.includes('"Alert me for this trip"') && plan.includes('nothing is sent until that press'));
  for (const s of ['Private notes are never copied', 'up to 12 stops', 'nearest the first stop', 'Reef group', 'Later edits to the browser plan do not change the saved alert', 'not a navigation route']) assert.ok(alerts.includes(s), s);
  assert.ok(!/every stop's weather|navigable route\b(?! )/.test(alerts.replace('not a navigation route', '')));
});

test('planner_alert_checked_launch_must_resolve_exactly', async () => {
  const ramp = {id: 'ramp.1', name: 'Ramp One', latitude: 35.37, longitude: -120.86}, other = {id: 'ramp.2', name: 'Other Ramp', latitude: 35.2, longitude: -120.7};
  const unavailable = [['loading (no list)', null], ['another region', {region: 'other-coast', points: [ramp]}], ['id not listed', {region: REGION.id, points: [other]}]];
  for (const [label, list] of unavailable) {
    m.launchPoints.value = list;
    const h = harness({launchId: 'ramp.1'}); await h.save(); await settle();
    assert.equal(h.calls.length, 0, `${label}: nothing sent`); assert.equal(h.planner.alertStatus.value, 'Some selected stops are unavailable. Review your plan before saving alerts.', label);
    const p = h.preview(); assert.equal(p.ok, false, `${label}: preview refuses`); h.planner.dispose();
  }
  m.launchPoints.value = {region: REGION.id, points: [other, ramp]};
  const ok1 = harness({launchId: 'ramp.1'}); await ok1.save(); await settle();
  assert.equal(ok1.calls.length, 1); assert.equal(ok1.calls[0].body.plan.spots.at(-1).name, 'Launch · Ramp One', 'the actual launch, not the first listed'); ok1.planner.dispose();
  m.launchPoints.value = null;
});

test('planner_alert_preview_shows_each_leg_basis_and_protected_area_reading', async () => {
  globalThis.document = {addEventListener() {}, removeEventListener() {}, dispatchEvent() {}};
  try {
    m.cruiseSpeed.value = 20;
    const legs = stops => ({legs: stops.slice(1).map((s, i) => ({from: stops[i].name, to: s.name, nm: 2.5, runMin: 10, basis: i ? 'water' : 'straight', screen: i ? {screened: true, inside: true, name: 'Test <b>Reserve</b>'} : {screened: false}})), skipped: []});
    const h = harness();
    const view = h.planner.alertPreview(legs); assert.equal(view.ok, true);
    assert.deepEqual(view.preview.legList.map(l => [l.from, l.to, l.nm, l.minutes, l.basis]), [['North Reef', 'Second Reef', 2.5, 10, 'straight']]);
    const only = harness({points: [FIRST, SECOND, wp('user:third', 'Third', 35.31, -120.91)]});
    const original = only.planner.alertPreview; only.planner.alertPreview = () => original(legs);
    const html = m.render(m.h(m.Planner, {model: only.planner, open: true}));
    const section = html.slice(html.indexOf('id="planner-alert-legs"'), html.indexOf('id="planner-save-alert"'));
    assert.match(section, /North Reef → Second Reef · 2\.5 nm straight line · at least 10 min · Protected areas not checked/);
    assert.match(section, /Second Reef → Third · 2\.5 nm · at least 10 min · Inside Test &lt;b>Reserve&lt;\/b>/);
    assert.match(section, /Straight-line legs between stops; the real route is longer\./);
    h.planner.dispose(); only.planner.dispose();
  } finally { delete globalThis.document; }
});

test('planner_alert_same_snapshot_is_not_saved_again_after_A_B_A', async () => {
  const h = harness();
  await h.save(); await settle(); assert.equal(h.calls.length, 1);
  h.planner.edit({date: '2026-10-14'}); await h.save(); await settle(); assert.equal(h.calls.length, 2);
  h.planner.edit({date: '2026-10-13'}); await h.save(); await settle();
  assert.equal(h.calls.length, 2, 'A again is not sent a third time'); assert.match(h.planner.alertStatus.value, /already saved/);
  assert.equal(h.planner.alertIsSaved(h.calls[0].body), true); assert.equal(h.planner.alertIsSaved(h.calls[1].body), true);
  h.planner.edit({date: '2026-10-15'}); await h.save(); await settle(); assert.equal(h.calls.length, 3, 'a new snapshot still saves');
  h.planner.dispose();
});
