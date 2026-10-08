// MapStage adapter (FE-71, docs/plans/front-end/design.md § 3A.2): the
// store-to-renderer and renderer-to-store flows over a fake terrain module,
// so neither three nor a GPU is needed. web/map/stage.ts runs by type stripping.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  HOME_ZOOM, NO_TERRAIN, UNAVAILABLE, UNSUPPORTED_CURRENT, camera, cameraParam, choosePresentation, coastSpecies, createStage,
  currentStatus, locationFor, parseCamera, shownPresentation, spanForZoom, terrainBlocked, terrainFailed, terrainHour, terrainMark,
  terrainState, zoomForSpan,
} from '../web/map/stage.ts';
import {configureStore, navigate, setParams, syncFromURL} from '../web/state.ts';

const ORIGIN = 'https://s.test/map';
const NOW = new Date('2026-10-05T20:17:00Z');
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

/** A browser just big enough for navigate(): an address, a history stack with Back, and no-op events. */
function browser(href) {
  const stack = [href];
  globalThis.location = {href};
  globalThis.history = {
    state: null,
    pushState(_s, _t, url) { stack.push(url); location.href = url; },
    replaceState(_s, _t, url) { stack[stack.length - 1] = url; location.href = url; },
  };
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  return {
    back() { stack.pop(); location.href = stack.at(-1); syncFromURL(location.href); },
    params: () => new URL(location.href).searchParams,
    stack,
  };
}

/** A fake terrain module: records every handle call and keeps the options mountCoast received. */
function terrain({ready = true, throws = false} = {}) {
  const fake = {calls: [], mounts: 0, destroyed: 0, options: null};
  const handle = {};
  for (const name of ['setPerspective', 'setLocation', 'setSpecies', 'setHour', 'setDepthLimit', 'setCurrentLayer', 'selectHabitat', 'setVisible']) {
    handle[name] = value => { fake.calls.push([name, value]); return true; };
  }
  handle.load = async () => ready;
  handle.destroy = () => { fake.destroyed++; };
  fake.module = {
    styles: ['coast.css'],
    mountCoast(host, options) {
      fake.mounts++;
      fake.host = host;
      fake.options = options;
      if (throws) { host.shadowRoot.children = ['scene']; throw new Error('WebGL unavailable'); }
      return handle;
    },
  };
  fake.last = name => fake.calls.filter(([n]) => n === name).at(-1)?.[1];
  fake.count = name => fake.calls.filter(([n]) => n === name).length;
  return fake;
}

function document() {
  const listeners = new Set();
  return {
    hidden: false,
    addEventListener: (_type, fn) => listeners.add(fn),
    removeEventListener: (_type, fn) => listeners.delete(fn),
    set(hidden) { this.hidden = hidden; for (const fn of listeners) fn(); },
    listeners,
  };
}

function stage(fake, {center = [35.37, -120.86], doc = document(), now = () => NOW} = {}) {
  const host = {shadowRoot: {children: [], replaceChildren() { this.children = []; }}};
  terrainFailed.value = false;
  terrainMark.value = null;
  const s = createStage({host, load: async () => fake.module, center: () => center, now, doc, viewDelay: 0});
  return {stage: s, host, doc};
}

test('the span-to-zoom rule is v1\'s, and a camera round-trips through ?view=', () => {
  assert.equal(zoomForSpan(7300), 12);
  assert.equal(zoomForSpan(14600), 11);
  assert.equal(zoomForSpan(1e9), 7, 'clamped to 7');
  assert.equal(zoomForSpan(1), 18, 'clamped to 18');
  assert.equal(spanForZoom(12), 7300);
  assert.equal(spanForZoom(22), 1200, 'clamped to v1\'s smallest span');
  for (const zoom of [8, 10.5, 12, 14]) assert.ok(Math.abs(zoomForSpan(spanForZoom(zoom)) - zoom) < 1e-9, `zoom ${zoom}`);
  assert.deepEqual(parseCamera('35.37,-120.86,12'), {latitude: 35.37, longitude: -120.86, zoom: 12});
  for (const value of ['conditions', 'coast', '35,-120', '95,-120,12', '35,,12', null]) assert.equal(parseCamera(value), null, String(value));
  assert.equal(cameraParam({latitude: 35.371234567, longitude: -120.86, zoom: 11.456}), '35.37123,-120.86000,11.46');
  assert.deepEqual(locationFor({latitude: 1, longitude: 2, zoom: 12}), {latitude: 1, longitude: 2, span: 7300});
});

