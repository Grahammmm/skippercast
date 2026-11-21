import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {CHLOROPHYLL_LAYER_ID, SST_LAYER_ID, WCOFS_LAYER_ID, habitatManifestURL, historyDays, layerOf, loadHistoryDay, regionalSST} from '../web/map/habitat-feed.ts';

const PAGE = 'https://s.test/map', REGION = 'test-coast';
const MANIFEST = habitatManifestURL(REGION, PAGE);
const NOW = new Date('2026-11-20T12:00:00Z');
const date = day => `2026-11-${day}T00:00:00Z`;
const epoch = sampleAt => Date.parse(sampleAt) / 1000;
const CURRENT = date(20), PAST = date(18), OLDER = date(17);

function feed(id = SST_LAYER_ID) {
  const kind = id === SST_LAYER_ID ? 'analysis' : 'observation';
  const fields = ['latitude', 'longitude', ...(kind === 'analysis' ? ['temperature_c', 'analysis_error_c'] : ['chlorophyll_mg_m3'])];
  const resolution = [0.05, 0.05], bodies = new Map(), asked = [];
  const url = path => new URL(path, MANIFEST).href;
  function tile(sampleAt, column = 0, change = {}) {
    const lon = -121 + column, bounds = [lon, 35, lon + 1, 36];
    const row = [35.025, lon + 0.025, ...(kind === 'analysis' ? [14 + column, 0.3] : [2 + column])];
    const frame = {time: epoch(sampleAt), cells: [row]};
    const body = Buffer.from(JSON.stringify({schema_version: 1, region_id: REGION, layer_id: id, fields, resolution_degrees: resolution, bounds, frames: [frame], ...change}));
    const sha256 = createHash('sha256').update(body).digest('hex');
    const folder = sampleAt === CURRENT ? 'habitat-tiles' : 'habitat-history';
    const path = `${folder}/${id}-${sampleAt.slice(0, 10)}-${column}-${sha256.slice(0, 16)}.json`;
    bodies.set(url(path), body);
    return {record: {path, sha256, bytes: body.length, bounds}, row, frame};
  }
  function day(sample_at, ...tiles) {
    return {sample_at, tiles: (tiles.length ? tiles : [tile(sample_at)]).map(t => t.record)};
  }
  const live = tile(CURRENT);
  const layer = {id, kind, fields, resolution_degrees: resolution, sample_at: CURRENT, status: 'ok', max_age_hours: 24,
    frames: [{time: epoch(CURRENT), valid_cells: 1}], tiles: [live.record]};
  const manifest = {schema_version: 1, region_id: REGION, layers: {[id]: layer}, sources: {[id]: {name: 'Fixture, 5 km', data_retrieved_at: CURRENT}}};
  const read = () => layerOf(manifest, REGION, id, kind, fields.slice(2));
  const options = {now: NOW, page: PAGE, fetchFn: async address => {
    asked.push(address);
    if (address === MANIFEST) return Response.json(manifest);
    return bodies.has(address) ? new Response(bodies.get(address)) : new Response(null, {status: 404});
  }};
  return {asked, bodies, manifest, layer, read, tile, day, live, url, options, load: at => loadHistoryDay(REGION, id, at, options)};
}

// History discovery can regress independently of tile loading: don't offer malformed, duplicate,
// present or future observations, even if the wire array is unsorted or exceeds the cap.
test('history lists the newest seven distinct valid past sample times', async () => {
  const f = feed(), good = Array.from({length: 9}, (_, i) => f.day(date(11 + i)));
  f.layer.history = [null, [], 7, {}, {...f.day(date(19)), tiles: []}, good[0], good[7], ...good.slice(1, 7), good[8],
    {...good[7], sample_at: '2026-11-17T16:00:00-08:00'}, {...good[8], sample_at: CURRENT}, f.day(date(21)),
    ...[null, epoch(PAST), '2026-11-16', '2026-11-16T00:00:00', '2026-10-32T00:00:00Z', '2026-02-30T00:00:00Z', 'yesterday']
      .map(sample_at => ({...good[7], sample_at}))];
  assert.deepEqual(historyDays(f.read()), [19, 18, 17, 16, 15, 14, 13].map(date));
  assert.deepEqual(f.asked, []);
  assert.deepEqual(await f.load(date(12)), {state: 'none'}, 'entries beyond the cap cannot be fetched');
  assert.deepEqual(f.asked, [MANIFEST]);
});

