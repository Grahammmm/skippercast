// SCA-613 / F02-09: a statewide cap must not hide a species' older in-window catch.
// CI qualifies the fixture; `node tests/test_f02_09_audit.mjs --baseline` also
// prints a read-only receipt from the checkout's unmodified recentCatches.
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';

// Synthetic build bindings; no deployment configuration or external I/O.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {recentCatches} = await import('../server/advisor/pages/species.ts');
const {exactSpecies} = await import('../server/advisor/answers/resolve.ts');
const {countLines} = await import('../server/advisor/pages/render.ts');

const key = 'vermilion', from = '2026-01-01', to = '2026-01-14';
const target = [
  {species_key: key, label: 'fixture-key-only', kept: 2, released: 1},
  {species_key: 'rockfish', label: 'colorados', kept: 3, released: 4},
];
const other = {species_key: 'lingcod', label: 'lingcod', kept: 9, released: 8};
const olderCatch = {date: from, port: 'fixture-port', kept: 5, released: 5, boats: 1};

async function replay({busy = true, speciesFirst = false} = {}) {
  const sql = new DatabaseSync(':memory:');
  try {
    sql.exec(`CREATE TABLE advisor_boats (id TEXT PRIMARY KEY, status TEXT NOT NULL);
      CREATE TABLE advisor_reports (id INTEGER PRIMARY KEY, boat_id TEXT, port TEXT,
        report_date TEXT, counts_json TEXT, status TEXT, verified INTEGER);`);
    const boat = sql.prepare('INSERT INTO advisor_boats VALUES (?, ?)');
    const report = sql.prepare(`INSERT INTO advisor_reports
      (boat_id, port, report_date, counts_json, status, verified) VALUES (?, ?, ?, ?, ?, ?)`);
    const add = (id, port, date, lines, status = 'published', verified = 1) =>
      report.run(id, port, date, JSON.stringify(lines), status, verified);
    boat.run('fixture-verified', 'verified');
    boat.run('fixture-unverified', 'pending');
    // Only one eligible in-window target in the busy case. The unrelated line
    // in that same report must not contribute to the port/day totals either.
    add('fixture-verified', 'fixture-port', from, [...target, other]);
    add('fixture-verified', 'fixture-before', '2025-12-31', target);
    add('fixture-verified', 'fixture-after', '2026-01-15', target);
    add('fixture-verified', 'fixture-draft', to, target, 'draft');
    add('fixture-verified', 'fixture-report-unverified', to, target, 'published', 0);
    add('fixture-unverified', 'fixture-boat-unverified', to, target);
    if (busy) {
      for (let i = 0; i < 500; i++) {
        const id = `fixture-padding-${i}`;
        boat.run(id, 'verified');
        add(id, 'fixture-other', to, [other]);
      }
    } else {
      add('fixture-verified', 'fixture-port', to, target);
    }

    if (speciesFirst) {
      // Reference projection only: SQLite excludes unrelated reports before
      // the real SELECT runs; the real eligibility checks and aggregation stay intact.
      sql.function('has_target', json => Number(countLines(json).some(c =>
        c.species_key === key || exactSpecies(c.label)?.key === key)));
      sql.exec(`ALTER TABLE advisor_reports RENAME TO fixture_reports;
        CREATE VIEW advisor_reports AS SELECT * FROM fixture_reports WHERE has_target(counts_json);`);
    }
    sql.exec('PRAGMA query_only = ON');
    const selected = [];
    const db = {prepare(query) {
      assert.match(query.trim(), /^SELECT\b/i);
      const statement = sql.prepare(query);
      return {bind: (...args) => ({all: async () => {
        const results = statement.all(...args);
        selected.push(results.length);
        return {results};
      }})};
    }};
    const catches = await recentCatches(db, key, from, to);
    return {catches, selected};
  } finally {
    sql.close();
  }
}

const expectBusyCatch = catches => assert.deepEqual(catches, [olderCatch]);

test('F02-09: sparse control counts key and label matches on both inclusive window bounds', async () => {
  const {catches} = await replay({busy: false});
  assert.deepEqual(catches, [{...olderCatch, date: to}, olderCatch]);
});

test('F02-09: species-first control retains the older catch and excludes unrelated species', async () => {
  expectBusyCatch((await replay({speciesFirst: true})).catches);
});

if (process.argv.includes('--baseline')) {
  test('F02-09 read-only baseline receipt (synthetic SQLite, not live D1)', async t => {
    const {catches, selected} = await replay();
    try {
      expectBusyCatch(catches);
      t.diagnostic(`NO GAP: selected=${JSON.stringify(selected)}; catches=${JSON.stringify(catches)}`);
    } catch (error) {
      if (!(error instanceof assert.AssertionError)) throw error;
      t.diagnostic(`GAP: selected=${JSON.stringify(selected)}; catches=${JSON.stringify(catches)}; expected=${JSON.stringify([olderCatch])}`);
    }
  });
}
