// SP-15-v1: complete named request function, actual migration-backed SQLite.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {restoreOffline} from './fixtures/sp1506_field_provenance/offline.mjs';
// Synthetic build configuration precedes the full product closure, like the
// original fleet-admin test. No region payloads, production deployment or store.
const buildGlobals = {REGIONS: {}, DEPLOYMENT: {allowed_origins: ['https://example.com']},
  SHELLS: {}, BUILD_ID: 'sp1506-synthetic'};
const savedGlobals = new Map(Object.keys(buildGlobals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
Object.assign(globalThis, buildGlobals);
test.after(() => {
  for (const [key, descriptor] of savedGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
});
// Dynamic imports ensure sentinels and configuration precede product imports.
const {advisorDatabase, sqliteUnavailable} = await import('./_advisor_d1.mjs');
const {vesselDetail} = await import('../server/fleet/admin/vessels.ts');
const F = JSON.parse(readFileSync(new URL('./fixtures/sp1506_field_provenance/cases.json', import.meta.url)));
if (sqliteUnavailable) throw new Error(sqliteUnavailable); // never skip acceptance
const hash = value => createHash('sha256').update(value).digest('hex');
const factID = key => hash(`sp1506:${key}`).slice(0, 32);
test.after(restoreOffline);
function setup() {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,year_built,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,'CA','synthetic-sp1506','Synthetic SP1506','SYNTHETICSP1506',?,?,?,?,?)`)
    .run(F.vessel_id, F.year_built, F.time, F.time, F.time, F.time);
  function fact(key, {field = 'year_built', value = F.year_built, method = 'page', confidence = 0.8,
    time = F.time, superseded = null, id = factID(key)} = {}) {
    sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,
      retrieved_at,first_seen_at,last_seen_at,superseded_at,run_id) VALUES(?,?,?,?,?,?,?,?,?,'facts-only',?,?,?,?,NULL)`)
      .run(id, F.vessel_id, field, JSON.stringify(value), hash(JSON.stringify(value)).slice(0, 16),
        method === 'admin' ? 'admin' : 'synthetic', `https://example.com/sp1506/${key}`, method, confidence, time, time, time, superseded);
    return id;
  }
  function history(count, field = 'beam_ft', current = false) {
    for (let i = 0; i < count; i++) fact(`history-${field}-${i}`, {field, value: field === 'beam_ft' ? 20 : 1900,
      superseded: current ? null : F.later});
  }
  // Detail must only read; every statement still runs against real SQLite.
  const readDB = {prepare(query) {
    assert.match(query.trim(), /^SELECT\b/i, 'detail may not mutate storage');
    return db.prepare(query);
  }, batch() { throw new Error('SP1506_LIVE_STORE: writes forbidden'); }};
  const snapshot = () => JSON.stringify(['fleet_vessels', 'fleet_vessel_facts'].map(table => sql.prepare(`SELECT * FROM ${table} ORDER BY id`).all()));
  async function detail() {
    const before = snapshot();
    const out = await vesselDetail(readDB, F.vessel_id);
    assert.equal(snapshot(), before, 'detail leaves columns, facts and pins unchanged');
    return out;
  }
  return {sql, fact, history, detail};
}

test('primary regression', async () => {
  const s = setup();
  try {
    s.history(F.history_cap);
    s.fact('winner', {id: F.winner_id});
    const out = await s.detail();
    assert.equal(out.fields.year_built.fact_id, F.winner_id, 'A1: current year_built provenance survives earlier-field cap');
  } finally { s.sql.close(); }
});

test('healthy control', async () => {
  const s = setup();
  try {
    s.fact('winner', {id: F.winner_id});
    assert.equal((await s.detail()).fields.year_built.fact_id, F.winner_id);
  } finally { s.sql.close(); }
});

