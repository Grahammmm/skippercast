// Charter fleet coverage and AIS health (CF-35; docs/plans/charter-fleet/design.md § 13).
// The report functions run against the real migrations (tests/_advisor_d1.mjs) on a fixed
// clock, and the routes through the Worker with the test session helper. Synthetic
// vessels, example.com URLs and 999xxxxxx MMSIs only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: deployed} = await import('../server/index.ts');
const {coverageReport, pct} = await import('../server/fleet/admin/coverage.ts');
const {aisHealth, hourKey} = await import('../server/fleet/admin/ais-health.ts');
const worker = withSessions(deployed);

const skip = sqliteUnavailable ?? false;
const ORIGIN = 'https://skippercast.com', ADMIN = 'admin-fleet-35';
const ASSETS = {fetch: async () => new Response('asset', {status: 299})};
const ON = {FLEET_ENABLED: 'true'};
const NOW = new Date('2026-10-05T12:30:00.000Z'), T0 = '2026-09-01T00:00:00.000Z';
const id = n => String(n).repeat(32).slice(0, 32);

function seedRegistry(sql) {
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,vessel_class,waters_json,uscg_doc,mmsi,length_ft,passengers_max,website,
    status,completeness,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
  const v = (n, region, port, cls, extra) => vessel.run(id(n), region, `test-boat-${n}`, `Test Boat ${n}`, `TESTBOAT${n}`, port, cls, extra.waters ?? null,
    extra.doc ?? null, extra.mmsi ?? null, extra.length ?? null, extra.pax ?? null, extra.website ?? null, extra.status ?? 'active', extra.completeness ?? 0, T0, T0, T0, T0);
  v(1, 'CA', 'morro-bay', 'six-pack', {waters: '[]', doc: '1234567', mmsi: '999000001', website: 'https://boat1.example.com/', completeness: 0.4});
  v(2, 'CA', 'morro-bay', 'six-pack', {completeness: 0.1});
  v(3, 'CA', 'morro-bay', 'inspected-party', {mmsi: '999000003', length: 65, pax: 40, completeness: 0.3});
  v(4, 'CA', 'avila', null, {completeness: 0});
  v(5, 'CA', 'morro-bay', 'six-pack', {mmsi: '999000005', status: 'excluded', completeness: 1});
  v(6, 'OR', 'newport', 'six-pack', {mmsi: '999000006', completeness: 0.5});
  const fact = sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,
    first_seen_at,last_seen_at,superseded_at,run_id) VALUES(?,?,?,?,?,?,?,?,0.8,'facts-only',?,?,?,?,?)`);
  let n = 0;
  const f = (vessel, source, superseded = null) => fact.run(String(++n).padStart(32, 'f'), id(vessel), 'name', '"x"', 'k'.repeat(16), source,
    source === 'admin' ? 'admin:someone' : `https://${source}.example.com/`, source === 'admin' ? 'admin' : source === 'aisstream' ? 'ais' : 'page', T0, T0, T0, superseded, source === 'admin' ? null : 'run-1');
  f(1, 'fcc-uls'); f(1, 'operator-site'); f(1, 'operator-site');
  f(2, 'teck-directory'); f(2, 'admin');                      // an admin fact is not a source
  f(2, 'aisstream');                                          // nor is an AIS fact (method 'ais', CF-46)
  f(3, 'landing-pages'); f(3, 'uscg-psix', T0);               // a superseded fact is not current
  f(6, 'fcc-uls');
  const watch = sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`);
  watch.run('CA', '999000001', id(1), 'fcc-uls', 0.9, 'watched', T0, '2026-10-01T10:00:00.000Z', T0);       // seen in 30 days
  watch.run('CA', '999000003', id(3), 'fcc-uls', 0.9, 'watched', T0, '2026-08-01T10:00:00.000Z', T0);       // watched, last heard 65 days ago
  watch.run('CA', '999000004', id(4), 'ais-static-name', 0.5, 'candidate', T0, '2026-10-04T10:00:00.000Z', T0);   // a candidate is not "seen"
  const run = sql.prepare('INSERT INTO fleet_runs(id,region,step,sink,started_at,finished_at,status,counts_json,error) VALUES(?,?,?,?,?,?,?,?,?)');
  run.run('r1:ingest', 'CA', 'ingest', 'worker', '2026-10-01T00:00:00.000Z', '2026-10-01T00:10:00.000Z', 'ok', '{"ops":12}', null);
  run.run('r2:ingest', 'CA', 'ingest', 'worker', '2026-10-04T00:00:00.000Z', null, 'failed', null, 'timeout');
  run.run('r3:ingest', 'OR', 'ingest', 'worker', '2026-10-05T00:00:00.000Z', null, 'running', null, null);
}

test('acceptance 1: coverage percentages by port and class match hand-computed values', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  seedRegistry(sql);
  const r = await coverageReport(db, 'CA', NOW);
  // Active CA vessels 1-4 (5 is excluded, 6 is OR). MMSI: 1, 3. Seen: 1 only. Sources: 1 → 2, 2 → 1, 3 → 1, 4 → 0.
  assert.deepEqual(r.totals.mmsi, {n: 2, pct: 50});
  assert.deepEqual(r.totals.ais, {seen: 1, not_seen: 3, seen_pct: 25});
  assert.equal(r.totals.boats, 4);
  assert.equal(r.totals.single_source, 2);
  assert.deepEqual(r.sources_per_boat, {'0': 1, '1': 2, '2': 1, '3+': 0});
  // Mean completeness (0.4+0.1+0.3+0)/4 = 20%. Groups: identity 7/16 (waters '[]' is empty), registry 3/20, specs 2/24, contact 1/20.
  assert.deepEqual(r.totals.completeness, {mean_pct: 20, groups: {identity: 43.8, registry: 15, specs: 8.3, contact: 5}});
  assert.deepEqual(r.ports.map(p => [p.region, p.port_id, p.boats, p.mmsi.pct, p.ais.seen_pct, p.single_source]),
    [['CA', 'avila', 1, 0, 0, 0], ['CA', 'morro-bay', 3, 66.7, 33.3, 2]]);
  const morro = r.ports[1];
  assert.deepEqual(morro.classes.map(c => [c.vessel_class, c.boats, c.mmsi.pct, c.ais.seen, c.ais.not_seen, c.ais.seen_pct, c.completeness.groups.specs]),
    [['inspected-party', 1, 100, 0, 1, 0, 33.3], ['six-pack', 2, 50, 1, 1, 50, 0]]);
  assert.deepEqual(r.ports[0].classes.map(c => c.vessel_class), [null]);
  assert.deepEqual(r.single_source.map(s => [s.id, s.source_id, s.ais]).sort(), [[id(2), 'teck-directory', 'not-seen'], [id(3), 'landing-pages', 'not-seen']]);
  assert.deepEqual(r.runs.map(x => [x.id, x.status, x.counts]), [['r2:ingest', 'failed', null], ['r1:ingest', 'ok', {ops: 12}]]);
  assert.equal(r.truncated, false);
  assert.equal(pct(1, 3), 33.3); assert.equal(pct(0, 0), null);

  const all = await coverageReport(db, null, NOW);
  assert.equal(all.totals.boats, 5);
  assert.deepEqual(all.ports.map(p => `${p.region}/${p.port_id}`), ['CA/avila', 'CA/morro-bay', 'OR/newport']);
  assert.equal(all.runs.length, 3);
});

test('acceptance 2: boats with no AIS are "not-seen", and nothing in the report or the views speaks of compliance', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  seedRegistry(sql);
  const text = JSON.stringify(await coverageReport(db, 'CA', NOW));
  assert.doesNotMatch(text, /compli|violat|illegal|required/i);
  const presence = new Set([...text.matchAll(/"ais":"([^"]+)"/g)].map(m => m[1]));
  assert.deepEqual([...presence].sort(), ['not-seen']);
  for (const file of ['../web/admin/fleet-coverage.tsx', '../web/admin/fleet-ais.tsx', '../web/admin/fleet-coverage-copy.ts']) {
    const source = readFileSync(new URL(file, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /non-?compliant|compliance|violation/i, file);
  }
  assert.match(readFileSync(new URL('../web/admin/fleet-coverage-copy.ts', import.meta.url), 'utf8'), /not seen/i);
});

function seedAis(sql) {
  const hour = sql.prepare('INSERT INTO fleet_ais_hours(region,hour,messages,watched_messages,vessels,reconnects,max_gap_s,dropped) VALUES(?,?,?,?,?,?,?,?)');
  const end = Date.parse('2026-10-05T12:00:00Z'), H = 3_600_000;
  const special = {
    '2026-10-05T08': {max_gap_s: 900, reconnects: 1},
    '2026-10-05T09': {dropped: 5},
    '2026-10-04T12': {reconnects: 1},
    '2026-10-04T11': {reconnects: 4, dropped: 7},        // just outside the 24 h window
    '2026-10-03T10': {messages: 0, max_gap_s: 3600},     // an empty hour is down: an outage, not a gap
    '2026-10-02T15': {max_gap_s: 601},
    '2026-10-01T00': {max_gap_s: 600},                   // exactly 10 minutes is not a gap
  };
  const down = new Set(['2026-10-04T03', '2026-10-04T04', '2026-10-04T05']);   // no counters at all
  for (let t = end - 168 * H; t < end; t += H) {
    const key = hourKey(t);
    if (down.has(key)) continue;
    const s = special[key] ?? {};
    // The processor's stamp (CF-45) is the hour start with ms; one row uses the bare hour: both read as the hour.
    hour.run('CA', key === '2026-10-05T07' ? key : `${key}:00:00.000Z`, s.messages ?? 100, 10, 5, s.reconnects ?? 0, s.max_gap_s ?? 120, s.dropped ?? 0);
  }
  // 36 earlier hours inside 30 days, one with a long gap outside the 7-day gap list.
  for (let t = Date.parse('2026-09-20T00:00:00Z'), i = 0; i < 36; i++, t += H) hour.run('CA', `${hourKey(t)}:00:00.000Z`, 50, 5, 3, 0, hourKey(t) === '2026-09-20T05' ? 4000 : 60, 0);
  hour.run('CA', '2026-10-05T12:00:00.000Z', 40, 4, 3, 2, 1200, 0);   // the current hour is not complete: left out
  hour.run('CA', '2026-08-01T00:00:00.000Z', 40, 4, 3, 0, 60, 0);     // older than 30 days
  // The heartbeat as CF-45's processor pushes it.
  const heartbeat = {source: 'aisstream', written_at: '2026-10-05T12:29:00Z', started_at: '2026-10-01T00:00:00Z', last_message_at: '2026-10-05T12:25:00Z',
    connected: true, messages_per_min: 412, watched_messages_per_min: 9, vessels: 218, reconnects: 2, dropped: 0, queue_depth: 3, watch_size: 2,
    git_sha: 'abc1234', received_at: '2026-10-05T12:03:29.512Z', messages_24h: 590000};
  const state = sql.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?)');
  state.run('fleet.ais.CA.heartbeat', JSON.stringify(heartbeat), '2026-10-05T12:03:30.000Z');
  state.run('fleet.ais.CA.processed', '{"at":"2026-10-05T12:03:30.000Z","run_id":"r9","counts":{}}', '2026-10-05T12:03:30.000Z');
  state.run('fleet.ais.OR.heartbeat', 'not json', '2026-10-05T12:03:30.000Z');
  const watch = sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`);
  watch.run('CA', '999000101', id(1), 'fcc-uls', 0.9, 'watched', T0, T0, T0);
  watch.run('CA', '999000102', id(2), 'fcc-uls', 0.9, 'watched', T0, T0, T0);
  watch.run('CA', '999000109', null, 'ais-static-name', 0.4, 'candidate', T0, T0, T0);
  watch.run('CA', '999000108', null, 'ais-static-name', 0.4, 'rejected', T0, T0, T0);
}

