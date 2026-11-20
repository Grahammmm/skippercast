// SCA-584 / F15-08: a delayed filter request must not leave stale events drawn
// or pickable, or leave Loading attached to a restored, completed result.

import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {configureStore, syncFromURL} from '../web/state.ts';
import {activityAccess, activityFilters, activityStatus, createFleetActivity, FLEET_EVENTS, FLEET_SOURCE, toggleActivity} from '../web/map/fleet.ts';
import {markData} from '../web/map/marks.ts';
import {readPalette} from '../web/map/palette.ts';

const A = 'drift-anchor', B = 'troll-slow';
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => Promise.withResolvers();
const ok = body => ({ok: true, status: 200, json: async () => body});
const event = kind => ({type: 'Feature', geometry: {type: 'Point', coordinates: [0, 0]}, properties: {id: kind, kind, dwell_min: 5}});
const features = kind => ok({type: 'FeatureCollection', features: [event(kind)], meta: {next: null}});

async function open(t) {
  t.mock.method(globalThis, 'fetch', () => { assert.fail('unexpected network call'); });
  configureStore({v2: true, storage: null});
  syncFromURL('https://example.test/map?region=morro-bay&layers=fleet');
  markData.value = {region: {id: 'morro-bay', jurisdiction_id: 'california-central'}};
  activityFilters.value = {kind: A};
  toggleActivity('events', true);
  const aDrawn = deferred(), bRequested = deferred(), lateB = deferred();
  let shown = [];
  const engine = signal({
    view: {size: () => ({width: 2, height: 2}), unproject: (x, y) => ({lon: x - 1, lat: 1 - y}), on: () => () => {}},
    setOverlay(id, overlay) {
      assert.equal(id, 'fleet-activity');
      shown = overlay?.sources[FLEET_SOURCE.events].data.features.map(f => f.properties.key) ?? [];
    },
    setData(id, data) {
      if (id !== FLEET_SOURCE.events) return;
      shown = data.features.map(f => f.properties.key);
      if (shown.includes(A)) aDrawn.resolve();
    },
  });
  const fleet = createFleetActivity({engine, palette: () => readPalette(() => '1'), fetchFn(path, init) {
    const url = new URL(path, 'https://example.test');
    if (url.pathname === '/api/session') return ok({is_admin: true});
    assert.equal(url.searchParams.get('region'), 'CA');
    if (url.pathname === '/api/fleet/map/filters') return ok({region: 'CA'});
    assert.equal(url.pathname, '/api/fleet/map/events');
    const kind = url.searchParams.get('kind');
    if (kind === A) return features(A);
    assert.equal(kind, B);
    bRequested.resolve(init.signal);
    return lateB.promise; // deliberately ignore abort so a late response is delivered
  }});
  t.after(() => { fleet.destroy(); toggleActivity('events', false); activityFilters.value = {}; markData.value = null; });
  const pick = key => fleet.pick.mark(FLEET_EVENTS, {key})?.id ?? null;
  const observe = () => ({drawn: [...shown], pickA: pick(A), pickB: pick(B), status: activityStatus.peek()});
  await aDrawn.promise;
  await flush();
  return {observe, bRequested, finishB: () => lateB.resolve(features(B)), failB: () => lateB.reject(new Error('offline fixture'))};
}

const aMark = `fleet:event:${A}`;
function checkA(a) {
  assert.equal(activityAccess.peek(), true, 'the real session and filters checks allow the local response');
  assert.deepEqual(a.drawn, [A]);
  assert.equal(a.pickA, aMark);
  assert.equal(a.pickB, null);
  assert.match(a.status, /^1 stop\b/);
}

function gaps({pending, restored, late}, accepted) {
  const reasons = [];
  if (pending.drawn.length) reasons.push('A remains drawn while B is pending');
  if (pending.pickA !== null || pending.pickB !== null) reasons.push('a stale hit can open a card while B is pending');
  if (!/^Loading\b/.test(pending.status)) reasons.push('pending B is not reported as loading');
  for (const [phase, x] of [['return to A', restored], ['late B reply', late]]) {
    if (x.drawn.join() !== A || x.pickA !== aMark || x.pickB !== null) reasons.push(`${phase}: wrong draw or pick generation`);
    if (x.status !== accepted.status) reasons.push(`${phase}: completed A status was not restored`);
  }
  return reasons;
}

test('F15-08: settled A passes; the race oracle distinguishes a clean return from stale draw, pick and status', {timeout: 5000}, async t => {
  const {observe} = await open(t);
  const a = observe();
  checkA(a);
  const pending = {drawn: [], pickA: null, pickB: null, status: 'Loading fleet activity…'};
  const valid = {pending, restored: a, late: a};
  assert.deepEqual(gaps(valid, a), []);
  assert.deepEqual(gaps({...valid, pending: {...pending, drawn: a.drawn, pickA: a.pickA}, restored: {...a, status: pending.status}}, a),
    ['A remains drawn while B is pending', 'a stale hit can open a card while B is pending', 'return to A: completed A status was not restored']);
  assert.deepEqual(gaps({...valid, late: {...a, drawn: [B]}}, a), ['late B reply: wrong draw or pick generation']);
});

test('F15-08: A → delayed B → A → late B keeps drawing, picks and status on the active query', {timeout: 5000}, async t => {
  const {observe, bRequested, finishB} = await open(t);
  const a = observe();
  checkA(a);
  activityFilters.value = {kind: B};
  const bSignal = await bRequested.promise;
  const pending = observe();
  activityFilters.value = {kind: A};
  assert.equal(bSignal.aborted, true, 'returning to A cancels the synthetic B request');
  const restored = observe();
  finishB();
  await flush();
  assert.deepEqual(gaps({pending, restored, late: observe()}, a), []);
});

test('F15-08: a failed replacement is not a successful empty result or an access denial', {timeout: 5000}, async t => {
  const {observe, bRequested, failB} = await open(t);
  const a = observe();
  checkA(a);
  activityFilters.value = {kind: B};
  await bRequested.promise;
  failB();
  await flush();
  assert.deepEqual(observe(), {drawn: [], pickA: null, pickB: null,
    status: 'Fleet activity could not load. The map and other layers remain available.'});
  assert.equal(activityAccess.peek(), true);
});
