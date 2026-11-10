// The admin fleet operator list ranks every matching operator before the 500-row cap
// (RF0854-8; docs/plans/charter-fleet/design.md § 13): do-not-contact last, then lead score,
// then name, then id. Real migrations in node:sqlite, the actual listOperators, a fixed clock
// and synthetic operators only (example ids, no contact details).
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const {listOperators, OPERATOR_LIMIT} = await import('../server/fleet/admin/operators.ts');
const skip = sqliteUnavailable ?? false;
const NOW = '2026-11-09T17:00:00.000Z', SEEN = '2026-11-08T17:00:00.000Z';
const AIS = 20, SOCIAL = 25;   // catalog/fleet/lead-score.json weights x scale
const pad = n => String(n).padStart(5, '0');

/** A database holding `ops` ({id, name, region?, outreach?, consent?, ais?, social?}). */
function fixture(ops) {
  const {sql, db} = advisorDatabase();
  const op = sql.prepare('INSERT INTO fleet_operators(id,region,slug,name,consent_status,outreach_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)');
  const vessel = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,operator_id,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,?,?,'Synthetic Boat','SYNTHETICBOAT',?,?,?,?,?)`);
  const watch = sql.prepare(`INSERT INTO fleet_ais_watch(region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,last_seen_at,updated_at)
    VALUES(?,?,?,'admin',1,'watched',?,?,?)`);
  const fact = sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at)
    VALUES(?,?,'social.instagram.url','"https://www.instagram.com/boat.example/"',?,'operator-site','https://boat.example.com/','page',0.8,'facts-only',?,?,?)`);
  sql.exec('BEGIN');
  ops.forEach((o, i) => {
    const region = o.region ?? 'CA';
    op.run(o.id, region, o.id, o.name, o.consent ?? 'unknown', o.outreach ?? 'none', NOW, NOW);
    if (!o.ais && !o.social) return;
    const v = `v${pad(i)}`.padEnd(32, '0');
    vessel.run(v, region, `boat-${o.id}`, o.id, NOW, NOW, NOW, NOW);
    if (o.ais) watch.run(region, String(999000000 + i), v, NOW, SEEN, NOW);
    if (o.social) fact.run(`f${pad(i)}`.padEnd(32, '0'), v, `k${i}`, NOW, NOW, NOW);
  });
  sql.exec('COMMIT');
  return {sql, db};
}

const score = o => (o.ais ? AIS : 0) + (o.social ? SOCIAL : 0);
/** The expected global order, built from the fixture itself, not from the code under test. */
const expected = ops => [...ops].sort((a, b) => Number(a.outreach === 'do-not-contact') - Number(b.outreach === 'do-not-contact')
  || score(b) - score(a) || a.name.localeCompare(b.name) || (a.id < b.id ? -1 : 1)).slice(0, OPERATOR_LIMIT).map(o => o.id);

async function check(ops, q, msg) {
  const {sql, db} = fixture(ops);
  try {
    const out = await listOperators(db, q, NOW);
    const ids = out.operators.map(o => o.id);
    assert.ok(ids.length <= OPERATOR_LIMIT, `${msg}: at most ${OPERATOR_LIMIT} rows`);
    assert.equal(new Set(ids).size, ids.length, `${msg}: no repeated operator`);
    const match = ops.filter(o => (!q.region || (o.region ?? 'CA') === q.region) && (!q.consent_status || (o.consent ?? 'unknown') === q.consent_status)
      && (!q.outreach_status || (o.outreach ?? 'none') === q.outreach_status));
    assert.ok(isDeepStrictEqual(ids, expected(match)), `${msg}: the global ranked prefix`);
    assert.equal(out.truncated, match.length > OPERATOR_LIMIT, `${msg}: truncated`);
    for (const o of out.operators) assert.equal(o.lead_score.score, score(ops.find(x => x.id === o.id)), `${msg}: ${o.id} score`);
    return out;
  } finally { sql.close(); }
}

const zeros = (n, prefix = 'op-a-', name = i => `A Synthetic ${pad(i)}`) => Array.from({length: n}, (_, i) => ({id: prefix + pad(i), name: name(i)}));

test('global_operator_ranking_includes_late_high_score: the best operator past the alphabetical cap ranks first', {skip}, async () => {
  // The reproduced case: 500 zero-score A-named operators and one Z-named operator seen on AIS.
  const z = {id: 'op-z-00000', name: 'Z Synthetic', ais: true};
  const out = await check([...zeros(OPERATOR_LIMIT), z], {region: 'CA'}, '501 rows');
  assert.equal(out.operators[0].id, z.id);
  assert.equal(out.operators[0].lead_score.score, AIS);
  assert.ok(!out.operators.some(o => o.id === `op-a-${pad(OPERATOR_LIMIT - 1)}`), 'the last zero-score A is cut');
  // Three fetch pages; the winners sort last by id and by name, so they arrive on the last page.
  const late = [{id: 'op-z-00001', name: 'Zz Late Best', ais: true, social: true}, {id: 'op-z-00002', name: 'Zz Late Next', social: true}, z];
  const big = await check([...zeros(1100), ...late], {}, '1103 rows');
  assert.deepEqual(big.operators.slice(0, 3).map(o => [o.id, o.lead_score.score]), [['op-z-00001', 45], ['op-z-00002', 25], ['op-z-00000', 20]]);
});

