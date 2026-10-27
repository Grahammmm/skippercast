// Synthetic-only public pairing APIs and migration-backed in-memory D1.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const fixture = read('./fixtures/sp1302_landing_conflict/reports.json');
const {a, b, healthy, now, from} = fixture;
// Catalogue port/region identities are public inert metadata; every feed is injected.
globalThis.REGIONS = {
  'morro-bay': {daily_feed: 'https://example.invalid/synthetic-one'},
  'southern-california': {daily_feed: 'https://example.invalid/synthetic-two'},
};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {landingRows, landingPairs, landingPrune, advisorPairs, advisorPrune, pairingDeps} = await import('../server/fleet/pairing.ts');
assert.equal(sqliteUnavailable, null, 'migration-backed D1 is mandatory, never skipped');
const originalRead = pairingDeps.readFeed;
test.after(() => { pairingDeps.readFeed = originalRead; });
const ports = ['morro-bay', 'port-san-luis', 'santa-barbara'];
const scope = {sql: 't.region=?', args: ['CA']};
const row = r => ({id: r.id, norm: 'ALPHAEXAMPLE', port: 'morro-bay', date: r.date});
function feeds(first, second = []) {
  pairingDeps.readFeed = async url => {
    const reports = url.endsWith('synthetic-one') ? first : second;
    if (reports instanceof Error) throw reports;
    return {reports};
  };
}
async function collect(first, second = [], wanted = ports) {
  feeds(first, second);
  return landingRows(wanted, from);
}
function database() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,port_id,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES('v-example','CA','alpha-example','Alpha Example','ALPHAEXAMPLE','morro-bay',?,?,?,?)`).run(now, now, now, now);
  const insert = sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,depart_port_id,return_port_id,departed_at,returned_at,local_date,season,season_part,status,distance_nm,max_offshore_nm,fishing_min,positions_n,gap_min,source,rights,classifier_version,computed_at)
    VALUES(?,'CA','v-example','999000301','morro-bay','morro-bay',?,'2026-10-01T20:00:00.000Z','2026-10-01','2026','fall','closed',12.5,4.2,?,300,0,'aisstream','internal-only','c1-0123456789abcdef',?)`);
  insert.run('trip-example', '2026-10-01T15:00:00.000Z', 70, now);
  return {sql, db, insert};
}
const pairs = sql => sql.prepare('SELECT trip_id,report_kind,report_ref,match,confidence,created_at FROM fleet_trip_reports ORDER BY report_kind,report_ref').all().map(r => ({...r}));
const expected = id => ({trip_id: 'trip-example', report_kind: 'landing', report_ref: id, match: 'alias-port-date', confidence: 0.8, created_at: now});
async function sweep(db, rows) {
  await db.batch([advisorPrune(db, scope), ...landingPrune(db, 'CA', scope, rows), advisorPairs(db, scope, now), ...landingPairs(db, 'CA', scope, rows, now)]);
}

test('primary regression', async t => {
  const result = await collect([a, b, a], [], ['morro-bay']);
  // Historical baseline may encounter a product SQL exception on these rows.
  // Preserve it as observed data BEFORE the semantic assertion, not a harness pass.
  const {sql, db} = database();
  try {
    try { await sweep(db, result.rows); }
    catch (error) { t.diagnostic(`observed product exception: ${error.code ?? ''}: ${error.message}`); }
    assert.deepEqual(result.rows, [], 'conflicting normalized names must withhold this report ID');
    assert.deepEqual(pairs(sql), [], 'withheld report creates no landing pair');
  } finally { sql.close(); }
});

test('healthy control', async () => {
  const result = await collect([healthy, {...healthy, boat: 'ALPHA EXAMPLE'}], [], ['morro-bay']);
  assert.deepEqual(result, {rows: [row(healthy)], feeds: 1, unavailable: 0});
  const {sql, db} = database();
  try {
    await sweep(db, result.rows);
    assert.deepEqual(pairs(sql), [expected(healthy.id)]);
    await sweep(db, result.rows);
    assert.deepEqual(pairs(sql), [expected(healthy.id)], 'repeat remains one pair');
  } finally { sql.close(); }
});

