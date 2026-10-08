// Coast keys in the shared store (FE-73, design § 3A.3): presentation,
// current and habitat are store signals parsed exactly as v1's coastal
// modules parse them; v1 readers keep the readURL shape they had.
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  COAST_KEYS, STORAGE_KEYS, UNSUPPORTED, URL_KEYS, configureStore, current, habitat, parseCurrent, parseHabitat, parsePresentation,
  presentation, presentationFor, readURL, region, selection, stagePresentation, syncFromURL, withParams,
} from '../web/state.ts';
import {currentLayers, habitatURL, presentationFromURL} from '../web/coast-context.ts';

const ORIGIN = 'https://s.test/map';
const memory = () => {const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), map: m};};
const reset = () => configureStore({v2: false, storage: null});

test('the coast keys are store keys', () => {
  assert.deepEqual(COAST_KEYS, ['presentation', 'current', 'habitat']);
  for (const key of COAST_KEYS) assert.ok(URL_KEYS.includes(key), key);
  assert.equal(STORAGE_KEYS.presentation, 'skippercast-presentation-v1');
});

test('each coast key round-trips through withParams and syncFromURL', () => {
  for (const v2 of [false, true]) {
    configureStore({v2, storage: memory()});
    const cases = [
      ...['chart', '2d', '3d'].map(value => ['presentation', value, () => presentation.value]),
      ...currentLayers.map(value => ['current', value, () => current.value]),
      ...['reef:r12', 'A.b_c-9', 'x'.repeat(160)].map(value => ['habitat', value, () => habitat.value]),
    ];
    for (const [key, value, read] of cases) {
      const href = withParams(ORIGIN + '?region=morro-bay&spot=r7', {[key]: value});
      assert.equal(readURL(href)[key], value, `${key}=${value} is read (v2 ${v2})`);
      syncFromURL(href);
      assert.equal(read(), value, `${key}=${value} reaches the signal (v2 ${v2})`);
      assert.equal(withParams(href, {[key]: read()}), href, `${key}=${value} writes back as it was read`);
      assert.equal(readURL(withParams(href, {[key]: null}))[key], undefined, `${key} clears`);
    }
    assert.equal(selection.value, 'r7', 'the atlas spot is independent of the habitat');
  }
  reset();
});

test('an absent coast key is not reported, and the signals return to their defaults', () => {
  reset();
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=3d&current=wcofs&habitat=h1');
  const state = readURL(ORIGIN + '?region=morro-bay');
  for (const key of COAST_KEYS) assert.ok(!(key in state), `${key} is left out of a link without it`);
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.equal(presentation.value, 'chart');
  assert.equal(current.value, 'off');
  assert.equal(habitat.value, null);
});

test('an unknown current stays in the URL and parses as unsupported', () => {
  reset();
  for (const value of ['hfr-2', 'WCOFS', '']) {
    const href = ORIGIN + '?region=morro-bay&current=' + encodeURIComponent(value);
    syncFromURL(href);
    assert.equal(current.value, UNSUPPORTED, `"${value}" is unsupported`);
    const moved = withParams(href, {hour: '2026-10-07T15:00Z', target: 'lingcod'});
    assert.equal(new URL(moved).searchParams.get('current'), value, `"${value}" survives another change`);
    assert.equal(readURL(moved).current, value);
  }
  assert.equal(parseCurrent(null), 'off');
  assert.equal(parseCurrent(undefined), 'off');
  for (const id of currentLayers) assert.equal(parseCurrent(id), id);
});

test('habitat rejects ids outside [A-Za-z0-9._:-]{1,160}', () => {
  reset();
  for (const bad of ['', 'reef 12', '<script>', 'reef/12', 'é', 'x'.repeat(161)]) {
    assert.equal(parseHabitat(bad), null, JSON.stringify(bad));
    syncFromURL(ORIGIN + '?habitat=' + encodeURIComponent(bad));
    assert.equal(habitat.value, null, `${JSON.stringify(bad)} selects nothing`);
    assert.equal(new URL(withParams(ORIGIN + '?habitat=h1', {habitat: bad})).searchParams.has('habitat'), false, `${JSON.stringify(bad)} is not written`);
  }
  assert.equal(parseHabitat(null), null);
});

test('the parsers agree with web/coast-context.ts', () => {
  for (const value of ['chart', '2d', '3d', '3D', 'terrain', '', ' 2d', '2d ']) {
    const shown = presentationFromURL(ORIGIN + '?presentation=' + encodeURIComponent(value));
    assert.equal(parsePresentation(value), shown === value ? shown : null, JSON.stringify(value));
  }
  for (const value of ['h1', 'reef:r12', 'reef 12', 'x'.repeat(160), 'x'.repeat(161)]) {
    assert.equal(parseHabitat(value), habitatURL(ORIGIN, value).searchParams.get('habitat'), JSON.stringify(value));
  }
});

test('v2 stores the presentation a link names and restores it when a link omits it; the URL wins', () => {
  const store = memory();
  configureStore({v2: true, storage: store});
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=2d');
  assert.equal(store.map.get(STORAGE_KEYS.presentation), '2d');
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.equal(presentation.value, '2d', 'restored from storage');
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=chart');
  assert.equal(presentation.value, 'chart', 'an explicit chart wins');
  assert.equal(store.map.get(STORAGE_KEYS.presentation), 'chart');
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=sideways');
  assert.equal(presentation.value, 'chart', 'junk falls back to the stored value');
  assert.equal(store.map.get(STORAGE_KEYS.presentation), 'chart', 'junk is not stored');
  store.map.set(STORAGE_KEYS.presentation, 'sideways');
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.equal(presentation.value, 'chart', 'a junk stored value is ignored');
  reset();
});

test('a v1 store neither writes nor reads the stored presentation', () => {
  const store = memory();
  store.map.set(STORAGE_KEYS.presentation, '3d');
  configureStore({v2: false, storage: store});
  syncFromURL(ORIGIN + '?region=morro-bay');
  assert.equal(presentation.value, 'chart', 'v1 removes the key to mean chart');
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=2d');
  assert.equal(presentation.value, '2d');
  assert.equal(store.map.get(STORAGE_KEYS.presentation), '3d', 'v1 leaves storage alone');
  reset();
});

test('terrain presentations show as chart where the region has no coast terrain, without rewriting the URL', () => {
  reset();
  const href = ORIGIN + '?region=southern-california&presentation=3d';
  syncFromURL(href);
  assert.equal(presentation.value, '3d', 'the request is kept');
  assert.equal(stagePresentation.value, 'chart');
  assert.equal(readURL(href).presentation, '3d');
  syncFromURL(ORIGIN + '?region=morro-bay&presentation=3d');
  assert.equal(stagePresentation.value, '3d');
  syncFromURL(ORIGIN + '?coast=central&presentation=2d');
  assert.equal(region.value, null);
  assert.equal(stagePresentation.value, 'chart', 'a coast without a region package has no terrain');
  assert.equal(presentationFor('chart', 'morro-bay'), 'chart');
  assert.equal(presentationFor('2d', 'cambria-san-simeon'), '2d');
  assert.equal(presentationFor('2d', null), 'chart');
});