test('the flow table: profile sets the depth limit, target the species, hour, camera, current, habitat and visibility', () => {
  const base = {profile: 'boat', target: null, hour: null, camera: null, current: 'off', habitat: null, presentation: '3d', appView: 'coast', hidden: false, now: NOW};
  assert.equal(terrainState({...base, profile: 'spear'}).depthLimit, 60, 'Spear: 60 ft');
  assert.equal(terrainState({...base, profile: 'boat'}).depthLimit, 300, 'Boat: 300 ft');
  assert.equal(terrainState({...base, profile: 'shore'}).depthLimit, 300, 'Shore has no limit of its own: the renderer\'s 300 ft (test_profile pins these to experience.ts)');
  assert.equal(terrainState({...base, profile: 'spear'}).species, 'cabezon-shallow-reef', 'no target: the profile default');
  assert.equal(coastSpecies('rockfish', 'boat'), 'rockfish-reef', 'SkipperCast targets map through coastTarget');
  assert.equal(coastSpecies('vermilion', 'boat'), 'vermilion', 'an unmapped target passes through; the renderer reports it unsupported');
  assert.deepEqual(terrainState({...base, hour: '2026-10-06T03:00Z'}).hour, new Date('2026-10-06T03:00:00Z'));
  assert.deepEqual(terrainState(base).hour, new Date('2026-10-05T20:00:00Z'), 'no hour: the current whole UTC hour');
  assert.deepEqual(terrainHour('nonsense', NOW), new Date('2026-10-05T20:00:00Z'));
  assert.equal(terrainState(base).location, null, 'no camera, no move');
  assert.deepEqual(terrainState({...base, camera: {latitude: 35.4, longitude: -120.9, zoom: 11}}).location, {latitude: 35.4, longitude: -120.9, span: 14600});
  assert.equal(terrainState({...base, current: 'wcofs'}).currentLayer, 'wcofs');
  assert.equal(terrainState({...base, current: 'unsupported'}).currentLayer, 'off', 'an unlisted source draws nothing, as in v1');
  assert.equal(terrainState({...base, habitat: 'reef:r1'}).habitat, 'reef:r1');
  assert.equal(terrainState({...base, presentation: '2d'}).perspective, '2d');
  assert.equal(terrainState({...base, presentation: '3d'}).perspective, '3d');
  assert.equal(terrainState(base).visible, true);
  assert.equal(terrainState({...base, presentation: 'chart'}).visible, false, 'Chart hides the terrain');
  assert.equal(terrainState({...base, appView: 'conditions'}).visible, false, 'another view hides it');
  assert.equal(terrainState({...base, hidden: true}).visible, false, 'a hidden page hides it');
});