// Baseline selection is explicit registration, not skipped tests.
if (!process.argv.includes('--sp1506-baseline')) {
  test('A2: own large history excludes superseded and different-value facts', async () => {
    for (const current of [false, true]) {
      const s = setup();
      try {
        s.history(F.history_cap + 1, 'year_built', current);
        s.fact('superseded-admin', {method: 'admin', confidence: 1, superseded: F.later});
        s.fact('wrong-admin', {value: 2000, method: 'admin', confidence: 1});
        s.fact('winner', {id: F.winner_id, time: '2020-01-01T00:00:00.000Z'});
        const out = await s.detail();
        assert.equal(out.fields.year_built.fact_id, F.winner_id);
        assert.equal(out.facts.length, F.history_cap);
        assert.equal(out.facts_truncated, true);
      } finally { s.sql.close(); }
    }
  });

  test('A3: admin, confidence, recency, stable ID ties and unknown stay compatible', async () => {
    const cases = [
      [{method: 'admin', confidence: 0.1}, {confidence: 1, time: F.later}],
      [{confidence: 0.9}, {confidence: 0.8, time: F.later}],
      [{time: F.later}, {time: F.time}],
      [{id: '1'.repeat(32)}, {id: '2'.repeat(32)}],
    ];
    for (const [winner, loser] of cases) {
      const s = setup();
      try {
        s.fact('loser', loser);
        const id = s.fact('winner', winner);
        assert.equal((await s.detail()).fields.year_built.fact_id, id);
      } finally { s.sql.close(); }
    }
    const s = setup();
    try {
      s.fact('wrong', {value: 2000});
      s.fact('old', {superseded: F.later});
      const out = await s.detail();
      assert.equal(out.fields.year_built.fact_id, null);
      assert.equal(out.fields.beam_ft.fact_id, null);
    } finally { s.sql.close(); }
  });

  test('A4: exact cap and cap-plus-one report truncation without losing provenance', async () => {
    for (const count of [F.history_cap, F.history_cap + 1]) {
      const s = setup();
      try {
        s.history(count - 1);
        s.fact('winner', {id: F.winner_id});
        const out = await s.detail();
        assert.equal(out.facts.length, F.history_cap);
        assert.equal(out.facts_truncated, count > F.history_cap);
        assert.equal(out.fields.year_built.fact_id, F.winner_id);
      } finally { s.sql.close(); }
    }
  });

  test('A4: small fixture retains facts, JSON/null provenance and pins', async () => {
    const s = setup();
    try {
      const pin = {by: 'synthetic-admin', at: F.time, fact_id: F.winner_id};
      s.sql.prepare('UPDATE fleet_vessels SET pinned_json=?,waters_json=? WHERE id=?')
        .run(JSON.stringify({year_built: pin}), '["ocean"]', F.vessel_id);
      s.fact('winner', {id: F.winner_id});
      const waters = s.fact('waters', {field: 'waters', value: ['ocean']});
      const beam = s.fact('beam-null', {field: 'beam_ft', value: null});
      const out = await s.detail();
      assert.equal(out.facts_truncated, false);
      assert.deepEqual(out.fields.year_built, {value: F.year_built, pinned: pin, fact_id: F.winner_id});
      assert.deepEqual(out.fields.waters_json, {value: ['ocean'], pinned: null, fact_id: waters});
      assert.equal(out.fields.beam_ft.fact_id, beam);
      assert.deepEqual(out.vessel.pinned, ['year_built']);
      assert.deepEqual(out.facts.map(f => f.id).sort(), [F.winner_id, waters, beam].sort());
      const raw = s.sql.prepare(`SELECT id,field,value_json,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at,
        superseded_at,superseded_by,run_id FROM fleet_vessel_facts WHERE vessel_id=? ORDER BY field,superseded_at IS NOT NULL,retrieved_at DESC,id`).all(F.vessel_id);
      assert.deepEqual(out.facts, raw.map(({value_json, ...f}) => ({...f, value: JSON.parse(value_json)})));
    } finally { s.sql.close(); }
  });
}
