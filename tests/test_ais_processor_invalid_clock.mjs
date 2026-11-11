// RF0725-10: an unparseable processor clock stays unknown (processor:null), never age zero. Synthetic rows only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const NOW = new Date('2026-10-05T12:30:00.000Z');
// Test-only decision-clock seam precedes Worker imports, including bound defaults.
const RealDate = globalThis.Date;
globalThis.Date = class extends RealDate {
  constructor(...args) { super(...(args.length ? args : [NOW.getTime()])); }
  static now() { return NOW.getTime(); }
};
const previous = Object.fromEntries(['REGIONS', 'DEPLOYMENT', 'SHELLS', 'BUILD_ID'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'rf0725-10-test';
const {aisHealth} = await import('../server/fleet/admin/ais-health.ts');
const {default: deployed} = await import('../server/index.ts');
const worker = withSessions(deployed);
test.after(() => {
  globalThis.Date = RealDate;
  for (const [key, descriptor] of Object.entries(previous)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});
if (sqliteUnavailable) throw new Error(sqliteUnavailable); // Never turn missing infrastructure into a pass/skip.

const BEAT = {written_at: '2026-10-05T12:29:00.000Z', last_message_at: '2026-10-05T12:25:00.000Z', connected: true, source: 'aisstream', git_sha: 'abc1234'};
function store(clocks) {   // clocks: {REGION: processed updated_at | undefined (no row)}
  const {sql, db} = advisorDatabase();
  const state = sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)');
  for (const [region, clock] of Object.entries(clocks)) {
    state.run(`fleet.ais.${region}.heartbeat`, JSON.stringify(BEAT), '2026-10-05T12:29:30.000Z');
    if (clock !== undefined) state.run(`fleet.ais.${region}.processed`, '{}', clock);
  }
  return {sql, db};
}
const snapshot = sql => ['job_state', 'fleet_ais_hours', 'fleet_ais_watch'].map(t => sql.prepare(`SELECT * FROM ${t} ORDER BY 1,2`).all());
const processorOf = async (clock) => {
  const {sql, db} = store({CA: clock});
  try {
    const before = snapshot(sql), r = (await aisHealth(db, 'CA', NOW)).regions[0];
    assert.ok(isDeepStrictEqual(snapshot(sql), before), 'aisHealth must not write');
    return r;
  } finally { sql.close(); }
};
const without = r => { const {processor, ...rest} = r; return rest; };

test('unparseable_processed_clock_is_unknown', async () => {
  for (const clock of ['not-a-date', '']) assert.equal((await processorOf(clock)).processor, null, JSON.stringify(clock));
});
test('absent_processed_row_stays_unknown', async () => {
  const r = await processorOf(undefined);
  assert.equal(r.processor, null);
  assert.equal(r.heartbeat.age_s, 60);
});
test('valid_zero_is_not_missing', async () => {
  for (const clock of ['2026-10-05T12:30:00.000Z', '2026-10-05T12:29:59.500Z'])
    assert.ok(isDeepStrictEqual((await processorOf(clock)).processor, {last_run_at: clock, age_s: 0}), clock);
});
test('valid_past_clock_keeps_floor_and_literal', async () => {
  const clock = '2026-10-05T12:03:30.000Z';
  assert.ok(isDeepStrictEqual((await processorOf(clock)).processor, {last_run_at: clock, age_s: 1590}));
});
test('future_clamp_is_unchanged', async () => {
  const clock = '2026-10-06T12:30:00.000Z';
  assert.ok(isDeepStrictEqual((await processorOf(clock)).processor, {last_run_at: clock, age_s: 0}));
});
test('malformed_region_does_not_poison_peer', async () => {
  const {sql, db} = store({CA: '2026-10-05T12:03:30.000Z', OR: 'not-a-date'});
  try {
    const before = snapshot(sql), report = await aisHealth(db, null, NOW);
    assert.deepEqual(report.regions.map(r => r.region), ['CA', 'OR']);
    const [healthy, bad] = report.regions;
    assert.ok(isDeepStrictEqual(healthy.processor, {last_run_at: '2026-10-05T12:03:30.000Z', age_s: 1590}));
    assert.equal(bad.processor, null);
    assert.equal(bad.heartbeat.age_s, healthy.heartbeat.age_s);
    assert.ok(isDeepStrictEqual(snapshot(sql), before));
  } finally { sql.close(); }
});
test('admin_route_preserves_gates_and_state', async () => {
  const {sql, db} = store({CA: 'not-a-date'});
  try {
    const admin = 'rf0725-10-synthetic-admin', origin = 'https://fleet.example.com';
    sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(admin, '2026-10-05T12:00:00.000Z');
    const assets = {fetch: async () => new Response('synthetic asset', {status: 299})};
    const request = (owner = admin) => new Request(origin + '/api/admin/fleet/ais/health?region=CA', {headers: owner ? {'x-test-owner': owner} : {}});
    const env = {ASSETS: assets, DB: db, FLEET_ENABLED: 'true', IDENTITY_PROVIDER: 'skippercast'};
    // Prepare sessions before the snapshot so setup is not counted as a handler write.
    const signed = await withSessions({fetch: async req => req}).fetch(request(), env);
    await withSessions({fetch: async req => req}).fetch(request('rf0725-10-synthetic-nonadmin'), env);
    const healthDb = {prepare(query) {
      assert.match(query.trim(), /^SELECT\b/i, 'health handler must only read D1');
      return db.prepare(query);
    }};
    const before = snapshot(sql);
    const response = await deployed.fetch(signed.clone(), {...env, DB: healthDb});
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    const body = await response.json();
    assert.equal(body.regions[0].processor, null);
    assert.ok(isDeepStrictEqual(snapshot(sql), before), 'route must not write');
    // Control: the same state with a valid clock differs only in the processor projection.
    sql.prepare('UPDATE job_state SET updated_at=? WHERE key=?').run('2026-10-05T12:03:30.000Z', 'fleet.ais.CA.processed');
    const control = await (await deployed.fetch(signed.clone(), {...env, DB: healthDb})).json();
    assert.ok(isDeepStrictEqual(control.regions[0].processor, {last_run_at: '2026-10-05T12:03:30.000Z', age_s: 1590}));
    assert.ok(isDeepStrictEqual(without(body.regions[0]), without(control.regions[0])));
    assert.equal((await worker.fetch(request('rf0725-10-synthetic-nonadmin'), env)).status, 404);
    assert.equal((await worker.fetch(request(), {...env, FLEET_ENABLED: 'false'})).status, 404);
  } finally { sql.close(); }
});