// Optional metadata must not perturb the live result or accidentally fetch archived tiles.
test('absent or malformed history preserves the live read and the live request list', async () => {
  const f = feed(), before = await regionalSST(REGION, f.options);
  assert.equal(before.state, 'ready');
  assert.deepEqual(historyDays(f.read()), []);
  assert.deepEqual(f.asked, [MANIFEST, f.url(f.live.record.path)]);
  for (const history of [null, 3, 'history', {}, [f.day(PAST), {tiles: []}]]) {
    f.layer.history = history;
    f.asked.length = 0;
    assert.deepEqual(historyDays(f.read()), Array.isArray(history) ? [PAST] : []);
    assert.equal(JSON.stringify(await regionalSST(REGION, f.options)), JSON.stringify(before));
    assert.deepEqual(f.asked, [MANIFEST, f.url(f.live.record.path)]);
  }
  delete f.layer.history;
  f.asked.length = 0;
  assert.deepEqual(await f.load(PAST), {state: 'none'});
  assert.deepEqual(f.asked, [MANIFEST]);
});

// Fetching the live grid or all history tiles on selection would fetch the wrong observation.
test('loads just the selected day, merging both tiles in manifest order even after live expiry', async () => {
  for (const id of [SST_LAYER_ID, CHLOROPHYLL_LAYER_ID]) {
    const f = feed(id), east = f.tile(PAST, 1), west = f.tile(PAST, 0);
    f.layer.history = [f.day(PAST, east, west), f.day(OLDER)];
    f.layer.status = 'stale';
    assert.deepEqual(await f.load('2026-11-17T16:00:00-08:00'), {state: 'ready', sampleAt: PAST,
      fields: f.layer.fields, resolution: f.layer.resolution_degrees, rows: [east.row, west.row]});
    assert.deepEqual(f.asked, [MANIFEST, f.url(east.record.path), f.url(west.record.path)]);
  }
  const f = feed();
  assert.deepEqual(await loadHistoryDay(REGION, WCOFS_LAYER_ID, PAST, f.options), {state: 'none'});
  assert.deepEqual(f.asked, []);
});

test('R2 descriptors without bounds load only valid bounded history tiles', async () => {
  for (const id of [SST_LAYER_ID, CHLOROPHYLL_LAYER_ID]) {
    const f = feed(id), good = f.tile(PAST), invalid = f.tile(OLDER, 0, {bounds: [0, 0, 0, 1]});
    const descriptor = ({path, sha256, bytes}) => ({path, sha256, bytes});
    f.layer.history = [{sample_at: PAST, tiles: [descriptor(good.record)]},
      {sample_at: OLDER, tiles: [descriptor(invalid.record)]}];
    assert.deepEqual(historyDays(f.read()), [PAST, OLDER]);
    assert.deepEqual(await f.load(PAST), {state: 'ready', sampleAt: PAST,
      fields: f.layer.fields, resolution: f.layer.resolution_degrees, rows: [good.row]});
    assert.deepEqual(await f.load(OLDER), {state: 'error'});
    assert.deepEqual(f.asked, [MANIFEST, f.url(good.record.path), MANIFEST, f.url(invalid.record.path)]);
  }
});

