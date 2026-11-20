// F19-14: replay importer SQL and admin confirmation against migrated SQLite.
// Historical negative control: run this file with --baseline at the pre-fix main.
import assert from 'node:assert/strict';
import test from 'node:test';
import {importRows, ruleId, rulesSql} from '../scripts/advisor/import-rules.mjs';
import {advisorDatabase} from './_advisor_d1.mjs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {createRule, editRule} = await import('../server/advisor/admin/rules.ts');

const jurisdiction = 'california-central';
const neighbor = 'california-north';
const t0 = Date.parse('2026-01-01T00:00:00Z');
const t1 = Date.parse('2026-01-02T00:00:00Z');
const file = (area, names, note) => ({jurisdiction: area, data: {
  official_map_url: 'https://example.invalid/fixture',
  species: Object.fromEntries(names.map(name => [name, {details: [note]}])),
}});
const present = ['changed', 'unchanged', 'retired', 'legacy', 'lingcod'];
const rows = importRows(t0, [file(jurisdiction, [...present.slice(0, -1), 'missing', 'legacy-missing', 'retired-missing', 'other-feed'], 'original'),
  file(neighbor, ['other-area'], 'original')]);
const ids = Object.fromEntries(rows.map(row => [row.file_species, row.id]));
const incoming = importRows(t1, [file(jurisdiction, present.filter(name => name !== 'unchanged'), 'changed'),
  file(jurisdiction, ['unchanged'], 'original'), file(neighbor, ['other-area'], 'changed')]);

// The complete case detects the historical missing-UPDATE bug; the other arms
// catch a nonempty partial/failed payload or an empty scope triggering writes.
for (const [label, state, payload] of [
  ['complete', 'complete', incoming],
  ['partial', 'partial', incoming],
  ['failed with rows', 'failed', incoming],
  ['empty', 'complete', []],
  ['empty scope', 'complete', incoming.filter(r => r.jurisdiction === neighbor)],
  ['seed (no completeness declaration)', 'seed', incoming.filter(r => r.jurisdiction === jurisdiction)],
]) {
  test(`F19-14: ${label} snapshot changes only eligible rules`, async t => {
    const {sql, db} = advisorDatabase();
    t.after(() => sql.close());
    const get = sql.prepare('SELECT * FROM advisor_rules WHERE id=?');
    const read = id => ({...get.get(id)});
    const snapshot = () => sql.prepare('SELECT * FROM advisor_rules ORDER BY id').all().map(row => ({...row}));
    sql.exec(rulesSql(rows));
    const origin = read(ids.missing).import_origin;
    assert.ok(origin, 'a forward import records its origin');
    sql.exec("UPDATE advisor_rules SET status='active';");
    sql.prepare("UPDATE advisor_rules SET status='retired' WHERE id IN (?,?)").run(ids.retired, ids['retired-missing']);
    // A NULL-origin collision is indistinguishable from a legacy import before
    // the migration; never claim it on a later import, even with changed content.
    sql.prepare('UPDATE advisor_rules SET import_origin=NULL WHERE id IN (?,?)').run(ids.legacy, ids['legacy-missing']);
    sql.prepare("UPDATE advisor_rules SET import_origin='other-feed' WHERE id=?").run(ids['other-feed']);
    const regional = {...rows.find(r => r.id === ids.missing), region: 'fixture-region'};
    const regionalId = ruleId(regional);
    sql.exec(rulesSql([{...regional, id: regionalId, status: 'active'}]));
    const manual = await createRule(db, {jurisdiction, species_key: 'lingcod', species_label: 'Lingcod',
      source_name: 'Synthetic bulletin', source_url: 'https://wildlife.ca.gov/synthetic'}, 'fixture-custodian', t0);
    assert.equal(manual.status, 'ok', manual.error);
    assert.equal(read(manual.rule.id).import_origin, null);
    // The production confirmation UPDATE must not lose provenance even though
    // it replaces updated_by; this confirmed row later drops out of the feed.
    const confirmed = await editRule(db, ids.missing, {}, 'fixture-custodian', t0);
    assert.equal(confirmed.status, 'ok');
    assert.equal(read(ids.missing).updated_by, 'fixture-custodian');
    assert.equal(read(ids.missing).import_origin, origin);
    const before = snapshot();
    // Contract: an import that changes a rule's state invalidates the cached species pages (advisor.pages.version);
    // one that changes nothing does not. Bug caught: the absent-rule UPDATE leaving a cached page quoting it as current.
    const pages = () => Number(sql.prepare("SELECT value FROM job_state WHERE key='advisor.pages.version'").get()?.value ?? 0);
    const version = pages();

    sql.exec(rulesSql(payload, {state, jurisdiction}));
    const after = snapshot();
    const demoted = after.some((row, i) => row.status === 'review' && before[i].status === 'active');
    assert.equal(pages() > version, demoted, 'pages version moves exactly when an active rule went to review');
    const settled = pages();
    sql.exec(rulesSql(payload, {state, jurisdiction}));
    assert.equal(pages(), settled, 'rerunning the same import changes nothing, so the version stays');
    const expected = before.map(row => {
      if (row.id === ids.missing && label === 'complete') return {...row, status: 'review'};
      if (row.id === ids.changed && (label === 'complete' || state === 'seed')) {
        const changed = incoming.find(r => r.id === row.id);
        const {gear_notes, updated_at, reviewed_at, review_due} = changed;
        return {...row, gear_notes, updated_at, reviewed_at, review_due, status: 'review'};
      }
      return row;
    });
    assert.deepEqual(after, expected, 'no unrelated writes, deletions or fabricated limits');
  });
}
