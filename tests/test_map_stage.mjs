// MapStage adapter (FE-71, docs/plans/front-end/design.md § 3A.2): the
// store-to-renderer and renderer-to-store flows over a fake terrain module,
// so neither three nor a GPU is needed. web/map/stage.ts runs by type stripping.
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {
  ENTRY_PITCH, ENTRY_ZOOM_DROP, FPS_WINDOW_MS, HOME_ZOOM, MAX_PITCH, MIN_3D_ZOOM, NO_TERRAIN, UNAVAILABLE, UNSUPPORTED_CURRENT, camera, cameraParam, choosePresentation, coastSpecies, createStage,
  currentStatus, locationFor, parseCamera, shownPresentation, spanForZoom, terrainBlocked, terrainFailed, terrainHour, terrainMark,
  terrainState, zoomForSpan, PHONE_QUERY, TERRAIN_DEFAULTS, createFrameMonitor, entryCamera, fpsFallback, setTerrainOption, threeDOffered, terrainActions, terrainCoverage, terrainOptions, terrainShading, terrainPick, terrainReading,
} from '../web/map/stage.ts';
import {configureStore, navigate, setParams, syncFromURL} from '../web/state.ts';
import {dockTime} from '../web/hour.ts';
import {createHourClock} from '../web/clock.ts';

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
function terrain({ready = true, throws = false, hold = false} = {}) {
  const fake = {calls: [], mounts: 0, destroyed: 0, options: null};
  const handle = {};
  for (const name of ['setPerspective', 'setLocation', 'setSpecies', 'setHour', 'setDepthLimit', 'setCurrentLayer', 'selectHabitat', 'setVisible',
    'setRelief', 'setTheme', 'setWaterVisible', 'setWaterOpacity', 'setContours', 'setSunAzimuth', 'setPhotoMix', 'setFixedRamp', 'setSourceCoverage', 'setHabitatVisible', 'zoom', 'resetView', 'topView', 'openSources']) {
    handle[name] = value => { fake.calls.push([name, value]); return true; };
  }
  // As packages/coast's viewer does: setPerspective reports the new mode through onPerspective, synchronously.
  handle.setPerspective = value => { fake.calls.push(['setPerspective', value]); fake.options?.onPerspective?.(value); return true; };
  // `hold`: the coast data never answers, so load() stays pending until fake.settle(ready) is called.
  handle.load = hold ? () => new Promise(resolve => { fake.settle = resolve; }) : async () => ready;
  handle.destroy = () => { fake.destroyed++; };
  // A repaint the renderer refuses (an unusable overlay palette) throws; `fake.refuseTheme` turns that on.
  handle.setTheme = value => { fake.calls.push(['setTheme', value]); if (fake.refuseTheme) throw new TypeError('refused'); return true; };
  fake.module = {
    styles: ['coast.css'],
    mountCoast(host, options) {
      fake.mounts++;
      fake.host = host;
      fake.options = options;
      if (throws) { host.shadowRoot.children = ['scene']; throw new Error('WebGL unavailable'); }
      if (hold) host.shadowRoot.children = ['scene'];
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

function stage(fake, {center = [35.37, -120.86], doc = document(), now = () => NOW, clock, ...extra} = {}) {
  const host = {dataset: {}, shadowRoot: {children: [], replaceChildren() { this.children = []; }}};
  terrainFailed.value = false;
  terrainMark.value = null;
  const s = createStage({host, load: async () => fake.module, center: () => center, now, clock, doc, viewDelay: 0, ...extra});
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
  for (const [value, dayValue] of [['2026-10-06T03:00Z', null], ['2026-10-06T03:00Z', '2026-10-07'], ['2026-10-12T23:00Z', null], ['2026-12-01T00:00Z', null]]) {
    assert.deepEqual(terrainHour(value, NOW, dayValue, 'America/Los_Angeles'), new Date(dockTime(dayValue, value, NOW, 'America/Los_Angeles').at),
      `?hour=${value} (day ${dayValue}) reads the same hour as the dock, inside or outside the horizon`);
  }
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

test('the first terrain choice mounts the renderer once with the store\'s state; later changes reach the handle', async t => {
  const nav = browser(`${ORIGIN}?region=morro-bay&profile=spear&target=rockfish&hour=2026-10-06T03:00Z&current=hfr-6&habitat=reef:r1`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  t.after(() => s.destroy());
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
    // MB-14: a 3D choice made from Chart starts at the entry camera: pitched 60°, half a zoom level wider (bearing 0: no 3D view to keep).
    currentLayer: 'hfr-6', species: 'rockfish-reef', depthLimit: 60, location: {latitude: 35.37, longitude: -120.86, span: spanForZoom(HOME_ZOOM - ENTRY_ZOOM_DROP), bearing: 0, pitch: ENTRY_PITCH},
    hour: new Date('2026-10-06T03:00:00Z'), perspective: '3d', habitat: 'reef:r1', visible: true,
  });
  assert.deepEqual(fake.calls.filter(([name]) => name !== 'setRelief'), [], 'the initial state is not sent twice');
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

test('Chart, 2D and 3D each select themselves from any other; the renderer\'s perspective echo never overrides the choice', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=2d&profile=spear&target=rockfish&hour=2026-10-06T03:00Z&habitat=reef:r1&view=35.5,-121,10`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  await tick();
  assert.equal(fake.mounts, 1);
  let from = '2d';
  for (const next of ['chart', '2d', '3d', 'chart', '3d', '2d', 'chart', '2d']) {
    const perspectiveCalls = fake.count('setPerspective');
    choosePresentation(next);
    assert.equal(nav.params().get('presentation'), next, `${from} → ${next}: the address keeps the choice`);
    assert.equal(shownPresentation.value, next, `${from} → ${next}: the stage shows it`);
    for (const key of ['region', 'profile', 'target', 'hour', 'habitat', 'view']) assert.ok(nav.params().get(key), `${from} → ${next}: ${key} kept`);
    assert.equal(fake.last('setVisible') ?? true, next !== 'chart', `${from} → ${next}: terrain visibility`);
    if (next !== 'chart') assert.equal(fake.last('setPerspective') ?? '2d', next, `${from} → ${next}: the camera mode`);
    else assert.equal(fake.count('setPerspective'), perspectiveCalls, `${from} → Chart: hiding terrain sends no camera mode`);
    from = next;
  }
  assert.equal(fake.mounts, 1, 'mounted once');
  s.destroy();
});

test('FE-60: a renderer 3D control callback from 2D updates presentation without an echo or stale Chart override', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=2d&profile=spear&target=rockfish&hour=2026-10-06T03:00Z&habitat=reef:r1&view=35.5,-121,10`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  try {
    await tick();
    const kept = [...nav.params()].filter(([key]) => key !== 'presentation');
    const assertPresentation = (mode, visible) => {
      assert.equal(nav.params().get('presentation'), mode, 'the address follows the selected presentation');
      assert.equal(shownPresentation.value, mode, 'the stage follows the selected presentation');
      assert.equal(fake.last('setVisible') ?? fake.options.initial.visible, visible, 'terrain visibility follows the presentation');
      assert.deepEqual([...nav.params()].filter(([key]) => key !== 'presentation'), kept, 'the other shared state is preserved');
    };
    assert.equal(fake.options.initial.perspective, '2d');
    assertPresentation('2d', true);
    const perspectiveCalls = fake.count('setPerspective');
    fake.options.onPerspective('3d');
    assertPresentation('3d', true);
    assert.equal(fake.count('setPerspective'), perspectiveCalls, 'the renderer control is not echoed back');

    choosePresentation('chart');
    assertPresentation('chart', false);
    assert.equal(fake.count('setPerspective'), perspectiveCalls, 'Chart sends no perspective to the renderer');
    fake.options.onPerspective('2d');
    assertPresentation('chart', false);
    assert.equal(fake.count('setPerspective'), perspectiveCalls, 'a hidden renderer callback cannot echo or replace Chart');

    choosePresentation('2d');
    assertPresentation('2d', true);
    assert.equal(fake.count('setPerspective'), perspectiveCalls + 1, 'returning from Chart sends the chosen mode once');
    assert.equal(fake.last('setPerspective'), '2d');
    fake.options.onPerspective('3d');
    assertPresentation('3d', true);
    assert.equal(fake.count('setPerspective'), perspectiveCalls + 1, 'the next renderer control also has no recursive echo');
    assert.equal(fake.mounts, 1, 'all transitions reuse the renderer');
  } finally {
    s.destroy();
  }
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

test('while the coast data never answers the scene stays mounted; it goes only when the renderer gives up (FE-60)', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const fake = terrain({hold: true});
  const {stage: s, host} = stage(fake);
  await tick();
  await tick();
  assert.equal(fake.mounts, 1);
  assert.deepEqual(host.shadowRoot.children, ['scene'], 'the loading scene is in the host while the load is pending');
  assert.equal(terrainFailed.value, false, 'a pending load is not a failure');
  assert.equal(shownPresentation.value, '3d');
  fake.settle(false);
  await tick();
  assert.equal(terrainFailed.value, true, 'the renderer gave up');
  assert.deepEqual(host.shadowRoot.children, [], 'only then is the scene removed and Chart shown');
  assert.equal(shownPresentation.value, 'chart');
  assert.equal(nav.params().get('presentation'), '3d');
  s.destroy();
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

/** An hour clock over a settable reader and a manual scheduler: `fire()` runs the one waiting timeout. */
function manualClock(start) {
  let at = new Date(start), next = 1;
  const timers = new Map();
  const clock = createHourClock({read: () => new Date(at), doc: document(), schedule: (callback, delay) => { timers.set(next, {callback, delay}); return next++; }, cancel: id => { timers.delete(id); }});
  return {clock, timers, set(value) { at = new Date(value); }, fire() { const [[id, timer]] = [...timers]; timers.delete(id); timer.callback(); }};
}

test('shared clock: a stage follows an injected clock across the hour, shows it on the host, and releases it on destroy', async () => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const fake = terrain();
  const c = manualClock('2026-10-05T20:59:59.999Z');
  const {stage: s, host} = stage(fake, {clock: c.clock, now: () => new Date('2030-01-01T00:00:00Z')});
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert.deepEqual(fake.options.initial.hour, new Date('2026-10-05T20:00:00Z'), 'an explicit clock wins over now');
  assert.equal(host.dataset.hour, '2026-10-05T20:00:00.000Z');
  assert.equal(c.timers.size, 1);
  c.set('2026-10-05T21:00:00Z');
  c.fire();
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-05T21:00:00Z'));
  assert.equal(host.dataset.hour, '2026-10-05T21:00:00.000Z', 'data-hour follows the clock');
  const mounts = fake.mounts;
  setParams({hour: '2026-10-06T03:00Z'});
  c.set('2026-10-05T23:30:00Z');
  c.fire();
  assert.deepEqual(fake.last('setHour'), new Date('2026-10-06T03:00:00Z'), 'a chosen hour survives the tick');
  assert.equal(fake.mounts, mounts, 'a tick does not remount the renderer');
  s.destroy();
  s.destroy();
  assert.equal(c.timers.size, 0, 'destroy releases the clock, once or twice');
});

test('shared clock: stages on one clock share one timeout, and the last destroy stops it', async () => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const c = manualClock('2026-10-05T20:17:00Z');
  const a = stage(terrain(), {clock: c.clock}), b = stage(terrain(), {clock: c.clock});
  assert.equal(c.timers.size, 1);
  a.stage.destroy();
  assert.equal(c.timers.size, 1, 'one stage still using it');
  b.stage.destroy();
  assert.equal(c.timers.size, 0);
});

test('FE-80: host chrome; the Seafloor entry\'s options reach the setters, readings and sources arrive as data, the view buttons drive the handle', async t => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d&layers=seafloor`);
  terrainOptions.value = TERRAIN_DEFAULTS;
  const fake = terrain();
  const {stage: s} = stage(fake);
  t.after(() => { s.destroy(); terrainOptions.value = TERRAIN_DEFAULTS; });
  await tick();
  const o = fake.options;
  assert.equal(o.chrome, 'host', 'the renderer\'s own panels leave the scene');
  const setters = ['setRelief', 'setWaterVisible', 'setWaterOpacity', 'setContours', 'setSourceCoverage', 'setHabitatVisible', 'setSunAzimuth', 'setPhotoMix', 'setFixedRamp'];
  // The native renderer still starts at 5×. Changing only the stage's default would move the slider but not the seabed.
  assert.deepEqual(fake.calls.filter(([name]) => setters.includes(name)), [['setRelief', 2]], 'only relief differs from the native defaults');
  assert.equal(terrainOptions.value.relief, 2, 'the rail and the scene start at the same factor');

  setTerrainOption('relief', 9); setTerrainOption('water', false); setTerrainOption('waterOpacity', 0.3);
  setTerrainOption('contours', false); setTerrainOption('sourceCoverage', true);
  assert.deepEqual(setters.slice(0, 5).map(n => fake.last(n)), [9, false, 0.3, false, true]);
  setTerrainOption('sunAzimuth', 200); setTerrainOption('photoMix', 0.25); setTerrainOption('fixedRamp', true);
  assert.deepEqual(setters.slice(6).map(n => fake.last(n)), [200, 0.25, true]);
  setTerrainOption('relief', 9);
  assert.equal(fake.count('setRelief'), 2, 'an unchanged option is not sent again');
  setParams({layers: 'currents'});
  assert.equal(fake.last('setHabitatVisible'), false, 'turning Seafloor off hides the reefs and pins');
  setParams({layers: 'seafloor,currents'});
  assert.equal(fake.last('setHabitatVisible'), true);

  const reading = {latitude: 35.37, longitude: -120.86, heightM: -12, spacingM: 2, label: 'MEASURED LIDAR · NAVD88', value: '39 ft depth', location: '35.37000° N · 120.86000° W',
    detail: 'NOAA lidar · 2022-06-14 · 2 m display spacing.', source: {id: 1, label: 'NOAA lidar', kind: 'lidar', resolutionM: 1, datum: 'NAVD88', sourceDate: '2022-06-14', url: 'https://example.test'}};
  terrainPick.value = {id: 'mpa:x', name: 'x', kind: 'x', reading: '', source: '', basis: ''};
  o.onReading(reading);
  assert.equal(terrainReading.value, reading, 'the reading arrives verbatim');
  assert.equal(terrainPick.value, null, 'a reading replaces a picked overlay\'s card');
  o.onReading(null);
  assert.equal(terrainReading.value, null);
  o.onSourceCoverage({sources: [reading.source], key: 'Mint: lidar'});
  assert.equal(terrainCoverage.value.key, 'Mint: lidar');
  const shading = {readout: 'Ramp 61–142 ft in view · contours 10 ft, index 50 ft', rampMinM: 18.6, rampMaxM: 43.3, contourMinorM: 3.048, contourIndexM: 15.24, fixedRamp: false, relief: 5};
  o.onShading(shading);
  assert.equal(terrainShading.value, shading, 'the shading readout arrives verbatim');

  const a = terrainActions.value;
  a.zoom('in'); a.zoom('out'); a.top(); a.sources();
  assert.deepEqual([fake.calls.filter(([n]) => n === 'zoom').map(([, v]) => v), fake.count('topView'), fake.count('openSources')], [['in', 'out'], 1, 1]);
  a.reset();
  assert.equal(nav.params().get('view'), '35.37000,-120.86000,12', 'reset is the stage\'s home, as the scene\'s own button');
  s.destroy();
  assert.equal(terrainActions.value, null, 'no view buttons without a renderer');
  // A new stage (e.g. after a desktop/phone layout change) must apply the prior choice, not the new default.
  const remounted = terrain(), second = stage(remounted);
  try {
    await tick();
    assert.deepEqual(remounted.calls.filter(([name]) => name === 'setRelief'), [['setRelief', 9]]);
  } finally { second.stage.destroy(); }
});

test('legacy_camera_links_are_byte_identical: three-field links parse to the old object and serialize unchanged', () => {
  const legacy = parseCamera('35.37,-120.86,12');
  assert.deepEqual(Object.keys(legacy), ['latitude', 'longitude', 'zoom'], 'precisely the old three properties');
  assert.equal(cameraParam(legacy), '35.37000,-120.86000,12');
  assert.deepEqual(locationFor(legacy), {latitude: 35.37, longitude: -120.86, span: 7300});
  assert.equal(cameraParam({latitude: 35.371234567, longitude: -120.86, zoom: 11.456}), '35.37123,-120.86000,11.46');
  assert.equal(cameraParam({latitude: 35, longitude: -120, zoom: 12, bearing: 30}), '35.00000,-120.00000,12', 'half a pair is not written');
  assert.deepEqual(locationFor({latitude: 35, longitude: -120, zoom: 12, pitch: 30}), {latitude: 35, longitude: -120, span: 7300});
});

test('oriented_camera_tuple_is_closed_and_finite: five fields in range parse; any other shape is refused whole', () => {
  assert.deepEqual(parseCamera('35.37,-120.86,12,35,50'), {latitude: 35.37, longitude: -120.86, zoom: 12, bearing: 35, pitch: 50});
  for (const [bearing, pitch] of [[0, 0], [-35.5, 90], [180, 45], [-180, 45]]) {
    assert.deepEqual(parseCamera(`35,-120,12,${bearing},${pitch}`), {latitude: 35, longitude: -120, zoom: 12, bearing, pitch}, `${bearing},${pitch}`);
  }
  for (const bad of ['35,-120,12,35', '35,-120,12,35,50,1', '35,-120,12,,50', '35,-120,12,35,', '35,-120,12,NaN,50', '35,-120,12,35,Infinity',
    '35,-120,12,180.01,50', '35,-120,12,-181,50', '35,-120,12,35,-0.01', '35,-120,12,35,90.01', '95,-120,12,35,50', '35,-181,12,35,50', '35,-120,12,x,50']) {
    assert.equal(parseCamera(bad), null, bad);
  }
  // Canonical: two decimals, and what is written parses back to what is written (no rewriting forever).
  const written = cameraParam({latitude: 35.37, longitude: -120.86, zoom: 12, bearing: 35.12345, pitch: 49.999});
  assert.equal(written, '35.37000,-120.86000,12,35.12,50');
  assert.equal(cameraParam(parseCamera(written)), written);
  assert.equal(cameraParam({latitude: 35, longitude: -120, zoom: 12, bearing: -0.001, pitch: 10}), '35.00000,-120.00000,12,0,10', 'no -0');
  assert.equal(cameraParam({latitude: 35, longitude: -120, zoom: 12, bearing: 190, pitch: 10}), '35.00000,-120.00000,12,-170,10', 'bearing in the signed interval');
  assert.equal(cameraParam({latitude: 35, longitude: -120, zoom: 12, bearing: 35, pitch: 120}), '35.00000,-120.00000,12', 'an out-of-range pitch is not written');
  assert.deepEqual(locationFor(parseCamera('35,-120,12,-35.5,50')), {latitude: 35, longitude: -120, span: 7300, bearing: -35.5, pitch: 50});
});

test('stage_orbit_share_reopen_has_no_echo: a 3D orbit report becomes the five-field view after the debounce, is not sent back, and reopening hands the pair to the renderer', async () => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d&profile=boat&target=rockfish&hour=2026-10-06T03:00Z&habitat=reef:r1`);
  const fake = terrain();
  const {stage: s} = stage(fake);
  await tick();
  const moves = fake.count('setLocation');
  fake.options.onView({latitude: 35.41, longitude: -120.95, span: 14600, bearing: -35.123, pitch: 49.876});
  assert.deepEqual(camera.value, {latitude: 35.41, longitude: -120.95, zoom: 11, bearing: -35.12, pitch: 49.88}, 'the shared camera follows at once, rounded');
  await tick();
  assert.equal(nav.params().get('view'), '35.41000,-120.95000,11,-35.12,49.88');
  assert.equal(fake.count('setLocation'), moves, 'the renderer\'s own orbit is not sent back');
  // 2D and old emitters without an orientation report the three-field form.
  fake.options.onView({latitude: 35.42, longitude: -120.95, span: 14600});
  await tick();
  assert.equal(nav.params().get('view'), '35.42000,-120.95000,11');
  fake.options.onView({latitude: 35.42, longitude: -120.95, span: 14600, bearing: 10, pitch: 20});
  choosePresentation('2d');
  fake.options.onView({latitude: 35.43, longitude: -120.95, span: 14600, bearing: 10, pitch: 20});
  await tick();
  assert.equal(nav.params().get('view'), '35.43000,-120.95000,11', 'a 2D camera carries no orientation');
  s.destroy();

  // Reopen the shared address in a fresh stage: initial.location carries the pair and nothing else moves.
  const shared = `${ORIGIN}?region=morro-bay&presentation=3d&profile=boat&target=rockfish&hour=2026-10-06T03:00Z&habitat=reef:r1&view=35.41000,-120.95000,11,-35.12,49.88`;
  browser(shared);
  const again = terrain();
  const second = stage(again);
  await tick();
  assert.deepEqual(again.options.initial.location, {latitude: 35.41, longitude: -120.95, span: 14600, bearing: -35.12, pitch: 49.88});
  assert.deepEqual([again.options.initial.species, again.options.initial.habitat, again.options.initial.depthLimit, again.options.initial.hour, again.options.initial.perspective],
    ['rockfish-reef', 'reef:r1', 300, new Date('2026-10-06T03:00:00Z'), '3d']);
  assert.equal(again.count('setLocation'), 0, 'the initial location is not sent twice');
  second.stage.destroy();
});

// MB-14. Contract: the 3D entry camera (§ 2.3). Bug it catches: entering 3D at the Chart's flat camera, forgetting the 3D bearing,
// or widening the view by half a zoom level again on every 2D/3D round trip.
test('MB-14 entry: a 3D choice after Chart or 2D starts at pitch 60°, half a zoom wider, keeping the 3D bearing, without drifting on a straight return', async t => {
  browser(`${ORIGIN}?region=morro-bay&presentation=2d&view=35.37,-120.86,13`);
  const fake = terrain(), {stage: s} = stage(fake);
  t.after(() => s.destroy());
  await tick();
  assert.equal(fake.count('setLocation'), 0, 'a 2D mount carries no orientation');
  choosePresentation('3d');
  assert.deepEqual(camera.value, {latitude: 35.37, longitude: -120.86, zoom: 13 - ENTRY_ZOOM_DROP, bearing: 0, pitch: ENTRY_PITCH}, 'no 3D view to keep: north-up');
  assert.deepEqual(fake.last('setLocation'), {latitude: 35.37, longitude: -120.86, span: spanForZoom(12.5), bearing: 0, pitch: 60});
  assert.equal(fake.last('setPerspective'), '3d');
  fake.options.onView({latitude: 35.37, longitude: -120.86, span: spanForZoom(12.5), bearing: 40, pitch: 55});
  choosePresentation('2d');
  fake.options.onView({latitude: 35.37, longitude: -120.86, span: spanForZoom(12.5)});
  choosePresentation('3d');
  assert.deepEqual(fake.last('setLocation'), {latitude: 35.37, longitude: -120.86, span: spanForZoom(12.5), bearing: 40, pitch: 60}, 'bearing kept, zoom not widened again');
  // A 2D view that moved is a new 3D entry.
  choosePresentation('2d');
  fake.options.onView({latitude: 35.37, longitude: -120.86, span: spanForZoom(14)});
  choosePresentation('3d');
  assert.equal(camera.value.zoom, 14 - ENTRY_ZOOM_DROP);
  assert.deepEqual(entryCamera({latitude: 1, longitude: 2, zoom: 0.2}, 5), {latitude: 1, longitude: 2, zoom: 0, bearing: 5, pitch: 60}, 'the entry zoom stays on the map\'s zoom range');
});

// Contract: 3D is offered from z11 on a desktop and z12 on a phone; no camera yet means the region's home zoom (12).
test('MB-14 offered: 3D needs z11 on a desktop and z12 on a phone', () => {
  assert.deepEqual([MIN_3D_ZOOM.desktop, MIN_3D_ZOOM.phone], [11, 12]);
  assert.deepEqual([10.99, 11, 11.5].map(z => threeDOffered(z, false)), [false, true, true]);
  assert.deepEqual([11.99, 12, 13].map(z => threeDOffered(z, true)), [false, true, true]);
  assert.equal(threeDOffered(null, true), true, 'no camera: the home zoom');
  // Bug it catches: a 599 px phone cutoff, which offers 3D at z11 on an 800 px tablet-width phone viewport.
  assert.equal(PHONE_QUERY, '(max-width: 899px)', 'phone means below 900 px');
});

// Contract: a page opened in 3D is a 3D entry too (§ 2.3), unless its link names an orbit. Bug it catches: starting the entry
// bookkeeping already in 3D, so a link without an orbit never gets the 60° pitch and half zoom drop; or overwriting a shared orbit.
test('MB-14 opening: a 3D link without an orbit gets the entry pose, one with an orbit keeps it, a late home waits for the centre', async t => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d&view=35.37,-120.86,13`);
  const plain = terrain(), first = stage(plain);
  t.after(() => first.stage.destroy());
  await tick();
  assert.deepEqual(plain.options.initial.location, {latitude: 35.37, longitude: -120.86, span: spanForZoom(12.5), bearing: 0, pitch: 60}, 'unoriented 3D link: entry pose at mount');
  assert.equal(plain.count('setLocation'), 0, 'sent once, as the initial state');
  first.stage.destroy();

  browser(`${ORIGIN}?region=morro-bay&presentation=3d&view=35.41000,-120.95000,11,-35.12,49.88`);
  const shared = terrain(), second = stage(shared);
  t.after(() => second.stage.destroy());
  await tick();
  assert.deepEqual(shared.options.initial.location, {latitude: 35.41, longitude: -120.95, span: spanForZoom(11), bearing: -35.12, pitch: 49.88}, 'shared orbit kept');
  second.stage.destroy();

  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  camera.value = null;
  const centre = signal(null), third = createStage({host: {dataset: {}, shadowRoot: {children: [], replaceChildren() {}}}, load: async () => terrain().module,
    center: () => centre.value, now: () => NOW, doc: document(), viewDelay: 0});
  t.after(() => third.destroy());
  await tick();
  centre.value = [35.37, -120.86];
  await tick();
  assert.deepEqual(camera.value, {latitude: 35.37, longitude: -120.86, zoom: 12 - ENTRY_ZOOM_DROP, bearing: 0, pitch: ENTRY_PITCH}, 'the entry pose follows the home camera');
});

// Contract: the renderer is told the host's pitch cap and token sky at mount, and is timed through its frame callback.
test('MB-14 mount: the renderer gets the 75° pitch cap, the token sky and a frame callback', async t => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const fake = terrain(), sky = {sky: '#s', horizon: '#h', fog: '#f', ground: '#g'}, {stage: s} = stage(fake, {sky: () => sky});
  t.after(() => s.destroy());
  await tick();
  assert.equal(fake.options.maxPitch, MAX_PITCH); assert.equal(MAX_PITCH, 75);
  assert.deepEqual(fake.options.sky, sky);
  assert.equal(typeof fake.options.onFrame, 'function');
});

// Contract: "under 24 fps for 2 s". Bug it catches: judging a window by one slow frame, never judging at all, or timing a tab
// that was in the background. The clock is the caller's, so no real time passes.
test('MB-14 frame watch on a fake clock: a full 2 s window under 24 fps fires, a healthy, idle or restarted one does not', () => {
  let slow = 0;
  const monitor = createFrameMonitor(() => { slow++; });
  const run = (fps, from, ms) => { let at = from; for (; at < from + ms; at += 1000 / fps) monitor.frame(at); return at; };
  let at = run(30, 0, 10_000);
  assert.equal(slow, 0, '30 fps is healthy');
  at = run(25, at, 6000);
  assert.equal(slow, 0, '25 fps is above the floor');
  at = run(60, at, 1000); at = run(20, at, 1000); at = run(60, at, 1000);
  assert.equal(slow, 0, 'one slow second between fast ones is not 2 s under the floor');
  at = run(20, at, FPS_WINDOW_MS + 100);
  assert.equal(slow, 1, 'a full window at 20 fps fires once, wherever the window falls');
  at = run(20, at, 1500); monitor.reset(); at = run(20, at, 1500);
  assert.equal(slow, 1, 'a reset drops the open window: neither half is 2 s');
  monitor.frame(at + 60_000); run(60, at + 60_000, 3000);
  assert.equal(slow, 1, 'a long gap (a throttled page) is not judged');
  const freeze = at + 120_000; monitor.frame(freeze); monitor.frame(freeze + 3000);
  assert.equal(slow, 2, 'a 3 s freeze is one frame in a full window');
});

// Contract: slow 3D returns to 2D with a notice; only a loaded, visible, shown 3D view is timed. Bug it catches: falling back during
// the terrain's own load, while hidden or on Chart, adding a history entry Back would return to, or never clearing the notice.
test('MB-14 fallback: 2 s under 24 fps on a loaded 3D view goes back to 2D in place with a notice', async t => {
  const nav = browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const fake = terrain({hold: true}), {stage: s, doc} = stage(fake);
  t.after(() => { s.destroy(); fpsFallback.value = false; });
  fpsFallback.value = false;
  await tick();
  let at = 1000;
  const frames = (fps, ms) => { const end = at + ms; for (; at < end; at += 1000 / fps) fake.options.onFrame(at); };
  frames(10, 5000);
  assert.equal(nav.params().get('presentation'), '3d', 'the terrain is still loading: nothing is timed');
  fake.settle(true); await tick();
  frames(60, 5000);
  assert.equal(nav.params().get('presentation'), '3d'); assert.equal(fpsFallback.value, false);
  doc.set(true); frames(10, 5000); doc.set(false);
  assert.equal(nav.params().get('presentation'), '3d', 'a hidden page is not timed');
  const entries = nav.stack.length;
  frames(15, FPS_WINDOW_MS + 200);
  assert.equal(nav.params().get('presentation'), '2d'); assert.equal(fpsFallback.value, true);
  assert.equal(shownPresentation.value, '2d'); assert.equal(fake.last('setPerspective'), '2d');
  assert.equal(nav.stack.length, entries, 'the link is rewritten in place: Back does not return to the slow view');
  frames(10, 5000);
  assert.equal(nav.params().get('presentation'), '2d', 'a 2D view is never timed');
  choosePresentation('3d');
  assert.equal(fpsFallback.value, false, 'choosing 3D again ends the notice');
});

// Contract (MB-21 follow-up): a live theme switch repaints in place. Bug it catches: remounting or re-draping on a switch (a
// request for tiles/feeds), moving the camera, repainting twice for one theme, or one failed repaint stopping later ones.
test('MB-14 theme: a live switch calls setTheme on the same handle with fresh tokens and nothing else', async t => {
  browser(`${ORIGIN}?region=morro-bay&presentation=3d`);
  const palettes = {dark: {id: 'dark-palette', mpaFillOpacity: '0.08'}, light: {id: 'light-palette', mpaFillOpacity: '0.08'}};
  const skies = {dark: {sky: 'd1', horizon: 'd2', fog: 'd3', ground: 'd4'}, light: {sky: 'l1', horizon: 'l2', fog: 'l3', ground: 'l4'}};
  let now = 'dark', emit;
  const fake = terrain(), {stage: s} = stage(fake, {
    overlayPalette: () => palettes[now], sky: () => skies[now], theme: notify => { emit = notify; return () => { emit = undefined; }; },
  });
  t.after(() => s.destroy());
  await tick();
  assert.deepEqual(fake.options.sky, skies.dark, 'mounted with the current theme');
  const before = fake.calls.length, view = camera.value, mounts = fake.mounts;
  now = 'light'; await emit('light');
  assert.deepEqual(fake.calls.slice(before), [['setTheme', {sky: skies.light, overlayPalette: palettes.light}]], 'one in-place repaint, nothing else');
  assert.equal(camera.value, view, 'camera kept'); assert.equal(fake.mounts, mounts, 'no remount');
  await emit('light');
  assert.equal(fake.count('setTheme'), 1, 'the same theme is not repainted');
  now = 'dark'; await emit('dark');
  assert.deepEqual(fake.last('setTheme'), {sky: skies.dark, overlayPalette: palettes.dark});
  // A repaint the renderer refuses is logged, not thrown; the next switch still lands.
  const warn = console.warn; let logged = 0; console.warn = () => { logged++; };
  try { fake.refuseTheme = true; now = 'light'; await emit('light'); } finally { console.warn = warn; }
  assert.equal(logged, 1, 'logged once');
  fake.refuseTheme = false; now = 'dark'; await emit('dark');
  assert.deepEqual(fake.last('setTheme'), {sky: skies.dark, overlayPalette: palettes.dark}, 'the next switch still lands');
});
