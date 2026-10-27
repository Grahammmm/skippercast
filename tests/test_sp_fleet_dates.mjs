// SP-FLEET-DATES: the public fleet heat route withholds a cell whose last_date is not a real
// YYYY-MM-DD calendar date (server/fleet/public-heat.ts publicCell). Before this, any string that
// sorted on or before the cutoff passed the 72 h delay floor: '', ' ', '2020-1-1', '2021-02-29',
// '2020-01-01T00:00:00Z' and the like. Offline: the module under test is imported directly, the D1 is
// the node:sqlite fake with the committed migrations (tests/_advisor_d1.mjs), the clock is frozen and
// every row is synthetic (no vessels, positions or feeds). fetch is a failing sentinel throughout.
import test, {after} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// Network sentinel before any import that could do IO; restored after the last test.
const realFetch = globalThis.fetch;
const fetchCalls = [];
globalThis.fetch = async (...args) => { fetchCalls.push(String(args[0])); throw new Error('network is not allowed in test_sp_fleet_dates'); };
// server/config.ts reads these globals when http.ts loads; set them like tests/test_fleet_public_heat.mjs does.
const savedGlobals = {REGIONS: globalThis.REGIONS, DEPLOYMENT: globalThis.DEPLOYMENT};
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
after(() => {
  assert.deepEqual(fetchCalls, [], 'no test reached the network');
  globalThis.fetch = realFetch;
  for (const [k, v] of Object.entries(savedGlobals)) { if (v === undefined) delete globalThis[k]; else globalThis[k] = v; }
});

const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
const {PUBLIC_HEAT, publicCutoffDate, publicCell, publicHeat, publicHeatGate, publicHeatQuery} = await import('../server/fleet/public-heat.ts');
const {fleetSettings, FLEET_DEFAULTS} = await import('../server/fleet/settings.ts');
const TOKENS = read('./fixtures/sp_fleet_dates/date_tokens.json');
const INVALID = Object.values(TOKENS.invalid).flat();

const HOUR = 3_600_000;
// Frozen clock: 2026-10-24 12:00 UTC. 72 h delay + 36 h date span = 108 h earlier is 2026-10-20 00:00 UTC.
const NOW = Date.UTC(2026, 9, 24, 12, 0, 0);
const CUTOFF = '2026-10-20';
const RIGHTS = 'api-terms';
const ok = (last_date, extra = {}) => ({vessels_n: 5, last_date, rights: RIGHTS, ...extra});
const skip = sqliteUnavailable ? {skip: sqliteUnavailable} : {};

test('A1 positive: delay, vessel floor, rights allowlist and cutoff arithmetic are unchanged', () => {
  assert.deepEqual({...PUBLIC_HEAT, rights: [...PUBLIC_HEAT.rights]},
    {min_vessels: 3, delay_hours: 72, rights: ['public-domain', 'public-record', 'facts-only', 'api-terms']});
  assert.ok(Object.isFrozen(PUBLIC_HEAT) && Object.isFrozen(PUBLIC_HEAT.rights));
  assert.equal(publicCutoffDate(NOW), CUTOFF);
  assert.equal(publicCutoffDate(NOW - 1), '2026-10-19', 'one millisecond earlier the cutoff is the day before');
  assert.equal(publicCutoffDate(Date.UTC(2026, 9, 20, 0, 0, 0) + 108 * HOUR), '2026-10-20');
  // A real date at the cutoff passes when every other gate passes; the following date fails.
  assert.equal(publicCell(ok(CUTOFF), CUTOFF), true, 'at the cutoff');
  assert.equal(publicCell(ok('2026-10-21'), CUTOFF), false, 'the day after the cutoff');
  for (const date of TOKENS.valid) assert.equal(publicCell(ok(date), CUTOFF), true, date);
  // The other floors still apply to a real date.
  assert.equal(publicCell(ok(CUTOFF, {vessels_n: 2}), CUTOFF), false, 'two vessels');
  assert.equal(publicCell(ok(CUTOFF, {vessels_n: 3}), CUTOFF), true, 'three vessels');
  assert.equal(publicCell(ok(CUTOFF, {vessels_n: 3.5}), CUTOFF), false, 'a fractional count');
  for (const rights of PUBLIC_HEAT.rights) assert.equal(publicCell(ok(CUTOFF, {rights}), CUTOFF), true, rights);
  for (const rights of ['internal-only', 'noaa-planning-only', '', 'API-TERMS']) assert.equal(publicCell(ok(CUTOFF, {rights}), CUTOFF), false, rights);
  // Whole-season cells only: a season_part query is still refused.
  assert.deepEqual(publicHeatQuery({region: 'CA', season_part: 'summer'}), {error: 'season_part is not offered: whole-season cells only'});
});

