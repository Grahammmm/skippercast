import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {themes} from '../scripts/check_contrast.mjs';
import {readPalette} from '../web/map/palette.ts';
import {basemapStyle} from '../web/map/style.ts';
import {basemapThemePaint, createThemeWatcher, paintEdits, restyle} from '../web/map/theme-restyle.ts';
import {assertThemePaintOracle, runThemePaintOracle} from './theme-paint-oracle.mjs';

function fakeTarget(...ids) {
  const layers = new Set(ids), edits = [], images = new Map(), imageCalls = [];
  const target = new Proxy({
    hasLayer: id => layers.has(id),
    setPaintProperty(layer, property, value) {
      assert.ok(layers.has(layer), `paint edit for missing layer ${layer}`);
      if (property === 'fill-pattern') assert.ok(images.has(value), `pattern not registered: ${value}`);
      edits.push([layer, property, value]);
    },
    hasImage: id => images.has(id),
    addImage(id, image, {pixelRatio}) {
      assert.ok(!images.has(id), `duplicate image ${id}`);
      images.set(id, {image, pixelRatio});
      imageCalls.push(['add', id]);
    },
    updateImage(id, image) {
      assert.ok(images.has(id), `image not found: ${id}`);
      images.get(id).image = image;
      imageCalls.push(['update', id]);
    },
  }, {
    get(target, property) {
      if (!Object.hasOwn(target, property)) throw new Error(`restyle touched ${String(property)}`);
      return target[property];
    },
  });
  return {target, layers, edits, images, imageCalls};
}

const sentinel = theme => readPalette(name => `${theme}/${name}`);
const providers = [
  {themePaint: p => [{layer: 'earth', property: 'fill-color', value: p.mapLand}]},
  {themePaint: p => [{layer: 'harbors', property: 'text-color', value: p.mapLabel},
    {layer: 'harbors', property: 'text-halo-color', value: p.mapHalo}]},
];
const expectedEdits = theme => [
  ['earth', 'fill-color', `${theme}/map-land`],
  ['harbors', 'text-color', `${theme}/map-label`],
  ['harbors', 'text-halo-color', `${theme}/map-halo`],
];
function watch(apply) {
  let notify;
  const stop = createThemeWatcher(onChange => {
    notify = onChange;
    return () => { notify = undefined; };
  }, apply);
  return {stop, emit: theme => notify?.(theme), subscriber: () => notify};
}

// A sync apply mistaken for an in-flight async apply would drop notifications.
test('10 rapid idle switches each apply all edits exactly once, with no source or camera access', async () => {
  const {target, edits} = fakeTarget('earth', 'harbors');
  const watcher = watch(theme => { restyle(target, sentinel(theme), providers); });
  const switches = Array.from({length: 10}, (_, i) => i % 2 ? 'light' : 'dark');
  await Promise.all(switches.map(watcher.emit));
  assert.deepEqual(edits, switches.flatMap(expectedEdits));
  watcher.stop();
});

