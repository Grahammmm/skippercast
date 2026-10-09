// Writes tests/fixtures/seafloor/chart.pmtiles (FE-14): two synthetic z12 tiles
// off Morro Bay in the seafloor publication's schema (docs/seafloor.md "URLs and
// layers": `habitat` and `cells`, nested evidence as canonical JSON strings).
// Every id, survey, credit and value is invented; nothing comes from a survey.
// The features cover each gate of web/map/seafloor.ts: a ranked candidate split
// across both tiles (one id), a deep candidate, a search area, an interpreted
// area, a held candidate, a candidate of a held reach, one without rights, and
// cells of tier 1, tier 0 and a held reach.
// PMTiles v3, uncompressed. Run: node tests/fixtures/seafloor/build-chart.mjs
import {readFileSync, writeFileSync} from 'node:fs';
import vm from 'node:vm';

const sandbox = {};
vm.runInNewContext(readFileSync(new URL('../../../dist/vendor/pmtiles-4.5.0/pmtiles.js', import.meta.url), 'utf8') + ';this.pmtiles = pmtiles;', sandbox);
const Z = 12, Y = 1617, WEST = 671, EAST = 672;

const varint = n => { const out = []; do { out.push((n % 128) | (n >= 128 ? 128 : 0)); n = Math.floor(n / 128); } while (n); return out; };
const zigzag = n => (n << 1) ^ (n >> 31);
const field = (number, value) => typeof value === 'number' ? [...varint(number * 8), ...varint(value)]
  : [...varint(number * 8 + 2), ...varint(value.length), ...value];
const text = s => [...new TextEncoder().encode(s)];
const packed = values => values.flatMap(varint);
const double = v => { const b = new DataView(new ArrayBuffer(8)); b.setFloat64(0, v, true); return [...varint(3 * 8 + 1), ...new Uint8Array(b.buffer)]; };
/** An MVT value: string, unsigned integer, double or boolean. */
const value = v => typeof v === 'string' ? field(1, text(v)) : typeof v === 'boolean' ? field(7, v ? 1 : 0)
  : Number.isInteger(v) && v >= 0 ? field(5, v) : double(v);

// One clockwise exterior ring (y down), as MVT commands: MoveTo, LineTo × 3, ClosePath.
function rect([x0, y0, x1, y1]) {
  let x = 0, y = 0;
  const delta = ([px, py]) => { const d = [zigzag(px - x), zigzag(py - y)]; [x, y] = [px, py]; return d; };
  const [first, ...rest] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  return [1 | (1 << 3), ...delta(first), 2 | (rest.length << 3), ...rest.flatMap(delta), 7 | (1 << 3)];
}

function layer(name, features) {
  const keys = [], values = [];
  const index = (list, v) => (list.includes(v) ? list : (list.push(v), list)).indexOf(v);
  const encoded = features.map(([box, props], id) => field(2, [
    ...field(1, id + 1),
    ...field(2, packed(Object.entries(props).flatMap(([k, v]) => [index(keys, k), index(values, v)]))),
    ...field(3, 3), ...field(4, packed(rect(box)))]));
  return field(3, [...field(15, 2), ...field(1, text(name)), ...encoded.flat(),
    ...keys.flatMap(k => field(3, text(k))), ...values.flatMap(v => field(4, value(v))), ...field(5, 4096)]);
}

const json = v => JSON.stringify(v);
const RIGHTS = json([{attribution: 'Fixture Survey Lab', license: 'synthetic-test', notice: 'Synthetic test credit; never survey data.',
  policy_url: 'https://example.org/terms', source_id: 'fixture-survey-2m', source_url: 'https://example.org/fixture-survey'}]);
const screen = status => json({layers: ['cdfw-mpa', 'noaa-federal', 'security'], scope: 'Spatial planning screen; season, gear and current notices still apply.',
  snapshot: '2026-10-01T00:00:00+00:00', status, version: 'whole-polygon-screen-v1'});
const BASE = {region: 'morro-bay', reach: 'morro-bay-fx1', screen: screen('pass'), hold_reasons: '[]', source_ids: json(['fixture-survey-2m']),
  source_rights: RIGHTS, source_year: 2010, resolution_m: 2, vertical_datum: 'NAVD88', depth_basis: 'nominal',
  planning_notice: 'Planning only. Not a navigation chart. Check current CDFW regulations.'};
const ranked = (id, grade, lingcod, min, max) => ({...BASE, id, status: 'habitat', tier: 2, exportable: true, terrain_grade: grade, terrain_score: 70,
  fit_lingcod: lingcod, fit_rockfish_reef: 2, depth_min_ft: min, depth_max_ft: max, label: 'Habitat candidate, unverified. Nominal depth (NAVD88); verify on your sounder.'});
const A = ranked('fixture-candidate-a', 'A', 3, 40.5, 90.25);