test('A1 positive: valid leap days pass within the cutoff and fail past it', () => {
  for (const day of ['2024-02-29', '2000-02-29', '2028-02-29']) {
    const nowAt = Date.parse(`${day}T00:00:00Z`) + 108 * HOUR;   // the first instant the leap day is the cutoff
    assert.equal(publicCutoffDate(nowAt), day);
    assert.equal(publicCell(ok(day), publicCutoffDate(nowAt)), true, `${day} at its cutoff`);
    assert.equal(publicCell(ok(day), publicCutoffDate(nowAt - 1)), false, `${day} one millisecond before`);
    const next = new Date(Date.parse(`${day}T00:00:00Z`) + 24 * HOUR).toISOString().slice(0, 10);
    assert.equal(publicCell(ok(next), publicCutoffDate(nowAt)), false, `${next} after the leap-day cutoff`);
  }
});

test('A2 invalid calendar: every malformed or impossible last_date string is withheld', () => {
  assert.ok(INVALID.length >= 40, 'the fixture lists the invalid tokens');
  const accepted = INVALID.filter(token => publicCell(ok(token), CUTOFF));
  assert.deepEqual(accepted, [], 'no invalid token clears the floor');
  // Not trimmed or normalized into acceptance: the same token with its padding removed is a real date that passes.
  for (const token of TOKENS.invalid['padded with whitespace']) {
    assert.equal(publicCell(ok(token), CUTOFF), false, JSON.stringify(token));
    assert.equal(publicCell(ok(token.trim()), CUTOFF), true, JSON.stringify(token.trim()));
  }
});

test('A2 invalid calendar: dates that Date.parse rolls into another day are withheld', () => {
  for (const token of TOKENS.normalized_by_date_parse) {
    const ms = Date.parse(token);
    assert.ok(Number.isFinite(ms), `${token} parses`);
    assert.notEqual(new Date(ms).toISOString().slice(0, 10), token, `${token} is normalized to another day`);
    assert.ok(token <= CUTOFF, `${token} sorts before the cutoff, so a lexical check alone would pass it`);
    assert.equal(publicCell(ok(token), CUTOFF), false, token);
  }
});

test('A2 invalid calendar: a non-string last_date is withheld', () => {
  const real = new Date(Date.UTC(2020, 0, 1));
  for (const value of [null, undefined, 20200101, 0, NaN, true, real, [CUTOFF], {toString: () => CUTOFF}, new String('2020-01-01'), Symbol.for('2020-01-01')])
    assert.equal(publicCell(ok(value), CUTOFF), false, typeof value === 'symbol' ? 'symbol' : String(value));
});

