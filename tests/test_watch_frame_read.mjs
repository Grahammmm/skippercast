import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {readWatchFrame} from '../server/watch-frame-read.ts';

const region = 'fixture-region';
const root = `conditions/regions/${region}/`;
const manifestKey = `${root}habitat-dynamics.json`;
const latest = 1_700_000_000;
const older = latest - 3600;
const resolution = [0.05, 0.1];
const bounds = [-2, 1, 0, 3];
const sst = ['latitude', 'longitude', 'temperature_c'];
const chl = ['latitude', 'longitude', 'chlorophyll_mg_m3'];
const gradient = 'temperature_gradient_c_per_km';
const contrast = [...sst, gradient];
const supported = 'thermal_contrast_supported';
const row = [2, -1, 19];
const bytes = text => new TextEncoder().encode(text).buffer;
const json = value => bytes(JSON.stringify(value));
const ready = (fields, rows, valueField = fields[2]) => ({state: 'ready', frame: {
  sampleAt: '2023-11-14T22:13:20.000Z', fields, resolution, rows, valueField,
}});

function fixture({id = 'sst-analysis', kind = 'analysis', fields = sst, frames = [{time: latest, valid_cells: 1}]} = {}) {
  const objects = new Map(), keys = [];
  const layer = {id, kind, fields, frames, resolution_degrees: resolution, status: 'ok', max_age_hours: 36, tiles: []};
  const manifest = {schema_version: 1, region_id: region, layers: {[id]: layer}, sources: {[id]: {name: 'Fixture analysis'}}};
  function addTile(tileFrames = [{time: latest, cells: [row]}], edit = tile => tile) {
    const tile = {schema_version: 1, region_id: region, layer_id: id, fields, resolution_degrees: resolution, bounds, frames: tileFrames};
    const body = json(edit(tile));
    const sha256 = createHash('sha256').update(new Uint8Array(body)).digest('hex');
    const path = `habitat-tiles/tile-${layer.tiles.length}-${sha256.slice(0, 16)}.json`;
    const ref = {path, sha256, bytes: body.byteLength, bounds};
    objects.set(root + path, body);
    layer.tiles.push(ref);
    return ref;
  }
  function run(watch = 'water-temp', manifestBytes = json(manifest)) {
    objects.set(manifestKey, manifestBytes);
    return readWatchFrame(async key => {
      keys.push(key);
      return objects.get(key) ?? null;
    }, region, watch);
  }
  return {addTile, run, manifest, layer, objects, keys};
}

for (const watch of ['currents', 'toString']) {
  test(`C1: unknown layer ${watch} does not select a feed or read keys`, async () => {
    const f = fixture();
    assert.deepEqual(await f.run(watch), {state: 'none'});
    assert.deepEqual(f.keys, []);
  });
}

test('C1: absent manifest is none, not an error or a withheld layer', async () => {
  const f = fixture();
  assert.deepEqual(await f.run('water-temp', null), {state: 'none'});
  assert.deepEqual(f.keys, [manifestKey]);
});

for (const [label, wire, state] of [
  ['invalid JSON', () => bytes('{'), 'error'],
  ['wrong region', f => json({...f.manifest, region_id: 'other-region'}), 'error'],
  ['malformed envelope', f => json({...f.manifest, layers: []}), 'error'],
  ['absent layer', f => json({...f.manifest, layers: {}}), 'none'],
]) {
  test(`C1: ${label} stops at the manifest with ${state}`, async () => {
    const f = fixture();
    f.addTile();
    assert.deepEqual(await f.run('water-temp', wire(f)), {state});
    assert.deepEqual(f.keys, [manifestKey]);
  });
}

for (const [watch, id, kind, fields, cells, value] of [
  ['water-temp', 'sst-analysis', 'analysis', sst, [row], 'temperature_c'],
  ['chlorophyll', 'chlorophyll-observation', 'observation', chl, [[2, -1, 0.47]], 'chlorophyll_mg_m3'],
  ['sst-contrast', 'sst-analysis', 'analysis', contrast, [[2, -1, 19, 0.3]], gradient],
]) {
  test(`C1: ${watch} selects the correct feed and value field`, async () => {
    const f = fixture({id, kind, fields});
    const ref = f.addTile([{time: latest, cells}]);
    assert.deepEqual(await f.run(watch), ready(fields, cells, value));
    assert.deepEqual(f.keys, [manifestKey, root + ref.path]);
  });
}

