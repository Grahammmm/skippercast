// SP-13-v2 / SP1305-AIS-FUTURE-MESSAGE; synthetic producer-shaped inputs only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/sp1305_ais_future_message/inputs.json', import.meta.url)));
const NOW = new Date(fixture.now);
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
globalThis.BUILD_ID = 'sp1305-test';
const {aisHealth, STALE_S} = await import('../server/fleet/admin/ais-health.ts');
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

function store(lastMessage = fixture.heartbeat.last_message_at) {
  const {sql, db} = advisorDatabase();
  const state = sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)');
  const beat = {...fixture.heartbeat, last_message_at: lastMessage};
  state.run('fleet.ais.CA.heartbeat', JSON.stringify(beat), fixture.pushed_at);
  state.run('fleet.ais.CA.processed', JSON.stringify({at: fixture.pushed_at, run_id: 'synthetic-run', counts: {hours: 2}}), fixture.pushed_at);
  const hour = sql.prepare('INSERT INTO fleet_ais_hours(region,hour,messages,watched_messages,vessels,reconnects,max_gap_s,dropped) VALUES(?,?,?,?,?,?,?,?)');
  hour.run('CA', '2026-10-05T11:00:00.000Z', 100, 10, 5, 1, 900, 2);
  hour.run('CA', '2026-10-05T10', 200, 20, 6, 0, 120, 0);
  const watch = sql.prepare('INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)');
  for (const [mmsi, status] of [['999000101', 'watched'], ['999000102', 'watched'], ['999000109', 'candidate'], ['999000108', 'rejected']]) {
    watch.run('CA', mmsi, null, 'ais-static-name', 0.5, status, fixture.pushed_at, fixture.pushed_at, fixture.pushed_at);
  }
  return {sql, db};
}
function snapshot(sql) {
  return ['job_state', 'fleet_ais_hours', 'fleet_ais_watch'].map(table => sql.prepare(`SELECT * FROM ${table} ORDER BY 1,2`).all());
}
function invariants(r) {
  assert.equal(r.region, 'CA');
  assert.deepEqual(r.heartbeat, {written_at: fixture.heartbeat.written_at, pushed_at: fixture.pushed_at, age_s: 60, connected: true, source: 'aisstream', git_sha: 'abc1234'});
  assert.equal(r.heartbeat_unreadable, false);
  assert.deepEqual(r.processor, {last_run_at: fixture.pushed_at, age_s: 1590});
  assert.equal(r.messages_per_min, 412);
  assert.equal(r.watched_messages_per_min, 9);
  assert.deepEqual(r.watch, {watched: 2, candidates: 1, listener: 2});
  assert.deepEqual(r.last_24h, {messages: 300, reconnects: 1, dropped: 2, hours_reported: 2});
  assert.deepEqual(r.uptime, {d7: {pct: 1.2, up_hours: 2, hours: 168}, d30: {pct: 0.3, up_hours: 2, hours: 720}});
  assert.deepEqual(r.gaps, [{hour: '2026-10-05T11', max_gap_s: 900}]);
  assert.deepEqual(r.outages, [{from: '2026-09-28T12', to: '2026-10-05T09', hours: 166}]);
  assert.equal(r.hours_24.length, 24);
  assert.equal(r.hours_24.at(-1).messages, 100);
}
function withoutMessage(r) {
  const {last_message_at, last_message_age_s, stale, ...rest} = r;
  return rest;
}

test('primary regression', async t => {
  const {sql, db} = store(fixture.future);
  try {
    const before = snapshot(sql);
    const report = await aisHealth(db, 'CA', NOW), r = report.regions[0];
    // Keep baseline observations BEFORE the deliberately red semantic assertion.
    t.diagnostic('observed ' + JSON.stringify({last_message_at: r.last_message_at, last_message_age_s: r.last_message_age_s, stale: r.stale}));
    assert.equal(report.checked_at, fixture.now);
    assert.equal(report.regions.length, 1);
    assert.equal(r.last_message_at, fixture.future);
    invariants(r);
    assert.deepEqual(snapshot(sql), before);
    assert.equal(r.last_message_age_s, null, 'future message must have unknown age');
    assert.equal(r.stale, true);
  } finally { sql.close(); }
});

test('healthy control', async () => {
  const {sql, db} = store();
  try {
    const before = snapshot(sql), r = (await aisHealth(db, 'CA', NOW)).regions[0];
    assert.equal(r.last_message_at, fixture.heartbeat.last_message_at);
    assert.equal(r.last_message_age_s, 300);
    assert.equal(r.stale, false);
    invariants(r);
    assert.deepEqual(snapshot(sql), before);
  } finally { sql.close(); }
});

