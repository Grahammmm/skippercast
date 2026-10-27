import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
// Block fetch (including HTTP model calls) before product import and in every case.
// Storage is the injected, migration-backed in-memory D1; no live bindings are supplied.
const savedFetch = globalThis.fetch;
const denyFetch = async () => { throw new Error('network sentinel: unexpected fetch'); };
globalThis.fetch = denyFetch;
const {watchUpdate, watchDeps} = await import('../server/fleet/watch.ts');
const savedNow = watchDeps.now;
const NOW = '2026-10-25T12:00:00.000Z';
const LATER = '2026-10-25T12:30:00.000Z';
let clock = NOW;
test.beforeEach(async () => {
  globalThis.fetch = denyFetch;
  clock = NOW;
  watchDeps.now = () => new Date(clock);
  await assert.rejects(globalThis.fetch('https://skippercast.invalid/sentinel-control'), /network sentinel: unexpected fetch/);
});
test.afterEach(() => {
  globalThis.fetch = savedFetch;
  watchDeps.now = savedNow;
});
test.after(() => {
  globalThis.fetch = savedFetch;
  watchDeps.now = savedNow;
});

const REGION = 'CA';
const RUN_ID = 'ais-20261025T120000Z';
const isoGood = '2026-02-28T00:00:00.000Z';
const row = (mmsi, extra = {}) => ({
  mmsi, vessel_id: null, match_method: 'ais-static-name', confidence: 0.7,
  status: 'candidate', ais_name: null, ais_call_sign: null, ais_class: null,
  first_seen_at: isoGood, last_seen_at: isoGood, last_seen_source: null,
  positions_30d: 0, ...extra,
});
async function submit(db, rows) {
  return watchUpdate(db, new Request('https://skippercast.invalid/api/fleet/jobs/watch', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({region: REGION, run_id: RUN_ID, rows}),
  }));
}
function setup() {
  const {sql, db} = advisorDatabase();
  let prewrites = 0;
  const wrapped = {
    prepare(...args) { prewrites++; return db.prepare(...args); },
    batch(...args) { prewrites++; return db.batch(...args); },
  };
  return {sql, db: wrapped, count: () => prewrites};
}

const fixtures = read('./fixtures/sp1411_watch_calendar/cases.json');
const baselineOnly = process.env.SP1411_BASELINE === '1';
const invalidTimestampCases = fixtures.invalid_timestamps;

// A4: this exact primary assertion is expected to fail on the pinned baseline.
test('primary regression: February 30 is rejected before any database operation', {skip: sqliteUnavailable ?? false}, async () => {
  const {sql, db, count} = setup();
  try {
    const result = await submit(db, [row('999000201', {first_seen_at: '2026-02-30T00:00:00.000Z', last_seen_at: '2026-02-30T00:00:00.000Z'})]);
    assert.equal(result.status, 400);
    assert.equal(result.body.error, 'rows[0].first_seen_at: invalid');
    assert.equal(count(), 0, 'invalid timestamp must be rejected before database access');
  } finally { sql.close(); }
});

test('healthy control: canonical February 28 timestamp is accepted unchanged', {skip: sqliteUnavailable ?? false}, async () => {
  const {sql, db} = setup();
  try {
    const result = await submit(db, [row('999000202')]);
    assert.equal(result.status, 200, JSON.stringify(result.body));
    assert.equal(sql.prepare('SELECT first_seen_at FROM fleet_ais_watch WHERE mmsi=?').get('999000202').first_seen_at, isoGood);
  } finally { sql.close(); }
});

if (!baselineOnly) test('watchUpdate rejects impossible first and last sightings atomically before prepares', {skip: sqliteUnavailable ?? false}, async () => {
  const {sql, db, count} = setup();
  try {
    assert.equal((await submit(db, [row('999000210')])).status, 200);
    const previous = sql.prepare('SELECT * FROM fleet_ais_watch WHERE mmsi=?').get('999000210');
    for (const {field, value} of invalidTimestampCases) {
      const before = count();
      const badRow = field === 'first_seen_at' ? row('999000210', {[field]: value, last_seen_at: value}) : row('999000210', {[field]: value});
      const result = await submit(db, [badRow]);
      assert.equal(result.status, 400, `${field} ${value}`);
      assert.equal(result.body.error, `rows[0].${field}: invalid`);
      assert.equal(count(), before, 'must reject before D1 access');
      assert.deepEqual(sql.prepare('SELECT * FROM fleet_ais_watch WHERE mmsi=?').get('999000210'), previous);
    }
    const before = count();
    const mixed = await submit(db, [row('999000211'), row('999000212', {last_seen_at: '2026-04-31T00:00:00.000Z'})]);
    assert.equal(mixed.status, 400);
    assert.equal(count(), before);
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_ais_watch WHERE mmsi IN (?,?)').get('999000211', '999000212').n, 0);
  } finally { sql.close(); }
});

if (!baselineOnly) test('canonical timestamps, leap day, precision, ordering and replay remain compatible', {skip: sqliteUnavailable ?? false}, async () => {
  const {sql, db} = setup();
  try {
    const [same, early, late] = fixtures.valid_timestamps;
    const valid = [
      row('999000220', {first_seen_at: same, last_seen_at: same}),
      row('999000221', {first_seen_at: early, last_seen_at: late}),
    ];
    assert.equal((await submit(db, valid)).status, 200);
    const snapshot = sql.prepare('SELECT mmsi,first_seen_at,last_seen_at,updated_at FROM fleet_ais_watch ORDER BY mmsi').all();
    assert.ok(snapshot.every(stored => stored.updated_at === NOW));
    clock = LATER;
    assert.equal((await submit(db, valid)).body.changed, 0);
    assert.deepEqual(sql.prepare('SELECT mmsi,first_seen_at,last_seen_at,updated_at FROM fleet_ais_watch ORDER BY mmsi').all(), snapshot);
    for (const invalid of fixtures.unsupported_formats) {
      assert.equal((await submit(db, [row('999000222', {first_seen_at: invalid})])).status, 400, invalid);
    }
  } finally { sql.close(); }
});