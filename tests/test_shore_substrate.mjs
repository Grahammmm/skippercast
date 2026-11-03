// FSC-03: a shore run may be sand or rocky (schemas/shore-habitat.schema.json `substrate`).
// The guidance (web/brief/shore.ts) and the Chart mark card (web/map/shore.ts) name a rocky run
// as rocky shore and keep today's exact sandy wording for sand runs. Offline: the committed
// package and protected-area snapshot, with one synthetic rocky copy of a committed run.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {shoreGuidance} from '../web/brief/shore.ts';
import {assessScreen} from '../web/map/habitat.ts';
import {runMark, shownRuns} from '../web/map/shore.ts';

const ROOT = new URL('..', import.meta.url);
const json = path => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const PACKAGE = json('dist/regions/morro-bay/shore-habitat.geojson');
const REGION = json('dist/regions/morro-bay/region.json');
const SNAPSHOT = json(`dist/${REGION.assets.protected_areas}`);
const HOUR = 3_600_000;
const NOW = Date.parse('2026-10-11T00:00:00Z');
const iso = ms => new Date(ms).toISOString();
const READY = assessScreen({areas: SNAPSHOT.features, checkedAt: iso(NOW - HOUR), live: false, closures: undefined}, NOW);
const checked = now => ({alerts: [], sources: [{id: 'nws-alerts', outcome: 'ok', fetchedAt: iso(now - HOUR)}], waterQuality: [], nearshore: []});
const CHECKS = ' Fish presence is unverified. Before you go, check the current CDFW rules for this area, the access point\'s posted status, the surf and the county\'s beach water-quality status.';

/** The sandy leads exactly as they read before FSC-03. */
const SANDY = {
  surfperch: 'Surfperch: a sandy-beach surf method; the run marks historical sandy shore to look along.',
  halibut: 'California halibut: a sandy-bottom method; the run marks historical sandy shore to look along, and size and bag limits apply.',
  lingcod: 'The run marks historical sandy shore to look along.',
};
const ROCKY = {
  surfperch: 'Surfperch: a rocky-shore surf method; the run marks historical rocky shore to look along.',
  halibut: 'California halibut: usually a sandy-bottom fish; the run marks historical rocky shore, so look at sand pockets beside it, and size and bag limits apply.',
  lingcod: 'The run marks historical rocky shore to look along.',
};
const NEUTRAL = 'The run marks historical shore to look along.';

test('sand guidance is byte-identical to today, with or without the substrate argument', () => {
  for (const [target, lead] of Object.entries(SANDY)) {
    assert.equal(shoreGuidance(target).text, lead + CHECKS, target);
    assert.equal(shoreGuidance(target, 'sand').text, lead + CHECKS, target);
    assert.equal(shoreGuidance(target, undefined).text, lead + CHECKS, `${target}: a run without substrate stays sand`);
  }
});

test('rocky guidance names rocky shore and never sandy shore', () => {
  for (const [target, lead] of Object.entries(ROCKY)) {
    const g = shoreGuidance(target, 'rocky');
    assert.equal(g.text, lead + CHECKS, target);
    assert.match(g.text, /rocky shore/);
    assert.doesNotMatch(g.text, /sandy shore|sandy-beach/, target);
    assert.deepEqual([g.href, g.label], [shoreGuidance(target).href, shoreGuidance(target).label], 'same rules link');
  }
  assert.match(shoreGuidance('halibut', 'rocky').text, /size and bag limits apply/);
});

test('an unknown substrate gets the neutral sentence, never sandy or rocky', () => {
  for (const substrate of ['Rock', 'ROCKY', 'gravel', '', 'sand ', 'rocky shore', null]) {
    for (const target of Object.keys(SANDY)) {
      const text = shoreGuidance(target, substrate).text;
      assert.equal(text, NEUTRAL + CHECKS, `${target}/${JSON.stringify(substrate)}`);
      assert.doesNotMatch(text, /sandy|rocky/i);
    }
  }
});

test('the Chart card of a rocky run shows the rocky lead; a sand run card is unchanged', () => {
  const sand = shownRuns(PACKAGE, READY, checked(NOW), NOW);
  assert.ok(sand.length > 0 && sand.every(r => r.run.properties.substrate === 'sand'), 'the committed runs are all sand');
  const rockyPkg = {...PACKAGE, features: PACKAGE.features.map(f => ({...f, properties: {...f.properties, substrate: 'rocky'}}))};
  const rocky = shownRuns(rockyPkg, READY, checked(NOW), NOW);
  assert.deepEqual(rocky.map(r => [r.run.id, r.status]), sand.map(r => [r.run.id, r.status]), 'substrate never changes priority');
  const bare = shownRuns({...PACKAGE, features: PACKAGE.features.map(f => {
    const {substrate: _s, ...properties} = f.properties; return {...f, properties};
  })}, READY, checked(NOW), NOW);
  for (const target of Object.keys(SANDY)) {
    for (const [i, r] of sand.entries()) {
      const card = runMark(r, target, NOW), rockCard = runMark(rocky[i], target, NOW);
      assert.ok(card.basis.includes(SANDY[target] + CHECKS), `${r.name}/${target}: sand lead`);
      assert.deepEqual(runMark(bare[i], target, NOW), card, 'a run without substrate reads as sand');
      assert.ok(rockCard.basis.includes(ROCKY[target] + CHECKS), `${r.name}/${target}: rocky lead`);
      assert.doesNotMatch(rockCard.basis, /sandy shore/);
      assert.deepEqual({...rockCard, basis: ''}, {...card, basis: ''}, 'only the guidance differs');
    }
  }
  const odd = {...sand[0], run: {...sand[0].run, properties: {...sand[0].run.properties, substrate: 'gravel'}}};
  assert.ok(runMark(odd, 'surfperch', NOW).basis.includes(NEUTRAL + CHECKS), 'unknown substrate card is neutral');
});
