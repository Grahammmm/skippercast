// Charter fleet map API (CF-50; docs/plans/charter-fleet/design.md § 14, D11): every
// filter, caps and paging, basis/rights on every feature, and the admin plus
// FLEET_ENABLED + FLEET_MAP_ENABLED gate. Offline, through the Worker, against the
// real migrations in the node:sqlite D1 fake. The fixture is synthetic: invented
// vessel names, example ports, MMSIs 999xxxxxx and made-up positions.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const {decodePolyline, CAPS, mapQuery} = await import('../server/fleet/map.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ON = {FLEET_ENABLED: 'true', FLEET_MAP_ENABLED: 'true'};
const NOW = '2026-10-04T12:00:00Z';
const REGION = 'morro-bay';
const skip = sqliteUnavailable ? {skip: sqliteUnavailable} : {};

/** Google polyline encoding (precision 5) of [lon, lat] pairs, for the fixture. */
function encode(coordinates) {
  let out = '', pLat = 0, pLon = 0;
  const one = v => { let n = v < 0 ? ~(v << 1) : v << 1; let s = ''; while (n >= 0x20) { s += String.fromCharCode((0x20 | (n & 0x1f)) + 63); n >>= 5; } return s + String.fromCharCode(n + 63); };
  for (const [lon, lat] of coordinates) {
    const la = Math.round(lat * 1e5), lo = Math.round(lon * 1e5);
    out += one(la - pLat) + one(lo - pLon); pLat = la; pLon = lo;
  }
  return out;
}

// Vessels: id, name, slug, class, home port.
const VESSELS = [
  ['v-sea-example', 'Sea Example', 'sea-example', 'six-pack', 'morro-bay'],
  ['v-tide-runner', 'Tide Runner', 'tide-runner', 'inspected-party', 'port-san-luis'],
  ['v-kelp-wanderer', 'Kelp Wanderer', 'kelp-wanderer', 'long-range', 'port-san-luis'],
];
// Trips: id, vessel, mmsi, port, departed_at, local_date, season, part, trip type, source, rights.
const TRIPS = [
  ['t1', 'v-sea-example', '999000001', 'morro-bay', '2026-06-10T13:00:00Z', '2026-06-10', '2026', 'summer', 'half-day', 'aisstream', 'internal-only'],
  ['t2', 'v-tide-runner', '999000002', 'port-san-luis', '2026-07-20T12:00:00Z', '2026-07-20', '2026', 'summer', 'full-day', 'aisstream', 'internal-only'],
  ['t3', 'v-kelp-wanderer', '999000003', 'port-san-luis', '2025-10-05T11:00:00Z', '2025-10-05', '2025', 'fall', 'multi-day', 'marinecadastre', 'noaa-planning-only'],
  ['t4', 'v-sea-example', '999000001', 'morro-bay', '2026-09-01T14:00:00Z', '2026-09-01', '2026', 'fall', 'half-day', 'aisstream', 'internal-only'],
];
// Events: id, trip, kind, lat, lon, started_at, dwell, event vessel_class (null: from the vessel), event trip_type (null: from the trip).
const EVENTS = [
  ['e1', 't1', 'drift-anchor', 35.40, -120.95, '2026-06-10T15:00:00Z', 40, 'six-pack', 'half-day'],
  ['e2', 't2', 'troll', 35.10, -120.80, '2026-07-20T14:00:00Z', 90, 'inspected-party', 'full-day'],
  ['e3', 't2', 'drift-anchor', 35.12, -120.78, '2026-07-20T17:00:00Z', 60, null, null],
  ['e4', 't3', 'drift-anchor', 34.50, -120.50, '2025-10-06T09:00:00Z', 120, 'long-range', 'multi-day'],
  ['e5', 't4', 'troll', 35.45, -121.00, '2026-09-01T16:00:00Z', 30, 'six-pack', 'half-day'],
];
// Segments per trip: kind and [lon, lat] points.
const SEGMENTS = {
  t1: [['transit', [[-120.86, 35.37], [-120.95, 35.40]]], ['fishing-drift', [[-120.95, 35.40], [-120.951, 35.401], [-120.952, 35.399]]], ['gap', [[-120.952, 35.399], [-120.86, 35.37]]]],
  t2: [['transit', [[-120.74, 35.17], [-120.80, 35.10]]], ['fishing-troll', [[-120.80, 35.10], [-120.78, 35.12]]], ['in-port', null]],
  t3: [['transit', [[-120.74, 35.17], [-120.50, 34.50]]]],
  t4: [['fishing-troll', [[-120.95, 35.42], [-121.00, 35.45]]]],
};
// Aggregate cells: id, cell, lat, lon, season, part, kind, vessels, events, dwell, first, last, rights.
const CELLS = [
  ['c1', 'g:1', 35.40, -120.95, '2026', 'summer', 'drift-anchor', 1, 1, 40, '2026-06-10', '2026-06-10', 'internal-only'],
  ['c2', 'g:2', 35.10, -120.80, '2026', 'summer', 'troll', 1, 1, 90, '2026-07-20', '2026-07-20', 'internal-only'],
  ['c3', 'g:3', 34.50, -120.50, '2025', 'fall', 'drift-anchor', 1, 1, 120, '2025-10-06', '2025-10-06', 'noaa-planning-only'],
];

