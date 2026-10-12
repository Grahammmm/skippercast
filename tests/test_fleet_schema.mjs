// Charter fleet registry schema (CF-02, migration 0013; docs/plans/charter-fleet/design.md § 5).
// Applies the committed migrations to node:sqlite (the D1 fake in _advisor_d1.mjs) and
// checks tables, indexes, NOT NULLs and defaults. Synthetic data only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable, journal, migrationSql} from './_advisor_d1.mjs';

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const NOW = '2026-10-04T12:00:00Z';

const REGISTRY_TABLES = ['fleet_operators', 'fleet_vessels', 'fleet_vessel_facts', 'fleet_aliases', 'fleet_offerings', 'fleet_departures',
  'fleet_reviews', 'fleet_changes', 'fleet_outreach', 'fleet_link_clicks', 'fleet_runs'];
// Every index § 5 names for 0013, by table (unique ones are checked separately).
const INDEXES = {
  fleet_operators: ['fo_slug', 'fo_region', 'fo_outreach'],
  fleet_vessels: ['fv_slug', 'fv_region_port', 'fv_mmsi', 'fv_doc', 'fv_state_reg', 'fv_name', 'fv_operator'],
  fleet_vessel_facts: ['fact_vessel_field', 'fact_source'],
  fleet_aliases: ['alias_lookup'],
  fleet_offerings: ['offer_vessel'],
  fleet_departures: ['dep_vessel_date'],
  fleet_reviews: ['fr_open'],
  fleet_changes: ['fc_vessel', 'fc_kind'],
  fleet_outreach: ['out_operator'],
  fleet_runs: ['run_region_time'],
  advisor_boats: ['boat_fleet'],
};
const INDEX_COLUMNS = {
  fv_region_port: ['region', 'port_id'], fv_name: ['region', 'name_norm'], fv_mmsi: ['mmsi'], fv_doc: ['uscg_doc'], fv_state_reg: ['state_reg'],
  fact_vessel_field: ['vessel_id', 'field', 'superseded_at'], fact_source: ['source_id', 'last_seen_at'], alias_lookup: ['alias_norm'],
  offer_vessel: ['vessel_id', 'status'], dep_vessel_date: ['vessel_id', 'date'], fr_open: ['region', 'status', 'opened_at'],
  fc_kind: ['kind', 'detected_at'], fc_vessel: ['vessel_id'], out_operator: ['operator_id'], fv_operator: ['operator_id'], fv_slug: ['slug'],
  fo_slug: ['slug'], fo_region: ['region'], fo_outreach: ['outreach_status'], run_region_time: ['region', 'started_at'], boat_fleet: ['fleet_vessel_id'],
};

const info = (sql, t) => sql.prepare(`PRAGMA table_info(${t})`).all();
const column = (sql, t, c) => info(sql, t).find(r => r.name === c);
const tables = sql => sql.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map(r => r.name);
const indexList = (sql, t) => sql.prepare(`PRAGMA index_list(${t})`).all();

async function upTo(idx) {
  const {DatabaseSync} = await import('node:sqlite'), sql = new DatabaseSync(':memory:');
  for (const {tag} of journal().entries.filter(e => e.idx <= idx).sort((a, b) => a.idx - b.idx)) sql.exec(migrationSql(tag));
  return sql;
}

const insertFact = (sql, overrides = {}) => {
  const row = {id: 'fact1', vessel_id: 'v1', field: 'mmsi', value_json: '"338000001"', value_key: 'k1', source_id: 'fcc-uls',
    source_url: 'https://example.test/uls/1', method: 'registry', confidence: 0.9, rights: 'public-domain', retrieved_at: NOW,
    first_seen_at: NOW, last_seen_at: NOW, run_id: 'run1', ...overrides};
  for (const k of Object.keys(row)) if (row[k] === undefined) delete row[k];
  const cols = Object.keys(row);
  return sql.prepare(`INSERT INTO fleet_vessel_facts(${cols.join(',')}) VALUES(${cols.map(() => '?').join(',')})`).run(...cols.map(c => row[c]));
};

