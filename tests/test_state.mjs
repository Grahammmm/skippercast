// State v2 (FE-04, design § 8): profile, view, day, layers, area and base
// round-trip through the URL; profile, layers and base persist and restore
// when the URL omits them; v2 never reloads on a region change.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  APP_VIEWS, BASES, STORAGE_KEYS, URL_KEYS, appView, area, base, configureStore, day, layers, layersParam, lockRegion,
  needsReload, parseDay, parseLayers, profile, readURL, regionLocked, resolveStored, syncFromURL, view, withParams,
} from '../web/state.ts';
import {PROFILE_TABLE} from '../web/profile.ts';

const memory = () => {const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m};};
const ORIGIN = 'https://s.test/map';

test('every v2 key round-trips through withParams, readURL and syncFromURL', () => {
  const store = memory();
  configureStore({storage: store});
  const patch = {region: 'morro-bay', coast: null, view: 'conditions', target: 'halibut', hour: '2026-09-30T15:00Z',
    profile: 'shore', day: '2026-10-06', layers: 'swell,water-temp', area: 'estero', base: 'chart',
    presentation: '3d', current: 'hfr-1', habitat: 'reef:r12'};
  assert.deepEqual(Object.keys(patch).sort(), [...URL_KEYS].sort(), 'the test covers every store key');
  const href = withParams(ORIGIN + '?focus=r12', patch);
  const read = readURL(href);
  for (const key of URL_KEYS) assert.equal(read[key], patch[key], key);
  assert.equal(read.selection, 'r12', 'focus still selects the spot');
  syncFromURL(href);
  assert.equal(profile.value, 'shore');
  assert.equal(appView.value, 'conditions');
  assert.equal(view.value, 'conditions', 'the raw ?view= stays readable for v1 parsers');
  assert.equal(day.value, '2026-10-06');
  assert.deepEqual(layers.value, ['swell', 'water-temp']);
  assert.equal(area.value, 'estero');
  assert.equal(base.value, 'chart');
  assert.equal(withParams(href, {layers: layersParam(layers.value)}), href, 'layers write back as they were read');
  const cleared = readURL(withParams(href, {profile: null, day: null, layers: null, area: null, base: null}));
  for (const key of ['profile', 'day', 'layers', 'area', 'base']) assert.equal(cleared[key], key === 'area' ? 'r12' : null, key);
});

test('stored profile, layers and base restore when the URL omits them; layers are kept per profile; the URL wins', () => {
  const store = memory();
  configureStore({storage: store});
  syncFromURL(ORIGIN + '?profile=spear&layers=seafloor&base=aerial');
  assert.equal(store.map.get(STORAGE_KEYS.profile), 'spear');
  assert.deepEqual(JSON.parse(store.map.get(STORAGE_KEYS.layers)), {spear: 'seafloor'});
  assert.equal(store.map.get(STORAGE_KEYS.base), 'aerial');
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.equal(profile.value, 'spear');
  assert.deepEqual(layers.value, ['seafloor']);
  assert.equal(base.value, 'aerial');
  syncFromURL(ORIGIN + '?profile=boat');
  assert.equal(profile.value, 'boat', '?profile= wins over storage');
  assert.deepEqual(layers.value, PROFILE_TABLE.boat.defaultLayers, 'another profile has its own layers, its defaults until chosen (FE-20)');
  syncFromURL(ORIGIN + '?layers=none');
  assert.deepEqual(layers.value, [], 'none empties the rail');
  assert.deepEqual(JSON.parse(store.map.get(STORAGE_KEYS.layers)), {spear: 'seafloor', boat: 'none'});
  syncFromURL(ORIGIN + '?profile=spear');
  assert.deepEqual(layers.value, ['seafloor'], 'each profile restores its own list');
  // FE-04's single stored list becomes the stored profile's own list; other profiles keep their defaults.
  store.setItem(STORAGE_KEYS.layers, 'clouds');
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.deepEqual(layers.value, ['clouds'], 'the legacy list loads for the stored profile');
  assert.deepEqual(JSON.parse(store.map.get(STORAGE_KEYS.layers)), {spear: 'clouds'});
  syncFromURL(ORIGIN + '?profile=boat');
  assert.deepEqual(layers.value, PROFILE_TABLE.boat.defaultLayers);
  syncFromURL(ORIGIN + '?profile=spear');
  assert.deepEqual(layers.value, ['clouds'], 'and stays that profile\'s after a switch');
  store.setItem(STORAGE_KEYS.layers, 'none');
  syncFromURL(ORIGIN + '?profile=spear');
  assert.deepEqual(layers.value, [], 'a legacy empty rail loads too');
  // Junk reads as nothing stored.
  for (const old of ['"clouds"', '[1]', '{"spear": 7}', '{']) {
    store.setItem(STORAGE_KEYS.layers, old);
    syncFromURL(ORIGIN + '?profile=spear');
    assert.deepEqual(layers.value, PROFILE_TABLE.spear.defaultLayers, old);
  }
});

test('without storage or parameters the profile defaults to boat with its layers; junk is ignored', () => {
  configureStore({storage: null});
  syncFromURL(ORIGIN + '?profile=kayak&view=35.36000,-120.94000,10&day=2026-02-30&layers=,Bad!,&base=sepia&focus=estero');
  assert.equal(profile.value, 'boat');
  assert.deepEqual(layers.value, PROFILE_TABLE.boat.defaultLayers);
  assert.equal(base.value, 'night');
  assert.equal(appView.value, 'coast', 'a v1 map position is not a masthead view');
  assert.equal(view.value, '35.36000,-120.94000,10');
  assert.equal(day.value, null, 'an impossible date is dropped');
  assert.equal(area.value, 'estero', '?focus= is read as the area');
  const broken = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }};
  configureStore({storage: broken});
  assert.doesNotThrow(() => syncFromURL(ORIGIN + '?profile=shore'));
  assert.equal(profile.value, 'shore');
  assert.deepEqual(resolveStored(readURL(ORIGIN)), {profile: 'boat', layers: PROFILE_TABLE.boat.defaultLayers, base: 'night'});
  configureStore({storage: null});
});

test('parsers accept the documented values only', () => {
  assert.equal(parseDay('2026-10-06'), '2026-10-06');
  for (const bad of ['2026-13-01', '2026-10-6', '06/10/2026', '', null]) assert.equal(parseDay(bad), null, String(bad));
  assert.deepEqual(parseLayers('seafloor, currents,seafloor'), ['seafloor', 'currents']);
  assert.deepEqual(parseLayers('none'), []);
  assert.equal(parseLayers(''), null);
  assert.equal(layersParam([]), 'none');
  assert.deepEqual(APP_VIEWS, ['coast', 'conditions', 'history', 'fleet', 'reports']);
  assert.deepEqual(BASES, ['night', 'chart', 'aerial']);
});

test('a v2 store never locks the region and reloads only for another page', () => {
  configureStore({v2: true});
  lockRegion(ORIGIN + '?region=morro-bay');
  assert.equal(regionLocked(), false);
  assert.equal(needsReload(ORIGIN + '?region=morro-bay', ORIGIN + '?region=southern-california', {region: 'morro-bay', coast: null}), false);
  assert.equal(needsReload(ORIGIN + '?region=morro-bay', 'https://s.test/sources.html', null), true);
  configureStore({v2: false});
  assert.equal(needsReload(ORIGIN + '?region=morro-bay', ORIGIN + '?region=southern-california', {region: 'morro-bay', coast: null}), true, 'v1 keeps the reload');
});
