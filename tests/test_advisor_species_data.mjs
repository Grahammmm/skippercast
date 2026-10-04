// Text Advisor species data (TA-A3; docs/plans/text-advisor/06-angler-answers.md
// § As built (TA-A3), 08 § public pages): catalog/advisor/lookalikes.json covers
// every fish key in catalog/species.json and every species-extra key with 2-3
// cues in English and Spanish, look-alikes that resolve and an agency source;
// protected.json names resolvable keys checked against CDFW's groundfish
// summary; species-pages.json has one entry per key a /species/<key> page shows,
// in both languages, pointing its season note at the rules table. No cue,
// description or note states a size (the rules guard's spirit): the rules
// table is the only place numbers live.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const species = await import('../server/advisor/vision/species.ts');

const catalog = read('../catalog/species.json').species;
const extra = read('../catalog/advisor/species-extra.json').species;
const looks = read('../catalog/advisor/lookalikes.json').species;
const prot = read('../catalog/advisor/protected.json').species;
const pages = read('../catalog/advisor/species-pages.json').species;

/** Catalog keys that are not fish (they still get cues; they are not required to). */
const NOT_FISH = new Set(['dungeness', 'lobster']);
const catalogKeys = new Set(catalog.map(s => s.id));
const known = new Set([...catalogKeys, ...extra.map(e => e.key)]);
/** The keys a /species/<key> page shows: catalog keys, then the species-extra keys that are not synonyms. */
const pageKeys = [...catalog.map(s => s.id), ...extra.filter(e => !e.same_as_parent).map(e => e.key)];
/** A synonym's entry stands in for its catalog key (halibut -> california-halibut), as species.ts does. */
const entryFor = key => looks[key] ?? looks[extra.find(e => e.same_as_parent && e.parent === key)?.key];

