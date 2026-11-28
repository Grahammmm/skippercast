// Fishing-friend species knowledge base v1 (catalog/advisor/species-kb.json +
// server/advisor/score/species-kb.ts, issue #3845 slice 2): every fact cites an allowed
// source with an explicit unit, unknowns stay null, no odds or scores, feet become metres,
// and every record points at a species the catalog and the rules table already know.
// The fixture rows below are typed from CDFW's Life History table (read 2026-11-28), not
// from the KB file, so a changed or mistyped KB value fails here. Offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const {SPECIES_KB, FEET_TO_M, kbFor, depthBandM} = await import('../server/advisor/score/species-kb.ts');
const {ruleKeys} = await import('../server/advisor/answers/rules.ts');

const RAW = read('../catalog/advisor/species-kb.json');
const CATALOG_IDS = new Set(read('../catalog/species.json').species.map(s => s.id));
const EXTRA = new Map(read('../catalog/advisor/species-extra.json').species.map(e => [e.key, e]));
const ALLOWED_HOSTS = ['wildlife.ca.gov', 'marinespecies.wildlife.ca.gov', 'nrm.dfg.ca.gov', 'fisheries.noaa.gov', 'www.fisheries.noaa.gov',
  'fishbase.se', 'www.fishbase.se', 'fishbase.org', 'www.fishbase.org', 'int-res.com', 'www.int-res.com'];
const KINDS = new Set(['agency', 'literature', 'global-check']);
const UNKNOWN_IN_V1 = ['temperature', 'tide', 'time_of_day'];
const records = () => SPECIES_KB.species.flatMap(s => [{key: s.id, ...s}, ...s.members.map(m => ({...m, group: s.id}))]);

// CDFW "Life History Information for Selected California Marine Fishes": primary depth (ft) and range.
const CDFW_FIXTURE = [
  ['lingcod', 0, 1400, ['N', 'NC', 'SC', 'S']], ['blue', 0, 300, ['N', 'NC', 'SC', 'S']], ['copper', 0, 600, ['N', 'NC', 'SC', 'S']],
  ['gopher', 0, 180, ['NC', 'SC', 'S']], ['vermilion', 0, 900, ['N', 'NC', 'SC', 'S']], ['olive-rockfish', 0, 480, ['NC', 'SC', 'S']],
  ['black', 0, 1200, ['N', 'NC', 'SC']], ['canary', 0, 900, ['N', 'NC', 'SC']], ['rosy-rockfish', 50, 420, ['N', 'NC', 'SC', 'S']],
  ['starry-rockfish', 80, 900, ['NC', 'SC', 'S']], ['yellowtail-rockfish', 0, 1800, ['N', 'NC', 'SC', 'S']], ['kelp-rockfish', 0, 150, ['NC', 'SC', 'S']],
  ['grass-rockfish', 0, 150, ['N', 'NC', 'SC', 'S']], ['brown-rockfish', 0, 420, ['N', 'NC', 'SC', 'S']], ['china-rockfish', 36, 420, ['N', 'NC', 'SC']],
];

test('1. every known fact cites an allowed source with a kind, a unit and a check date', () => {
  let facts = 0;
  for (const r of records()) for (const [name, fact] of Object.entries(r.facts)) {
    if (fact === null) continue;
    facts++;
    assert.deepEqual(Object.keys(fact).sort(), ['checked_at', 'source_kind', 'source_url', 'unit', 'value'], `${r.key}.${name} fields`);
    const url = new URL(fact.source_url);
    assert.equal(url.protocol, 'https:', `${r.key}.${name} https`);
    assert.ok(ALLOWED_HOSTS.includes(url.hostname), `${r.key}.${name} host ${url.hostname} not allowed`);
    assert.ok(KINDS.has(fact.source_kind), `${r.key}.${name} kind ${fact.source_kind}`);
    assert.ok(typeof fact.unit === 'string' && fact.unit.length > 0, `${r.key}.${name} unit`);
    assert.match(fact.checked_at, /^\d{4}-\d{2}-\d{2}$/, `${r.key}.${name} checked_at`);
    assert.notEqual(fact.value, null, `${r.key}.${name}: a known fact has a value; an unknown one is null itself`);
  }
  assert.ok(facts >= CDFW_FIXTURE.length * 5, `expected the CDFW facts for every fixture row, got ${facts}`);
});