for (const [label, watch, id, kind, fields] of [
  ['analysis kind', 'water-temp', 'sst-analysis', 'observation', sst],
  ['observation kind', 'chlorophyll', 'chlorophyll-observation', 'analysis', chl],
  ['temperature', 'water-temp', 'sst-analysis', 'analysis', chl],
  ['chlorophyll', 'chlorophyll', 'chlorophyll-observation', 'observation', sst],
  ['contrast base field', 'sst-contrast', 'sst-analysis', 'analysis', [...sst.slice(0, 2), gradient]],
  ['contrast value field', 'sst-contrast', 'sst-analysis', 'analysis', sst],
]) {
  test(`C1: missing required ${label} refuses the manifest layer before tile reads`, async () => {
    const f = fixture({id, kind, fields});
    f.addTile();
    assert.deepEqual(await f.run(watch), {state: 'error'});
    assert.deepEqual(f.keys, [manifestKey]);
  });
}

test('C2: stale status withholds even a listed populated frame, without tile reads', async () => {
  const f = fixture();
  f.layer.status = 'stale';
  f.addTile();
  assert.deepEqual(await f.run(), {state: 'withheld'});
  assert.deepEqual(f.keys, [manifestKey]);
});

test('C2: no frames withholds without tile reads', async () => {
  const f = fixture({frames: []});
  f.addTile([]);
  assert.deepEqual(await f.run(), {state: 'withheld'});
  assert.deepEqual(f.keys, [manifestKey]);
});

for (const [count, populated] of [[undefined, true], [null, true], ['-1', true], [0, false], [-3, false], [5, true]]) {
  test(`C2: browser populated-frame parity for ${count === undefined ? 'absent' : JSON.stringify(count)}`, async () => {
    const frames = [{time: latest, ...(count === undefined ? {} : {valid_cells: count})}];
    const f = fixture({frames});
    const ref = f.addTile();
    assert.deepEqual(await f.run(), populated ? ready(sst, [row]) : {state: 'withheld'});
    assert.deepEqual(f.keys, populated ? [manifestKey, root + ref.path] : [manifestKey]);
  });
}

test('C2: retained layer selects the latest populated time, merging in tile order', async () => {
  const newerEmpty = latest + 3600;
  const frames = [{time: newerEmpty, valid_cells: 0}, {time: latest}, {time: older}];
  const f = fixture({frames});
  f.layer.status = 'retained';
  const first = f.addTile([{time: older, cells: [[2, -1, 13]]}, {time: latest, cells: [row]}]);
  const secondRow = [2.05, -1, 21];
  const second = f.addTile([{time: latest, cells: [secondRow]}]);
  assert.deepEqual(await f.run(), ready(sst, [row, secondRow]));
  assert.deepEqual(f.keys, [manifestKey, root + first.path, root + second.path]);
});

test('C2: a valid tile with only an older frame contributes no fallback rows', async () => {
  const f = fixture({frames: [{time: older}, {time: latest}]});
  const ref = f.addTile([{time: older, cells: [row]}]);
  assert.deepEqual(await f.run(), ready(sst, []));
  assert.deepEqual(f.keys, [manifestKey, root + ref.path]);
});

for (const path of ['../habitat-tiles/tile-0123456789abcdef.json', 'habitat-history/tile-0123456789abcdef.json', 'habitat-tiles/tile-short.json']) {
  test(`C2: refuses path ${path} before any tile reads`, async () => {
    const f = fixture();
    f.addTile();
    f.addTile().path = path;
    assert.deepEqual(await f.run(), {state: 'error'});
    assert.deepEqual(f.keys, [manifestKey]);
  });
}