test('migration 0013 is fleet_registry and follows 0012', () => {
  const entries = journal().entries, entry = entries.find(e => e.tag.startsWith('0013_'));
  assert.equal(entry?.tag, '0013_fleet_registry');
  assert.equal(entries[entry.idx - 1].tag, '0012_advisor_source_post');
  assert.match(migrationSql('0013_fleet_registry'), /ALTER TABLE `advisor_boats` ADD `fleet_vessel_id` text;/);
});

dbTest('a fresh database has every 0013 registry table and index', async () => {
  const sql = await upTo(13);
  for (const t of REGISTRY_TABLES) assert.ok(tables(sql).includes(t), t);
  for (const t of ['fleet_ais_watch', 'fleet_trips', 'fleet_events', 'fleet_trip_reports']) assert.ok(!tables(sql).includes(t), `${t} belongs to 0014`);
  for (const [t, names] of Object.entries(INDEXES)) {
    const have = indexList(sql, t).map(r => r.name);
    for (const n of names) assert.ok(have.includes(n), `${t}.${n}`);
  }
  for (const [n, cols] of Object.entries(INDEX_COLUMNS))
    assert.deepEqual(sql.prepare(`PRAGMA index_info(${n})`).all().map(r => r.name), cols, n);
  const unique = (t, n) => indexList(sql, t).find(r => r.name === n)?.unique;
  assert.equal(unique('fleet_vessels', 'fv_slug'), 1); assert.equal(unique('fleet_operators', 'fo_slug'), 1);
  // Stable keys are deliberately not unique: a conflict is a review, not a failed insert.
  for (const n of ['fv_mmsi', 'fv_doc', 'fv_state_reg']) assert.equal(unique('fleet_vessels', n), 0, n);
  const pk = t => info(sql, t).filter(c => c.pk > 0).sort((a, b) => a.pk - b.pk).map(c => c.name);
  assert.deepEqual(pk('fleet_aliases'), ['vessel_id', 'alias_norm']);
  assert.deepEqual(pk('fleet_link_clicks'), ['vessel_id', 'target', 'placement', 'day']);
  for (const t of REGISTRY_TABLES.filter(t => !['fleet_aliases', 'fleet_link_clicks'].includes(t))) assert.deepEqual(pk(t), ['id'], t);
});

dbTest('the full migration chain (D1 fake) includes the registry', () => {
  const {sql} = advisorDatabase();
  for (const t of REGISTRY_TABLES) assert.ok(tables(sql).includes(t), t);
  assert.ok(column(sql, 'advisor_boats', 'fleet_vessel_id'));
});

dbTest('0013 applies over a 0012 database with advisor data and keeps advisor_boats rows', async () => {
  const sql = await upTo(12);
  const boat = sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,phone_public,status,auto_publish,clean_reports,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`);
  boat.run('boat1', 'sea-example', 'Sea Example', 'example-landing', 'morro-bay', 'morro-bay', '805-555-0101', 'verified', 1, 4, NOW, NOW);
  boat.run('boat2', 'reel-example', 'Reel Example', null, 'port-san-luis', 'morro-bay', null, 'pending', 0, 0, NOW, NOW);
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,created_at,updated_at)
    VALUES('r1','boat1','morro-bay','morro-bay','2026-10-01','{}','sms',?,?)`).run(NOW, NOW);
  const before = sql.prepare('SELECT * FROM advisor_boats ORDER BY id').all().map(r => ({...r}));
  sql.exec(migrationSql('0013_fleet_registry'));
  const after = sql.prepare('SELECT * FROM advisor_boats ORDER BY id').all();
  assert.equal(after.length, 2);
  assert.deepEqual(after.map(({fleet_vessel_id, ...rest}) => rest), before);
  assert.deepEqual(after.map(r => r.fleet_vessel_id), [null, null]);
  assert.equal(sql.prepare('SELECT count(*) n FROM advisor_reports').get().n, 1);
  for (const t of REGISTRY_TABLES) assert.ok(tables(sql).includes(t), t);
  // The link an admin sets on an advisor-link decision.
  sql.prepare("UPDATE advisor_boats SET fleet_vessel_id='v1' WHERE id='boat1'").run();
  assert.equal(sql.prepare("SELECT id FROM advisor_boats WHERE fleet_vessel_id='v1'").get().id, 'boat1');
});