/** Agency pages only: CDFW (site, Marine Species Portal, document library) and NOAA Fisheries. */
const AGENCY = /^https:\/\/(?:wildlife\.ca\.gov|marinespecies\.wildlife\.ca\.gov|nrm\.dfg\.ca\.gov|www\.fisheries\.noaa\.gov)\//;
/** A size in inches in any form ("12 in", '12"', "12-inch", "12 pulgadas"): rules belong to the rules table. */
const SIZE = /\d\s*(?:-\s*)?(?:in\b|"|”|inch|pulg)/i;
const CLAIMS = /hotspot|\d\s*%|guarantee|best spot/i;

test('every fish key and every species-extra key has 2-3 cues in English and Spanish', () => {
  const required = [...catalog.map(s => s.id).filter(k => !NOT_FISH.has(k)), ...extra.map(e => e.key)];
  assert.ok(required.length >= 34, 'the catalog fish plus the extra keys');
  for (const key of required) {
    const entry = entryFor(key);
    assert.ok(entry, `lookalikes for ${key}`);
    assert.ok(entry.cues.length >= 2 && entry.cues.length <= 3, `${key}: 2-3 cues`);
    assert.equal(entry.cues_es?.length, entry.cues.length, `${key}: a Spanish cue for each cue`);
    // The server's own lookup agrees (canonical keys, synonyms, the Spanish arm).
    const k = species.canonicalSpecies(key);
    assert.deepEqual(species.speciesCues(k), entry.cues, `${key}: speciesCues`);
    assert.deepEqual(species.speciesCues(k, 'es'), entry.cues_es, `${key}: speciesCues es`);
  }
  for (const k of NOT_FISH) assert.ok(looks[k], `${k} has cues too`);
});

test('look-alike entries are well formed: known keys, translated cues, resolvable look-alikes, agency sources', () => {
  for (const [key, v] of Object.entries(looks)) {
    assert.ok(known.has(key), `${key} is a catalog or species-extra key`);
    assert.deepEqual(Object.keys(v).sort(), ['cues', 'cues_es', 'lookalikes', 'source'], key);
    v.cues.forEach((c, i) => {
      assert.ok(c.trim().length > 3 && c === c.trim(), `${key} cues[${i}]`);
      assert.ok(v.cues_es[i].trim().length > 3, `${key} cues_es[${i}]`);
      assert.notEqual(v.cues_es[i], c, `${key} cues_es[${i}] is translated`);
    });
    assert.equal(new Set(v.cues).size, v.cues.length, `${key}: no repeated cue`);
    assert.equal(new Set(v.lookalikes).size, v.lookalikes.length, `${key}: no repeated look-alike`);
    for (const l of v.lookalikes) {
      assert.ok(known.has(l), `${key} -> ${l} resolves`);
      assert.notEqual(species.canonicalSpecies(l), species.canonicalSpecies(key), `${key} is not its own look-alike`);
    }
    assert.match(v.source, AGENCY, `${key}: agency source`);
    assert.notEqual(v.source, 'https://wildlife.ca.gov/Fishing/Ocean', `${key}: a species page, not the ocean fishing index`);
  }
});

test('protected keys resolve and follow the CDFW groundfish summary, with no rule in the file', () => {
  for (const p of prot) {
    assert.ok(known.has(p.key), `${p.key} resolves`);
    assert.equal(p.source, 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Groundfish-Summary', p.key);
    assert.match(p.checked_at, /^\d{4}-\d{2}-\d{2}$/, `${p.key}: checked_at`);
    assert.match(p.note, /rules table/, p.key);
    assert.match(p.note, /descending device/, p.key);
    assert.doesNotMatch(p.note, /\d/, `${p.key}: no number in the note`);
    assert.ok(entryFor(p.key), `${p.key} has look-alike cues for the warning`);
  }
  assert.deepEqual(prot.filter(p => p.must_release).map(p => p.key).sort(), ['bronzespotted', 'cowcod', 'quillback', 'yelloweye']);
  assert.deepEqual(prot.filter(p => !p.must_release).map(p => p.key), ['canary']);
  assert.deepEqual(species.PROTECTED.map(p => p.key), prot.map(p => p.key));
});

test('species pages: one entry per page key, both languages, a parent catalog key and the rules table', () => {
  assert.deepEqual(Object.keys(pages), pageKeys, 'one entry per page key, in catalog order');
  for (const [key, p] of Object.entries(pages)) {
    for (const l of ['en', 'es']) {
      assert.ok(p.names?.[l]?.trim(), `${key}: names.${l}`);
      assert.ok(p.description?.[l]?.trim().length > 60, `${key}: description.${l}`);
      assert.ok(!/\n/.test(p.description[l]), `${key}: description.${l} is one paragraph`);
    }
    assert.notEqual(p.description.es, p.description.en, `${key}: translated`);
    const e = extra.find(x => x.key === key);
    assert.equal(p.parent, catalogKeys.has(key) ? key : e.parent, `${key}: parent`);
    assert.ok(p.parent === null ? typeof e.target === 'string' : catalogKeys.has(p.parent), `${key}: parent is a catalog key`);
    assert.ok(p.sources.length >= 1, `${key}: sources`);
    for (const s of p.sources) assert.match(s, AGENCY, `${key}: ${s}`);
    assert.deepEqual(p.season_note_source, {table: 'advisor_rules', species_key: key}, `${key}: season note from the rules table`);
    assert.ok(entryFor(key), `${key}: the page has look-alike cues`);
  }
});

test('no cue, description or note states a size, a probability or a hotspot', () => {
  const texts = [];
  for (const [k, v] of Object.entries(looks)) for (const c of [...v.cues, ...v.cues_es]) texts.push([`lookalikes ${k}`, c]);
  for (const [k, p] of Object.entries(pages)) for (const l of ['en', 'es']) texts.push([`species-pages ${k}.${l}`, p.description[l]], [`species-pages ${k} name`, p.names[l]]);
  for (const p of prot) texts.push([`protected ${p.key}`, p.note]);
  for (const [where, s] of texts) {
    assert.doesNotMatch(s, SIZE, `${where}: ${s}`);
    assert.doesNotMatch(s, CLAIMS, `${where}: ${s}`);
  }
  // The guard itself catches the forms it is meant to.
  for (const bad of ['at least 12 in long', 'over 10" fork length', 'a 22-inch minimum', '30 pulgadas']) assert.match(bad, SIZE, bad);
  for (const ok of ['two white stripes', 'the rear two-thirds of the lateral line', 'in the kelp']) assert.doesNotMatch(ok, SIZE, ok);
});