function seed(sql) {
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-1',?,'admin')").run(NOW);
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,vessel_class,port_id,mmsi,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?, 'active','hidden',?,?,?,?)`);
  VESSELS.forEach(([id, name, slug, cls, port], i) => vessel.run(id, REGION, slug, name, name.toLowerCase(), cls, port, `99900000${i + 1}`, NOW, NOW, NOW, NOW));
  const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,depart_port_id,return_port_id,departed_at,returned_at,local_date,season,season_part,status,
    trip_type_inferred,source,rights,classifier_version,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'closed',?,?,?,'cv-test',?)`);
  for (const [id, v, mmsi, port, at, date, season, part, type, source, rights] of TRIPS) trip.run(id, REGION, v, mmsi, port, port, at, at, date, season, part, type, source, rights, NOW);
  const segment = sql.prepare('INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at,geometry,points_n) VALUES(?,?,?,?,?,?,?,?)');
  for (const [tripId, list] of Object.entries(SEGMENTS)) list.forEach(([kind, points], seq) =>
    segment.run(`${tripId}-s${seq}`, tripId, seq, kind, NOW, NOW, points ? encode(points) : null, points?.length ?? 0));
  const event = sql.prepare(`INSERT INTO fleet_events(id,trip_id,segment_id,vessel_id,region,kind,lat,lon,radius_m,started_at,ended_at,dwell_min,port_id,vessel_class,trip_type,
    season,season_part,source,rights,classifier_version) VALUES(?,?,?,?,?,?,?,?,80,?,?,?,?,?,?,?,?,?,?,'cv-test')`);
  for (const [id, tripId, kind, lat, lon, at, dwell, cls, type] of EVENTS) {
    const t = TRIPS.find(r => r[0] === tripId);
    event.run(id, tripId, `${tripId}-s1`, t[1], REGION, kind, lat, lon, at, at, dwell, t[3], cls, type, t[6], t[7], t[9], t[10]);
  }
  const cell = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,season_part,kind,vessels_n,events_n,dwell_min,first_date,last_date,rights,computed_at)
    VALUES(?,?,'grid','{"resolution_m":1000}',?,?,?,?,?,?,?,?,?,?,?,?,?)`);
  for (const [id, c, lat, lon, season, part, kind, vn, en, dwell, first, last, rights] of CELLS) cell.run(id, REGION, c, lat, lon, season, part, kind, vn, en, dwell, first, last, rights, NOW);
}

function setup() {
  const {sql, db} = advisorDatabase(); seed(sql);
  const as = (path, env = ON, owner = 'admin-1') => worker.fetch(new Request(ORIGIN + path, {headers: {'x-test-owner': owner}}), {ASSETS, DB: db, ...env});
  const get = async path => { const r = await as(path); assert.equal(r.status, 200, `${path}: ${r.status}`); return r.json(); };
  const ids = async path => (await get(path)).features.map(f => f.id).sort();
  const trips = async path => [...new Set((await get(path)).features.map(f => f.properties.trip_id))].sort();
  return {sql, db, as, get, ids, trips};
}

test('decodePolyline reads the Google reference polyline and rejects garbage', () => {
  assert.deepEqual(decodePolyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]);
  assert.deepEqual(decodePolyline(encode([[-120.95, 35.4], [-121, 35.45]])), [[-120.95, 35.4], [-121, 35.45]]);
  assert.deepEqual(decodePolyline('_p~iF'), []);
  assert.deepEqual(decodePolyline(' \u0000'), []);
});

test('acceptance 4: 404 for non-admins, with either flag off, and for unknown layers; anonymous is 401 at the private gate', skip, async () => {
  const {sql, db, as} = setup();
  try {
    for (const layer of ['filters', 'events', 'tracks', 'heat']) {
      const path = `/api/fleet/map/${layer}?region=${REGION}`;
      assert.equal((await as(path)).status, 200, `${layer} on`);
      assert.equal((await as(path, {})).status, 404, `${layer}: both flags off`);
      assert.equal((await as(path, {FLEET_ENABLED: 'true'})).status, 404, `${layer}: map flag off`);
      assert.equal((await as(path, {FLEET_MAP_ENABLED: 'true'})).status, 404, `${layer}: fleet flag off`);
      assert.equal((await as(path, {...ON, FLEET_MAP_ENABLED: 'yes'})).status, 404, `${layer}: a typo keeps the default`);
      assert.equal((await as(path, {TEXT_ADVISOR_ENABLED: 'true', FLEET_MAP_ENABLED: 'true'})).status, 404, `${layer}: the advisor flag does not open map routes`);
      assert.equal((await as(path, ON, 'someone')).status, 404, `${layer}: non-admin`);
      assert.equal((await as(path, {TEXT_ADVISOR_ENABLED: 'true', ...ON}, 'someone')).status, 404, `${layer}: non-admin with every flag on`);
      assert.equal((await worker.fetch(new Request(ORIGIN + path), {ASSETS, DB: db, ...ON})).status, 401, `${layer}: anonymous`);
    }
    assert.equal((await as('/api/fleet/map/positions?region=morro-bay')).status, 404);
    assert.equal((await as('/api/fleet/map/events/extra?region=morro-bay')).status, 404);
    const response = await as(`/api/fleet/map/events?region=${REGION}`);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
  } finally { sql.close(); }
});

test('acceptance 1: each events filter narrows the seeded fixture as expected', skip, async () => {
  const {sql, ids, get} = setup();
  const q = `/api/fleet/map/events?region=${REGION}`;
  try {
    assert.deepEqual(await ids(q), ['e1', 'e2', 'e3', 'e4', 'e5']);
    assert.deepEqual(await ids(`${q}&vessel=v-sea-example`), ['e1', 'e5']);
    assert.deepEqual(await ids(`${q}&vessel=v-sea-example,v-kelp-wanderer`), ['e1', 'e4', 'e5']);
    assert.deepEqual(await ids(`${q}&port=port-san-luis`), ['e2', 'e3', 'e4']);
    // e3 has no class or trip type of its own: both come from its vessel and trip.
    assert.deepEqual(await ids(`${q}&class=inspected-party`), ['e2', 'e3']);
    assert.deepEqual(await ids(`${q}&class=six-pack`), ['e1', 'e5']);
    assert.deepEqual(await ids(`${q}&trip_type=full-day`), ['e2', 'e3']);
    assert.deepEqual(await ids(`${q}&trip_type=half-day,multi-day`), ['e1', 'e4', 'e5']);
    assert.deepEqual(await ids(`${q}&kind=troll`), ['e2', 'e5']);
    assert.deepEqual(await ids(`${q}&kind=drift-anchor`), ['e1', 'e3', 'e4']);
    // The date range is the trip's local departure date: e4 started 2025-10-06 on a trip that left 2025-10-05.
    assert.deepEqual(await ids(`${q}&from=2026-07-01&to=2026-07-31`), ['e2', 'e3']);
    assert.deepEqual(await ids(`${q}&from=2026-07-21`), ['e5']);
    assert.deepEqual(await ids(`${q}&to=2025-10-05`), ['e4']);
    assert.deepEqual(await ids(`${q}&from=2025-10-06&to=2025-10-31`), []);
    assert.deepEqual(await ids(`${q}&season=2025`), ['e4']);
    assert.deepEqual(await ids(`${q}&season=2026&season_part=fall`), ['e5']);
    assert.deepEqual(await ids(`${q}&season_part=summer`), ['e1', 'e2', 'e3']);
    assert.deepEqual(await ids(`${q}&source=marinecadastre`), ['e4']);
    assert.deepEqual(await ids(`${q}&source=aisstream`), ['e1', 'e2', 'e3', 'e5']);
    assert.deepEqual(await ids(`${q}&bbox=-120.9,35.0,-120.7,35.2`), ['e2', 'e3']);
    assert.deepEqual(await ids(`${q}&vessel=v-sea-example&kind=troll&season_part=fall&bbox=-121.1,35.3,-120.9,35.5`), ['e5']);
    assert.deepEqual(await ids(`/api/fleet/map/events?region=elsewhere`), []);
    // The feature: a Point at [lon, lat] with the card's fields.
    const {features: [e5]} = await get(`${q}&vessel=v-sea-example&kind=troll`);
    assert.deepEqual(e5.geometry, {type: 'Point', coordinates: [-121, 35.45]});
    assert.equal(e5.properties.vessel_name, 'Sea Example');
    assert.equal(e5.properties.port_id, 'morro-bay');
    assert.equal(e5.properties.dwell_min, 30);
    assert.equal(e5.properties.local_date, '2026-09-01');
  } finally { sql.close(); }
});

test('acceptance 1: each tracks filter narrows the seeded trips; segments decode to LineStrings', skip, async () => {
  const {sql, trips, get} = setup();
  const q = `/api/fleet/map/tracks?region=${REGION}`;
  try {
    assert.deepEqual(await trips(q), ['t1', 't2', 't3', 't4']);
    assert.deepEqual(await trips(`${q}&vessel=v-tide-runner`), ['t2']);
    assert.deepEqual(await trips(`${q}&port=morro-bay`), ['t1', 't4']);
    assert.deepEqual(await trips(`${q}&class=long-range`), ['t3']);
    assert.deepEqual(await trips(`${q}&trip_type=half-day`), ['t1', 't4']);
    assert.deepEqual(await trips(`${q}&kind=troll`), ['t2', 't4']);
    assert.deepEqual(await trips(`${q}&from=2026-06-01&to=2026-07-31`), ['t1', 't2']);
    assert.deepEqual(await trips(`${q}&season=2025&season_part=fall`), ['t3']);
    assert.deepEqual(await trips(`${q}&season_part=fall`), ['t3', 't4']);
    assert.deepEqual(await trips(`${q}&source=marinecadastre`), ['t3']);
    // bbox keeps the segments whose extent overlaps it, and the trips that have one.
    const boxed = await get(`${q}&bbox=-121.1,35.4,-120.94,35.5`);
    assert.deepEqual([...new Set(boxed.features.map(f => f.properties.trip_id))].sort(), ['t1', 't4']);
    assert.deepEqual(boxed.features.map(f => f.id).sort(), ['t1-s0', 't1-s1', 't4-s0']);
    const all = await get(`${q}&vessel=v-tide-runner`);
    // The in-port segment without geometry is not drawn.
    assert.deepEqual(all.features.map(f => [f.id, f.properties.segment_kind]), [['t2-s0', 'transit'], ['t2-s1', 'fishing-troll']]);
    assert.deepEqual(all.features[1].geometry, {type: 'LineString', coordinates: [[-120.8, 35.1], [-120.78, 35.12]]});
    assert.equal(all.meta.trips, 1);
    assert.equal(all.features[0].properties.vessel_class, 'inspected-party');
    assert.equal(all.features[0].properties.trip_type, 'full-day');
  } finally { sql.close(); }
});

test('acceptance 1: heat filters by kind, season, part, dates and bbox, and lists filters aggregates cannot apply', skip, async () => {
  const {sql, ids, get} = setup();
  const q = `/api/fleet/map/heat?region=${REGION}`;
  try {
    const all = await get(q);
    assert.deepEqual(all.features.map(f => f.id), ['c3', 'c2', 'c1'], 'most dwell first');
    assert.deepEqual(all.meta.ignored, []);
    assert.deepEqual(await ids(`${q}&kind=drift-anchor`), ['c1', 'c3']);
    assert.deepEqual(await ids(`${q}&season=2026`), ['c1', 'c2']);
    assert.deepEqual(await ids(`${q}&season_part=fall`), ['c3']);
    assert.deepEqual(await ids(`${q}&from=2026-07-01`), ['c2']);
    assert.deepEqual(await ids(`${q}&to=2026-06-30`), ['c1', 'c3']);
    assert.deepEqual(await ids(`${q}&bbox=-121,35.3,-120.9,35.5`), ['c1']);
    assert.deepEqual(await ids(`${q}&module=h3`), []);
    const ignored = await get(`${q}&vessel=v-sea-example&class=six-pack&port=morro-bay&trip_type=half-day&source=aisstream&kind=troll`);
    assert.deepEqual(ignored.meta.ignored, ['vessel', 'port', 'class', 'trip_type', 'source']);
    assert.deepEqual(ignored.features.map(f => f.id), ['c2'], 'kind still applies');
    // A 1 km rectangle centred on the cell.
    const [ring] = all.features.find(f => f.id === 'c1').geometry.coordinates;
    assert.equal(ring.length, 5);
    assert.deepEqual(ring[0], ring[4]);
    assert.ok(Math.abs((ring[2][1] - ring[0][1]) * 111_320 - 1000) < 1);
    assert.ok(Math.abs((ring[0][0] + ring[2][0]) / 2 - -120.95) < 1e-6);
  } finally { sql.close(); }
});

test('acceptance 3: every feature carries basis and rights; noaa-planning-only rows are included and tagged', skip, async () => {
  const {sql, get} = setup();
  try {
    for (const layer of ['events', 'tracks', 'heat']) {
      const page = await get(`/api/fleet/map/${layer}?region=${REGION}`);
      assert.equal(page.type, 'FeatureCollection');
      assert.ok(page.features.length > 0, layer);
      for (const f of page.features) {
        assert.equal(f.properties.basis, 'inferred-from-movement', `${layer} ${f.id}`);
        assert.ok(typeof f.properties.rights === 'string' && f.properties.rights, `${layer} ${f.id}`);
        assert.equal(f.properties.planning_only, f.properties.rights === 'noaa-planning-only', `${layer} ${f.id}`);
      }
      const tagged = page.features.filter(f => f.properties.planning_only);
      assert.ok(tagged.length > 0, `${layer}: the MarineCadastre rows are included`);
      assert.equal(page.meta.planning_only, tagged.length);
    }
  } finally { sql.close(); }
});

test('acceptance 2: caps are enforced and pages are complete and disjoint', skip, async () => {
  const {sql, as, get} = setup();
  try {
    for (const [layer, cap] of Object.entries(CAPS)) {
      assert.equal((await as(`/api/fleet/map/${layer}?region=${REGION}&limit=${cap + 1}`)).status, 400, layer);
      assert.equal((await as(`/api/fleet/map/${layer}?region=${REGION}&limit=0`)).status, 400, layer);
    }
    // Small pages walk the whole fixture once.
    for (const [layer, limit, all] of [['events', 2, ['e1', 'e2', 'e3', 'e4', 'e5']], ['tracks', 1, ['t1', 't2', 't3', 't4']], ['heat', 2, ['c1', 'c2', 'c3']]]) {
      const seen = []; let cursor = null, pages = 0;
      do {
        const page = await get(`/api/fleet/map/${layer}?region=${REGION}&limit=${limit}${cursor ? `&cursor=${cursor}` : ''}`);
        seen.push(...new Set(page.features.map(f => layer === 'tracks' ? f.properties.trip_id : f.id)));
        cursor = page.meta.next; pages++;
      } while (cursor && pages < 10);
      assert.deepEqual(seen.sort(), all, layer);
    }
    assert.equal((await as(`/api/fleet/map/events?region=${REGION}&cursor=not-a-cursor!`)).status, 400);
    assert.equal((await as(`/api/fleet/map/heat?region=${REGION}&cursor=${btoa('["x","y"]')}`)).status, 400, 'heat cursors start with a number');

    // Fill past each cap: the default page stops at the cap and offers the rest.
    const event = sql.prepare(`INSERT INTO fleet_events(id,trip_id,segment_id,vessel_id,region,kind,lat,lon,started_at,ended_at,dwell_min,season,source,rights,classifier_version)
      VALUES(?,'t1','t1-s1','v-sea-example',?,'drift-anchor',35.4,-120.95,?,?,20,'2026','aisstream','internal-only','cv-test')`);
    const trip = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,trip_type_inferred,source,rights,classifier_version,computed_at)
      VALUES(?,?,'v-sea-example','999000001',?,'2026-05-01','2026','half-day','aisstream','internal-only','cv-test',?)`);
    const segment = sql.prepare("INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at,geometry) VALUES(?,?,0,'transit',?,?,?)");
    const cell = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,kind,dwell_min,rights,computed_at)
      VALUES(?,?,'grid','{}',?,35,-121,'2026','drift-anchor',1,'internal-only',?)`);
    const line = encode([[-120.9, 35.3], [-120.91, 35.31]]);
    sql.exec('BEGIN');
    for (let i = 0; i < CAPS.events; i++) event.run(`bulk-e${String(i).padStart(5, '0')}`, REGION, '2026-05-01T12:00:00Z', '2026-05-01T12:30:00Z');
    for (let i = 0; i < CAPS.tracks; i++) { trip.run(`bulk-t${String(i).padStart(4, '0')}`, REGION, '2026-05-01T12:00:00Z', NOW); segment.run(`bulk-s${i}`, `bulk-t${String(i).padStart(4, '0')}`, NOW, NOW, line); }
    for (let i = 0; i < CAPS.heat; i++) cell.run(`bulk-c${String(i).padStart(5, '0')}`, REGION, `b:${i}`, NOW);
    sql.exec('COMMIT');
    for (const [layer, cap, total] of [['events', CAPS.events, CAPS.events + 5], ['tracks', CAPS.tracks, CAPS.tracks + 4], ['heat', CAPS.heat, CAPS.heat + 3]]) {
      const first = await get(`/api/fleet/map/${layer}?region=${REGION}`);
      const count = layer === 'tracks' ? first.meta.trips : first.features.length;
      assert.equal(count, cap, layer);
      assert.equal(first.meta.cap, cap, layer);
      assert.ok(first.meta.next, layer);
      const second = await get(`/api/fleet/map/${layer}?region=${REGION}&cursor=${first.meta.next}`);
      assert.equal((layer === 'tracks' ? second.meta.trips : second.features.length), total - cap, layer);
      assert.equal(second.meta.next, null, layer);
    }
  } finally { sql.close(); }
});

test('malformed queries answer 400', skip, async () => {
  const {sql, as} = setup();
  try {
    for (const query of ['', 'region=../x', 'region=morro-bay&bbox=1,2,3', 'region=morro-bay&bbox=-120,35,-121,36', 'region=morro-bay&bbox=-200,35,-120,36',
      'region=morro-bay&from=2026-13-01', 'region=morro-bay&from=2026-07-02&to=2026-07-01', 'region=morro-bay&season=26', 'region=morro-bay&kind=anchored',
      'region=morro-bay&source=vesselfinder', 'region=morro-bay&vessel=a;b', `region=morro-bay&port=${Array.from({length: 11}, (_, i) => 'p' + i).join(',')}`,
      'region=morro-bay&limit=ten', 'region=morro-bay&season_part=%20x'])
      for (const layer of ['events', 'tracks', 'heat']) assert.equal((await as(`/api/fleet/map/${layer}?${query}`)).status, 400, `${layer}?${query}`);
    assert.equal((await as('/api/fleet/map/filters')).status, 400);
    assert.ok('error' in mapQuery('events', {region: 'x', limit: '2001'}));
    assert.equal(mapQuery('events', {region: 'x'}).limit, 2000);
  } finally { sql.close(); }
});

test('filters lists the values present for the region', skip, async () => {
  const {sql, get} = setup();
  try {
    const filters = await get(`/api/fleet/map/filters?region=${REGION}`);
    assert.deepEqual(filters.vessels.map(v => v.id), ['v-kelp-wanderer', 'v-sea-example', 'v-tide-runner']);
    assert.deepEqual(filters.vessels[1], {id: 'v-sea-example', name: 'Sea Example', slug: 'sea-example', vessel_class: 'six-pack', port_id: 'morro-bay'});
    assert.deepEqual(filters.ports, ['morro-bay', 'port-san-luis']);
    assert.deepEqual(filters.classes, ['inspected-party', 'long-range', 'six-pack']);
    assert.deepEqual(filters.trip_types, ['full-day', 'half-day', 'multi-day']);
    assert.deepEqual(filters.kinds, ['drift-anchor', 'troll']);
    assert.deepEqual(filters.seasons, ['2026', '2025']);
    assert.deepEqual(filters.season_parts, ['fall', 'summer']);
    assert.deepEqual(filters.sources, ['aisstream', 'marinecadastre']);
    assert.deepEqual(filters.modules, ['grid']);
    assert.deepEqual(filters.dates, {min: '2025-10-05', max: '2026-09-01'});
    assert.deepEqual(filters.rights, ['internal-only', 'noaa-planning-only']);
    assert.equal(filters.planning_only_rights, 'noaa-planning-only');
    assert.deepEqual(filters.caps, {events: 2000, tracks: 300, heat: 5000});
    const empty = await get('/api/fleet/map/filters?region=elsewhere');
    assert.deepEqual([empty.vessels, empty.ports, empty.dates], [[], [], {min: null, max: null}]);
  } finally { sql.close(); }
});
