// RF1300-6: get_trips lists at most MAX_BOATS (12) verified boats; when a port has
// more, the result says how many more (`more: n`) and the note tells the model to
// say so and link the port page. With 12 or fewer the result is exactly as before.
// Offline: real migrations in node:sqlite through tests/_advisor_d1.mjs, synthetic
// boats only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {getTrips, MAX_BOATS} = await import('../server/advisor/tools/get_trips.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const NOW = Date.parse('2026-10-25T19:00:00Z'); // 2026-10-25 in Pacific time
const CREATED = '2026-07-01T00:00:00Z';
const LISTED = 'Listed by most recent report, not ranked. Never recommend one boat over another.';

function setup(t) {
  const d = advisorDatabase();
  t.after(() => d.sql.close());
  return d;
}
function boat(sql, id, {port = 'morro-bay', status = 'verified', name = `Sea Example ${id}`} = {}) {
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,status,created_at,updated_at) VALUES(?,?,?,'Example Landing',?,'morro-bay',?,?,?)`)
    .run(id, id, name, port, status, CREATED, CREATED);
}
function report(sql, id, boatId, date) {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES(?,?,'morro-bay','morro-bay',?,'half-day',20,'[]','text','published',1,?,?,?)`)
    .run(id, boatId, date, `${date}T22:00:00Z`, CREATED, CREATED);
}
/** n verified boats in a port, boat i reported on 2026-10-(i+1) so the newest is the last one. */
function boats(sql, n, {port = 'morro-bay', prefix = 'b', reports = true} = {}) {
  for (let i = 0; i < n; i++) {
    const id = `${prefix}${String(i).padStart(2, '0')}`;
    boat(sql, id, {port});
    if (reports) report(sql, `r-${id}`, id, `2026-10-${String(i + 1).padStart(2, '0')}`);
  }
}
async function trips(db, port = 'morro-bay') {
  return (await getTrips.run({port}, {db, now: NOW, env: {}, contact: {id: 'synthetic', role: 'angler'}, message: {id: 'synthetic'},
    language: 'en', settings: advisorSettings({}), deps: {}})).result;
}

dbTest('RF1300-6 exactly 12 verified boats: 12 listed, no more key, note unchanged', async t => {
  const {sql, db} = setup(t);
  assert.equal(MAX_BOATS, 12);
  boats(sql, 12);
  const out = await trips(db);
  assert.equal(out.boats.length, 12);
  assert.ok(!('more' in out), 'no more key at 12');
  assert.equal(out.few, false);
  assert.equal(out.note, LISTED);
});

dbTest('RF1300-6 13 and 20 verified boats: more 1 (boat) and more 8 (boats)', async t => {
  const {sql, db} = setup(t);
  boats(sql, 13);
  const one = await trips(db);
  assert.equal(one.boats.length, 12);
  assert.equal(one.more, 1);
  assert.equal(one.note, `${LISTED} 1 more verified boat is on the port page; say so and link it.`);
  assert.equal(one.link, '{{link:port:morro-bay}}');
  boats(sql, 7, {prefix: 'x'});
  const eight = await trips(db);
  assert.equal(eight.boats.length, 12);
  assert.equal(eight.more, 8);
  assert.equal(eight.note, `${LISTED} 8 more verified boats are on the port page; say so and link it.`);
});

dbTest('RF1300-6 only verified boats are counted: 12 verified plus pending and rejected gives no more', async t => {
  const {sql, db} = setup(t);
  boats(sql, 12);
  for (const [i, status] of ['pending', 'pending', 'pending', 'rejected', 'rejected'].entries()) boat(sql, `u${i}`, {status});
  const out = await trips(db);
  assert.equal(out.boats.length, 12);
  assert.ok(!('more' in out), 'unverified boats never counted');
  assert.equal(out.note, LISTED);
  assert.ok(out.boats.every(b => b.name.startsWith('Sea Example b')), 'unverified boats never listed');
});

dbTest('RF1300-6 boats in another port are not counted', async t => {
  const {sql, db} = setup(t);
  boats(sql, 12);
  boats(sql, 3, {port: 'port-san-luis', prefix: 'p'});
  const out = await trips(db);
  assert.ok(!('more' in out), 'other port not counted');
  assert.equal(out.note, LISTED);
  const other = await trips(db, 'port-san-luis');
  assert.equal(other.boats.length, 3);
  assert.ok(!('more' in other));
});

dbTest('RF1300-6 order kept: the 12 listed are the most recently reported, the unreported 13th is the one counted', async t => {
  const {sql, db} = setup(t);
  boats(sql, 12);
  boat(sql, 'aaa', {name: 'AAA Sea Example'}); // alphabetically first, never reported
  const out = await trips(db);
  assert.equal(out.more, 1);
  const expected = Array.from({length: 12}, (_, i) => `Sea Example b${String(11 - i).padStart(2, '0')}`);
  assert.deepEqual(out.boats.map(b => b.name), expected);
  assert.deepEqual(out.boats.map(b => b.last_report), expected.map((_, i) => `2026-10-${String(12 - i).padStart(2, '0')}`));
  assert.ok(!out.boats.some(b => b.name === 'AAA Sea Example'));
});

dbTest('RF1300-6 few boats: one verified boat is few with no more key', async t => {
  const {sql, db} = setup(t);
  boats(sql, 1);
  const out = await trips(db);
  assert.equal(out.few, true);
  assert.ok(!('more' in out));
  assert.match(out.note, /the boats I work with so far/);
  const empty = await trips(db, 'port-san-luis');
  assert.deepEqual([empty.boats, empty.few, 'more' in empty], [[], true, false]);
});
