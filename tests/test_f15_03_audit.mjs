// SCA-201 / F15-03: offline atlas binding controls. Synthetic payloads only; no real transport.
import assert from 'node:assert/strict';
import test from 'node:test';
import {createMarks, markData, markScreen} from '../web/map/marks.ts';
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
    return body === null || body === undefined ? new Response(null, {status: 503}) : Response.json(body);
  };
  const marks = createMarks({fetchFn, page: () => PAGE, onError: () => {}});
  try {
    await settle();
    return {targets: markData.value?.atlas?.targets?.length ?? 0, count: regionAtlas.value?.marks ?? null,
      region: markData.value?.region?.id, screen: markScreen.value.status, asked};
  } finally { marks.destroy(); }
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

const WRONG = stamped(OTHER, 'southern-california');
for (const [name, light, full] of [
  ['wrong region on both forms', WRONG, WRONG],
  ['wrong region on full atlas after a failed startup read', null, WRONG],
  ['no region on either form, even with provenance naming the full atlas', {
    ...OTHER, startup_form: 'atlas-marks', derived_from: {
      path: REGION.assets.atlas, sha256: '57e35ad2430f6ca48a9d79e4da4fa2db8ce88ab93758e8565d3d2565ec7529dd',
    },
  }, OTHER],
]) {
  test(`F15-03 contract: ${name} never populates marks or counts`, async () => {
    const seen = await load({light, full});
    assert.equal(seen.region, 'morro-bay', 'valid metadata finished loading');
    assert.ok(seen.asked.includes(REGION.assets.atlas), 'the full atlas was tried');
    assert.deepEqual({targets: seen.targets, count: seen.count}, {targets: 0, count: null});
  });
}

test('F15-03 contract: a mismatched startup copy falls through to the region\'s own bound full atlas', async () => {
  const seen = await load({light: WRONG, full: stamped(OWN, 'morro-bay')});
  assert.equal(seen.targets, OWN.targets.length);
  assert.equal(seen.count, OWN.targets.length);
});

for (const [name, meta] of [['wrong region', ALT_REGION], ['missing ID', {assets: REGION.assets}]]) {
  test(`F15-03 contract: ${name} in region metadata stops all asset reads`, async () => {
    const seen = await load({meta, light: stamped(OWN_LIGHT, 'morro-bay'), full: stamped(OWN, 'morro-bay')});
    assert.deepEqual(seen.asked, ['regions/morro-bay/region.json']);
    assert.equal(seen.screen, 'unavailable');
    assert.deepEqual({targets: seen.targets, count: seen.count, region: seen.region}, {targets: 0, count: null, region: undefined});
  });
}