test('acceptance 3: ais/health gives uptime, gaps over 10 minutes and last-message age from fleet_ais_hours and job_state', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  seedAis(sql);
  const report = await aisHealth(db, 'CA', NOW);
  const ca = report.regions[0];
  assert.equal(report.regions.length, 1);
  assert.equal(ca.last_message_at, '2026-10-05T12:25:00Z');
  assert.equal(ca.last_message_age_s, 300);
  assert.equal(ca.stale, false);
  assert.equal(ca.heartbeat.age_s, 60);
  assert.equal(ca.heartbeat.connected, true);
  assert.equal(ca.messages_per_min, 412);
  // 7 days = 168 hours, 4 down (three missing, one with no messages): 164/168. 30 days = 720 hours: 164 + 36 = 200.
  assert.deepEqual(ca.uptime, {d7: {pct: 97.6, up_hours: 164, hours: 168}, d30: {pct: 27.8, up_hours: 200, hours: 720}});
  assert.deepEqual(ca.gaps, [{hour: '2026-10-05T08', max_gap_s: 900}, {hour: '2026-10-02T15', max_gap_s: 601}]);
  assert.deepEqual(ca.outages, [{from: '2026-10-04T03', to: '2026-10-04T05', hours: 3}, {from: '2026-10-03T10', to: '2026-10-03T10', hours: 1}]);
  assert.deepEqual(ca.last_24h, {messages: 2400, reconnects: 2, dropped: 5, hours_reported: 24});
  assert.equal(ca.hours_24.length, 24);
  assert.equal(ca.hours_24[0].hour, '2026-10-04T12');
  assert.equal(ca.hours_24.find(h => h.hour === '2026-10-05T07').messages, 100);
  assert.deepEqual(ca.processor, {last_run_at: '2026-10-05T12:03:30.000Z', age_s: 1590});
  assert.deepEqual(ca.watch, {watched: 2, candidates: 1, listener: 2});

  // Every region with state; an unreadable heartbeat is flagged and the region is stale with no last message.
  const all = await aisHealth(db, null, NOW);
  assert.deepEqual(all.regions.map(r => r.region), ['CA', 'OR']);
  const or = all.regions[1];
  assert.equal(or.heartbeat, null); assert.equal(or.heartbeat_unreadable, true);
  assert.equal(or.last_message_at, null); assert.equal(or.stale, true);
  assert.deepEqual(or.uptime.d7, {pct: 0, up_hours: 0, hours: 168});
  assert.deepEqual(or.outages, [{from: '2026-09-28T12', to: '2026-10-05T11', hours: 168}]);

  // Three hours after the last message the listener is stale.
  const later = await aisHealth(db, 'CA', new Date('2026-10-05T15:25:01.000Z'));
  assert.equal(later.regions[0].stale, true);
});