test('2. depth units are explicit; feet convert to metres and the CDFW rows round-trip', () => {
  assert.equal(FEET_TO_M, 0.3048);
  for (const [key, minFt, maxFt, range] of CDFW_FIXTURE) {
    const rec = kbFor(key);
    assert.ok(rec, `${key} in the KB`);
    assert.deepEqual(rec.facts.primary_depth.value, [minFt, maxFt], `${key} primary depth (ft)`);
    assert.equal(rec.facts.primary_depth.unit, 'ft', `${key} depth unit`);
    assert.deepEqual(rec.facts.ca_range.value, range, `${key} CA range`);
    const band = depthBandM(key);
    assert.equal(band.min, Math.round(minFt * 0.3048 * 10) / 10, `${key} min m`);
    assert.equal(band.max, Math.round(maxFt * 0.3048 * 10) / 10, `${key} max m`);
    assert.equal(band.source_url, rec.facts.primary_depth.source_url);
  }
  assert.deepEqual(depthBandM('lingcod'), {min: 0, max: 426.7, source_url: 'https://wildlife.ca.gov/Conservation/Marine/Life-History-Fish'});
  assert.deepEqual([depthBandM('rosy-rockfish').min, depthBandM('china-rockfish').min], [15.2, 11]);
  assert.equal(depthBandM('rockfish'), null, 'a group has no depth of its own; its members do');
  assert.equal(depthBandM('white-seabass'), null, 'not in v1 -> null, never a guess');
  assert.equal(kbFor('Vermilion').group, 'rockfish', 'lookup is case-insensitive and names the group');
  assert.equal(kbFor('no-such-fish'), null);
});

test('3. every record is a species the catalog and the rules table already know; no odds or scores anywhere', () => {
  const keys = records().map(r => r.key);
  assert.equal(new Set(keys).size, keys.length, 'keys unique');
  assert.deepEqual(SPECIES_KB.species.map(s => s.id).sort(), ['lingcod', 'rockfish']);
  for (const s of SPECIES_KB.species) assert.ok(CATALOG_IDS.has(s.id), `${s.id} in catalog/species.json`);
  for (const m of records().filter(r => r.group)) {
    assert.ok(!CATALOG_IDS.has(m.key), `member ${m.key} must not collide with a catalog species (e.g. the fish yellowtail)`);
    const extra = EXTRA.get(m.key);
    if (extra) {
      assert.equal(extra.parent, m.group, `${m.key} parent in species-extra`);
      assert.equal(m.regulations_ref, m.key, `${m.key} uses its own rules key`);
      assert.deepEqual(ruleKeys(m.regulations_ref).group, [m.group], `${m.key} rules fall back to the group`);
    } else {
      assert.equal(m.regulations_ref, m.group, `${m.key} has no rules key of its own -> the group's rule`);
    }
    assert.match(m.cdfw_row, /^Rockfish, /i, `${m.key} names its CDFW table row`);
  }
  const banned = /probab|odds|score|percent|chance|catch_rate|cpue/i;
  const walk = (v, path) => {
    if (Array.isArray(v)) return v.forEach((x, i) => walk(x, `${path}[${i}]`));
    if (v && typeof v === 'object') return Object.entries(v).forEach(([k, x]) => { assert.doesNotMatch(k, banned, `${path}.${k}`); walk(x, `${path}.${k}`); });
    if (typeof v === 'string' && !path.endsWith('.method')) assert.doesNotMatch(v, /%|\bodds\b|probab/i, `${path}: ${v}`);
  };
  walk(RAW, 'kb');
});

test('4. unknown stays null: temperature, tide and time of day have no cited source in v1', () => {
  for (const r of records()) {
    for (const name of UNKNOWN_IN_V1) assert.ok(name in r.facts && r.facts[name] === null, `${r.key}.${name} must be present and null`);
    for (const name of ['season', 'prey', 'tactics']) assert.equal(r.facts[name], null, `${r.key}.${name} not sourced yet`);
  }
  for (const name of Object.keys(kbFor('rockfish').facts)) assert.equal(kbFor('rockfish').facts[name], null, `group fact ${name}`);
});