// Without serialization a delayed apply can overwrite a newer paint. Without
// queued waiters a subscriber can resume before even the superseding paint runs.
test('switches during a region load wait for the latest paint on all mounted layers', async () => {
  const {target, layers, edits} = fakeTarget('earth');
  const palettes = tokenPalettes();
  const paint = theme => [
    ['earth', 'fill-color', palettes[theme].mapLand],
    ['harbors', 'text-color', palettes[theme].mapLabel],
    ['harbors', 'text-halo-color', palettes[theme].mapHalo],
  ];
  const gates = [Promise.withResolvers(), Promise.withResolvers()];
  const latestStarted = Promise.withResolvers(), starts = [], completed = [];
  const watcher = watch(async theme => {
    const gate = gates[starts.length];
    starts.push(theme);
    if (starts.length === 2) latestStarted.resolve();
    await gate.promise;
    restyle(target, palettes[theme], providers);
  });
  const emit = (label, theme) => watcher.emit(theme).then(() => {
    completed.push([label, edits.slice()]);
  });
  // A dark refresh is already in flight when the user switches light–dark–light.
  const first = emit('in-flight', 'dark');
  const queued = [emit('light', 'light'), emit('dark', 'dark'), emit('latest', 'light')];
  await new Promise(setImmediate);
  assert.deepEqual(starts, ['dark']);
  assert.deepEqual(completed, [], 'notifications settled before the first paint');
  layers.add('harbors');
  gates[0].resolve();
  await latestStarted.promise;
  await new Promise(setImmediate);
  assert.deepEqual(edits, paint('dark'));
  assert.deepEqual(completed, [['in-flight', paint('dark')]], 'queued notifications must wait for the superseding paint');
  gates[1].resolve();
  await Promise.all([first, ...queued]);
  const finalEdits = [...paint('dark'), ...paint('light')];
  assert.deepEqual(starts, ['dark', 'light']);
  assert.deepEqual(edits, finalEdits);
  assert.deepEqual(completed.slice(1), ['light', 'dark', 'latest'].map(label => [label, finalEdits]));
  watcher.stop();
});

// A paint for an absent layer must not abort the remaining edits; two edits for
// one absent layer must not make the report look like two layers are missing.
test('missing layers are skipped and reported once by ID', () => {
  const {target, edits} = fakeTarget('earth');
  assert.deepEqual(restyle(target, sentinel('dark'), [...providers].reverse()), {applied: 1, skipped: ['harbors']});
  assert.deepEqual(edits, expectedEdits('dark').slice(0, 1));
});

// A duplicate add fails on the second restyle; add after paint fails on the first.
test('pattern images are installed before paint and replaced under the same ID', () => {
  const {target, images, imageCalls} = fakeTarget('survey');
  const pixel = red => ({width: 1, height: 1, data: Uint8ClampedArray.of(red, 0, 0, 255)});
  const dark = pixel(32), light = pixel(200);
  const providers = [
    {themePaint: () => [{layer: 'survey', property: 'fill-pattern', value: 'hatch'}]},
    {themePatterns: p => [{id: 'hatch', image: p.bg.startsWith('dark') ? dark : light, pixelRatio: 2}]},
  ];
  restyle(target, sentinel('dark'), providers);
  assert.deepEqual(images.get('hatch'), {image: dark, pixelRatio: 2});
  restyle(target, sentinel('light'), providers);
  assert.deepEqual(imageCalls, [['add', 'hatch'], ['update', 'hatch']]);
  assert.deepEqual([...images], [['hatch', {image: light, pixelRatio: 2}]]);
});

// Exiting on failure strands the queue; rejecting the drain as a whole hands
// the wrong error to subscribers. An unattended receipt must not leak a rejection.
test('each failed paint rejects its own waiters and later notifications still paint', async () => {
  const first = Promise.withResolvers(), latest = Promise.withResolvers(), seen = [];
  const watcher = watch(theme => {
    seen.push(theme);
    return [first.promise, latest.promise][seen.length - 1];
  });
  const firstError = new Error('in-flight paint failed'), latestError = new Error('queued paint failed');
  const inFlight = assert.rejects(watcher.emit('dark'), error => error === firstError);
  const superseded = watcher.emit('dark');
  const queued = watcher.emit('light');
  first.reject(firstError);
  await inFlight;
  assert.deepEqual(seen, ['dark', 'light']);
  latest.reject(latestError);
  // Leave queued receipts unobserved for a turn. node:test fails on an unhandled rejection.
  await new Promise(setImmediate);
  await Promise.all([
    assert.rejects(superseded, error => error === latestError),
    assert.rejects(queued, error => error === latestError),
  ]);
  await watcher.emit('dark');
  assert.deepEqual(seen, ['dark', 'light', 'dark']);
  watcher.stop();
});