dbTest('fleet_vessel_facts requires its provenance columns', async () => {
  const sql = await upTo(13);
  for (const c of ['source_url', 'source_id', 'retrieved_at', 'method', 'confidence', 'rights'])
    assert.equal(column(sql, 'fleet_vessel_facts', c).notnull, 1, c);
  assert.throws(() => insertFact(sql, {source_url: undefined}), /NOT NULL constraint failed: fleet_vessel_facts\.source_url/);
  assert.throws(() => insertFact(sql, {source_url: null}), /NOT NULL constraint failed: fleet_vessel_facts\.source_url/);
  for (const c of ['source_id', 'retrieved_at', 'method', 'confidence', 'rights'])
    assert.throws(() => insertFact(sql, {id: `f-${c}`, [c]: undefined}), new RegExp(`NOT NULL constraint failed: fleet_vessel_facts\\.${c}`), c);
  // Admin edits have no pipeline run.
  assert.equal(column(sql, 'fleet_vessel_facts', 'run_id').notnull, 0);
  insertFact(sql, {id: 'fact-admin', source_id: 'admin', source_url: 'admin:user1', method: 'admin', run_id: undefined});
  insertFact(sql);
  const row = sql.prepare("SELECT superseded_at, superseded_by FROM fleet_vessel_facts WHERE id='fact1'").get();
  assert.deepEqual({...row}, {superseded_at: null, superseded_by: null});
});