test('the first terrain choice mounts the renderer once with the store\'s state; later changes reach the handle', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&profile=spear&target=rockfish&hour=2026-10-06T03:00Z&current=hfr-6&habitat=reef:r1`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  await tick();
  assert.equal(fake.mounts, 0, 'Chart (the default) loads no terrain');
  assert.deepEqual(camera.value, {latitude: 35.37, longitude: -120.86, zoom: HOME_ZOOM}, 'no ?view=: the region centre');
  choosePresentation('3d');
  assert.equal(nav.params().get('presentation'), '3d');
  await tick();
  assert.equal(fake.mounts, 1);
  assert.deepEqual(fake.options.styles, ['coast.css']);
  assert.equal(fake.options.hostCurrents, true, 'the rail owns the surface-current choice');
  assert.deepEqual(fake.options.initial, {
    currentLayer: 'hfr-6', species: 'rockfish-reef', depthLimit: 60, location: {latitude: 35.37, longitude: -120.86, span: 7300},
    hour: new Date('2026-10-06T03:00:00Z'), perspective: '3d', habitat: 'reef:r1', visible: true,
  });
  assert.equal(fake.calls.length, 0, 'the initial state is not sent twice');
  assert.equal(terrainBlocked.value, null, 'nothing blocks the terrain here');

  setParams({profile: 'boat'});
  assert.equal(fake.last('setDepthLimit'), 300, 'Boat: 300 ft');
  assert.equal(fake.count('setSpecies'), 0, 'the target is unchanged, so it is not resent');
  setParams({profile: 'spear', target: null});
  assert.equal(fake.last('setDepthLimit'), 60, 'Spear: 60 ft');
  assert.equal(fake.last('setSpecies'), 'cabezon-shallow-reef');
  setParams({hour: '2026-10-06T05:00Z'});
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-06T05:00:00Z'));
  setParams({current: 'wcofs'});
  assert.equal(fake.last('setCurrentLayer'), 'wcofs');
  setParams({current: 'radar'});
  assert.equal(fake.last('setCurrentLayer'), 'off');
  assert.equal(currentStatus.value, UNSUPPORTED_CURRENT);
  setParams({view: '35.5,-121,10'});
  assert.deepEqual(fake.last('setLocation'), {latitude: 35.5, longitude: -121, span: 29200});

  // 3D → 2D keeps place, target, profile, hour and selection: only the camera mode changes.
  const before = fake.calls.length;
  choosePresentation('2d');
  assert.deepEqual(fake.calls.slice(before), [['setPerspective', '2d']]);
  for (const key of ['region', 'profile', 'hour', 'habitat', 'view']) assert.ok(nav.params().get(key), `${key} kept`);
  // Chart hides the renderer and keeps it, so going back is immediate.
  choosePresentation('chart');
  assert.equal(fake.last('setVisible'), false);
  choosePresentation('3d');
  assert.equal(fake.last('setVisible'), true);
  assert.equal(fake.mounts, 1, 'mounted once');
  s.destroy();
  assert.equal(fake.destroyed, 1, 'destroy releases the renderer');
});

test('visibility follows the masthead view and the page', async () => {
  browser(`${ORIGIN}?region=morro-bay&presentation=2d`);
  const fake = terrain(), doc = document();
  const {stage: s} = stage(fake, {doc});
  await tick();
  assert.equal(fake.options.initial.visible, true);
  doc.set(true);
  assert.equal(fake.last('setVisible'), false, 'hidden page');
  doc.set(false);
  assert.equal(fake.last('setVisible'), true);
  navigate(`${ORIGIN}?region=morro-bay&presentation=2d&view=conditions`);
  assert.equal(fake.last('setVisible'), false, 'Conditions view');
  assert.equal(fake.count('setLocation'), 0, 'leaving the map moves no camera');
  s.destroy();
  assert.equal(doc.listeners.size, 0, 'the visibility listener is removed');
});

test('renderer callbacks write the store: selection to ?habitat= (Back restores), camera to ?view=, perspective to ?presentation=', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d&habitat=reef:r1`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  await tick();
  const o = fake.options;

  o.onSelection({latitude: 35.4, longitude: -120.9, id: 'reef:r2'});
  assert.equal(nav.params().get('habitat'), 'reef:r2', 'a terrain selection writes ?habitat=');
  assert.equal(nav.stack.length, 2, 'with a history entry');
  assert.deepEqual(terrainMark.value, {latitude: 35.4, longitude: -120.9, id: 'reef:r2'});
  assert.equal(fake.count('selectHabitat'), 0, 'the renderer already shows it; nothing is echoed back');
  nav.back();
  assert.equal(fake.last('selectHabitat'), 'reef:r1', 'Back restores the previous selection');
  o.onRestoredSelection({latitude: 35.3, longitude: -120.8, id: 'reef:r1'});
  assert.equal(terrainMark.value.id, 'reef:r1');
  o.onSelectionInvalidated();
  assert.equal(terrainMark.value, null);
  assert.equal(nav.params().get('habitat'), 'reef:r1', 'as v1: an invalidated selection stays in the link');
  o.onCloseSelection();
  assert.equal(nav.params().get('habitat'), null, 'the close button clears it');
  assert.equal(fake.last('selectHabitat'), null);

  const moves = fake.count('setLocation');
  o.onView({latitude: 35.41, longitude: -120.95, span: 14600});
  assert.deepEqual(camera.value, {latitude: 35.41, longitude: -120.95, zoom: 11}, 'the shared camera follows at once');
  await tick();
  assert.equal(nav.params().get('view'), '35.41000,-120.95000,11', '?view= is written after the move settles');
  assert.equal(fake.count('setLocation'), moves, 'the renderer\'s own move is not sent back');
  o.onReset();
  assert.equal(nav.params().get('view'), '35.37000,-120.86000,12', 'reset returns to the region centre');
  assert.deepEqual(fake.last('setLocation'), {latitude: 35.37, longitude: -120.86, span: 7300});

  o.onPerspective('2d');
  assert.equal(nav.params().get('presentation'), '2d');
  assert.equal(fake.count('setPerspective'), 0, 'the renderer\'s own perspective change is not echoed');
  o.onCurrentStatus('WCOFS · 4 km source');
  assert.equal(currentStatus.value, 'WCOFS · 4 km source');
  s.destroy();
});

