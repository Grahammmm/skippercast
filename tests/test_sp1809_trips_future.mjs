// SP-18-v1 / SP1809-TRIPS-FUTURE. No copied SQL, sliced source or fake DB.
import './fixtures/sp1809_trips_future/offline.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const f = read('./fixtures/sp1809_trips_future/scenarios.json');
const previous = Object.fromEntries(['REGIONS', 'DEPLOYMENT'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
// Real static catalog inputs, as in the existing advisor suites, before imports.
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
if (sqliteUnavailable) throw new Error(sqliteUnavailable); // never skip
const {getTrips, MAX_BOATS, TRIP_TYPE_DAYS} = await import('../server/advisor/tools/get_trips.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {localDate, addDays} = await import('../server/advisor/answers/time.ts');
const {after} = await import('node:test');
after(() => {
  for (const [k, descriptor] of Object.entries(previous)) {
    if (descriptor) Object.defineProperty(globalThis, k, descriptor);
    else delete globalThis[k];
  }
});

const created = '2026-07-01T00:00:00Z';
function boat(sql, id, over = {}) {
  const b = {id, slug: id, name: id, landing: 'Example Landing', port: 'morro-bay', region: 'morro-bay', booking_url: null, status: 'verified', ...over};
  sql.prepare(`INSERT INTO advisor_boats(id,slug,name,landing,port,region,booking_url,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
    .run(b.id, b.slug, b.name, b.landing, b.port, b.region, b.booking_url, b.status, created, created);
}
function report(sql, id, boatId, date, type, status = 'published') {
  sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,trip_type,anglers,counts_json,source,status,verified,published_at,created_at,updated_at)
    VALUES(?,?,'morro-bay','morro-bay',?,?,20,'[]',?,?,1,?,?,?)`)
    .run(id, boatId, date, type, `text-${id}`, status, status === 'published' ? `${date}T22:00:00Z` : null, created, created);
}
function setup(t, primary = false) {
  const d = advisorDatabase();
  t.after(() => d.sql.close());
  if (primary) {
    for (const b of f.boats) boat(d.sql, b.id, b);
    for (const r of f.reports) report(d.sql, r.id, r.boat_id, r.report_date, r.trip_type, r.status);
  }
  return d;
}
async function trips(db, {port = 'morro-bay', now = f.now, language = 'en'} = {}) {
  return (await getTrips.run({port}, {db, now: Date.parse(now), env: {}, contact: {id: 'synthetic', role: 'angler'},
    message: {id: 'synthetic'}, language, settings: advisorSettings({}), deps: {
      fetcher: async () => { throw new Error('SP1809_MODEL_FORBIDDEN'); },
      feeds: async () => { throw new Error('SP1809_FEEDS_FORBIDDEN'); },
    }})).result;
}
const summary = out => out.boats.map(b => [b.name, b.last_report, b.trip_types]);
const cases = [
  ['control', 'SP1809 healthy control: Alpha before Beta with valid observed types', async t => {
    const {db} = setup(t, true);
    assert.equal(localDate(Date.parse(f.now)), f.today);
    assert.deepEqual(summary(await trips(db)), [['Alpha', '2026-10-24', ['half-day']], ['Beta', '2026-10-23', ['full-day']]]);
  }],
  ['primary', 'SP1809 A1 primary regression: future rows leave boat order recency and types unchanged', async t => {
    const {sql, db} = setup(t, true);
    const before = await trips(db);
    assert.deepEqual(summary(before), [['Alpha', '2026-10-24', ['half-day']], ['Beta', '2026-10-23', ['full-day']]]);
    report(sql, 'future-beta', 'beta', f.tomorrow, 'future-only overnight');
    report(sql, 'far-beta', 'beta', f.much_later, 'far-future-only');
    assert.deepEqual(await trips(db), before, 'SP1809_A1_FUTURE_INVARIANCE');
  }],
  ['A1', 'SP1809 A1 boundaries: yesterday today tomorrow much later and Pacific not UTC day', async t => {
    const {sql, db} = setup(t);
    boat(sql, 'alpha', {name: 'Alpha'}); boat(sql, 'beta', {name: 'Beta'});
    report(sql, 'yesterday', 'alpha', f.yesterday, 'yesterday-type');
    report(sql, 'today', 'beta', f.today, 'today-type');
    const before = await trips(db);
    assert.deepEqual(summary(before), [['Beta', f.today, ['today-type']], ['Alpha', f.yesterday, ['yesterday-type']]]);
    report(sql, 'tomorrow', 'alpha', f.tomorrow, 'tomorrow-type');
    report(sql, 'much-later', 'alpha', f.much_later, 'later-type');
    assert.deepEqual(await trips(db), before);
    assert.equal(localDate(Date.parse(f.pacific_evening)), f.today);
    assert.deepEqual(await trips(db, {now: f.pacific_evening}), before);
  }],
  ['A2', 'SP1809 A2 latest eligible past report including history older than sixty days', async t => {
    const {sql, db} = setup(t);
    boat(sql, 'mixed'); boat(sql, 'historical');
    report(sql, 'old', 'historical', '2026-01-01', 'old-type');
    report(sql, 'old-future', 'historical', f.much_later, 'future-type');
    report(sql, 'mixed-early', 'mixed', '2026-10-01', 'half-day');
    report(sql, 'mixed-late', 'mixed', f.yesterday, 'full-day');
    report(sql, 'mixed-future', 'mixed', f.tomorrow, 'future-type');
    assert.deepEqual(summary(await trips(db)), [['mixed', f.yesterday, ['full-day', 'half-day']], ['historical', '2026-01-01', []]]);
  }],
  ['A3', 'SP1809 A3 future-only and no-report verified boats remain listed with alphabetical null ties', async t => {
    const {sql, db} = setup(t);
    boat(sql, 'zulu'); boat(sql, 'alpha');
    report(sql, 'future-only', 'zulu', f.tomorrow, 'future-only');
    assert.deepEqual(summary(await trips(db)), [['alpha', null, []], ['zulu', null, []]]);
  }],
  ['A4', 'SP1809 A4 inclusive since and today boundaries with distinct types', async t => {
    const {sql, db} = setup(t); boat(sql, 'boundary');
    assert.equal(TRIP_TYPE_DAYS, 60);
    assert.equal(addDays(f.today, -TRIP_TYPE_DAYS), f.since);
    for (const [id, date, type] of [['before', f.before_since, 'excluded'], ['since', f.since, 'boundary'],
      ['today', f.today, 'today'], ['duplicate', f.today, 'today'], ['null', f.today, null], ['future', f.tomorrow, 'future']]) report(sql, id, 'boundary', date, type);
    assert.deepEqual(summary(await trips(db)), [['boundary', f.today, ['boundary', 'today']]]);
  }],
  ['A5', 'SP1809 A5 pending rejected and unpublished rows never qualify', async t => {
    const {sql, db} = setup(t);
    for (const status of ['verified', 'pending', 'rejected']) {
      boat(sql, status, {status}); report(sql, `${status}-pub`, status, f.yesterday, 'half-day');
    }
    for (const [i, status] of ['draft', 'withdrawn', 'pending', 'rejected'].entries()) {
      report(sql, `unpublished-${i}`, 'verified', f.today, `excluded-${status}`, status);
      report(sql, `unpublished-future-${i}`, 'verified', f.much_later, `future-${status}`, status);
    }
    assert.deepEqual(summary(await trips(db)), [['verified', f.yesterday, ['half-day']]]);
  }],
  ['A6', 'SP1809 A6 future report cannot displace an eligible boat under LIMIT twelve', async t => {
    const {sql, db} = setup(t);
    assert.equal(MAX_BOATS, 12);
    const names = Array.from({length: 12}, (_, i) => `eligible-${String(i).padStart(2, '0')}`);
    for (const name of names) { boat(sql, name); report(sql, `r-${name}`, name, f.yesterday, 'full-day'); }
    boat(sql, 'aaa-future');
    const before = await trips(db);
    assert.deepEqual(before.boats.map(b => b.name), names);
    report(sql, 'future-displacer', 'aaa-future', f.much_later, 'future-only');
    assert.deepEqual(await trips(db), before);
    assert.equal(before.boats.length, 12);
  }],
  ['A7', 'SP1809 A7 port booking few and unranked contracts unchanged', async t => {
    const {sql, db} = setup(t);
    boat(sql, 'https', {booking_url: 'https://example.com/book'}); boat(sql, 'none');
    boat(sql, 'insecure', {booking_url: 'http://example.com/book'});
    boat(sql, 'other', {port: 'port-san-luis'});
    report(sql, 'other-new', 'other', f.today, 'other-port');
    const out = await trips(db, {port: 'MB'});
    assert.equal(out.port, 'morro-bay'); assert.equal(out.port_name, 'Morro Bay');
    assert.deepEqual(out.boats.map(b => [b.name, b.booking_url]), [['https', 'https://example.com/book'], ['insecure', null], ['none', null]]);
    assert.equal(out.boats[0].boat_page, '{{link:boat:https}}');
    assert.equal(out.boats[0].landing, 'Example Landing');
    assert.equal(out.few, false); assert.match(out.note, /not ranked/);
    assert.match(out.note, /Never recommend one boat over another/);
    assert.equal(out.link, '{{link:port:morro-bay}}');
    const few = await trips(db, {port: 'Avila'});
    assert.deepEqual(summary(few), [['other', f.today, ['other-port']]]);
    assert.equal(few.few, true); assert.match(few.note, /the boats I work with so far/);
    assert.equal(few.link, '{{link:port:port-san-luis}}');
    const empty = await trips(db, {port: 'monterey'});
    assert.deepEqual([empty.boats, empty.few], [[], true]);
    assert.match(empty.note, /the boats I work with so far/);
  }],
];
const selection = process.env.SP1809_CASE ?? 'all';
if (!['all', 'primary', 'control'].includes(selection)) throw new Error('Unknown SP1809_CASE');
for (const [id, name, fn] of cases) if (selection === 'all' || selection === id) test(name, fn);
