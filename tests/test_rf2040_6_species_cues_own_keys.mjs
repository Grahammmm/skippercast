// RF2040-6: speciesCues returns [] for keys that only exist on Object.prototype.
import test from 'node:test';
import assert from 'node:assert/strict';
const {speciesCues, speciesForTargets} = await import('../server/advisor/vision/species.ts');

test('species_cues_inherited_names_are_empty', () => {
  for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf'])
    for (const lang of ['en', 'es']) assert.deepEqual(speciesCues(key, lang), [], `${key} ${lang}`);
});

test('species_cues_missing_and_unknown_boundary', () => {
  for (const key of [null, undefined, '', 'invented-rf2040'])
    for (const lang of ['en', 'es']) assert.deepEqual(speciesCues(key, lang), [], `${key} ${lang}`);
});

test('species_cues_bilingual_catalog_control', () => {
  const en = speciesCues('lingcod', 'en');
  const es = speciesCues('lingcod', 'es');
  assert.equal(en.length, 3);
  assert.equal(es.length, en.length);
  assert.notDeepEqual(en, es);
  en.length = 0;
  assert.equal(speciesCues('lingcod', 'en').length, 3);
});

test('species_cues_canonical_synonym_control', () => {
  for (const lang of ['en', 'es']) {
    const cues = speciesCues('halibut', lang);
    assert.ok(cues.length > 0);
    assert.deepEqual(speciesCues('california-halibut', lang), cues);
  }
  assert.equal(speciesForTargets(['reef']).length, 16);
});