// A3/A4 rows: the committed fleet_aggregates shape (drizzle/0014_fleet_activity.sql) and the synthetic style of
// tests/test_fleet_public_heat.mjs. Every row is otherwise public: 5 vessels, api-terms, whole season, grid.
const PARAMS = '{"module":"grid","resolution_m":1000,"resolution_by_kind":{"troll-pelagic":3000},"min_distinct_vessels":null,"delay_hours":null}';
function seed(sql, rows) {
  const insert = sql.prepare(`INSERT INTO fleet_aggregates(id,region,module,params_json,cell_id,lat,lon,season,season_part,kind,vessels_n,events_n,dwell_min,
    first_date,last_date,rights,computed_at) VALUES(?,'CA','grid',?,?,?,?,'2026',NULL,'drift-anchor',5,9,?,'2026-01-01',?,?,'2026-10-01T00:00:00.000Z')`);
  for (const r of rows) insert.run(r.id, PARAMS, r.cell_id, r.lat, r.lon, r.dwell_min, r.last_date, RIGHTS);
}
// Bad dates that the SQL floor (last_date<=cutoff, a string comparison) lets through, so publicCell is the only gate.
const BAD_SQL_PASSING = ['', ' ', '2020-1-1', '2020-01-01 ', '2020-01-01T00:00:00Z', '2021-02-29', '2020-02-30', '2026-02-29'];
const FORBIDDEN = /(^|[^a-z])(vessel|mmsi|port|class|trip|event|track|name|slug|rights|id|source)([^a-z]|$)/i;
function leaks(node, where = '$', found = []) {
  if (typeof node === 'string') { if (where !== '$.meta.next' && FORBIDDEN.test(node)) found.push(`${where}=${node}`); return found; }
  if (!node || typeof node !== 'object') return found;
  for (const [key, value] of Object.entries(node)) { if (!Array.isArray(node) && FORBIDDEN.test(key)) found.push(`${where}.${key}`); leaks(value, `${where}.${key}`, found); }
  return found;
}
const query = (extra = {}) => { const q = publicHeatQuery({region: 'CA', ...extra}); assert.ok(!('error' in q), JSON.stringify(q)); return q; };

test('A3 consumer: publicHeat emits only the good row beside otherwise-qualified bad-date rows', skip, async () => {
  const {sql, db} = advisorDatabase();
  try {
    const bad = BAD_SQL_PASSING.map((last_date, i) => ({id: `bad-${i}`, cell_id: `g1000:${3790 + i}:-12010`, lat: 34.1 + i / 100, lon: -119.6, dwell_min: 900 - i, last_date}));
    seed(sql, [{id: 'good-0', cell_id: 'g1000:3780:-12000', lat: 34.0, lon: -119.5, dwell_min: 500, last_date: '2026-10-01'}, ...bad]);
    // Every bad row reaches the code: the SQL floor alone does not hide it.
    const scanned = sql.prepare("SELECT id FROM fleet_aggregates WHERE last_date IS NOT NULL AND last_date<=? ORDER BY id").all(CUTOFF).map(r => r.id);
    assert.deepEqual(scanned, [...bad.map(r => r.id), 'good-0'].sort());
    const body = await publicHeat(db, query(), NOW);
    assert.deepEqual(body.features.map(f => f.properties.dwell_min), [500], 'only the good row');
    assert.equal(body.meta.count, body.features.length);
    assert.equal(body.meta.capped, false);
    assert.equal(body.meta.next, null);
    assert.deepEqual(Object.keys(body.features[0].properties).sort(), ['basis', 'computed_at', 'dwell_min', 'kind', 'season', 'vessels_n']);
    // Omitted rows leak nothing: no id, cell or date from any bad row (their dwell is absent above); no identity keys at all.
    const text = JSON.stringify(body);
    for (const r of bad) {
      for (const value of [r.id, r.cell_id]) assert.ok(!text.includes(value), value);
      if (r.last_date.trim()) assert.ok(!text.includes(r.last_date), r.last_date);
    }
    for (const word of ['good-0', 'g1000', RIGHTS, 'last_date', 'first_date', 'cell_id', '2026-10-01"']) assert.ok(!text.includes(word), word);
    assert.deepEqual(leaks(body), []);
  } finally { sql.close(); }
});

