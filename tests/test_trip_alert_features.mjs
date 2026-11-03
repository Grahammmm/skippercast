// SC1322-03: in checkTrip a null or non-object feature in the NWS alerts answer is an advisory of
// unknown timing (fail closed, SC1537-02); a non-array `features` is "alerts unavailable", exactly
// like a missing one. Neither throws, so the remaining trips of the page or owner are still checked.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {checkTrips} = await import('../server/index.ts');
const {checkOwnerTrips} = await import('../server/trips.ts');
const REGION = globalThis.REGIONS['morro-bay'];
const ADV = 'Applicable marine advisory', UNAVAILABLE = 'Marine advisories unavailable';
const COASTAL = REGION.marine_zones.coastal, OFFSHORE = REGION.marine_zones.offshore;
const NOW = Date.now();
const DATE = new Intl.DateTimeFormat('en-CA', {timeZone: REGION.timezone}).format(new Date(NOW + 2 * 86400000));
// Hourly gfs_global times covering the whole trip date, so advisories are judged by the saved window.
const hourly = {time: Array.from({length: 24 * 6}, (_, i) => Math.floor(NOW / 3600000) * 3600 - 86400 + i * 3600)};
const INTEL = {region_id: REGION.id, completed_at: new Date(NOW).toISOString(),
  forecast: {requested_points: REGION.forecast_points.map(p => [p.id, p.latitude, p.longitude]),
    models: {gfs_global: {data: REGION.forecast_points.map(() => ({hourly}))}}}};
// Readable times well before (PAST) or across (SPAN) the trip date.
const PAST = {event: 'Small Craft Advisory', onset: '2000-01-01T00:00:00Z', ends: '2000-01-02T00:00:00Z'};
const SPAN = {event: 'Small Craft Advisory', onset: new Date(NOW - 86400000).toISOString(), ends: new Date(NOW + 5 * 86400000).toISOString()};

function database(trips) {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; },
    async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
  async batch(queries) { sql.exec('BEGIN'); try { const result = []; for (const q of queries) result.push(await q.run()); sql.exec('COMMIT'); return result; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  for (const [id, point] of trips) sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
    .run(id, 'alice', 'morro-bay', point, 'reef', DATE, 7, 13, 8, 12, 3, new Date(NOW).toISOString());
  return {sql, adapter};
}

// Run one checkTrips page (or the owner's queue unit) with the NWS answer per zone; returns the result and each trip's assessment.
async function run(answers, {trips = [['trip-1', 'north']], owner = false} = {}) {
  const {sql, adapter} = database(trips), original = globalThis.fetch;
  globalThis.fetch = async url => {
    const u = new URL(String(url));
    if (u.hostname === 'api.weather.gov') { const body = answers[u.searchParams.get('zone')]; return body === undefined ? Response.json({}, {status: 503}) : Response.json(body); }
    return String(url) === REGION.intelligence_feed ? Response.json(INTEL) : Response.json({}, {status: 503});
  };
  try {
    const result = owner ? await checkOwnerTrips({DB: adapter}, 'alice', NOW, new Map()) : await checkTrips({DB: adapter});
    const assessed = Object.fromEntries(sql.prepare('SELECT id,last_assessment FROM trips ORDER BY id').all().map(r => [r.id, JSON.parse(r.last_assessment)]));
    return {result, assessed};
  } finally { globalThis.fetch = original; sql.close(); }
}
const coastal = async body => (await run({[COASTAL]: body})).assessed['trip-1'];
const show = v => JSON.stringify(v) ?? 'undefined';

test('control: readable advisories are judged by their times, an empty list and a missing answer are unchanged', async () => {
  const past = await coastal({features: [{properties: PAST}]});
  assert.ok(!past.issues.includes(ADV) && !past.issues.includes(UNAVAILABLE), past.issues.join('; '));
  assert.ok((await coastal({features: [{properties: SPAN}]})).issues.includes(ADV));
  const none = await coastal({features: []});
  assert.ok(!none.issues.includes(ADV) && !none.issues.includes(UNAVAILABLE));
  const missing = await coastal({});
  assert.ok(missing.issues.includes(UNAVAILABLE) && !missing.issues.includes(ADV));
});

test('features: [null] is an advisory of unknown timing (same as a garbled time), no throw', async () => {
  const garbled = await coastal({features: [{properties: {...PAST, onset: 'not a date'}}]});
  assert.equal(garbled.status, 'unverified');
  assert.ok(garbled.issues.includes(ADV));
  const out = await coastal({features: [null]});
  assert.equal(out.status, garbled.status);
  assert.deepEqual(out.issues, garbled.issues);
  assert.equal(out.issues.filter(s => s === ADV).length, 1);
  assert.ok(!out.issues.includes(UNAVAILABLE));
});

test('features: [1, "x", []] and objects without properties count as null entries', async () => {
  const nul = await coastal({features: [null]});
  for (const features of [[1, 'x', []], [1], ['x'], [[]], [[{properties: PAST}]], [true], [{}], [{properties: null}]]) {
    const out = await coastal({features});
    assert.equal(out.status, nul.status, show(features));
    assert.deepEqual(out.issues, nul.issues, show(features));
  }
});

test('a non-array features ({} or "x" or a number) is alerts unavailable, same as features missing', async () => {
  const missing = await coastal({});
  assert.ok(missing.issues.includes(UNAVAILABLE));
  for (const features of [{}, 'x', {0: null, length: 1}, 7, null]) {
    const out = await coastal({features});
    assert.equal(out.status, missing.status, show(features));
    assert.deepEqual(out.issues, missing.issues, show(features));
  }
});

test('a valid feature is assessed by its times; a null one next to it fails closed', async () => {
  assert.ok(!(await coastal({features: [{properties: PAST}]})).issues.includes(ADV), 'the readable past advisory alone does not apply');
  for (const features of [[{properties: PAST}, null], [null, {properties: PAST}], [{properties: PAST}, 'x']]) {
    const out = await coastal({features});
    assert.equal(out.status, 'unverified', show(features));
    assert.ok(out.issues.includes(ADV) && !out.issues.includes(UNAVAILABLE), show(features));
  }
});

test('a broken alerts answer for the first trip does not stop the next trip of the page or owner', async () => {
  // trip-a is offshore (PZZ670, broken answer); trip-b is coastal (PZZ645, a readable empty list).
  const trips = [['trip-a', 'offshore-0-0'], ['trip-b', 'north']];
  for (const broken of [{features: [null]}, {features: [1, 'x', []]}, {features: 'x'}, {features: {}}])
    for (const owner of [false, true]) {
      const label = show(broken) + (owner ? ' checkOwnerTrips' : ' checkTrips');
      const {result, assessed} = await run({[OFFSHORE]: broken, [COASTAL]: {features: []}}, {trips, owner});
      assert.equal(result.checked, 2, label);
      assert.equal(result.changes, 2, label);
      assert.equal(result.in_app, 2, label);
      assert.equal(assessed['trip-a'].status, 'unverified', label);
      assert.ok(assessed['trip-a'].issues.includes(Array.isArray(broken.features) ? ADV : UNAVAILABLE), label);
      assert.ok(!assessed['trip-b'].issues.includes(ADV) && !assessed['trip-b'].issues.includes(UNAVAILABLE), label);
    }
});
