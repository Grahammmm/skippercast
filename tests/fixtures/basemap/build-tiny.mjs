// Writes tests/fixtures/basemap/tiny.pmtiles (FE-72): one synthetic z10 vector
// tile over Morro Bay in the Protomaps basemap schema (earth, water, landuse,
// boundaries, roads, places, pois; `kind`, `name`, `min_zoom`). Every shape and
// name is invented ("Fixture Town"); nothing comes from OpenStreetMap.
// PMTiles v3, uncompressed. Run: node tests/fixtures/basemap/build-tiny.mjs
import {readFileSync, writeFileSync} from 'node:fs';
import vm from 'node:vm';

const sandbox = {};
vm.runInNewContext(readFileSync(new URL('../../../dist/vendor/pmtiles-4.5.0/pmtiles.js', import.meta.url), 'utf8') + ';this.pmtiles = pmtiles;', sandbox);
const [Z, X, Y] = [10, 168, 404];

const varint = n => { const out = []; do { out.push((n % 128) | (n >= 128 ? 128 : 0)); n = Math.floor(n / 128); } while (n); return out; };
const zigzag = n => (n << 1) ^ (n >> 31);
const field = (number, value) => typeof value === 'number' ? [...varint(number * 8), ...varint(value)]
  : [...varint(number * 8 + 2), ...varint(value.length), ...value];
const text = s => [...new TextEncoder().encode(s)];
const packed = values => values.flatMap(varint);

// MVT geometry commands: MoveTo 1, LineTo 2, ClosePath 7; deltas zigzag-encoded.
function geometry(type, points) {
  let x = 0, y = 0;
  const delta = ([px, py]) => { const d = [zigzag(px - x), zigzag(py - y)]; [x, y] = [px, py]; return d; };
  const [first, ...rest] = points;
  const out = [1 | (1 << 3), ...delta(first)];
  if (type === 1) return out;
  out.push(2 | (rest.length << 3), ...rest.flatMap(delta));
  return type === 3 ? [...out, 7 | (1 << 3)] : out;
}
const rect = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];  // clockwise with y down: an exterior ring

const LAYERS = {
  earth: [[3, rect(2048, 0, 4096, 4096), {kind: 'earth'}]],
  water: [
    [3, rect(2600, 600, 2900, 900), {kind: 'lake', name: 'Fixture Lake'}],
    [2, [[3000, 1200], [2100, 1800]], {kind: 'river', name: 'Fixture Creek'}],
    [1, [[1200, 2000]], {kind: 'bay', name: 'Fixture Bay'}],
  ],
  landuse: [[3, rect(3300, 2600, 3800, 3200), {kind: 'park', name: 'Fixture Park'}]],
  boundaries: [[2, [[3900, 0], [3900, 4096]], {kind: 'region'}]],
  roads: [
    [2, [[2300, 0], [2300, 4096]], {kind: 'highway', name: 'Fixture Highway'}],
    [2, [[2300, 2000], [4000, 2200]], {kind: 'major_road', name: 'Fixture Road'}],
    [2, [[2600, 2600], [3200, 3400]], {kind: 'minor_road', name: 'Fixture Lane'}],
  ],
  places: [[1, [[2500, 2100]], {kind: 'locality', name: 'Fixture Town', min_zoom: 9, population_rank: 8}]],
  pois: [[1, [[2150, 2500]], {kind: 'marina', name: 'Fixture Marina', min_zoom: 12}]],
};

function layer(name, features) {
  const keys = [], values = [];
  const index = (list, v) => (list.includes(v) ? list : (list.push(v), list)).indexOf(v);
  const encoded = features.map(([type, points, props], id) => field(2, [
    ...field(1, id + 1),
    ...field(2, packed(Object.entries(props).flatMap(([k, v]) => [index(keys, k), index(values, v)]))),
    ...field(3, type), ...field(4, packed(geometry(type, points)))]));
  return field(3, [...field(15, 2), ...field(1, text(name)), ...encoded.flat(),
    ...keys.flatMap(k => field(3, text(k))),
    ...values.flatMap(v => field(4, typeof v === 'number' ? field(5, v) : field(1, text(v)))), ...field(5, 4096)]);
}

const tile = Uint8Array.from(Object.entries(LAYERS).flatMap(([name, features]) => layer(name, features)));
const fields = {kind: 'String', name: 'String', min_zoom: 'Number', population_rank: 'Number'};
const metadata = new TextEncoder().encode(JSON.stringify({
  name: 'skippercast-basemap-fixture', description: 'Synthetic test tile in the Protomaps basemap schema; not map data.',
  type: 'baselayer', format: 'pbf',
  vector_layers: Object.keys(LAYERS).map(id => ({id, minzoom: Z, maxzoom: Z, fields})),
}));
const directory = Uint8Array.from([...varint(1), ...varint(sandbox.pmtiles.zxyToTileId(Z, X, Y)), ...varint(1), ...varint(tile.length), ...varint(1)]);

const lon = x => (x / 2 ** Z) * 360 - 180;
const lat = y => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** Z))) * 180) / Math.PI;
const header = new DataView(new ArrayBuffer(127));
new Uint8Array(header.buffer).set([...text('PMTiles'), 3]);
const offsets = [127, directory.length, 127 + directory.length, metadata.length, 127 + directory.length + metadata.length, 0,
  127 + directory.length + metadata.length, tile.length, 1, 1, 1];
offsets.forEach((v, i) => header.setBigUint64(8 + i * 8, BigInt(v), true));
[1, 1, 1, 1, Z, Z].forEach((v, i) => header.setUint8(96 + i, v));  // clustered, no compression, MVT, zooms
[lon(X), lat(Y + 1), lon(X + 1), lat(Y)].forEach((v, i) => header.setInt32(102 + i * 4, Math.round(v * 1e7), true));
header.setUint8(118, Z);
header.setInt32(119, Math.round(lon(X + 0.5) * 1e7), true);
header.setInt32(123, Math.round(lat(Y + 0.5) * 1e7), true);

const out = new URL('./tiny.pmtiles', import.meta.url);
writeFileSync(out, Buffer.concat([new Uint8Array(header.buffer), directory, metadata, tile]));
console.log(`${out.pathname}: ${127 + directory.length + metadata.length + tile.length} bytes`);