// After the map is disposed, neither a previously queued nor a late callback
// may write paint on it, even if an older apply settles afterwards.
test('unsubscribe drops queued and late notifications', async () => {
  const first = Promise.withResolvers(), seen = [];
  const watcher = watch(theme => { seen.push(theme); return first.promise; });
  const notify = watcher.subscriber();
  const done = watcher.emit('dark');
  let painted = false;
  const inFlight = done.then(() => { painted = true; });
  const dropped = [watcher.emit('light'), watcher.emit('dark')];
  watcher.stop();
  assert.equal(watcher.subscriber(), undefined);
  await Promise.all([...dropped, notify('light')]);
  assert.equal(painted, false, 'disposal must not acknowledge an in-flight paint');
  assert.deepEqual(seen, ['dark']);
  first.resolve();
  await inFlight;
  assert.deepEqual(seen, ['dark']);
});

// Independent §10.2 oracle for actual token values and layer/property ids. A
// missing label or a switch to a chrome (rather than map) token fails here.
test('basemap theme edits use §10.2 light values and preserve the original dark values', () => {
  const css = readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8');
  const colours = themes(css);
  const controls = {'map-road-opacity': '0.65', 'map-label-opacity': '0.75'};
  for (const [theme, water, land, park, major, minor, boundary, label] of [
    ['dark', '#07131d', '#0e1d2b', '#122535', '#223849', '#122535', '#223849', '#8ba5b7'],
    ['light', '#f4f8f9', '#dcd8ce', '#d3d7c9', '#ffffff', '#f1efe9', '#b9c2c8', '#3d5566'],
  ]) {
    const changes = basemapThemePaint(readPalette(name => controls[name] ?? colours[theme][name] ?? '1'));
    const actual = Object.fromEntries(changes.map(({layer, property, value}) => [`${layer}/${property}`, value]));
    assert.equal(changes.length, Object.keys(actual).length, `${theme}: duplicate edit`);
    assert.deepEqual(actual, {
      'background/background-color': water, 'earth/fill-color': land, 'parks/fill-color': park,
      'water/fill-color': water, 'rivers/line-color': water, 'boundaries/line-color': boundary,
      'roads-highway/line-color': major, 'roads-highway/line-opacity': 0.65,
      'roads-major/line-color': major, 'roads-major/line-opacity': 0.65,
      'roads-minor/line-color': minor, 'roads-minor/line-opacity': 0.65,
      ...Object.fromEntries(['labels-water', 'labels-roads', 'labels-harbor', 'labels-places'].flatMap(id => [
        [`${id}/text-color`, label], [`${id}/text-halo-color`, water], [`${id}/text-opacity`, 0.75],
      ])),
    }, theme);
  }
});

// Contract: `paintEdits` is the one shared projection of built layer paints.
// A default that drops properties, or a `keep` that is ignored, would leave
// adopters' layers with stale paints after a theme switch.
test('paintEdits lists every paint entry by default, filters with keep, and skips layers without paint', () => {
  const layers = [
    {id: 'a', type: 'fill', paint: {'fill-color': '#111', 'fill-opacity': 0.5}},
    {id: 'b', type: 'symbol'},
    {id: 'c', type: 'line', paint: {'line-width': 3}},
  ];
  assert.deepEqual(paintEdits(layers), [
    {layer: 'a', property: 'fill-color', value: '#111'},
    {layer: 'a', property: 'fill-opacity', value: 0.5},
    {layer: 'c', property: 'line-width', value: 3},
  ]);
  assert.deepEqual(paintEdits(layers, property => property.endsWith('-color')), [{layer: 'a', property: 'fill-color', value: '#111'}]);
  assert.deepEqual(paintEdits([]), []);
});