test('global_operator_ranking_puts_do_not_contact_last_before_cap', {skip}, async () => {
  // 100 early-named do-not-contact operators outscore 500 later eligible ones: the eligible fill the cap.
  const dnc = zeros(100, 'op-a-', i => `A Blocked ${pad(i)}`).map(o => ({...o, outreach: 'do-not-contact', ais: true, social: true}));
  const eligible = zeros(OPERATOR_LIMIT, 'op-b-', i => `B Synthetic ${pad(i)}`);
  const out = await check([...dnc, ...eligible], {}, 'dnc over cap');
  assert.ok(!out.operators.some(o => o.outreach_status === 'do-not-contact'), 'no do-not-contact operator inside the cap');
  // One eligible fewer than the cap: the best do-not-contact fills the last place.
  const short = await check([...dnc, ...eligible.slice(1)], {}, 'dnc fills the gap');
  assert.equal(short.operators.at(-1).id, dnc[0].id);
  // A small set is unchanged: do-not-contact last, then score, then name.
  const small = [{id: 'op-s-1', name: 'Alpha', outreach: 'do-not-contact', ais: true, social: true}, {id: 'op-s-2', name: 'Bravo'}, {id: 'op-s-3', name: 'Charlie', ais: true}];
  const few = await check(small, {}, 'small set');
  assert.deepEqual(few.operators.map(o => o.id), ['op-s-3', 'op-s-2', 'op-s-1']);
});

test('global_operator_ranking_filters_every_page: excluded rows never rank or count', {skip}, async () => {
  // 1400 rows in id order: every 2nd row is OR, every 3rd is partner; excluded rows score highest.
  const ops = Array.from({length: 1400}, (_, i) => {
    const region = i % 2 ? 'OR' : 'CA', consent = i % 3 ? 'unknown' : 'partner', outreach = i % 5 ? 'none' : 'replied';
    const hit = region === 'CA' && consent === 'partner';
    return {id: `op-f-${pad(i)}`, name: `F Synthetic ${pad(i)}`, region, consent, outreach, ais: hit ? i % 7 === 0 : true, social: !hit};
  });
  await check(ops, {region: 'CA'}, 'region only (700 matches)');
  await check(ops, {region: 'CA', consent_status: 'partner'}, 'region and consent (234 matches)');
  await check(ops, {region: 'OR', consent_status: 'unknown', outreach_status: 'none'}, 'three filters');
  const out = await check(ops, {region: 'CA', consent_status: 'partner'}, 'filtered winners');
  assert.ok(out.operators.every(o => o.region === 'CA' && o.consent_status === 'partner'));
  assert.equal(out.truncated, false);
});

test('global_operator_ranking_empty_exact_and_over_cap: 0, 1, 499, 500, 501 and 1003 matches', {skip}, async () => {
  // Equal names and scores order by id; the rows either side of each cursor boundary score higher.
  const boundary = new Set([0, 499, 500, 501, 1000, 1001, 1002]);
  for (const n of [0, 1, 499, 500, 501, 1003]) {
    const ops = Array.from({length: n}, (_, i) => ({id: `op-e-${pad(i)}`, name: 'Same Name', ais: boundary.has(i)}));
    const out = await check(ops, {}, `${n} rows`);
    assert.equal(out.operators.length, Math.min(n, OPERATOR_LIMIT));
  }
});

test('global_operator_ranking_is_bounded_and_read_only: keyset pages, one score scope, no writes', {skip}, async () => {
  const ops = [...zeros(1100), {id: 'op-z-00000', name: 'Z Synthetic', ais: true}];
  const {sql, db} = fixture(ops);
  try {
    const log = [];
    const spy = {prepare(q) { const s = db.prepare(q), entry = {q, args: []}; log.push(entry); return {...s, bind(...a) { entry.args = a; s.bind(...a); return this; }, all: () => s.all(), first: () => s.first(), run: () => s.run()}; }};
    const before = sql.prepare('SELECT total_changes() AS n').get().n, rows = sql.prepare('SELECT * FROM fleet_operators ORDER BY id').all();
    const out = await listOperators(spy, {region: 'CA'}, NOW);
    assert.equal(out.operators[0].id, 'op-z-00000');
    assert.equal(out.truncated, true);
    assert.ok(log.every(e => !/\bOFFSET\b/i.test(e.q) && /^\s*SELECT\b/i.test(e.q)), 'reads only, no OFFSET');
    const pages = log.filter(e => /ORDER BY o\.id\b/.test(e.q));
    assert.equal(pages.length, 3, '1101 rows read in three pages');
    assert.ok(pages.every(e => e.args.at(-1) <= OPERATOR_LIMIT + 1 && e.args[0] === 'CA'), 'page size bound and the filter on every page');
    const cursors = pages.slice(1).map(e => e.args.at(-2));
    assert.deepEqual(cursors, ['op-a-00500', 'op-a-01001'], 'forward-only cursor from the last fetched id');
    assert.equal(log.length - pages.length, 4, 'one leadInputs scope calculation, no per-operator scoring');
    assert.equal(sql.prepare('SELECT total_changes() AS n').get().n, before, 'no writes');
    assert.ok(isDeepStrictEqual(sql.prepare('SELECT * FROM fleet_operators ORDER BY id').all(), rows), 'operators unchanged');
  } finally { sql.close(); }
});
