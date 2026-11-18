// SCA-544 / F15-03: offline controls for web/map/marks.ts `read` (atlas binding). Synthetic payloads
// only; no browser, live data or transport. `node tests/test_f15_03_audit.mjs --baseline` also runs
// the SCA-201 contract (a mispackaged atlas never populates marks or counts); it is opt-in until the
// production fix lands, so the default run stays green.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createMarks, markData} from '../web/map/marks.ts';
import {regionAtlas} from '../web/species.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
// Fabricated, location-free payloads: targets carry only an id and a label.
const targets = (prefix, n) => Array.from({length: n}, (_, i) => ({id: `${prefix}-${i}`, name: `${prefix} mark ${i}`}));
const REGION = {id: 'morro-bay', name: 'Synthetic Bay', assets: {atlas: 'data/atlas.json'}};
const ALT_REGION = {id: 'synthetic-other', name: 'Synthetic Other', assets: {atlas: 'regions/synthetic-other/atlas.json'}};
const OWN = {targets: targets('own', 5)};            // the selected region's full atlas
const OTHER = {targets: targets('other', 3)};        // another region's atlas
const OWN_LIGHT = {targets: targets('own', 2)};      // the selected region's startup copy
// Identity stamp by validated region id (the producers carry none today: the committed atlases are unstamped).
const stamped = (atlas, region_id) => ({...atlas, region_id});

function browser() {
  const href = `${PAGE}?region=morro-bay&presentation=chart`;
  globalThis.location = {href};
  globalThis.history = {state: null, pushState() {}, replaceState() {}};
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
}

/** Loads morro-bay with the given startup copy and full atlas payloads; reports what the loader exposed. */
async function load({light, full, meta = REGION}) {
  browser();
  markData.value = null; regionAtlas.value = null;
  const asked = [];
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    asked.push(path);
    const body = path === 'regions/morro-bay/region.json' ? meta : path === 'regions/morro-bay/atlas-marks.json' ? light
      : path === 'data/atlas.json' || path === 'regions/synthetic-other/atlas.json' ? full : null;
    if (body === null || body === undefined) return {ok: false, status: 503, json: async () => ({})};
    return {ok: true, json: async () => body};
  };
  const marks = createMarks({fetchFn, page: () => PAGE, onError: () => {}});
  await settle();
  const seen = {targets: markData.value?.atlas?.targets?.length ?? 0, count: regionAtlas.value?.marks ?? 0,
    region: markData.value?.region?.id, asked};
  marks.destroy();
  return seen;
}

test('F15-03 control: a startup copy bound to the selected region populates marks and counts, without the full file', async () => {
  const seen = await load({light: stamped(OWN_LIGHT, 'morro-bay'), full: stamped(OWN, 'morro-bay')});
  assert.equal(seen.region, 'morro-bay');
  assert.equal(seen.targets, OWN_LIGHT.targets.length);
  assert.equal(seen.count, OWN_LIGHT.targets.length);
  assert.equal(seen.asked.includes('data/atlas.json'), false, 'no full atlas while the bound copy loads');
});

test('F15-03 control: a full atlas bound to the selected region loads when the copy fails', async () => {
  const seen = await load({light: null, full: stamped(OWN, 'morro-bay')});
  assert.equal(seen.targets, OWN.targets.length);
  assert.equal(seen.count, OWN.targets.length);
});

if (process.argv.includes('--baseline')) {
  const none = {targets: 0, count: 0};
  test('F15-03 contract: another region\'s startup copy and full atlas never populate morro-bay', async () => {
    const seen = await load({light: stamped(OTHER, 'southern-california'), full: stamped(OTHER, 'southern-california')});
    assert.deepEqual({targets: seen.targets, count: seen.count}, none, `mismatched atlas exposed ${seen.targets} targets / count ${seen.count} under ${seen.region}`);
  });
  test('F15-03 contract: another region\'s full atlas never populates morro-bay after the copy fails', async () => {
    const seen = await load({light: null, full: stamped(OTHER, 'southern-california')});
    assert.deepEqual({targets: seen.targets, count: seen.count}, none, `mismatched full atlas exposed ${seen.targets} targets / count ${seen.count}`);
  });
  test('F15-03 contract: a mismatched startup copy falls through to the region\'s own bound full atlas', async () => {
    const seen = await load({light: stamped(OTHER, 'southern-california'), full: stamped(OWN, 'morro-bay')});
    assert.equal(seen.targets, OWN.targets.length, `exposed ${seen.targets} targets, expected morro-bay's ${OWN.targets.length}`);
    assert.equal(seen.count, OWN.targets.length);
  });
  test('F15-03 contract: region metadata naming another region is rejected before any asset is fetched', async () => {
    const seen = await load({meta: ALT_REGION, light: stamped(OTHER, 'synthetic-other'), full: stamped(OTHER, 'synthetic-other')});
    const assets = seen.asked.filter(path => /atlas/.test(path));
    assert.deepEqual(assets, [], `fetched ${assets.join(', ')} for mismatched metadata`);
    assert.deepEqual({targets: seen.targets, count: seen.count}, none);
  });
}
