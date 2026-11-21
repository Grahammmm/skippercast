import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {regionalSsh, SSH_LAYER_ID} from '../web/map/habitat-feed.ts';

const PAGE = 'https://s.test/map', REGION = 'test-coast', ID = 'wcofs-ssh';
const BASE = `https://s.test/feeds/conditions/regions/${REGION}/`, MANIFEST = `${BASE}habitat-dynamics.json`;
const ISSUED = '2026-11-19T00:00:00Z', NOW = new Date('2026-11-19T01:00:00Z');
const EARLY = '2026-11-19T03:00:00.000Z', LATE = '2026-11-19T09:00:00.000Z';
const early = Date.parse(EARLY) / 1000, late = Date.parse(LATE) / 1000, empty = early + 10_800;
const FIELDS = ['latitude', 'longitude', 'wet', 'ssh_cm'];
const RESOLUTION = [0.04, 0.05];
const ROW = [35.04, -121.05, true, 12.5];
const CELL = {lat: 35.04, lon: -121.05, sshCm: 12.5};

function tile(index, frames, overrides = {}) {
  const bounds = index === 0 ? [-121.2, 35, -121, 35.2] : [-121, 35, -120.8, 35.2];
  const data = {schema_version: 1, region_id: REGION, layer_id: ID, fields: FIELDS, resolution_degrees: RESOLUTION, bounds, frames, ...overrides};
  const body = Buffer.from(JSON.stringify(data)), sha256 = createHash('sha256').update(body).digest('hex');
  return {body, record: {bounds, bytes: body.length, sha256, path: `habitat-tiles/${ID}-${index}-${sha256.slice(0, 16)}.json`}};
}

function feed(tiles = [tile(0, [{time: early, cells: [ROW]}])]) {
  const layer = {id: ID, kind: 'forecast', fields: FIELDS, resolution_degrees: RESOLUTION, status: 'ok', max_age_hours: 6,
    issued_at: ISSUED, surface_only: true, frames: [{time: early, valid_cells: 1}], tiles: tiles.map(t => t.record)};
  const source = {name: 'NOAA WCOFS, regular grid', data_retrieved_at: '2026-11-19T00:30:00Z'};
  const manifest = {schema_version: 1, region_id: REGION, layers: {[ID]: layer}, sources: {[ID]: source}};
  return {manifest, layer, source, tiles};
}

function server({manifest, tiles}, manifestStatus = 200) {
  const asked = [];
  const fetchFn = async url => {
    asked.push(url);
    if (url === MANIFEST) return manifestStatus === 200 ? Response.json(manifest) : new Response(null, {status: manifestStatus});
    const match = tiles.find(t => url === BASE + t.record.path);
    return match ? new Response(match.body) : new Response(null, {status: 404});
  };
  return {fetchFn, asked};
}

const read = (fetchFn, options = {}) => regionalSsh(REGION, {page: PAGE, now: NOW, fetchFn, ...options});
const ready = frames => ({state: 'ready', product: 'NOAA WCOFS', issuedAt: ISSUED, resolution: [0.04, 0.05], maxAgeMs: 21_600_000, frames});

test('C1: exports the published SSH layer identifier', () => {
  assert.deepEqual(SSH_LAYER_ID, ID);
});

test('C2: a missing manifest returns none, not a read error', async () => {
  assert.deepEqual(await read(server(feed(), 404).fetchFn), {state: 'none'});
});

test('C2: a manifest listing only currents does not supply SSH', async () => {
  const f = feed();
  delete f.manifest.layers[ID];
  f.manifest.layers['wcofs-surface-forecast'] = {...f.layer, id: 'wcofs-surface-forecast', fields: ['latitude', 'longitude', 'u_mps', 'v_mps']};
  f.manifest.sources['wcofs-surface-forecast'] = f.source;
  assert.deepEqual(await read(server(f).fetchFn), {state: 'none'});
});

test('C2: an HTTP failure is an error, not a missing layer or offline fetch', async () => {
  assert.deepEqual(await read(server(feed(), 503).fetchFn), {state: 'error'});
});

for (const [invalid, override] of [
  ['an SSH analysis', {kind: 'analysis'}],
  ['a forecast without ssh_cm', {fields: ['latitude', 'longitude', 'wet']}],
]) {
  test(`C2: refuses ${invalid} before fetching tiles`, async () => {
    const f = feed();
    Object.assign(f.layer, override);
    const {fetchFn, asked} = server(f);
    assert.deepEqual(await read(fetchFn), {state: 'error'});
    assert.deepEqual(asked, [MANIFEST]);
  });
}

