import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {themes} from '../scripts/check_contrast.mjs';
import {readPalette} from '../web/map/palette.ts';
import {basemapThemePaint, createThemeWatcher, restyle} from '../web/map/theme-restyle.ts';

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

// Without serialization, the older delayed apply could overwrite a newer
// theme after the region's layers are mounted. No timers or browser are needed.
test('switches during a region load replay only the latest theme on all mounted layers', async () => {
  const {target, layers, edits} = fakeTarget('earth');
  const loaded = Promise.withResolvers(), starts = [];
  const watcher = watch(async theme => {
    starts.push(theme);
    if (starts.length === 1) await loaded.promise;
    restyle(target, sentinel(theme), providers);
  });
  const burst = [watcher.emit('light')];
  for (let i = 0; i < 9; ++i) burst.push(watcher.emit(i % 2 ? 'light' : 'dark'));
  assert.deepEqual(starts, ['light']);
  layers.add('harbors');
  loaded.resolve();
  await Promise.all(burst);
  assert.deepEqual(starts, ['light', 'dark']);
  assert.deepEqual(edits, [...expectedEdits('light'), ...expectedEdits('dark')]);
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

// Force the in-flight error case: simply exiting the drain would strand the
// latest notification; swallowing the error would hide the renderer failure.
test('a rejected apply reports the failure without stranding a queued theme', async () => {
  const first = Promise.withResolvers(), seen = [];
  const watcher = watch(theme => {
    seen.push(theme);
    if (theme === 'dark') return first.promise;
  });
  const done = watcher.emit('dark');
  await watcher.emit('light');
  const error = new Error('apply failed');
  first.reject(error);
  await assert.rejects(done, error);
  assert.deepEqual(seen, ['dark', 'light']);
  watcher.stop();
});

// After the map is disposed, neither a previously queued nor a late callback
// may write paint on it, even if an older apply settles afterwards.
test('unsubscribe drops queued and late notifications', async () => {
  const first = Promise.withResolvers(), seen = [];
  const watcher = watch(theme => { seen.push(theme); return first.promise; });
  const notify = watcher.subscriber();
  const done = watcher.emit('dark');
  await watcher.emit('light');
  watcher.stop();
  assert.equal(watcher.subscriber(), undefined);
  await notify('light');
  first.resolve();
  await done;
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
