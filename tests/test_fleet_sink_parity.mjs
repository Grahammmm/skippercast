// SqliteSink parity with the Worker (CF-10; docs/plans/charter-fleet/design.md § 9
// "Operation contract"). The same registry operations go through the Worker's
// POST /api/fleet/jobs/registry handler (server/fleet/jobs.ts over the real
// migrations, tests/_advisor_d1.mjs) and through the Python SqliteSink
// (src/skippercast/fleet/sinks.py); each step's result and the final fleet_*
// tables must match. Fixtures follow tests/test_fleet_jobs.mjs and are synthetic.
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {registry, jobsDeps} = await import('../server/fleet/jobs.ts');
const ROOT = fileURLToPath(new URL('..', import.meta.url));
const REGION = 'CA', RUN = 'run-20261005', NOW = '2026-10-05T10:00:00.000Z';
const T0 = '2026-10-05T09:47:00Z', T1 = '2026-10-12T09:47:00.000Z', TM = '2026-09-28T09:47:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex');
const python = ['python3', 'python'].find(cmd => spawnSync(cmd, ['--version']).status === 0);
const skip = sqliteUnavailable ?? (python ? false : 'no Python interpreter on PATH');

const vid = n => sha(`${REGION}:name-port:test-boat-${n}|morro-bay`).slice(0, 32);
const OPERATOR = 'op-test-0000000000000001';
const vessel = (n, extra = {}) => ({op: 'vessel.upsert', id: vid(n), creation_key: `name-port:test-boat-${n}|morro-bay`, slug: `test-boat-${n}`,
  name: `Test Boat ${n}`, name_norm: `TESTBOAT${n}`, operator_id: OPERATOR, port_id: 'morro-bay', vessel_class: 'inspected-party',
  waters_json: ['ocean', 'bay'], mmsi: String(366000000 + n), passengers_max: 30, length_ft: 58.5, website: `https://boat${n}.example.com/`,
  phone_business: '+18055550100', status: 'active', profile_status: 'listed', completeness: 0.5, first_seen_at: T0, last_seen_at: T0, ...extra});
const fact = (n, field, value, extra = {}) => ({op: 'fact.upsert', vessel_id: vid(n), field, value_json: value, source_id: 'fcc-uls',
  source_url: `https://registry.example.gov/vessel/${n}`, method: 'registry', confidence: 0.9, rights: 'public-domain', retrieved_at: T0, ...extra});
const factId = (n, field, value) => sha([vid(n), field, 'fcc-uls', `https://registry.example.gov/vessel/${n}`, sha(JSON.stringify(value)).slice(0, 16)].join('|')).slice(0, 32);
const operator = (extra = {}) => ({op: 'operator.upsert', id: OPERATOR, slug: 'test-landing', name: 'Test Landing Sportfishing',
  website: 'https://landing.example.com/', phone_business: '+18055550101', booking_platform: 'fareharbor', seen_at: T0, ...extra});
const offering = (n, extra = {}) => ({op: 'offering.upsert', id: sha(`${vid(n)}|HALFDAY|`).slice(0, 32), vessel_id: vid(n), name: 'Half Day',
  trip_type: 'half-day', duration_h: 5, price_cents: 9500, price_basis: 'per-person', capacity: 30, currency: 'USD', departs_local: '06:30',
  days_json: ['sat', 'sun'], season_from: '04-01', season_to: '10-31', target_species_json: ['rockfish', 'lingcod'],
  booking_url: 'https://landing.example.com/book', status: 'active', seen_at: T0, ...extra});
const departure = n => ({op: 'departure.upsert', offering_id: offering(n).id, vessel_id: vid(n), date: '2026-10-10', departs_local: '06:30',
  price_cents: 9500, load_text: '12 of 30', source_url: 'https://landing.example.com/schedule', retrieved_at: T0});
const review = (extra = {}) => ({op: 'review.open', kind: 'merge', fingerprint: 'fcc-uls:WDZ0000', subject_id: vid(1),
  candidate_json: {name: 'TEST BOAT 1', source: 'fcc-uls'}, proposal_json: {vessels: [vid(1), vid(2)]}, score: 0.72, opened_at: T0, ...extra});
const change = n => ({op: 'change.record', vessel_id: vid(n), kind: 'new', before_json: null, after_json: {name: `Test Boat ${n}`}, detected_at: T0});
const alias = (n, extra = {}) => ({op: 'alias.upsert', vessel_id: vid(n), alias: `Test Boat ${n} II`, alias_norm: `TESTBOAT${n}2`, kind: 'former-name',
  source_url: 'https://reports.example.com/boats', first_seen_at: T0, last_seen_at: T0, ...extra});
const run = {op: 'run.record', step: 'ingest', sink: 'staging', started_at: T0, finished_at: T0, status: 'ok', counts_json: {facts: 3}};

function fullBatch() {
  const ops = [operator()];
  for (let n = 1; n <= 3; n++) ops.push(vessel(n), fact(n, 'mmsi', String(366000000 + n)), fact(n, 'name', `Test Boat ${n}`), alias(n), offering(n), departure(n), change(n));
  return [...ops, review(), run];
}