for (const [label, breakTile] of [
  ['is missing', (f, ref) => f.objects.delete(root + ref.path)],
  ['has the wrong length', (f, ref) => f.objects.set(root + ref.path, bytes('{}'))],
  ['is tampered without changing its length', (f, ref) => {
    const key = root + ref.path;
    const original = new TextDecoder().decode(f.objects.get(key));
    f.objects.set(key, bytes(original.replace('[2,-1,19]', '[2,-1,18]')));
  }],
]) {
  test(`C2: no partial frame when the second tile ${label}`, async () => {
    const f = fixture();
    const first = f.addTile(), second = f.addTile();
    breakTile(f, second);
    assert.deepEqual(await f.run(), {state: 'error'});
    assert.deepEqual(f.keys, [manifestKey, root + first.path, root + second.path]);
  });
}

for (const [label, edit] of [
  ['wrong region', tile => ({...tile, region_id: 'other-region'})],
  ['wrong layer', tile => ({...tile, layer_id: 'chlorophyll-observation'})],
  ['wrong fields', tile => ({...tile, fields: chl})],
  ['wrong resolution', tile => ({...tile, resolution_degrees: [0.05, 0.05]})],
  ['wrong bounds', tile => ({...tile, bounds: [-3, 1, 0, 3]})],
  ['unlisted frame time', tile => ({...tile, frames: [{time: older - 1, cells: [row]}]})],
  ['duplicate frame', tile => ({...tile, frames: [...tile.frames, tile.frames[0]]})],
  ['invalid row in an older frame', tile => ({...tile, frames: [...tile.frames, {time: older, cells: [[2, -1, '19']]}]})],
]) {
  test(`C2: a matching hash is not enough to accept ${label}`, async () => {
    const f = fixture({frames: [{time: older}, {time: latest}]});
    const ref = f.addTile(undefined, edit);
    assert.deepEqual(await f.run(), {state: 'error'});
    assert.deepEqual(f.keys, [manifestKey, root + ref.path]);
  });
}

test('C3: contrast masks only the value and only when support is neither 1 nor true', async () => {
  const fields = [...contrast, supported];
  const f = fixture({fields});
  f.addTile([{time: latest, cells: [
    [2, -1, 19, 0.3, 1], [2, -0.9, 20, 0.4, true], [2, -0.8, 21, 0.5, 0],
    [2, -0.7, 22, 0.6, false], [2, -0.6, 23, 0.7, null], [2, -0.5, 24, 0.8, 2],
  ]}]);
  assert.deepEqual(await f.run('sst-contrast'), ready(fields, [
    [2, -1, 19, 0.3, 1], [2, -0.9, 20, 0.4, true], [2, -0.8, 21, null, 0],
    [2, -0.7, 22, null, false], [2, -0.6, 23, null, null], [2, -0.5, 24, null, 2],
  ], gradient));
});

test('C3: an unsupported contrast cell keeps its ordinary temperature', async () => {
  const fields = [...contrast, supported];
  const cells = [[2, -1, 19, 0.3, 0]];
  const f = fixture({fields});
  f.addTile([{time: latest, cells}]);
  assert.deepEqual(await f.run(), ready(fields, cells));
});

test('C3: an epoch outside the ISO date range does not produce a ready frame', async () => {
  const f = fixture({frames: [{time: 1e14}]});
  assert.deepEqual(await f.run(), {state: 'error'});
});

test('C4: uses only the injected feed keys and makes no fetch or log calls on success or read failure', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw new Error('unexpected fetch'); });
  const logs = ['log', 'info', 'warn', 'error', 'debug'].map(level => t.mock.method(console, level, () => {}));
  const f = fixture();
  const ref = f.addTile();
  assert.deepEqual(await f.run(), ready(sst, [row]));
  assert.deepEqual(f.keys, [manifestKey, root + ref.path]);
  for (const failKey of f.keys) {
    const keys = [];
    const read = async key => {
      keys.push(key);
      if (key === failKey) throw new Error('fixture reader failure');
      return f.objects.get(key) ?? null;
    };
    assert.deepEqual(await readWatchFrame(read, region, 'water-temp'), {state: 'error'});
    assert.deepEqual(keys, failKey === manifestKey ? [manifestKey] : f.keys);
  }
  assert.equal(fetch.mock.callCount(), 0);
  for (const log of logs) assert.equal(log.mock.callCount(), 0);
});
