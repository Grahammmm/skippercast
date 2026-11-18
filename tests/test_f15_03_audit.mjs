// SCA-544 / F15-03: offline controls for web/map/marks.ts `read` (atlas binding). Synthetic payloads
// only; no browser, live data or transport. `node tests/test_f15_03_audit.mjs --baseline` also runs
// the SCA-201 contract (a mispackaged atlas never populates marks or counts); it is opt-in until the
// production fix lands, so the default run stays green.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createMarks, markData} from '../web/map/marks.ts';
import {regionAtlas} from '../web/species.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const PAGE = 'https://s.test/map';
const read = path => JSON.parse(readFileSync(new URL(`../dist/${path}`, import.meta.url), 'utf8'));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setTimeout(resolve, 0)); };
const REGION = read('regions/morro-bay/region.json');
const OWN = read('data/atlas.json');                                // morro-bay's own full atlas
const OTHER = read('regions/southern-california/atlas.json');       // another region's atlas
const OWN_LIGHT = read('regions/morro-bay/atlas-marks.json');       // morro-bay's own startup copy
assert.ok(OTHER.targets.length > 0 && OTHER.targets.length !== OWN.targets.length, 'the two atlases are told apart by count');
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
async function load({light, full}) {
  browser();
  markData.value = null; regionAtlas.value = null;
  const asked = [];
  const fetchFn = async url => {
    const path = new URL(url).pathname.slice(1);
    asked.push(path);
    const body = path === 'regions/morro-bay/region.json' ? REGION : path === 'regions/morro-bay/atlas-marks.json' ? light
      : path === 'data/atlas.json' ? full : null;
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
}