const STEPS = [
  {ops: fullBatch()},
  {ops: fullBatch()},                                                            // replay: zero changes
  {sql: `UPDATE fleet_vessels SET pinned_json='{"name":"admin"}' WHERE id='${vid(1)}'`},
  {sql: `UPDATE fleet_vessels SET removal_requested_at='${T0}', profile_status='hidden' WHERE id='${vid(3)}'`},
  {sql: `UPDATE fleet_reviews SET status='rejected', decided_at='${T0}'`},
  {ops: [
    vessel(1, {name: 'Renamed One', length_ft: 60, last_seen_at: T1}),         // name pinned, length moves
    vessel(2, {name: 'Older Two', first_seen_at: TM, last_seen_at: TM}),      // older replay: only first_seen_at moves back
    vessel(3, {last_seen_at: T1, profile_status: 'listed'}),                  // removal requested: never re-listed
    fact(1, 'mmsi', '366000099', {retrieved_at: T1, supersedes: [factId(1, 'mmsi', '366000001')]}),
    fact(2, 'name', 'Test Boat 2', {retrieved_at: TM, confidence: 0.5}),    // older replay of a stored fact
    alias(1, {alias: 'Test Boat 1 Two', last_seen_at: T1}),
    operator({name: 'Older Landing Name', seen_at: TM}),                      // older replay: ignored
    offering(1, {price_cents: 10500, seen_at: T1}),
    review({score: 0.9}),                                                     // decided: not reopened
  ]},
  {ops: [vessel(4, {slug: 'test-boat-1'}), fact(9, 'mmsi', '1'), fact(1, 'mmsi', '2', {source_url: 'admin:user-1'}),
    fact(1, 'mmsi', '3', {method: 'admin'}), {...alias(1), colour: 'red'}, review({fingerprint: undefined}), offering(2, {seen_at: undefined})]},
];

const TABLES = ['fleet_operators', 'fleet_vessels', 'fleet_vessel_facts', 'fleet_aliases', 'fleet_offerings', 'fleet_departures', 'fleet_reviews', 'fleet_changes'];
const plain = value => JSON.parse(JSON.stringify(value));

async function throughWorker() {
  const {sql, db} = advisorDatabase(), saved = jobsDeps.now;
  jobsDeps.now = () => new Date(NOW);
  try {
    const results = [];
    for (const [i, step] of STEPS.entries()) {
      if (step.sql) { sql.exec(step.sql); results.push(null); continue; }
      const out = await registry(db, new Request('https://skippercast.com/api/fleet/jobs/registry', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({region: REGION, run_id: RUN, batch: i, ops: step.ops})}));
      results.push(out.status === 200 ? {changed: out.body.changed, counts: out.body.counts} : {status: out.status, errors: out.body.errors});
    }
    const dump = Object.fromEntries(TABLES.map(t => [t, sql.prepare(`SELECT * FROM ${t} ORDER BY 1, 2`).all()]));
    dump.fleet_runs = sql.prepare("SELECT * FROM fleet_runs WHERE id NOT LIKE '%:registry.%' ORDER BY 1").all();
    return plain({results, dump});
  } finally { jobsDeps.now = saved; sql.close(); }
}

const DRIVER = `
import datetime, json, sqlite3, sys, tempfile
from skippercast.fleet.sinks import SinkError, SqliteSink
scenario = json.load(sys.stdin)
now = datetime.datetime(2026, 10, 5, 10, 0, tzinfo=datetime.timezone.utc)
sink = SqliteSink(tempfile.mkdtemp() + "/CA.sqlite", scenario["region"], scenario["run_id"], clock=lambda: now)
results = []
for step in scenario["steps"]:
    if "sql" in step:
        sink.db.execute(step["sql"]); results.append(None); continue
    try:
        out = sink.apply(step["ops"]); results.append({"changed": out["changed"], "counts": out["counts"]})
    except SinkError as error:
        results.append({"status": 400, "errors": error.errors})
sink.db.row_factory = sqlite3.Row
dump = {t: [dict(r) for r in sink.db.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in scenario["tables"]}
dump["fleet_runs"] = [dict(r) for r in sink.db.execute("SELECT * FROM fleet_runs ORDER BY 1")]
print(json.dumps({"results": results, "dump": dump}))
`;

function throughSqliteSink() {
  const result = spawnSync(python, ['-c', DRIVER], {cwd: ROOT, encoding: 'utf8', env: {...process.env, PYTHONPATH: ROOT + 'src'},
    input: JSON.stringify({region: REGION, run_id: RUN, steps: STEPS, tables: TABLES})});
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test('SqliteSink stores and refuses exactly what the Worker registry route does', {skip}, async () => {
  const worker = await throughWorker(), sink = throughSqliteSink();
  assert.equal(worker.results[1].changed, 0, 'the Worker replay changes nothing');
  assert.equal(worker.results[6].status, 400);
  for (const [i, expected] of worker.results.entries()) assert.deepEqual(sink.results[i], expected, `step ${i}`);
  for (const table of [...TABLES, 'fleet_runs']) assert.deepEqual(sink.dump[table], worker.dump[table], table);
  const v1 = worker.dump.fleet_vessels.find(v => v.id === vid(1));
  assert.equal(v1.name, 'Test Boat 1', 'pinned name kept');
  assert.equal(worker.dump.fleet_vessels.find(v => v.id === vid(3)).profile_status, 'hidden');
  assert.equal(worker.dump.fleet_reviews[0].status, 'rejected');
});
