// Paint oracle for live theme providers. A helper, not a test: its name does not
// match `tests/test_*.mjs`, so neither `pnpm test` nor CI runs it on its own.
// A layer module's test imports it and calls `assertThemePaintOracle`.
//
// Contract it protects: after the theme goes dark -> light -> dark through
// `restyle`, every layer the pure builder makes holds exactly the paint a fresh
// build of that theme has, and a pattern image is added once, then updated in
// place. The believable bug: a provider that omits a palette-dependent paint
// (or names a layer/image id the build does not use) leaves stale colours.
import assert from 'node:assert/strict';
import {restyle} from '../web/map/theme-restyle.ts';

const clone = value => structuredClone(value);

/** A `Restylable` whose layers start as copies of `layers` and record every change. */
export function fakeMap(layers) {
  const paints = new Map(layers.map(({id, paint}) => [id, clone(paint ?? {})]));
  const images = new Map(), imageCalls = [];
  const target = {
    hasLayer: id => paints.has(id),
    setPaintProperty(layer, property, value) {
      assert.ok(paints.has(layer), `paint edit for missing layer ${layer}`);
      paints.get(layer)[property] = clone(value);
    },
    hasImage: id => images.has(id),
    addImage(id, image, {pixelRatio}) {
      assert.ok(!images.has(id), `duplicate addImage ${id}`);
      images.set(id, {image, pixelRatio});
      imageCalls.push(['add', id]);
    },
    updateImage(id, image) {
      const old = images.get(id);
      assert.ok(old, `updateImage before addImage ${id}`);
      assert.deepEqual([image.width, image.height], [old.image.width, old.image.height], `image ${id} changed size`);
      old.image = image;
      imageCalls.push(['update', id]);
    },
  };
  return {target, paints, images, imageCalls};
}

/**
 * Run dark (install) -> light -> dark and report what differs.
 * `build(palette)` is the pure builder returning `{layers}`; `provider` has
 * `themePaint` and/or `themePatterns`; `palettes` is `{dark, light}`.
 * Returns `{steps, missing, addImage, updateImage, addedIds}`:
 * - `steps[i].mismatches` lists `{layer, property, actual, expected}` for each
 *   built layer paint that differs from the fresh build of that step's theme;
 * - `missing` lists layer IDs a build has that the map lacks, or a provider
 *   edited that the map lacks (each once);
 * - `addImage`/`updateImage` count image calls over the whole run.
 */
export function runThemePaintOracle({build, provider, palettes}) {
  const map = fakeMap(build(palettes.dark).layers);
  const missing = new Set(), steps = [];
  for (const theme of ['dark', 'light', 'dark']) {
    const fresh = build(palettes[theme]).layers;
    for (const id of restyle(map.target, palettes[theme], [provider]).skipped) missing.add(id);
    const mismatches = [];
    for (const {id, paint} of fresh) {
      if (!map.paints.has(id)) { missing.add(id); continue; }
      const actual = map.paints.get(id), expected = paint ?? {};
      for (const property of new Set([...Object.keys(actual), ...Object.keys(expected)])) {
        try {
          assert.deepEqual(actual[property], expected[property]);
        } catch {
          mismatches.push({layer: id, property, actual: actual[property], expected: expected[property]});
        }
      }
    }
    steps.push({theme, mismatches});
  }
  const count = kind => map.imageCalls.filter(([call]) => call === kind).length;
  return {
    steps, missing: [...missing], addImage: count('add'), updateImage: count('update'),
    addedIds: map.imageCalls.filter(([call]) => call === 'add').map(([, id]) => id),
    imageIds: [...map.images.keys()],
  };
}

/** Run the oracle and assert: no mismatch, no missing layer, each pattern added once then updated in place. */
export function assertThemePaintOracle(options) {
  const report = runThemePaintOracle(options);
  for (const {theme, mismatches} of report.steps) {
    assert.deepEqual(mismatches, [], `paint differs from a fresh ${theme} build`);
  }
  assert.deepEqual(report.missing, [], 'layers missing from the map');
  assert.equal(new Set(report.addedIds).size, report.addImage, 'an image was added more than once');
  assert.equal(report.addImage, report.imageIds.length, 'every registered image is added exactly once');
  // Install (dark), light, dark: each id is added on the first pass, then updated twice.
  assert.equal(report.updateImage, 2 * report.addImage, 'patterns must update in place after the first add');
  return report;
}
