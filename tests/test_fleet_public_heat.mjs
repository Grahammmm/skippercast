// Charter fleet public heat route (N6; docs/plans/charter-fleet/graph.md N6, design.md § 14-16, #469 D21):
// anonymous, gated by FLEET_ENABLED and FLEET_PUBLIC_HEAT_ENABLED, cells only. Every cell has at least 3
// distinct vessels, a last date wholly at least 72 h old and allowlisted rights (never internal-only or
// noaa-planning-only). Offline, through the Worker, against the real migrations in the node:sqlite D1
// fake. The fixture is synthetic: made-up cells and positions, no vessels at all.
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
const {PUBLIC_HEAT, publicCutoffDate, publicCell} = await import('../server/fleet/public-heat.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ON = {FLEET_ENABLED: 'true', FLEET_PUBLIC_HEAT_ENABLED: 'true'};
const REGION = 'CA';
const HOUR = 3_600_000, DAY = 24 * HOUR;
const NOW = Date.now();
const skip = sqliteUnavailable ? {skip: sqliteUnavailable} : {};
const ago = ms => new Date(NOW - ms).toISOString().slice(0, 10);
const PARAMS = '{"module":"grid","resolution_m":1000,"resolution_by_kind":{"troll-pelagic":3000},"min_distinct_vessels":null,"delay_hours":null}';

// A public cell: 5 vessels, 30 days old, api-terms, whole-season, 1 km drift. Each case changes one thing and
// has its own dwell, so a feature names its case without any id in the response.
const BASE = {region: REGION, module: 'grid', cell_id: 'g1000:3780:-12000', lat: 34.0, lon: -119.5, season: '2026', season_part: null,
  kind: 'drift-anchor', vessels_n: 5, events_n: 9, dwell_min: 0, first_date: ago(40 * DAY), last_date: ago(30 * DAY), rights: 'api-terms'};
const CASES = {
  vessels1: [{vessels_n: 1}, false], vessels2: [{vessels_n: 2}, false], vessels3: [{vessels_n: 3}, true], vessels5: [{vessels_n: 5}, true],
  age1h: [{last_date: ago(HOUR)}, false], age71h: [{last_date: ago(71 * HOUR)}, false],
  // 73 h ago falls on a local date that is not yet over everywhere 72 h ago: withheld (publicCutoffDate).
  age73h: [{last_date: ago(73 * HOUR)}, false], age30d: [{last_date: ago(30 * DAY)}, true],
  atCutoff: [{last_date: publicCutoffDate(NOW)}, true], dayAfterCutoff: [{last_date: ago((PUBLIC_HEAT.delay_hours + 12) * HOUR)}, false],
  undated: [{last_date: null, first_date: null}, false],
  internal: [{rights: 'internal-only'}, false], planning: [{rights: 'noaa-planning-only'}, false],
  apiTerms: [{rights: 'api-terms'}, true], publicRecord: [{rights: 'public-record'}, true], publicDomain: [{rights: 'public-domain'}, true],
  pelagic3km: [{kind: 'troll-pelagic', cell_id: 'g3000:1260:-4000', lat: 34.01, lon: -119.48}, true],
  slow: [{kind: 'troll-slow', season: '2025', last_date: '2025-09-01', first_date: '2025-06-01'}, true],
  summerPart: [{season_part: 'summer'}, false], h3: [{module: 'h3', cell_id: '8a2a1072b59ffff'}, false], oregon: [{region: 'OR'}, false],
};
const NAMES = Object.keys(CASES);
const dwellOf = name => 1000 - NAMES.indexOf(name) * 10;
const nameOf = dwell => NAMES[(1000 - dwell) / 10];
const PUBLIC = NAMES.filter(n => CASES[n][1]);

function seed(sql) {
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-1',?,'admin')").run(new Date(NOW).toISOString());
  const cell = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,season_part,kind,vessels_n,events_n,dwell_min,
    first_date,last_date,rights,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'2026-10-01T00:00:00.000Z')`);
  NAMES.forEach((name, i) => {
    const r = {...BASE, ...CASES[name][0], dwell_min: dwellOf(name)};
    cell.run(`a${String(i).padStart(2, '0')}`, r.region, r.module, PARAMS, r.cell_id, r.lat, r.lon, r.season, r.season_part, r.kind, r.vessels_n, r.events_n,
      r.dwell_min, r.first_date, r.last_date, r.rights);
  });
}

function setup() {
  const {sql, db} = advisorDatabase(); seed(sql);
  const call = (path, env = ON, init = {}) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS, DB: db, ...env});
  const get = async path => { const r = await call(path); assert.equal(r.status, 200, `${path}: ${r.status}`); return r.json(); };
  const names = async path => (await get(path)).features.map(f => nameOf(f.properties.dwell_min));
  return {sql, db, call, get, names};
}

// Whole words in keys and strings: vessels_n and min_vessels are counts, not a vessel.
const FORBIDDEN = /(^|[^a-z])(vessel|mmsi|port|class|trip|event|track|name|slug|rights|id|source)([^a-z]|$)/i;
// The paging cursor is opaque base64 (checked by shape instead), so its letters are not read as words.
function walk(node, where, found) {
  if (typeof node === 'string') { if (where !== '$.meta.next' && FORBIDDEN.test(node)) found.push(`${where}=${node}`); return; }
  if (!node || typeof node !== 'object') return;
  for (const [key, value] of Object.entries(node)) {
    if (!Array.isArray(node) && FORBIDDEN.test(key)) found.push(`${where}.${key}`);
    walk(value, `${where}.${key}`, found);
  }
}

test('404 unless FLEET_ENABLED and FLEET_PUBLIC_HEAT_ENABLED; anonymous 200 when both are on', skip, async () => {
  const {sql, call} = setup();
  const path = `/api/fleet/public/heat?region=${REGION}`;
  try {
    const on = await call(path);
    assert.equal(on.status, 200);
    assert.equal(on.headers.get('Content-Type'), 'application/json');
    for (const env of [{}, {FLEET_ENABLED: 'true'}, {FLEET_PUBLIC_HEAT_ENABLED: 'true'}, {FLEET_ENABLED: 'true', FLEET_MAP_ENABLED: 'true'},
      {...ON, FLEET_PUBLIC_HEAT_ENABLED: 'yes'}, {...ON, FLEET_ENABLED: 'false'}]) {
      const response = await call(path, env);
      assert.equal(response.status, 404, JSON.stringify(env));
      assert.equal((await response.json()).error, 'Not found');
    }
    assert.equal((await call(path, {...ON, FLEET_MAP_ENABLED: 'false'})).status, 200, 'the admin map flag is independent');
    assert.equal((await call(path, ON, {headers: {'x-test-owner': 'admin-1'}})).status, 200);
    assert.equal((await call(path, {...ON, DB: undefined})).status, 503);
  } finally { sql.close(); }
});

test('no route under /api/fleet/public/ returns events, tracks or anything but heat', skip, async () => {
  const {sql, call} = setup();
  try {
    for (const env of [ON, {}])
      for (const path of ['/api/fleet/public/heat/anything', '/api/fleet/public/events', '/api/fleet/public/tracks', '/api/fleet/public/filters',
        '/api/fleet/public/vessels', '/api/fleet/public/', '/api/fleet/public', '/api/fleet/public/heat/', '/api/fleet/public/map/events']) {
        const response = await call(`${path}?region=${REGION}`, env);
        assert.equal(response.status, 404, `${path} ${JSON.stringify(env)}`);
        assert.equal((await response.json()).error, 'Not found');
      }
    assert.equal((await call(`/api/fleet/public/heat?region=${REGION}`, ON, {method: 'POST'})).status, 404);
    // The admin map stays admin-only: anonymous is stopped at the private gate even with every flag on.
    assert.equal((await call(`/api/fleet/map/events?region=${REGION}`, {...ON, FLEET_MAP_ENABLED: 'true'})).status, 401);
  } finally { sql.close(); }
});

test('only cells with >= 3 vessels, >= 72 h old and allowed rights come back; noaa-planning-only never', skip, async () => {
  const {sql, call, get, names} = setup();
  const q = `/api/fleet/public/heat?region=${REGION}`;
  try {
    const body = await get(q);
    assert.deepEqual(body.features.map(f => nameOf(f.properties.dwell_min)).sort(), [...PUBLIC].sort());
    const cutoff = publicCutoffDate(NOW);
    for (const f of body.features) {
      const r = {...BASE, ...CASES[nameOf(f.properties.dwell_min)][0]};
      assert.ok(f.properties.vessels_n >= 3, 'at least 3 distinct vessels');
      assert.ok(r.last_date <= cutoff, 'nothing newer than 72 h');
      // The whole last local date (to 24:00 at UTC-12) ended at least 72 h before now.
      assert.ok(Date.parse(r.last_date) + 36 * HOUR <= NOW - 72 * HOUR);
      assert.ok(PUBLIC_HEAT.rights.includes(r.rights));
    }
    const text = JSON.stringify(body);
    for (const word of ['internal-only', 'noaa-planning-only', 'api-terms', 'public-record', 'g1000', 'g3000', 'a0', 'a1']) assert.ok(!text.includes(word), word);
    // Filters: kind, season, part.
    assert.deepEqual(await names(`${q}&kind=troll-pelagic`), ['pelagic3km']);
    assert.deepEqual(await names(`${q}&season=2025`), ['slow']);
    assert.deepEqual(await names(`${q}&season=2026&kind=troll-slow`), []);
    // Whole-season cells only: a part cell never comes back, so no reader can subtract published parts from a whole
    // season to recover a withheld part's dwell. Asking for a part is refused rather than silently widened.
    for (const part of ['summer', 'all', '']) assert.equal((await call(`${q}&season_part=${part}`)).status, 400, part);
    assert.ok(!(await get(q)).features.some(f => nameOf(f.properties.dwell_min) === 'summerPart'));
    // Another region's cells only through its region.
    assert.deepEqual(await names(`/api/fleet/public/heat?region=OR`), ['oregon']);
    // The code re-checks what SQL returned.
    assert.equal(publicCell({vessels_n: 2, last_date: '2020-01-01', rights: 'api-terms'}, cutoff), false);
    assert.equal(publicCell({vessels_n: 3, last_date: null, rights: 'api-terms'}, cutoff), false);
    assert.equal(publicCell({vessels_n: 3, last_date: '2020-01-01', rights: 'noaa-planning-only'}, cutoff), false);
    assert.equal(publicCell({vessels_n: 3, last_date: ago(HOUR), rights: 'api-terms'}, cutoff), false);
    assert.equal(publicCell({vessels_n: 3, last_date: '2020-01-01', rights: 'public-domain'}, cutoff), true);
  } finally { sql.close(); }
});

test('cells only: exact feature and meta keys, and no vessel, mmsi, port, class, trip, event or track anywhere', skip, async () => {
  const {sql, get} = setup();
  try {
    for (const path of [`/api/fleet/public/heat?region=${REGION}`, `/api/fleet/public/heat?region=${REGION}&limit=2`,
      `/api/fleet/public/heat?region=${REGION}&kind=troll-pelagic`, `/api/fleet/public/heat?region=nowhere`]) {
      const body = await get(path);
      assert.deepEqual(Object.keys(body).sort(), ['features', 'meta', 'type']);
      assert.equal(body.type, 'FeatureCollection');
      assert.deepEqual(Object.keys(body.meta).sort(), ['capped', 'cell_m', 'count', 'delay_hours', 'min_vessels', 'next', 'region']);
      assert.equal(body.meta.min_vessels, 3);
      assert.equal(body.meta.delay_hours, 72);
      assert.equal(body.meta.count, body.features.length);
      for (const f of body.features) {
        assert.deepEqual(Object.keys(f).sort(), ['geometry', 'properties', 'type'], 'no feature id');
        assert.equal(f.geometry.type, 'Polygon');
        assert.deepEqual(Object.keys(f.geometry).sort(), ['coordinates', 'type']);
        assert.deepEqual(Object.keys(f.properties).sort(), ['basis', 'computed_at', 'dwell_min', 'kind', 'season', 'vessels_n']);
        assert.equal(f.properties.basis, 'inferred-from-movement');
      }
      if (body.meta.next !== null) {
        const parts = JSON.parse(atob(body.meta.next.replace(/-/g, '+').replace(/_/g, '/')));
        assert.ok(Array.isArray(parts) && parts.length === 2 && Number.isFinite(parts[0]) && typeof parts[1] === 'string', 'cursor is [dwell, row key]');
      }
      const found = [];
      walk(body, '$', found);
      assert.deepEqual(found, [], path);
    }
  } finally { sql.close(); }
});

test('the pelagic cell is a 3 km ring, the rest 1 km, and meta.cell_m reports both; the admin map draws it the same', skip, async () => {
  const {sql, get, call} = setup();
  try {
    const body = await get(`/api/fleet/public/heat?region=${REGION}`);
    assert.deepEqual(body.meta.cell_m, [1000, 3000]);
    const edge = f => { const ring = f.geometry.coordinates[0], lats = ring.map(p => p[1]); return (Math.max(...lats) - Math.min(...lats)) * 111_320; };
    for (const f of body.features) {
      const ring = f.geometry.coordinates[0];
      assert.equal(ring.length, 5);
      assert.deepEqual(ring[0], ring[4], 'closed');
      assert.ok(Math.abs(edge(f) - (f.properties.kind === 'troll-pelagic' ? 3000 : 1000)) < 1, `${f.properties.kind}: ${edge(f)}`);
    }
    assert.deepEqual((await get(`/api/fleet/public/heat?region=${REGION}&kind=drift-anchor`)).meta.cell_m, [1000]);
    const admin = await (await call(`/api/fleet/map/heat?region=${REGION}&kind=troll-pelagic`, {...ON, FLEET_MAP_ENABLED: 'true'}, {headers: {'x-test-owner': 'admin-1'}})).json();
    assert.equal(admin.features.length, 1);
    assert.ok(Math.abs(edge(admin.features[0]) - 3000) < 1);
  } finally { sql.close(); }
});

test('bad queries are 400', skip, async () => {
  const {sql, call} = setup();
  try {
    for (const query of ['', 'region=../x', `region=${REGION}&kind=transit`, `region=${REGION}&kind=uncertain`, `region=${REGION}&season=26`,
      `region=${REGION}&season_part=summer`, `region=${REGION}&limit=0`, `region=${REGION}&limit=5001`, `region=${REGION}&cursor=nope!`,
      `region=${REGION}&cursor=${btoa('["x","y"]')}`])
      assert.equal((await call(`/api/fleet/public/heat?${query}`)).status, 400, query);
  } finally { sql.close(); }
});

test('paging: limit and cursor walk every public cell once; the default page stops at 5,000 and says capped', skip, async () => {
  const {sql, get} = setup();
  try {
    const seen = [];
    let next = null, pages = 0;
    do {
      const page = await get(`/api/fleet/public/heat?region=${REGION}&limit=3${next ? `&cursor=${next}` : ''}`);
      seen.push(...page.features.map(f => nameOf(f.properties.dwell_min)));
      assert.equal(page.meta.capped, page.meta.next !== null);
      next = page.meta.next; pages++;
    } while (next && pages < 20);
    assert.deepEqual([...seen].sort(), [...PUBLIC].sort());
    assert.equal(new Set(seen).size, seen.length, 'no cell twice');

    const cell = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,kind,vessels_n,dwell_min,last_date,rights,computed_at)
      VALUES(?,?,'grid',?,?,34,-119,'2026','drift-anchor',4,1,?,'public-record','2026-10-01T00:00:00.000Z')`);
    const hidden = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,kind,vessels_n,dwell_min,last_date,rights,computed_at)
      VALUES(?,?,'grid',?,?,34,-119,'2026','drift-anchor',2,1,?,'public-record','2026-10-01T00:00:00.000Z')`);
    sql.exec('BEGIN');
    for (let i = 0; i < 5000; i++) cell.run(`bulk-${String(i).padStart(5, '0')}`, REGION, PARAMS, `g1000:${i}:0`, ago(10 * DAY));
    for (let i = 0; i < 50; i++) hidden.run(`low-${String(i).padStart(5, '0')}`, REGION, PARAMS, `g1000:${i}:1`, ago(10 * DAY));
    sql.exec('COMMIT');
    const first = await get(`/api/fleet/public/heat?region=${REGION}`);
    assert.equal(first.features.length, 5000);
    assert.equal(first.meta.capped, true);
    assert.ok(first.meta.next);
    const second = await get(`/api/fleet/public/heat?region=${REGION}&cursor=${first.meta.next}`);
    assert.equal(second.features.length, PUBLIC.length);
    assert.equal(second.meta.capped, false);
    assert.equal(second.meta.next, null);
    assert.ok([...first.features, ...second.features].every(f => f.properties.vessels_n >= 3));
  } finally { sql.close(); }
});
