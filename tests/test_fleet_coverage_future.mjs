// RF1345-9: the admin coverage report (server/fleet/admin/coverage.ts, CF-35) counts a boat as
// "seen" only for a watched fleet_ais_watch row last heard inside [now - 30 days, now] on the
// report clock. A row dated after the report clock is not a recent sighting: it neither counts
// alone nor hides another valid row, and reading the report never rewrites it. Real migrations
// (tests/_advisor_d1.mjs), a fixed clock, synthetic vessels and 999xxxxxx MMSIs only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {coverageReport, SEEN_DAYS} = await import('../server/fleet/admin/coverage.ts');
const {watchUpdate, watchDeps} = await import('../server/fleet/watch.ts');

const skip = sqliteUnavailable ?? false;
const NOW = new Date('2026-11-09T20:00:00.000Z'), T0 = '2026-01-01T00:00:00.000Z';
const at = ms => new Date(NOW.getTime() + ms).toISOString();
const SINCE = at(-SEEN_DAYS * 86_400_000);
const id = n => String(n).repeat(32).slice(0, 32);
watchDeps.now = () => NOW;

/** Active vessel n with one current non-AIS source fact, so it is a single-source boat. */
function vessel(sql, n, {region = 'CA', port = 'morro-bay', cls = 'six-pack'} = {}) {
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,vessel_class,status,completeness,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,'active',0,?,?,?,?)`).run(id(n), region, `test-boat-${n}`, `Test Boat ${n}`, `TESTBOAT${n}`, port, cls, T0, T0, T0, T0);
  sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at)
    VALUES(?,?,'name','"x"',?,'operator-site','https://boat.example.com/','page',0.9,'facts-only',?,?,?)`).run(id(n).replace(/./, 'f'), id(n), 'k'.repeat(16), T0, T0, T0);
}
function watch(sql, mmsi, n, lastSeen, {status = 'watched', region = 'CA'} = {}) {
  sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)`)
    .run(region, mmsi, id(n), status === 'watched' ? 'fcc-uls' : 'ais-static-name', status === 'watched' ? 0.9 : 0.5, status, T0, lastSeen, T0);
}
const post = payload => new Request('https://example.com/api/fleet/jobs/watch',
  {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
/** Every place the report states one boat's presence: totals, port, class and its single-source row. */
const presence = (r, n = 1) => ({totals: r.totals.ais, port: r.ports[0].ais, cls: r.ports[0].classes[0].ais,
  single: r.single_source.find(s => s.id === id(n))?.ais});
const SEEN = {totals: {seen: 1, not_seen: 0, seen_pct: 100}, port: {seen: 1, not_seen: 0, seen_pct: 100}, cls: {seen: 1, not_seen: 0, seen_pct: 100}, single: 'seen'};
const NOT_SEEN = {totals: {seen: 0, not_seen: 1, seen_pct: 0}, port: {seen: 0, not_seen: 1, seen_pct: 0}, cls: {seen: 0, not_seen: 1, seen_pct: 0}, single: 'not-seen'};

test('future_only_watch_is_not_recent_coverage', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  vessel(sql, 1);
  const future = '2027-11-09T20:00:00.000Z';
  const result = await watchUpdate(db, post({region: 'CA', run_id: 'rf1345-9', rows: [{mmsi: '999000801', vessel_id: id(1),
    match_method: 'fcc-uls', confidence: 0.9, status: 'watched', first_seen_at: T0, last_seen_at: future}]}));
  assert.equal(result.status, 200, 'a canonical future date is accepted by watchUpdate');
  const r = await coverageReport(db, 'CA', NOW);
  assert.ok(r.single_source.length === 1);
  assert.deepEqual(presence(r), NOT_SEEN);
  assert.equal(sql.prepare('SELECT last_seen_at FROM fleet_ais_watch WHERE mmsi=?').get('999000801').last_seen_at, future);
});

test('seen_interval_boundaries_are_inclusive', {skip}, async () => {
  const cases = [[at(0), SEEN], [SINCE, SEEN], [at(-86_400_000), SEEN],
    [at(1), NOT_SEEN], [at(-SEEN_DAYS * 86_400_000 - 1), NOT_SEEN], ['2027-11-09T20:00:00.000Z', NOT_SEEN], ['9999-12-31T23:59:59.999Z', NOT_SEEN]];
  for (const [lastSeen, want] of cases) {
    const {sql, db} = advisorDatabase();
    vessel(sql, 1); watch(sql, '999000801', 1, lastSeen);
    const r = await coverageReport(db, 'CA', NOW);
    assert.deepEqual(presence(r), want, lastSeen);
    assert.equal(r.generated_at, NOW.toISOString());
    assert.equal(r.seen_since, SINCE);
  }
});

test('one_eligible_watch_suffices_without_duplicate_boats', {skip}, async () => {
  for (const [rows, want] of [[[at(86_400_000), at(-3_600_000)], SEEN], [[at(-3_600_000), at(-7_200_000)], SEEN],
    [[at(86_400_000), at(-SEEN_DAYS * 86_400_000 - 1)], NOT_SEEN], [[at(1), at(1000)], NOT_SEEN]]) {
    const {sql, db} = advisorDatabase();
    vessel(sql, 1);
    rows.forEach((lastSeen, i) => watch(sql, `99900080${i + 1}`, 1, lastSeen));
    const r = await coverageReport(db, 'CA', NOW);
    assert.equal(r.totals.boats, 1, rows.join(' '));
    assert.equal(r.single_source.length, 1, rows.join(' '));
    assert.deepEqual(presence(r), want, rows.join(' '));
  }
});

test('nonwatched_and_empty_states_keep_existing_semantics', {skip}, async () => {
  for (const [status, lastSeen] of [['candidate', at(-3_600_000)], ['rejected', at(-3_600_000)], ['watched', '2026-08-01T10:00:00.000Z'], [null, null]]) {
    const {sql, db} = advisorDatabase();
    vessel(sql, 1);
    if (status) watch(sql, '999000801', 1, lastSeen, {status});
    assert.deepEqual(presence(await coverageReport(db, 'CA', NOW)), NOT_SEEN, `${status} ${lastSeen}`);
  }
  const {db} = advisorDatabase();
  const empty = await coverageReport(db, 'CA', NOW);
  assert.deepEqual(empty.totals.ais, {seen: 0, not_seen: 0, seen_pct: null});
  assert.deepEqual([empty.totals.boats, empty.ports, empty.single_source], [0, [], []]);
});

test('coverage_read_does_not_rewrite_clock_skew', {skip}, async () => {
  const {sql, db} = advisorDatabase();
  vessel(sql, 1); watch(sql, '999000801', 1, at(86_400_000));                                       // CA, future only
  vessel(sql, 2, {cls: 'inspected-party'}); watch(sql, '999000802', 2, at(-86_400_000));            // CA, recent
  vessel(sql, 3, {region: 'OR', port: 'newport'}); watch(sql, '999000803', 3, at(1), {region: 'OR'}); // OR, 1 ms ahead
  const snapshot = () => JSON.stringify(['fleet_ais_watch', 'fleet_vessels', 'fleet_vessel_facts'].map(t => sql.prepare(`SELECT * FROM ${t} ORDER BY 1,2`).all()));
  const before = snapshot();
  const ca = await coverageReport(db, 'CA', NOW), all = await coverageReport(db, null, NOW);
  assert.equal(snapshot(), before, 'the report writes nothing');
  assert.equal(sql.prepare('SELECT last_seen_at FROM fleet_ais_watch WHERE mmsi=?').get('999000801').last_seen_at, at(86_400_000));
  assert.deepEqual(ca.totals.ais, {seen: 1, not_seen: 1, seen_pct: 50});
  assert.deepEqual(ca.ports[0].classes.map(c => [c.vessel_class, c.ais.seen, c.ais.not_seen]), [['inspected-party', 1, 0], ['six-pack', 0, 1]]);
  assert.deepEqual(all.totals.ais, {seen: 1, not_seen: 2, seen_pct: 33.3});
  assert.deepEqual(all.ports.map(p => [p.region, p.port_id, p.ais.seen, p.ais.not_seen]), [['CA', 'morro-bay', 1, 1], ['OR', 'newport', 0, 1]]);
  assert.deepEqual(all.single_source.map(s => [s.id, s.ais]).sort(), [[id(1), 'not-seen'], [id(2), 'seen'], [id(3), 'not-seen']]);
});
