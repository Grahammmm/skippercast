// SCA-249 / F03-10: a fact.upsert that names facts in `supersedes` retires only facts of its own
// source. Contract protected: "a newer value from the same source supersedes the facts it names".
// Believable bug: the UPDATE matched vessel + field + id only, so an import naming a second source's
// current fact for the same field retired that independent record (lost corroboration/display).
// Synthetic data, in-memory D1 (tests/_advisor_d1.mjs); no network, no real rows.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {validateRegistry, applyRegistry} = await import('../server/fleet/registry.ts');

const skip = sqliteUnavailable ?? false;
const REGION = 'CA', T0 = '2026-10-05T09:47:00.000Z', T1 = '2026-10-12T09:47:00.000Z';
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex');
const VID = sha(`${REGION}:name-port:test-boat-1|morro-bay`).slice(0, 32);
const vessel = {op: 'vessel.upsert', id: VID, creation_key: 'name-port:test-boat-1|morro-bay', slug: 'test-boat-1', name: 'Test Boat 1',
  name_norm: 'TESTBOAT1', port_id: 'morro-bay', vessel_class: 'inspected-party', waters_json: ['ocean'], status: 'active',
  profile_status: 'listed', completeness: 0.5, first_seen_at: T0, last_seen_at: T0};
const fact = (source, value, extra = {}) => ({op: 'fact.upsert', vessel_id: VID, field: 'website', value_json: value, source_id: source,
  source_url: `https://${source}.example.test/boat-1`, method: 'registry', confidence: 0.9, rights: 'public-domain', retrieved_at: T0, ...extra});

async function apply(db, ops, now = T1) {
  const request = {region: REGION, runId: 'run-test', ops};
  const v = await validateRegistry(db, request);
  assert.equal(v.ok, true, JSON.stringify(v.errors));
  return applyRegistry(db, request, v.rows, now);
}
const current = sql => Object.fromEntries(sql.prepare('SELECT source_id, value_json, superseded_at FROM fleet_vessel_facts ORDER BY source_id, value_json').all()
  .map(r => [`${r.source_id}|${r.value_json}`, r.superseded_at]));
const idOf = (sql, source, value) => sql.prepare('SELECT id FROM fleet_vessel_facts WHERE source_id=? AND value_json=?').get(source, JSON.stringify(value)).id;

/** Two sources each hold a current website fact; returns their ids. */
async function seeded() {
  const {sql, db} = advisorDatabase();
  await apply(db, [vessel, fact('src-a', 'https://a-old.example.test/'), fact('src-b', 'https://b-old.example.test/')], T0);
  return {sql, db, a: idOf(sql, 'src-a', 'https://a-old.example.test/'), b: idOf(sql, 'src-b', 'https://b-old.example.test/')};
}

test('negative control: the pre-fix statement retires a second source (the scenario can fail)', {skip}, async () => {
  const {sql, a, b} = await seeded();
  try {
    // The statement as it was before SCA-249 (no source_id predicate), naming both facts.
    sql.prepare(`UPDATE fleet_vessel_facts SET superseded_at=?,superseded_by=? WHERE vessel_id=? AND field=? AND superseded_at IS NULL
      AND retrieved_at<=? AND id IN (?,?)`).run(T1, 'x', VID, 'website', T1, a, b);
    assert.equal(sql.prepare('SELECT count(*) n FROM fleet_vessel_facts WHERE superseded_at IS NOT NULL').get().n, 2, 'both sources retired');
  } finally { sql.close(); }
});

test('a correction from one source retires only that source\'s own old fact, even when it names another source\'s fact', {skip}, async () => {
  const {sql, db, a, b} = await seeded();
  try {
    const r = await apply(db, [fact('src-a', 'https://a-new.example.test/', {retrieved_at: T1, supersedes: [a, b]})]);
    assert.equal(r.changed, 2, 'one new fact inserted, one old fact superseded');
    assert.deepEqual(current(sql), {
      'src-a|"https://a-new.example.test/"': null,
      'src-a|"https://a-old.example.test/"': T1,
      'src-b|"https://b-old.example.test/"': null,   // the independent source stays current
    });
  } finally { sql.close(); }
});

test('positive control: a same-source correction still supersedes, and a stale replay stays harmless', {skip}, async () => {
  const {sql, db, a} = await seeded();
  try {
    const fresh = fact('src-a', 'https://a-new.example.test/', {retrieved_at: T1, supersedes: [a]});
    assert.equal((await apply(db, [fresh])).changed, 2);
    const before = current(sql);
    assert.equal(before['src-a|"https://a-old.example.test/"'], T1);
    // Replaying the identical correction, and an older replay of the old fact, change nothing.
    assert.equal((await apply(db, [fresh])).changed, 0);
    assert.equal((await apply(db, [fact('src-a', 'https://a-old.example.test/')], T0)).changed, 0);
    assert.deepEqual(current(sql), before);
  } finally { sql.close(); }
});