// Baseline registers ONLY the required pair; there are no filtered/skipped tests.
if (process.env.SP1302_BASELINE !== '1') {
  test('A1 every A-B-A permutation is withheld and A-A agrees', async () => {
    for (const records of [[a,b,a], [b,a,a], [a,a,b]]) {
      assert.deepEqual((await collect(records)).rows, [], JSON.stringify(records));
    }
    assert.deepEqual((await collect([a,a])).rows, [row(a)]);
    assert.deepEqual((await collect([a,{...a, boat: 'The Alpha Example'}])).rows, [row(a)]);
  });

  test('A2 independent name port date conflicts within and across two valid feeds', async () => {
    for (const other of [b, {...a, port: 'Avila Beach'}, {...a, date: '2026-10-02'}]) {
      for (const records of [[a,other,a], [other,a,a], [a,a,other]]) {
        assert.deepEqual((await collect(records)).rows, [], JSON.stringify(other));
      }
      for (const [left, right] of [[[a,a],[other]], [[other],[a,a]]]) {
        const result = await collect(left, right);
        assert.deepEqual(result, {rows: [], feeds: 2, unavailable: 0});
      }
    }
    assert.deepEqual((await collect([a,a])).rows, [row(a)], 'conflict state is per call');
    const p = {...a, port: 'Avila Beach'};
    assert.deepEqual((await collect([p,{...p, port: 'Port San Luis'}])).rows,
      [{...row(a), port: 'port-san-luis'}], 'catalogue aliases agree on canonical port');
  });

  test('A2 eligibility and distinct healthy IDs survive conflict and unavailable feeds', async () => {
    const south = {...healthy, id: 'south-example', port: 'Santa Barbara'};
    const irrelevant = [
      {...b, port: 'Unknown Example Port'}, {...b, port: 'Santa Cruz'},
      {...b, date: '2026-09-03'}, {...b, date: 'not-a-date'},
      {...b, boat: ''}, {...b, boat: null}, {...b, id: null},
    ];
    for (const records of [[...irrelevant,a], [a,...irrelevant]]) {
      assert.deepEqual((await collect(records, [south])).rows,
        [row(a), {...row(south), port: 'santa-barbara'}]);
    }
    assert.deepEqual(await collect([a,b,a,healthy], [south]), {
      rows: [row(healthy), {...row(south), port: 'santa-barbara'}], feeds: 2, unavailable: 0,
    });
    assert.deepEqual(await collect(new Error('synthetic feed unavailable'), [south]), {
      rows: [{...row(south), port: 'santa-barbara'}], feeds: 2, unavailable: 1,
    });
    pairingDeps.readFeed = async () => ({notReports: []});
    assert.deepEqual(await landingRows(['morro-bay'], from), {rows: [], feeds: 1, unavailable: 1});
    assert.deepEqual(await landingRows([], from), {rows: [], feeds: 0, unavailable: 0});
  });

  test('A3 D1 conflict omission preserves stored pairs and healthy ranking and advisor attribution', async () => {
    const {sql, db, insert} = database();
    try {
      insert.run('trip-short-example', '2026-10-01T08:00:00.000Z', 30, now);
      await sweep(db, (await collect([a])).rows);
      assert.deepEqual(pairs(sql), [expected(a.id)]);
      // Insert a linked published advisor report using the same migrated schema.
      sql.prepare(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at,fleet_vessel_id)
        VALUES('boat-example','advisor-example','Alpha Example','morro-bay','morro-bay','verified',?,?,'v-example')`).run(now, now);
      sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,status,created_at,updated_at)
        VALUES('advisor-example','boat-example','morro-bay','morro-bay','2026-10-01','{}','sms','published',?,?)`).run(now, now);
      const freshConflict = {...a, id: 'new-conflict-example'};
      await sweep(db, (await collect([a,b,a,freshConflict,{...freshConflict, boat: b.boat},healthy])).rows);
      assert.deepEqual(pairs(sql), [
        {...expected('advisor-example'), report_kind: 'advisor', match: 'boat-date', confidence: 0.9},
        expected(a.id), expected(healthy.id),
      ], 'old conflicted pair remains; new conflicted ID omitted; healthy and advisor pair');
      insert.run('trip-earlier-example', '2026-10-01T10:00:00.000Z', 70, now);
      await sweep(db, (await collect([a,b,healthy])).rows);
      assert.deepEqual(pairs(sql), [
        {...expected('advisor-example'), trip_id: 'trip-earlier-example', report_kind: 'advisor', match: 'boat-date', confidence: 0.9},
        expected(a.id), {...expected(healthy.id), trip_id: 'trip-earlier-example'},
      ], 'only visible reports rerank, preserving omitted historical attribution');
      const before = pairs(sql);
      const missing = await collect(new Error('synthetic unavailable'), [], ['morro-bay']);
      assert.deepEqual(missing, {rows: [], feeds: 1, unavailable: 1});
      await sweep(db, missing.rows);
      assert.deepEqual(pairs(sql), before, 'unavailable landing reports retain stored pairings');
      sql.prepare("UPDATE advisor_reports SET status='withdrawn' WHERE id='advisor-example'").run();
      await sweep(db, []);
      assert.deepEqual(pairs(sql), before.filter(r => r.report_kind === 'landing'));
    } finally { sql.close(); }
  });
}
