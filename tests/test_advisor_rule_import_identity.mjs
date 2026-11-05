// Advisor rules importer (scripts/advisor/import-rules.mjs): two rows with one
// deterministic rule id are refused before any SQL is generated, so input order
// can no longer decide which bag limit is stored. Offline, fixed timestamps,
// synthetic regulation files, the in-memory D1 from _advisor_d1.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const importer = await import('../scripts/advisor/import-rules.mjs');
const NOW = Date.parse('2026-06-01T00:00:00Z');
const species = (name, bag) => ({name, bag, season: 'Open all year'});
const file = (jurisdiction, spec) => ({jurisdiction, data: {species: spec, sources: {}, official_map_url: 'https://example.invalid/map'}});
const DUP = 'Duplicate imported rule: california-central/*/halibut';

test('canonical_species_alias_collision_is_refused_in_both_orders', () => {
  for (const order of [['halibut', 'california-halibut'], ['california-halibut', 'halibut']]) {
    const spec = {};
    for (const id of order) spec[id] = species('Halibut', id === 'halibut' ? '3 fish' : '2 fish');
    assert.throws(() => importer.importRows(NOW, [file('california-central', spec)]), {message: DUP});
  }
});

test('same_identity_across_input_files_is_refused', () => {
  const same = () => file('california-central', {halibut: species('Halibut', '3 fish')});
  assert.throws(() => importer.importRows(NOW, [same(), same()]), {message: DUP});
  assert.throws(() => importer.importRows(NOW, [same(), file('california-central', {'california-halibut': species('Halibut', '2 fish')})]), {message: DUP});
});

test('same_unknown_label_collision_is_refused', () => {
  const dup = file('california-central', {'zz-mystery-a': species('Mystery fish', '1 fish'), 'zz-mystery-b': species('Mystery fish', '2 fish')});
  assert.throws(() => importer.importRows(NOW, [dup]), {message: 'Duplicate imported rule: california-central/*/other'});
  const distinct = file('california-central', {'zz-mystery-a': species('Mystery fish', '1 fish'), 'zz-mystery-b': species('Other mystery', '2 fish')});
  assert.equal(importer.importRows(NOW, [distinct]).length, 2);
});

test('different_jurisdictions_and_distinct_species_are_not_duplicates', () => {
  const rows = importer.importRows(NOW, [
    file('california-central', {halibut: species('Halibut', '3 fish'), lingcod: species('Lingcod', '2 fish')}),
    file('california-northern', {'california-halibut': species('Halibut', '2 fish')}),
  ]);
  assert.deepEqual(rows.map(r => `${r.jurisdiction}/${r.species_key}`), ['california-central/halibut', 'california-central/lingcod', 'california-northern/halibut']);
  assert.equal(new Set(rows.map(r => r.id)).size, 3);
});

test('collision_free_committed_batch_preserves_idempotency', {skip: sqliteUnavailable ?? false}, () => {
  const rows = importer.importRows(NOW);
  assert.ok(rows.length > 0);
  assert.equal(new Set(rows.map(r => r.id)).size, rows.length, 'committed inputs have unique ids');
  const {sql} = advisorDatabase();
  sql.exec(importer.rulesSql(rows));
  const first = sql.prepare('SELECT * FROM advisor_rules ORDER BY id').all();
  sql.exec(importer.rulesSql(importer.importRows(NOW)));
  const second = sql.prepare('SELECT * FROM advisor_rules ORDER BY id').all();
  assert.equal(first.length, rows.length);
  assert.ok(JSON.stringify(first) === JSON.stringify(second), 'second run changes nothing');
});

test('refusal_precedes_sql_generation', {skip: sqliteUnavailable ?? false}, () => {
  const {sql} = advisorDatabase();
  sql.exec(importer.rulesSql(importer.importRows(NOW, [file('california-central', {halibut: species('Halibut', '3 fish')})])));
  const before = JSON.stringify(sql.prepare('SELECT * FROM advisor_rules').all());
  const bad = [file('california-central', {halibut: species('Halibut', '3 fish'), 'california-halibut': species('Halibut', '2 fish')})];
  let generated = false;
  assert.throws(() => { const out = importer.rulesSql(importer.importRows(NOW, bad)); generated = true; sql.exec(out); }, {message: DUP});
  assert.equal(generated, false);
  assert.ok(JSON.stringify(sql.prepare('SELECT * FROM advisor_rules').all()) === before, 'stored rows unchanged');
});