test('acceptance 4: both routes 404 for non-admins and with FLEET_ENABLED off; admins get the reports', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES(?,?,'admin')").run(ADMIN, T0);
  seedRegistry(sql); seedAis(sql);
  const get = (path, extra = ON, owner = ADMIN) => worker.fetch(new Request(ORIGIN + path, {headers: owner ? {'x-test-owner': owner} : {}}), {ASSETS, DB: db, ...extra});
  for (const path of ['/api/admin/fleet/coverage', '/api/admin/fleet/ais/health']) {
    assert.equal((await get(path, ON, 'someone-else')).status, 404, `non-admin ${path}`);
    assert.equal((await get(path, {})).status, 404, `fleet off ${path}`);
    assert.equal((await get(path, {TEXT_ADVISOR_ENABLED: 'true'})).status, 404, `advisor flag only ${path}`);
    assert.ok([401, 404].includes((await get(path, ON, null)).status), `anonymous ${path}`);
    assert.equal((await get(path + '?region=../x')).status, 400, `bad region ${path}`);
    const ok = await get(path + '?region=CA');
    assert.equal(ok.status, 200, path);
    assert.equal(ok.headers.get('Cache-Control'), 'no-store');
  }
  const coverage = await (await get('/api/admin/fleet/coverage?region=CA')).json();
  assert.equal(coverage.totals.boats, 4);
  const health = await (await get('/api/admin/fleet/ais/health?region=CA')).json();
  assert.equal(health.regions[0].region, 'CA');
  assert.equal(health.regions[0].watch.watched, 4);   // two from each seed
});