dbTest('fleet_vessels consent and removal columns (US-C4, US-C3) and other defaults', async () => {
  const sql = await upTo(13);
  const consent = column(sql, 'fleet_vessels', 'map_display_consent');
  assert.equal(consent.notnull, 1); assert.equal(consent.dflt_value, "'none'");
  const removal = column(sql, 'fleet_vessels', 'removal_requested_at');
  assert.equal(removal.type.toLowerCase(), 'text'); assert.equal(removal.notnull, 0); assert.equal(removal.dflt_value, null);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,vessel_class,waters_json,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v1','CA','sea-example','Sea Example','sea example','inspected-party','["ocean"]',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  const v = sql.prepare("SELECT * FROM fleet_vessels WHERE id='v1'").get();
  assert.equal(v.map_display_consent, 'none'); assert.equal(v.removal_requested_at, null);
  assert.equal(v.status, 'active'); assert.equal(v.profile_status, 'hidden'); assert.equal(v.pinned_json, '{}'); assert.equal(v.completeness, 0);
  for (const c of ['operator_id', 'port_id', 'landing_id', 'uscg_doc', 'state_reg', 'hull_id', 'call_sign', 'mmsi', 'year_built', 'length_ft', 'phone_business'])
    assert.equal(v[c], null, c);
  // A discovery candidate (FCC/PSIX) has no class or waters yet.
  for (const c of ['vessel_class', 'waters_json']) assert.equal(column(sql, 'fleet_vessels', c).notnull, 0, c);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('cand','CA','candidate-example','Candidate Example','candidate example',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  assert.deepEqual({...sql.prepare("SELECT vessel_class, waters_json, profile_status FROM fleet_vessels WHERE id='cand'").get()},
    {vessel_class: null, waters_json: null, profile_status: 'hidden'});
  assert.throws(() => sql.prepare("INSERT INTO fleet_vessels(id,region,slug,name,name_norm,vessel_class,waters_json,map_display_consent,first_seen_at,last_seen_at,created_at,updated_at) VALUES('v2','CA','other','O','o','inspected-party','[]',NULL,?,?,?,?)").run(NOW, NOW, NOW, NOW),
    /NOT NULL constraint failed: fleet_vessels\.map_display_consent/);
  // Two vessels may share an MMSI (a review, not a failed insert); slugs may not repeat.
  sql.prepare("UPDATE fleet_vessels SET mmsi='338000001' WHERE id='v1'").run();
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,vessel_class,waters_json,mmsi,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v3','CA','sea-example-2','Sea Example','sea example','inspected-party','[]','338000001',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  assert.throws(() => sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,vessel_class,waters_json,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v4','CA','sea-example','X','x','inspected-party','[]',?,?,?,?)`).run(NOW, NOW, NOW, NOW), /UNIQUE constraint failed: fleet_vessels\.slug/);
});

dbTest('fleet_operators: user_id nullable (US-B3), consent_revoked_at nullable ISO text (US-S3), status defaults', async () => {
  const sql = await upTo(13);
  const user = column(sql, 'fleet_operators', 'user_id'), revoked = column(sql, 'fleet_operators', 'consent_revoked_at');
  assert.equal(user.notnull, 0);
  assert.equal(revoked.type.toLowerCase(), 'text'); assert.equal(revoked.notnull, 0); assert.equal(revoked.dflt_value, null);
  sql.prepare("INSERT INTO fleet_operators(id,region,slug,name,created_at,updated_at) VALUES('op1','CA','example-sportfishing','Example Sportfishing',?,?)").run(NOW, NOW);
  const op = sql.prepare("SELECT * FROM fleet_operators WHERE id='op1'").get();
  assert.equal(op.user_id, null); assert.equal(op.consent_revoked_at, null);
  assert.equal(op.consent_status, 'unknown'); assert.equal(op.outreach_status, 'none');
});

dbTest('other registry tables take their documented defaults', async () => {
  const sql = await upTo(13);
  sql.prepare("INSERT INTO fleet_reviews(id,region,kind,opened_at) VALUES('r1','CA','merge',?)").run(NOW);
  assert.equal(sql.prepare("SELECT status FROM fleet_reviews").get().status, 'open');
  sql.prepare("INSERT INTO fleet_offerings(id,vessel_id,name,trip_type,updated_at) VALUES('o1','v1','Half day','half-day',?)").run(NOW);
  const o = sql.prepare('SELECT status, currency, capacity FROM fleet_offerings').get();
  assert.deepEqual({...o}, {status: 'active', currency: 'USD', capacity: null});
  sql.prepare("INSERT INTO fleet_outreach(id,operator_id,kind,body,created_by,created_at) VALUES('n1','op1','note','synthetic note','user1',?)").run(NOW);
  assert.equal(sql.prepare('SELECT status FROM fleet_outreach').get().status, 'draft');
  sql.prepare("INSERT INTO fleet_runs(id,region,step,sink,started_at) VALUES('run1:discover','CA','discover','sqlite',?)").run(NOW);
  assert.equal(sql.prepare('SELECT status FROM fleet_runs').get().status, 'running');
  sql.prepare("INSERT INTO fleet_link_clicks(vessel_id,target,placement,day) VALUES('v1','booking','profile','2026-10-04')").run();
  assert.equal(sql.prepare('SELECT count FROM fleet_link_clicks').get().count, 0);
  // D15: click counts carry no visitor data.
  assert.deepEqual(info(sql, 'fleet_link_clicks').map(c => c.name).sort(), ['count', 'day', 'placement', 'target', 'vessel_id']);
});

// ---- 0014 fleet_activity (CF-03) ----

const ACTIVITY_TABLES = ['fleet_ais_watch', 'fleet_trips', 'fleet_segments', 'fleet_events', 'fleet_aggregates', 'fleet_segment_labels',
  'fleet_ais_hours', 'fleet_trip_reports'];
// Every index § 5 names for 0014, with its columns.
const ACTIVITY_INDEX_COLUMNS = {
  fleet_ais_watch: {watch_vessel: ['vessel_id']},
  fleet_trips: {trip_vessel_date: ['vessel_id', 'local_date'], trip_region_season: ['region', 'season'], trip_source_time: ['source', 'departed_at']},
  fleet_segments: {seg_trip: ['trip_id', 'seq']},
  fleet_events: {ev_region_time: ['region', 'started_at'], ev_vessel: ['vessel_id', 'started_at'], ev_season: ['region', 'season', 'kind']},
  fleet_aggregates: {agg_lookup: ['region', 'module', 'season', 'kind']},
  fleet_segment_labels: {label_trip: ['trip_id']},
};

const insertRow = (sql, table, row) => {
  const cols = Object.keys(row);
  return sql.prepare(`INSERT INTO ${table}(${cols.join(',')}) VALUES(${cols.map(() => '?').join(',')})`).run(...cols.map(c => row[c]));
};
const trip = (overrides = {}) => ({id: 't1', region: 'CA', vessel_id: 'v1', mmsi: '338000001', depart_port_id: 'morro-bay',
  return_port_id: 'morro-bay', departed_at: '2026-09-30T13:05:00Z', returned_at: '2026-09-30T22:40:00Z', local_date: '2026-09-30',
  season: '2026', source: 'aisstream', rights: 'api-terms', classifier_version: 'cv1', computed_at: NOW, ...overrides});

test('migration 0014 is fleet_activity and follows 0013', () => {
  const entries = journal().entries, entry = entries.find(e => e.tag.startsWith('0014_'));
  assert.equal(entry?.tag, '0014_fleet_activity');
  assert.equal(entries[entry.idx - 1].tag, '0013_fleet_registry');
  // Activity only: 0014 creates tables and indexes and alters nothing that exists.
  assert.doesNotMatch(migrationSql('0014_fleet_activity'), /ALTER TABLE|DROP /);
});

dbTest('a fresh database has every 0014 activity table, index and key', async () => {
  const sql = await upTo(14);
  for (const t of [...REGISTRY_TABLES, ...ACTIVITY_TABLES]) assert.ok(tables(sql).includes(t), t);
  for (const [t, byName] of Object.entries(ACTIVITY_INDEX_COLUMNS)) {
    const have = indexList(sql, t);
    for (const [n, cols] of Object.entries(byName)) {
      assert.equal(have.find(r => r.name === n)?.unique, 0, `${t}.${n}`);
      assert.deepEqual(sql.prepare(`PRAGMA index_info(${n})`).all().map(r => r.name), cols, n);
    }
  }
  const pk = t => info(sql, t).filter(c => c.pk > 0).sort((a, b) => a.pk - b.pk).map(c => c.name);
  assert.deepEqual(pk('fleet_ais_watch'), ['region', 'mmsi']);
  assert.deepEqual(pk('fleet_ais_hours'), ['region', 'hour']);
  assert.deepEqual(pk('fleet_trip_reports'), ['trip_id', 'report_kind', 'report_ref']);
  for (const t of ['fleet_trips', 'fleet_segments', 'fleet_events', 'fleet_aggregates', 'fleet_segment_labels']) assert.deepEqual(pk(t), ['id'], t);
  // US-B4: the catch-log join keys are always present on a trip.
  for (const c of ['vessel_id', 'local_date']) assert.equal(column(sql, 'fleet_trips', c).notnull, 1, c);
  // Raw positions never reach D1: no activity table has a per-position column.
  for (const t of ACTIVITY_TABLES) for (const c of ['positions', 'positions_json', 'ts', 'sog', 'cog']) assert.equal(column(sql, t, c), undefined, `${t}.${c}`);
});

dbTest('the full migration chain (D1 fake) includes the activity tables', () => {
  const {sql} = advisorDatabase();
  for (const t of ACTIVITY_TABLES) assert.ok(tables(sql).includes(t), t);
});

dbTest('0014 applies over a 0013 database with registry rows and keeps them', async () => {
  const sql = await upTo(13);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v1','CA','sea-example','Sea Example','sea example',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  sql.exec(migrationSql('0014_fleet_activity'));
  assert.equal(sql.prepare('SELECT count(*) n FROM fleet_vessels').get().n, 1);
  for (const t of ACTIVITY_TABLES) assert.ok(tables(sql).includes(t), t);
});

dbTest('fleet_events.basis defaults to inferred-from-movement and species_json starts null', async () => {
  const sql = await upTo(14);
  const basis = column(sql, 'fleet_events', 'basis');
  assert.equal(basis.notnull, 1); assert.equal(basis.dflt_value, "'inferred-from-movement'");
  const event = {id: 'e1', trip_id: 't1', segment_id: 's1', vessel_id: 'v1', region: 'CA', kind: 'drift-anchor', lat: 35.3, lon: -121.0,
    radius_m: 180, started_at: '2026-09-30T15:00:00Z', ended_at: '2026-09-30T15:45:00Z', dwell_min: 45, season: '2026', source: 'aisstream',
    rights: 'api-terms', classifier_version: 'cv1'};
  insertRow(sql, 'fleet_events', event);
  assert.deepEqual({...sql.prepare("SELECT basis, species_json FROM fleet_events WHERE id='e1'").get()}, {basis: 'inferred-from-movement', species_json: null});
  assert.throws(() => insertRow(sql, 'fleet_events', {...event, id: 'e2', basis: null}), /NOT NULL constraint failed: fleet_events\.basis/);
});

dbTest('other activity tables take their documented defaults', async () => {
  const sql = await upTo(14);
  // A candidate MMSI has no vessel yet.
  insertRow(sql, 'fleet_ais_watch', {region: 'CA', mmsi: '338000002', match_method: 'ais-static-name', confidence: 0.6,
    first_seen_at: NOW, last_seen_at: NOW, updated_at: NOW});
  assert.deepEqual({...sql.prepare('SELECT vessel_id, status, positions_30d FROM fleet_ais_watch').get()}, {vessel_id: null, status: 'candidate', positions_30d: 0});
  insertRow(sql, 'fleet_trips', trip({returned_at: null, return_port_id: null}));
  assert.equal(sql.prepare("SELECT status FROM fleet_trips WHERE id='t1'").get().status, 'open');
  assert.throws(() => insertRow(sql, 'fleet_trips', trip({id: 't2', local_date: null})), /NOT NULL constraint failed: fleet_trips\.local_date/);
  sql.prepare("INSERT INTO fleet_ais_hours(region,hour) VALUES('CA','2026-10-04T12')").run();
  assert.deepEqual({...sql.prepare('SELECT messages, watched_messages, vessels, reconnects, max_gap_s, dropped FROM fleet_ais_hours').get()},
    {messages: 0, watched_messages: 0, vessels: 0, reconnects: 0, max_gap_s: 0, dropped: 0});
  insertRow(sql, 'fleet_aggregates', {id: 'a1', region: 'CA', module: 'grid', params_json: '{"resolution_m":500}', cell_id: 'c1', lat: 35.3,
    lon: -121, season: '2026', kind: 'drift-anchor', rights: 'api-terms', computed_at: NOW});
  assert.deepEqual({...sql.prepare('SELECT vessels_n, events_n, dwell_min FROM fleet_aggregates').get()}, {vessels_n: 0, events_n: 0, dwell_min: 0});
  // Pairing the same trip and report twice is one row.
  const pair = {trip_id: 't1', report_kind: 'advisor', report_ref: 'r1', match: 'boat-date', confidence: 0.9, created_at: NOW};
  insertRow(sql, 'fleet_trip_reports', pair);
  assert.throws(() => insertRow(sql, 'fleet_trip_reports', pair), /UNIQUE constraint failed: fleet_trip_reports/);
});

// US-B4: a skipper report and a landing report for a boat's trip date both resolve to the
// AIS trip through the fleet_trip_reports keys, with plain SQL. Landing reports live in the
// daily feed (id, boat, port, date), not D1; the fixture loads feed rows into a temp table
// with the port already resolved to a region port id. The pairing code is server/fleet/pairing.ts (#345).
dbTest('US-B4 join fixture: advisor and landing reports resolve to the trip', async () => {
  const sql = await upTo(14);
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,mmsi,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v1','CA','sea-example','Sea Example','sea example','morro-bay','338000001',?,?,?,?)`).run(NOW, NOW, NOW, NOW);
  sql.prepare(`INSERT INTO fleet_aliases(vessel_id,alias_norm,alias,kind,first_seen_at,last_seen_at)
    VALUES('v1','sea example ii','Sea Example II','report-name',?,?)`).run(NOW, NOW);
  insertRow(sql, 'fleet_trips', trip({status: 'closed'}));
  // Distractors: the same vessel the next day, and another vessel the same day.
  insertRow(sql, 'fleet_trips', trip({id: 't-next', departed_at: '2026-10-01T13:00:00Z', local_date: '2026-10-01'}));
  insertRow(sql, 'fleet_trips', trip({id: 't-other', vessel_id: 'v2', mmsi: '338000009'}));
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at,fleet_vessel_id)
    VALUES('boat1','sea-example-adv','Sea Example','morro-bay','morro-bay','verified',?,?,'v1')`).run(NOW, NOW);
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at)
    VALUES('boat2','unlinked-example','Unlinked Example','morro-bay','morro-bay','verified',?,?)`).run(NOW, NOW);
  const report = sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,created_at,updated_at)
    VALUES(?,?,'morro-bay','morro-bay',?,'{}','sms',?,?)`);
  report.run('r1', 'boat1', '2026-09-30', NOW, NOW);
  report.run('r-unlinked', 'boat2', '2026-09-30', NOW, NOW);
  sql.exec('CREATE TEMP TABLE landing_feed(id TEXT, boat TEXT, port TEXT, date TEXT)');
  const landing = sql.prepare('INSERT INTO landing_feed VALUES(?,?,?,?)');
  landing.run('land-1', 'Sea Example II', 'morro-bay', '2026-09-30');
  landing.run('land-other-port', 'Sea Example II', 'port-san-luis', '2026-09-30');

  // Advisor: advisor_reports.boat_id -> advisor_boats.fleet_vessel_id = trip vessel, report_date = local_date.
  const advisor = sql.prepare(`SELECT r.id report_ref, t.id trip_id FROM advisor_reports r
    JOIN advisor_boats b ON b.id = r.boat_id
    JOIN fleet_trips t ON t.vessel_id = b.fleet_vessel_id AND t.local_date = r.report_date ORDER BY r.id`).all();
  assert.deepEqual(advisor.map(r => ({...r})), [{report_ref: 'r1', trip_id: 't1'}]);
  // Landing: normalised boat name -> fleet_aliases.alias_norm, plus port and date.
  const landed = sql.prepare(`SELECT l.id report_ref, t.id trip_id FROM landing_feed l
    JOIN fleet_aliases a ON a.alias_norm = lower(trim(l.boat))
    JOIN fleet_trips t ON t.vessel_id = a.vessel_id AND t.local_date = l.date AND t.depart_port_id = l.port ORDER BY l.id`).all();
  assert.deepEqual(landed.map(r => ({...r})), [{report_ref: 'land-1', trip_id: 't1'}]);

  const pair = sql.prepare('INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at) VALUES(?,?,?,?,?,?)');
  for (const r of advisor) pair.run(r.trip_id, 'advisor', r.report_ref, 'boat-date', 0.9, NOW);
  for (const r of landed) pair.run(r.trip_id, 'landing', r.report_ref, 'alias-port-date', 0.8, NOW);
  // Back from each pairing to the report its key names.
  const paired = sql.prepare(`SELECT p.report_kind, p.match, coalesce(r.id, l.id) found, t.local_date FROM fleet_trip_reports p
    JOIN fleet_trips t ON t.id = p.trip_id
    LEFT JOIN advisor_reports r ON p.report_kind = 'advisor' AND r.id = p.report_ref
    LEFT JOIN landing_feed l ON p.report_kind = 'landing' AND l.id = p.report_ref
    WHERE p.trip_id = 't1' ORDER BY p.report_kind`).all();
  assert.deepEqual(paired.map(r => ({...r})), [
    {report_kind: 'advisor', match: 'boat-date', found: 'r1', local_date: '2026-09-30'},
    {report_kind: 'landing', match: 'alias-port-date', found: 'land-1', local_date: '2026-09-30'}]);
  // The trip_vessel_date index serves the (vessel, date) lookup.
  const plan = sql.prepare("EXPLAIN QUERY PLAN SELECT id FROM fleet_trips WHERE vessel_id='v1' AND local_date='2026-09-30'").all().map(r => r.detail).join(' ');
  assert.match(plan, /trip_vessel_date/);
});