// Baseline registers exactly A4's pair, not a larger suite filtered into skips.
if (process.env.SP1305_SUITE !== 'baseline') {
  test('A2 future instants offsets flooring and exact stale threshold', async () => {
    assert.equal(STALE_S, 10800);
    assert.equal(Date.parse(fixture.cases[2][1]), Date.parse(fixture.future));
    assert.equal(Date.parse(fixture.cases[3][1]), Date.parse(fixture.future));
    for (const [name, value, age, stale] of fixture.cases) {
      const {sql, db} = store(value);
      try {
        const before = snapshot(sql), r = (await aisHealth(db, 'CA', NOW)).regions[0];
        assert.equal(r.last_message_at, value, name);
        assert.equal(r.last_message_age_s, age, name);
        assert.equal(r.stale, stale, name);
        invariants(r);
        assert.deepEqual(snapshot(sql), before, name);
      } finally { sql.close(); }
    }
  });
  test('A2 missing null non-string and malformed clocks preserve a healthy peer', async () => {
    for (const value of [undefined, null, 42, false, {}, [], '', 'not-a-date']) {
      const {sql, db} = store();
      try {
        sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)').run('fleet.ais.OR.heartbeat', JSON.stringify({...fixture.heartbeat, last_message_at: value}), fixture.pushed_at);
        const before = snapshot(sql), report = await aisHealth(db, null, NOW);
        assert.deepEqual(report.regions.map(r => r.region), ['CA', 'OR']);
        const [healthy, invalid] = report.regions;
        assert.equal(healthy.last_message_age_s, 300);
        assert.equal(healthy.stale, false);
        invariants(healthy);
        assert.equal(invalid.last_message_at, typeof value === 'string' ? value : null);
        assert.equal(invalid.last_message_age_s, null);
        assert.equal(invalid.stale, true);
        assert.deepEqual(snapshot(sql), before);
      } finally { sql.close(); }
    }
  });
  test('A2 shared heartbeat and processor future-age behavior stays unchanged', async () => {
    const {sql, db} = store();
    try {
      sql.prepare('UPDATE job_state SET value=? WHERE key=?').run(JSON.stringify({...fixture.heartbeat, written_at: fixture.future}), 'fleet.ais.CA.heartbeat');
      sql.prepare('UPDATE job_state SET updated_at=? WHERE key=?').run(fixture.future, 'fleet.ais.CA.processed');
      const r = (await aisHealth(db, 'CA', NOW)).regions[0];
      assert.equal(r.heartbeat.age_s, 0);
      assert.equal(r.processor.age_s, 0);
      assert.equal(r.last_message_age_s, 300);
      assert.equal(r.stale, false);
    } finally { sql.close(); }
  });
  test('A3 admin route preserves stores reports and authorization gates', async () => {
    const {sql, db} = store();
    try {
      const admin = 'sp1305-synthetic-admin', origin = 'https://fleet.example.com';
      sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(admin, fixture.pushed_at);
      const assets = {fetch: async () => new Response('synthetic asset', {status: 299})};
      const path = '/api/admin/fleet/ais/health?region=CA';
      const request = (owner = admin) => new Request(origin + path, {headers: owner ? {'x-test-owner': owner} : {}});
      const env = {ASSETS: assets, DB: db, FLEET_ENABLED: 'true', IDENTITY_PROVIDER: 'skippercast'};
      // Prepare synthetic sessions separately, then exclude all writes while the
      // actual health handler runs. No fixture preparation is called a handler write.
      const sessionOnly = withSessions({fetch: async req => req});
      const signed = await sessionOnly.fetch(request(), env);
      await sessionOnly.fetch(request('sp1305-synthetic-nonadmin'), env);
      const healthDb = {prepare(query) {
        assert.match(query.trim(), /^SELECT\b/i, 'health handler must only read D1');
        return db.prepare(query);
      }};
      const before = snapshot(sql);
      const healthyResponse = await deployed.fetch(signed.clone(), {...env, DB: healthDb});
      assert.equal(healthyResponse.status, 200);
      assert.equal(healthyResponse.headers.get('Cache-Control'), 'no-store');
      const healthy = await healthyResponse.json();
      assert.equal(healthy.checked_at, fixture.now);
      invariants(healthy.regions[0]);
      assert.equal(healthy.regions[0].last_message_age_s, 300);
      assert.equal(healthy.regions[0].stale, false);
      assert.deepEqual(snapshot(sql), before);
      sql.prepare('UPDATE job_state SET value=? WHERE key=?').run(JSON.stringify({...fixture.heartbeat, last_message_at: fixture.future}), 'fleet.ais.CA.heartbeat');
      const futureBefore = snapshot(sql);
      const response = await deployed.fetch(signed.clone(), {...env, DB: healthDb});
      assert.equal(response.status, 200);
      const future = await response.json();
      assert.equal(future.regions[0].last_message_at, fixture.future);
      assert.equal(future.regions[0].last_message_age_s, null);
      assert.equal(future.regions[0].stale, true);
      assert.deepEqual(withoutMessage(future.regions[0]), withoutMessage(healthy.regions[0]));
      assert.deepEqual(snapshot(sql), futureBefore);
      assert.equal((await worker.fetch(request('sp1305-synthetic-nonadmin'), env)).status, 404);
      assert.equal((await worker.fetch(request(), {...env, FLEET_ENABLED: 'false'})).status, 404);
      assert.equal((await worker.fetch(request(), {...env, FLEET_ENABLED: undefined, TEXT_ADVISOR_ENABLED: 'true'})).status, 404);
      assert.ok([401, 404].includes((await worker.fetch(request(null), env)).status));
    } finally { sql.close(); }
  });
}