const tokenPalettes = () => {
  const colours = themes(readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8'));
  const controls = {'map-road-opacity': '0.65', 'map-label-opacity': '0.75'};
  return Object.fromEntries(['dark', 'light'].map(theme => [theme, readPalette(name => controls[name] ?? colours[theme][name] ?? '1')]));
};
const basemapBuild = palette => basemapStyle(palette, {archive: '', assets: ''});

// Contract: re-expressing `basemapThemePaint` through `paintEdits` changed nothing.
// The reference below is the pre-refactor implementation, kept verbatim.
test('basemapThemePaint output equals the pre-refactor implementation for dark and light', () => {
  const legacy = palette => basemapBuild(palette).layers.flatMap(({id: layer, paint}) => Object.entries(paint ?? {})
    .filter(([property]) => property.endsWith('-color') || property === 'line-opacity' || property === 'text-opacity')
    .map(([property, value]) => ({layer, property, value})));
  const palettes = tokenPalettes();
  for (const theme of ['dark', 'light']) {
    const edits = basemapThemePaint(palettes[theme]);
    assert.ok(edits.length > 20, `${theme}: suspiciously few edits`);
    assert.deepEqual(edits, legacy(palettes[theme]), theme);
  }
});

// Contract: the oracle accepts a complete provider and catches an incomplete one,
// a provider naming an absent layer, and a pattern that is re-added instead of
// updated. Without this the oracle could pass everything.
test('the paint oracle accepts basemapThemePaint in both directions and catches broken providers', () => {
  const palettes = tokenPalettes();
  const good = assertThemePaintOracle({build: basemapBuild, provider: {themePaint: basemapThemePaint}, palettes});
  assert.deepEqual([good.addImage, good.updateImage, good.missing], [0, 0, []]);

  const omits = runThemePaintOracle({
    build: basemapBuild, palettes,
    provider: {themePaint: p => basemapThemePaint(p).filter(({layer, property}) => !(layer === 'water' && property === 'fill-color'))},
  });
  assert.deepEqual(omits.steps.map(step => step.mismatches.map(({layer, property}) => `${layer}/${property}`)), [[], ['water/fill-color'], []]);

  const absent = runThemePaintOracle({
    build: basemapBuild, palettes,
    provider: {themePaint: p => [...basemapThemePaint(p), {layer: 'no-such-layer', property: 'fill-color', value: '#000'}]},
  });
  assert.deepEqual(absent.missing, ['no-such-layer']);

  const image = {width: 1, height: 1, data: Uint8ClampedArray.of(0, 0, 0, 255)};
  const pattern = {themePatterns: () => [{id: 'hatch', image, pixelRatio: 2}]};
  const hatch = assertThemePaintOracle({build: basemapBuild, palettes, provider: {themePaint: basemapThemePaint, ...pattern}});
  assert.deepEqual([hatch.addImage, hatch.updateImage, hatch.addedIds], [1, 2, ['hatch']]);
});

// Contract: the oracle checks that every pattern ID a built layer paint references is
// registered on the map. Bug: a provider registering 'wrong-id' while the builder's layer
// uses `fill-pattern: 'hatch'` passes every paint and image-count check, yet the pattern
// is missing on the real map.
test('the paint oracle reports a layer pattern whose image is registered under another id', () => {
  const palettes = tokenPalettes();
  const build = palette => {
    const style = basemapBuild(palette);
    return {...style, layers: [...style.layers, {id: 'survey', type: 'fill', source: 'earth', paint: {'fill-pattern': 'hatch'}}]};
  };
  const image = {width: 1, height: 1, data: Uint8ClampedArray.of(0, 0, 0, 255)};
  const providerWith = id => ({themePaint: basemapThemePaint, themePatterns: () => [{id, image, pixelRatio: 2}]});

  const wrong = runThemePaintOracle({build, palettes, provider: providerWith('wrong-id')});
  assert.deepEqual(wrong.missingImages, ['hatch']);
  assert.deepEqual(wrong.imageIds, ['wrong-id']);
  assert.throws(() => assertThemePaintOracle({build, palettes, provider: providerWith('wrong-id')}), /not registered/);

  const right = assertThemePaintOracle({build, palettes, provider: providerWith('hatch')});
  assert.deepEqual([right.missingImages, right.imageIds], [[], ['hatch']]);
});