test('a graphics or asset failure returns the stage to Chart with v1\'s message', async () => {
  for (const options of [{ready: false}, {throws: true}]) {
    const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
    const fake = terrain(options);
    const {stage: s, host} = stage(fake);
    await tick();
    assert.equal(terrainFailed.value, true, JSON.stringify(options));
    assert.equal(shownPresentation.value, 'chart');
    assert.equal(terrainBlocked.value, UNAVAILABLE, 'the terrain choices are disabled with the reason');
    assert.equal(nav.params().get('presentation'), '3d', 'the link keeps the request');
    assert.deepEqual(host.shadowRoot.children, [], 'nothing of the renderer is left in the host');
    if (options.ready === false) assert.equal(fake.destroyed, 1);
    choosePresentation('2d');
    await tick();
    assert.equal(fake.mounts, 1, 'no retry until a reload, as in v1');
    s.destroy();
  }
});

test('a region without terrain shows Chart and says why; the link keeps the request', async () => {
  const nav = browser(`${ORIGIN}?region=channel-islands&presentation=3d`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  await tick();
  assert.equal(fake.mounts, 0);
  assert.equal(shownPresentation.value, 'chart');
  assert.equal(terrainBlocked.value, NO_TERRAIN);
  assert.equal(nav.params().get('presentation'), '3d');
  navigate(`${ORIGIN}?region=cambria-san-simeon&presentation=3d`);
  await tick();
  assert.equal(fake.mounts, 1, 'a region with terrain mounts it without a reload');
  s.destroy();
});

test('without ?hour= the terrain hour moves on at each hour boundary, not frozen at mount', async t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const fake = terrain();
  let clock = NOW;
  const {stage: s} = stage(fake, {now: () => clock});
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.deepEqual(fake.options.initial.hour, new Date('2026-10-05T20:00:00Z'));
  clock = new Date('2026-10-05T21:00:01Z');
  t.mock.timers.tick(43 * 60 * 1000 + 1000);
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-05T21:00:00Z'), 'the next whole hour reaches the renderer');
  clock = new Date('2026-10-05T22:00:01Z');
  t.mock.timers.tick(60 * 60 * 1000);
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-05T22:00:00Z'));
  setParams({hour: '2026-10-06T03:00Z'});
  clock = new Date('2026-10-05T23:00:01Z');
  t.mock.timers.tick(60 * 60 * 1000);
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-06T03:00:00Z'), 'a chosen hour stays chosen');
  s.destroy();
});