test('A3 consumer: paging follows the scanned rows, so withheld rows never stall a page', skip, async () => {
  const {sql, db} = advisorDatabase();
  try {
    // Dwell order: good, bad, bad, bad, good, good. With limit 2 the first page ends on a withheld row and the
    // second page scans only withheld rows; next must still advance past them to the last page.
    const plan = [['g1', 600, '2026-10-01'], ['b1', 550, ''], ['b2', 500, '2021-02-29'], ['b3', 450, '2020-1-1'], ['g2', 400, '2025-12-31'], ['g3', 350, CUTOFF]];
    seed(sql, plan.map(([id, dwell_min, last_date], i) => ({id, cell_id: `g1000:${3780 + i}:-12000`, lat: 34 + i / 100, lon: -119.5, dwell_min, last_date})));
    const pages = [];
    let next = null;
    do {
      const body = await publicHeat(db, query({limit: '2', ...(next ? {cursor: next} : {})}), NOW);
      assert.equal(body.meta.count, body.features.length);
      assert.equal(body.meta.capped, body.meta.next !== null);
      pages.push(body.features.map(f => f.properties.dwell_min));
      if (body.meta.next) {
        const [dwell, key] = JSON.parse(atob(body.meta.next.replace(/-/g, '+').replace(/_/g, '/')));
        assert.ok(typeof dwell === 'number' && typeof key === 'string');
      }
      assert.notEqual(body.meta.next, next, 'the cursor advances');
      next = body.meta.next;
    } while (next && pages.length < 10);
    // Scanned pages g1+b1, b2+b3, g2+g3: the empty middle page still carries next, so no public row is lost or repeated.
    assert.deepEqual(pages, [[600], [], [400, 350]]);
  } finally { sql.close(); }
});

test('A3 consumer: both enable flags stay off by default and the gate answers 404', async () => {
  assert.deepEqual(FLEET_DEFAULTS, {enabled: false, mapEnabled: false, publicHeatEnabled: false});
  assert.deepEqual(fleetSettings(), FLEET_DEFAULTS);
  assert.deepEqual(fleetSettings({}), FLEET_DEFAULTS);
  for (const env of [{}, {FLEET_ENABLED: 'true'}, {FLEET_PUBLIC_HEAT_ENABLED: 'true'}, {FLEET_ENABLED: 'true', FLEET_PUBLIC_HEAT_ENABLED: 'yes'}]) {
    let called = false;
    const response = await publicHeatGate({env}, async () => { called = true; });
    assert.equal(called, false, JSON.stringify(env));
    assert.equal(response.status, 404, JSON.stringify(env));
  }
  let reached = false;
  await publicHeatGate({env: {FLEET_ENABLED: 'true', FLEET_PUBLIC_HEAT_ENABLED: 'true'}}, async () => { reached = true; });
  assert.equal(reached, true, 'only both flags open the route');
});

test('A4 negative control: an empty last_date with valid rights, vessels and geometry is withheld; its real-date twin is shown', skip, async () => {
  const row = {cell_id: 'g1000:3780:-12000', lat: 34.0, lon: -119.5, dwell_min: 700};
  assert.equal(publicCell(ok(''), CUTOFF), false, 'empty last_date');
  assert.equal(publicCell(ok('2026-10-01'), CUTOFF), true, 'genuine positive');
  for (const [last_date, expected] of [['', []], ['2026-10-01', [700]]]) {
    const {sql, db} = advisorDatabase();
    try {
      seed(sql, [{...row, id: 'only', last_date}]);
      assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM fleet_aggregates WHERE vessels_n>=3 AND last_date<=? AND season_part IS NULL').get(CUTOFF).n, 1,
        'no other predicate hides the row');
      const body = await publicHeat(db, query(), NOW);
      assert.deepEqual(body.features.map(f => f.properties.dwell_min), expected, JSON.stringify(last_date));
      assert.equal(body.meta.count, expected.length);
      if (expected.length) assert.equal(body.features[0].geometry.coordinates[0].length, 5, 'a closed cell ring');
    } finally { sql.close(); }
  }
});