// Bad descriptor shapes must be filtered before any tile fetch, not just fail later as a 404.
test('a malformed descriptor hides only its day without fetching any part of it', async () => {
  const f = feed(), d = f.day(PAST), [r] = d.tiles, good = f.day(OLDER);
  const leaf = r.path.split('/')[1];
  const badPaths = [null, 42, '', `habitat-tiles/${leaf}`, `../other/habitat-history/${leaf}`, `habitat-history/../${leaf}`,
    `habitat-history/%2e%2e/${leaf}`, `habitat-history\\${leaf}`, `habitat-history/nested/${leaf}`, `/habitat-history/${leaf}`,
    `https://elsewhere.test/${r.path}`, `${r.path}?v=1`, `${r.path}#x`, `${r.path}\n`, 'habitat-history/SST-123.json',
    `habitat-history/${'a'.repeat(16)}.json`, `habitat-history/sst-${'A'.repeat(16)}.json`];
  const badTiles = [null, {}, [], [r, r], Array.from({length: 65}, (_, i) => ({...r, path: `habitat-history/sst-${i}-${'a'.repeat(16)}.json`})),
    ...[null, [], {}, {...r, bounds: null}, {...r, bounds: [0, 0, 0, 1]}, {...r, bounds: [-181, 0, 0, 1]},
      ...[null, 'abc', 'A'.repeat(64)].map(sha256 => ({...r, sha256})),
      ...[undefined, '42', 0, -1, 1.5, 5_000_001].map(bytes => ({...r, bytes})),
      ...badPaths.map(path => ({...r, path}))].map(record => [f.tile(PAST, 1).record, record])];
  for (const tiles of badTiles) {
    f.layer.history = [{...d, tiles}, good];
    const label = JSON.stringify(tiles);
    assert.deepEqual(historyDays(f.read()), [OLDER], label);
    f.asked.length = 0;
    assert.deepEqual(await f.load(PAST), {state: 'none'}, label);
    assert.deepEqual(f.asked, [MANIFEST], label);
  }
  assert.equal((await f.load(OLDER)).state, 'ready');
  assert.equal((await regionalSST(REGION, f.options)).state, 'ready');
});

// Use one healthy tile alongside the bad one: no verified subset may escape as a ready day.
// Identity and sample negatives are rehashed, so SHA verification alone cannot pass the test.
test('a bad tile body refuses the whole selected day but not a sibling day or Today', async () => {
  const f = feed(), first = f.tile(PAST), second = f.tile(PAST, 1), older = f.day(OLDER);
  const {frame} = second;
  const changed = [
    ['schema', {schema_version: 2}], ['region', {region_id: 'other-coast'}], ['layer', {layer_id: CHLOROPHYLL_LAYER_ID}],
    ['fields', {fields: f.layer.fields.toReversed()}], ['grid', {resolution_degrees: [0.1, 0.1]}],
    ['bounds', {bounds: first.record.bounds}], ['current frame', {frames: [{...frame, time: epoch(CURRENT)}]}],
    ['duplicate frame', {frames: [frame, frame]}], ['missing frame', {frames: []}],
    ['bad cell', {frames: [{...frame, cells: [[35, -120, '14', 0.3]]}]}],
  ];
  const body = f.bodies.get(f.url(second.record.path));
  for (const [why, badTile, served] of [
    ['tamper at identical length', second, Buffer.from(body.toString().replace('15,0.3', '16,0.3'))],
    ['short read', second, body.subarray(0, body.length - 1)], ['oversize body', second, Buffer.concat([body, Buffer.from(' ')])],
    ['404', second, undefined], ...changed.map(([reason, patch]) => {
      const bad = f.tile(PAST, 1, patch);
      return [reason, bad, f.bodies.get(f.url(bad.record.path))];
    }),
  ]) {
    const address = f.url(badTile.record.path);
    if (served === undefined) f.bodies.delete(address); else f.bodies.set(address, served);
    f.layer.history = [f.day(PAST, first, badTile), older];
    f.asked.length = 0;
    assert.deepEqual(await f.load(PAST), {state: 'error'}, why);
    assert.deepEqual(f.asked, [MANIFEST, f.url(first.record.path), address], why);
  }
  assert.equal((await f.load(OLDER)).state, 'ready');
  assert.equal((await regionalSST(REGION, f.options)).state, 'ready');
});

// A manifest from the wrong region cannot authorize any archive read.
test('refuses a manifest for a different region before following its history paths', async () => {
  const f = feed();
  f.layer.history = [f.day(PAST)];
  f.manifest.region_id = 'other-coast';
  assert.deepEqual(await f.load(PAST), {state: 'error'});
  assert.deepEqual(f.asked, [MANIFEST]);
});