for (const [reason, change, expectedTimes = [EARLY, LATE], status = 'ok'] of [
  ['non-loading status', f => { f.layer.status = 'stale'; }, [EARLY, LATE], 'stale'],
  ['no populated frame', f => { f.layer.frames.forEach(frame => { frame.valid_cells = 0; }); }, []],
  ['missing issue time', f => { delete f.layer.issued_at; }],
  ['unparseable issue time', f => { f.layer.issued_at = 'not a date'; }],
  ['age equal to the maximum', f => { f.layer.issued_at = '2026-11-18T19:00:00Z'; }],
  ['age above the maximum', f => { f.layer.issued_at = '2026-11-18T18:59:59Z'; }],
  ['missing retrieval time', f => { delete f.source.data_retrieved_at; }],
  ['non-boolean surface_only', f => { f.layer.surface_only = 1; }],
]) {
  test(`C3: ${reason} lists only populated times and does not request tiles`, async () => {
    const f = feed();
    f.layer.frames = [{time: late, valid_cells: 1}, {time: empty, valid_cells: 0}, {time: early, valid_cells: 1}];
    change(f);
    const {fetchFn, asked} = server(f);
    assert.deepEqual(await read(fetchFn), {state: 'listed', validAt: expectedTimes, layerStatus: status});
    assert.deepEqual(asked, [MANIFEST]);
  });
}

test('C4: retained forecast just under max age reads all tiles in frame and row order, including both bounds', async () => {
  const f = feed([
    tile(0, [{time: late, cells: [[35.04, -121.05, true, -2000]]}, {time: early, cells: [ROW, [35.04, -121.1, true, 2000]]}]),
    tile(1, [{time: early, cells: [[35.04, -120.95, true, 0]]}]),
  ]);
  f.layer.status = 'retained';
  f.layer.frames = [{time: late, valid_cells: 1}, {time: empty, valid_cells: 0}, {time: early, valid_cells: 3}];
  assert.deepEqual(await read(server(f).fetchFn, {now: new Date('2026-11-19T05:59:59.999Z')}), ready([
    {validAt: EARLY, cells: [CELL, {lat: 35.04, lon: -121.1, sshCm: 2000}, {lat: 35.04, lon: -120.95, sshCm: 0}]},
    {validAt: LATE, cells: [{lat: 35.04, lon: -121.05, sshCm: -2000}]},
  ]));
});

// Valid wire values can still be invalid SSH heights; do not coerce them or discard the good row.
for (const value of [2001, -2001, null, true]) {
  test(`C4: drops ${value} without dropping the good cell`, async () => {
    const f = feed([tile(0, [{time: early, cells: [ROW, [35.04, -121.1, true, value]]}])]);
    assert.deepEqual(await read(server(f).fetchFn), ready([{validAt: EARLY, cells: [CELL]}]));
  });
}

// Rehash the invalid payloads so the sample-shape check, not the digest, must reject them.
for (const value of ['12', {}, []]) {
  test(`C4: malformed wire sample ${JSON.stringify(value)} refuses the entire layer`, async () => {
    const f = feed([tile(0, [{time: early, cells: [ROW, [35.04, -121.1, true, value]]}])]);
    assert.deepEqual(await read(server(f).fetchFn), {state: 'error'});
  });
}

for (const [reason, change] of [
  ['same-length tampering', t => { t.body = Buffer.from(t.body.toString().replace('12.5', '13.5')); }],
  ['wrong byte length', t => { t.record.bytes++; }],
  ['a path escaping the region', t => { t.record.path = `../other-region/${t.record.path}`; }],
]) {
  test(`C4: ${reason} in the second tile refuses the layer, not just that tile`, async () => {
    const first = tile(0, [{time: early, cells: [ROW]}]);
    const second = tile(1, [{time: early, cells: [[35.04, -120.95, true, 12.5]]}]);
    change(second);
    const {fetchFn, asked} = server(feed([first, second]));
    assert.deepEqual(await read(fetchFn), {state: 'error'});
    if (second.record.path.startsWith('../')) assert.deepEqual(asked, [MANIFEST]);
  });
}

test('C4: a correctly hashed tile from another region refuses the layer even with a good sibling tile', async () => {
  const first = tile(0, [{time: early, cells: [ROW]}]);
  const wrongRegion = tile(1, [{time: early, cells: [[35.04, -120.95, true, 12.5]]}], {region_id: 'other-region'});
  assert.deepEqual(await read(server(feed([first, wrongRegion])).fetchFn), {state: 'error'});
});

for (const stage of ['manifest', 'tile']) {
  test(`C5: offline ${stage} fetch preserves the network flag`, async () => {
    const {fetchFn} = server(feed());
    const offline = async url => {
      if (stage === 'manifest' || url !== MANIFEST) throw new TypeError('offline');
      return fetchFn(url);
    };
    assert.deepEqual(await read(offline), {state: 'error', network: true});
  });
}

test('C5: a non-network exception reading the manifest is a plain error', async () => {
  assert.deepEqual(await read(async () => new Response('{')), {state: 'error'});
});

test('C5: cancellation during a tile read rethrows the caller’s AbortError', async () => {
  const controller = new AbortController(), reason = new DOMException('canceled SSH read', 'AbortError');
  const {fetchFn} = server(feed());
  const abortDuringTile = async (url, {signal}) => {
    if (url !== MANIFEST) {
      controller.abort(reason);
      signal.throwIfAborted();
    }
    return fetchFn(url);
  };
  await assert.rejects(read(abortDuringTile, {signal: controller.signal}), error =>
    error.constructor === DOMException && error.name === 'AbortError' && error === reason);
});
