import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';

globalThis.REGIONS = {fixture: {timezone: 'UTC'}};
globalThis.DEPLOYMENT = {allowed_origins: ['https://fixture.invalid']};
const {reportFlow} = await import('../server/advisor/intake/reports.ts');
const {readCountBoard} = await import('../server/advisor/tools/read_count_board.ts');

const NOW = Date.parse('2026-10-03T17:00:00Z');
const TODAY = '2026-10-03';

function fixture(t, {auto, existing}) {
  const sql = new DatabaseSync(':memory:');
  t.after(() => sql.close());
  // Exercise the production lookups against real SQLite NULL and equality semantics.
  // Only the boat/media/report tables are needed; the contact is a fixture input.
  sql.exec(`
    CREATE TABLE advisor_boats (id TEXT, owner_contact_id TEXT, created_at TEXT, name TEXT, slug TEXT, region TEXT, auto_publish INTEGER);
    CREATE TABLE advisor_crew (boat_id TEXT, contact_id TEXT, removed_at TEXT);
    CREATE TABLE advisor_media (id TEXT, contact_id TEXT, boat_id TEXT, mime TEXT, width INTEGER, height INTEGER,
      bytes INTEGER, r2_key TEXT, kind TEXT, orientation INTEGER, publish_state TEXT);
    CREATE TABLE advisor_reports (id TEXT, boat_id TEXT, report_date TEXT, status TEXT, source TEXT, created_at TEXT,
      counts_json TEXT, anglers INTEGER, trip_type TEXT, notes TEXT);
    INSERT INTO advisor_media (id, contact_id, boat_id, mime, r2_key, kind, publish_state) VALUES
      ('current', 'skipper', 'current-boat', 'image/png', 'current.png', 'image', 'private'),
      ('former', 'skipper', 'former-boat', 'image/png', 'former.png', 'image', 'private'),
      ('unassigned', 'skipper', NULL, 'image/png', 'unassigned.png', 'image', 'private');
  `);
  sql.prepare('INSERT INTO advisor_boats VALUES (?, ?, ?, ?, ?, ?, ?)')
    .run('current-boat', 'skipper', TODAY, 'Fixture Boat', 'fixture-boat', 'fixture', auto ? 1 : 0);
  if (existing) sql.prepare('INSERT INTO advisor_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
    .run('earlier-report', 'current-boat', TODAY, 'pending_confirm', 'text', TODAY, '[]', 1, null, null);
  const db = {prepare(query) {
    const statement = sql.prepare(query);
    return {bind(...args) { return {
      async first() { return statement.get(...args) ?? null; },
      async all() { return {results: statement.all(...args)}; },
    }; }};
  }};
  const reads = [];
  const ctx = {
    db, env: {ADVISOR_MEDIA: {}}, settings: {publicBase: 'https://fixture.invalid'},
    contact: {id: 'skipper', boat_id: 'current-boat'}, message: {id: 'board-message'}, language: 'en', now: NOW,
    deps: {vision: {
      async classify() { return {kind: 'count_board', kind_confidence: 1, text_present: true}; },
      async readCountBoard(image) {
        reads.push(image.media_id);
        return {overall_confidence: 1, anglers: 4, lines: [{label: 'lingcod', count: 3, released: null, confidence: 1}]};
      },
    }},
  };
  return {ctx, reads};
}

const paths = {
  tool: (ctx, id) => readCountBoard.run({media_id: id}, ctx),
  'media-only': (ctx, id) => reportFlow({...ctx, text: '', media: [id], carry: []}),
};

for (const [path, run] of Object.entries(paths)) {
  // A contact-only lookup can turn the wrong photo into a new auto-publish action
  // or overwrite a same-day report; matching by contact alone is not sufficient.
  for (const existing of [false, true]) {
    test(`${path}: former and unassigned boards cannot ${existing ? 'replace' : 'create'} a report`, async t => {
      const {ctx, reads} = fixture(t, {auto: true, existing});
      for (const id of ['former', 'unassigned']) {
        const out = await run(ctx, id);
        assert.ok(!(out?.actions ?? []).some(a => a.type === 'report_draft' || a.type === 'report_edit'), id);
        if (path === 'tool') assert.equal(out.result.read, false, id);
      }
      assert.deepEqual(reads, [], 'neither photo reaches count extraction');
    });
  }

  for (const auto of [false, true]) {
    test(`${path}: same-boat board keeps ${auto ? 'auto-publish' : 'confirmation'}`, async t => {
      const {ctx, reads} = fixture(t, {auto, existing: false});
      const {actions} = await run(ctx, 'current');
      assert.deepEqual(reads, ['current']);
      assert.deepEqual(actions.map(a => a.type), ['report_draft', 'send_text']);
      assert.deepEqual([actions[0].report.boat_id, actions[0].report.media_id], ['current-boat', 'current']);
      assert.equal(actions[0].report.counts[0].kept, 3);
      assert.equal(actions[0].publish === true, auto);
      assert.equal(actions[1].text.includes('Reply Y to post'), !auto);
    });
  }
}