const HABITAT = {
  [WEST]: [
    [[2048, 1024, 4096, 3072], A],
    [[200, 200, 900, 900], ranked('fixture-candidate-deep', 'C', 1, 120, 180)],
    [[200, 3000, 900, 3800], {...BASE, id: 'fixture-search', status: 'search-area', tier: 1, exportable: false, terrain_grade: 'unknown', fit_lingcod: 'unknown',
      depth_min_ft: 50, depth_max_ft: 70, search_area: json({basis: 'Synthetic rough patch.', target_species: ['lingcod']})}],
    [[1000, 200, 1800, 900], {...ranked('fixture-held', 'B', 2, 40, 60), status: 'held', screen: screen('held'), hold_reasons: json(['overlap-cdfw-mpa'])}],
    [[2600, 3300, 3400, 3900], {...ranked('fixture-held-reach', 'B', 2, 40, 60), reach: 'morro-bay-fx2'}],
  ],
  [EAST]: [
    [[0, 1024, 1024, 3072], A],
    [[1400, 2800, 2400, 3600], {...BASE, id: 'fixture-interpreted', status: 'classified-area', tier: 1, exportable: false, detail_level: 'classified-area',
      terrain_grade: 'unknown', fit_lingcod: 'unknown', depth_min_ft: 25, depth_max_ft: 300, depth_basis: 'nominal-band', source_year: 'unknown', vertical_datum: 'unknown',
      classified_area: json({profile: 'original-rugose-classified-area-v1', policy_id: 'fixture-policy'})}],
    [[1400, 200, 2200, 800], {...ranked('fixture-uncredited', 'A', 3, 40, 60), source_rights: '[]'}],
  ],
};
const cell = (id, reach, tier) => ({id, reach, tier, source_id: tier ? 'fixture-survey-2m' : 'unknown', reference_band: 'provisional', band_area_m2: 62500,
  planning_notice: BASE.planning_notice});
const CELLS = {
  [WEST]: [
    [[1800, 1800, 2600, 2600], cell('3310:fx:1', 'morro-bay-fx1', 1)],
    [[3000, 200, 3800, 900], cell('3310:fx:0', 'morro-bay-fx1', 0)],
    [[2600, 2600, 3400, 3300], cell('3310:fx:2', 'morro-bay-fx2', 1)],
  ],
  [EAST]: [],
};

const tiles = [WEST, EAST].map(x => Uint8Array.from([...layer('cells', CELLS[x]), ...layer('habitat', HABITAT[x])]));
const fields = {id: 'String', reach: 'String', status: 'String'};
const metadata = new TextEncoder().encode(JSON.stringify({
  name: 'SkipperCast seafloor — fixture', description: 'Synthetic test tiles in the seafloor publication schema; not survey data.',
  type: 'overlay', format: 'pbf', vector_layers: ['cells', 'habitat'].map(id => ({id, minzoom: Z, maxzoom: Z, fields})),
}));
const ids = [WEST, EAST].map(x => sandbox.pmtiles.zxyToTileId(Z, x, Y));
// Entries: count, tile-id deltas, run lengths, lengths, offsets (first + 1; 0 = right after the previous one).
const directory = Uint8Array.from([...varint(2), ...varint(ids[0]), ...varint(ids[1] - ids[0]), ...varint(1), ...varint(1),
  ...varint(tiles[0].length), ...varint(tiles[1].length), ...varint(1), ...varint(0)]);
const data = Buffer.concat(tiles);

const lon = x => (x / 2 ** Z) * 360 - 180;
const lat = y => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** Z))) * 180) / Math.PI;
const header = new DataView(new ArrayBuffer(127));
new Uint8Array(header.buffer).set([...text('PMTiles'), 3]);
const offsets = [127, directory.length, 127 + directory.length, metadata.length, 127 + directory.length + metadata.length, 0,
  127 + directory.length + metadata.length, data.length, 2, 2, 2];
offsets.forEach((v, i) => header.setBigUint64(8 + i * 8, BigInt(v), true));
[1, 1, 1, 1, Z, Z].forEach((v, i) => header.setUint8(96 + i, v));  // clustered, no compression, MVT, zooms
[lon(WEST), lat(Y + 1), lon(EAST + 1), lat(Y)].forEach((v, i) => header.setInt32(102 + i * 4, Math.round(v * 1e7), true));
header.setUint8(118, Z);
header.setInt32(119, Math.round(lon(EAST) * 1e7), true);
header.setInt32(123, Math.round(lat(Y + 0.5) * 1e7), true);

const out = new URL('./chart.pmtiles', import.meta.url);
writeFileSync(out, Buffer.concat([new Uint8Array(header.buffer), directory, metadata, data]));
console.log(`${out.pathname}: ${127 + directory.length + metadata.length + data.length} bytes`);
