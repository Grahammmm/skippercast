// RF1050-16: only finite, nonnegative, ordered depth bands wholly inside the profile limit enter Where to look,
// from the atlas, the reviewed terrain release and the planner's publication alike. Synthetic fixtures; offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';

globalThis.fetch = () => { throw new Error('network is denied in this suite'); };
const {TOP, atlasPicks, habitatPicks, ranking} = await import('../web/ranking.ts');

const NOW = Date.UTC(2026, 10, 4, 12);
const box = (w, s, e, n) => ({type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]});
const SCREEN = {status: 'ready', note: '', source: 'synthetic', boundaries: [], until: Infinity};
const WATER = () => ({state: 'water'});
const REGION = 'morro-bay';
const ORIGIN = {latitude: 35.3, longitude: -120.95, name: 'Synthetic harbor'};

/** An atlas mark the lingcod screen shows (rough relief), differing only in depth band and habitat score. */
const mark = (id, depth, score = 10, extra = {}) => ({id, label: id, latitude: 35.3 + score / 1000, longitude: -120.95, neighborhood_depth_ft: depth, habitat_score: score,
  terrain_interpretation: `${id} relief.`, metrics: {relief_210m_m: 8, rugose_or_bedrock_fraction_210m: 0.8, rough_habitat_within_250m_ha: 6, plane_residual_rms_250m_m: 1}, ...extra});
const dataOf = targets => ({region: {id: REGION}, atlas: {targets}, survey: null, geology: null});
const atlasIds = (targets, limit = 60, place = WATER) => atlasPicks(dataOf(targets), SCREEN, 'lingcod', limit, null, undefined, place).map(p => p.id);

/** A reviewed terrain polygon with the properties the brief reads. */
const feature = (id, min, max, score = 10, extra = {}) => ({type: 'Feature', id, geometry: box(0, 0, 1, 1), properties: {id, region: REGION, depth_min_ft: min, depth_max_ft: max,
  waypoint_latitude: 35.3 + score / 1000, waypoint_longitude: -120.95, terrain_score: score, terrain_grade: 'B', fit_lingcod: 2, ...extra}});
const terrainIds = (features, limit = 60, place = WATER) => habitatPicks(features, SCREEN, REGION, 'lingcod', limit, null, undefined, place).map(p => p.id);

const MALFORMED = [[400, 40], [-1, 40], [-20, -10], [null, 40], [undefined, 40], [NaN, 40], [10, Infinity], [10, null], [-Infinity, 10], ['10', 40], [10, '40'], [0, 60.0001], [10, 61]];

/** A published reef the planner's bestSpots admits (confidence, resolution, fit, one area each, spaced apart). */
const pub = (i, id, depth, fit = 3, percent = 90) => ({id, canonical_habitat: true, name: id, label: 'Surveyed reef habitat', latitude: 35.0 + i * 0.01, longitude: -121.1, neighborhood_depth_ft: depth,
  habitat_score: 50, species_fit: {lingcod: fit, 'rockfish-reef': fit}, resolution_m: 2, evidence_confidence: {percent}, area_ids: [id], terrain_interpretation: `${id} relief.`});
const publicationOf = targets => ({targets, areas: targets.map(t => ({id: t.id, geometry: box(t.longitude - 0.001, t.latitude - 0.001, t.longitude + 0.001, t.latitude + 0.001)})),
  publication: {status: 'ready', region: REGION, archive_sha256: 'a'.repeat(64), export_sha256: 'b'.repeat(64), expires_at: new Date(NOW + 3600000).toISOString()}});
const OPEN = {state: 'loaded', region: REGION, screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true}};
const fromPublication = (loaded, patch = {}) => ranking({region: REGION, profile: 'boat', target: 'lingcod', coast: 'lingcod', data: dataOf([]), screen: SCREEN, terrain: {state: 'idle'}, now: NOW,
  place: WATER, origin: ORIGIN, publication: {state: 'ready', region: REGION, loaded}, plannerScreen: OPEN, ...patch});

test('atlas_and_terrain_reject_reversed_negative_nonfinite_bands', () => {
  for (const depth of MALFORMED) {
    assert.deepEqual(atlasIds([mark('bad', depth, 99), mark('ok', [20, 40], 1)]), ['ok'], `atlas ${String(depth)}`);
    assert.deepEqual(terrainIds([feature('bad', depth[0], depth[1], 99), feature('ok', 20, 40, 1)]), ['ok'], `terrain ${String(depth)}`);
  }
  // A missing, non-array, short or long atlas band is omitted, never thrown on.
  for (const depth of [undefined, null, false, true, 'ab', '40', 40, {0: 10, 1: 40, length: 2}, {lo: 10, hi: 40}, [], [40], [10, 20, 40], [[10], [40]]]) {
    assert.deepEqual(atlasIds([mark('bad', depth, 99), mark('ok', [20, 40], 1)]), ['ok'], `atlas shape ${JSON.stringify(depth)}`);
  }
  assert.deepEqual(atlasIds([mark('no-band', undefined, 9, {neighborhood_depth_ft: undefined}), mark('ok', [20, 40], 1)]), ['ok']);
  assert.deepEqual(terrainIds([feature('x', undefined, undefined, 9), feature('ok', 20, 40, 1)]), ['ok']);
});

test('all_sources_accept_zero_equal_and_exact_limit', () => {
  const bands = [[0, 0], [40, 40], [0, 60]];
  assert.deepEqual(atlasIds(bands.map((b, i) => mark(`a${i}`, b, 30 - i))), ['a0', 'a1', 'a2']);
  assert.deepEqual(terrainIds(bands.map((b, i) => feature(`t${i}`, b[0], b[1], 30 - i))), ['t0', 't1', 't2']);
  assert.deepEqual(atlasIds([mark('over', [0, 60.0001], 9)]), [], 'atlas: over the limit despite display rounding');
  assert.deepEqual(terrainIds([feature('over', 0, 60.0001, 9)]), [], 'terrain: over the limit despite display rounding');
  assert.deepEqual(atlasPicks(dataOf([mark('z', [0, 0]), mark('e', [40, 40], 5), mark('l', [0, 60], 1)]), SCREEN, 'lingcod', 60, null, undefined, WATER).map(p => p.depth),
    ['~0–0 ft', '~40–40 ft', '~0–60 ft'], 'admitted bands keep the existing formatting');
  assert.deepEqual(habitatPicks([feature('t', 0, 60)], SCREEN, REGION, 'lingcod', 60, null, undefined, WATER).map(p => p.depth), ['~0–60 ft']);
  // Publication: the same three bands pass, 60.0001 does not, and the string "10" never does.
  const loaded = publicationOf([pub(0, 'p-zero', [0, 0], 3), pub(1, 'p-equal', [40, 40], 3, 80), pub(2, 'p-exact', [0, 60], 2, 70), pub(3, 'p-over', [0, 60.0001], 3, 99), pub(4, 'p-str', ['10', 40], 3, 99)]);
  const r = fromPublication(loaded, {profile: 'spear'});
  assert.deepEqual(r.picks.map(p => p.id), ['p-zero', 'p-equal', 'p-exact']);
  assert.deepEqual(r.picks.map(p => p.depth), ['~0–0 ft', '~40–40 ft', '~0–60 ft']);
});

test('publication_rejects_before_fifty_candidate_cap', () => {
  const reversed = Array.from({length: 55}, (_, i) => pub(i, `rev-${i}`, [400, 40], 3, 99));
  const valid = [pub(60, 'v-first', [50, 90], 2, 70), pub(61, 'v-second', [30, 60], 2, 65), pub(62, 'v-over', [100, 400], 3, 99)];
  const loaded = publicationOf([...reversed, ...valid]);
  const before = structuredClone(loaded);
  const r = fromPublication(loaded);
  assert.equal(r.source, 'publication');
  assert.deepEqual(r.picks.map(p => p.id), ['v-first', 'v-second'], 'valid places are ranked in planner order; no reversed band fills the 50 candidates');
  assert.deepEqual(r.picks.map(p => p.depth), ['~50–90 ft', '~30–60 ft']);
  assert.ok(r.picks.every(p => p.screen && p.kind === 'reef'));
  assert.ok(isDeepStrictEqual(loaded, before), 'targets and areas are not mutated');
  assert.equal(loaded.targets.length, 58, 'the cached targets keep every entry');
  // A malformed pair that is not iterable must not throw inside the planner's ranking either.
  const odd = publicationOf([pub(0, 'o-object', {0: 10, 1: 40, length: 2}), pub(1, 'o-null', null), pub(2, 'o-short', [10]), pub(3, 'ok', [20, 80], 2, 70)]);
  assert.deepEqual(fromPublication(odd).picks.map(p => p.id), ['ok']);
  assert.deepEqual(fromPublication({...odd, targets: [null, ...odd.targets]}).picks.map(p => p.id), ['ok']);
});

test('invalid_depths_do_not_consume_top_or_water_counts', () => {
  // Atlas: the best-ranked entries are malformed; lower-ranked valid ones fill every TOP slot.
  const bad = MALFORMED.map((d, i) => mark(`bad-${i}`, d, 500 + i));
  const good = Array.from({length: TOP + 2}, (_, i) => mark(`good-${i}`, [10, 50], 20 - i));
  const seen = [];
  const watch = p => { seen.push(p.t.id); return {state: 'water'}; };
  assert.deepEqual(atlasIds([...bad, ...good], 60, watch), good.slice(0, TOP).map(t => t.id));
  assert.ok(seen.length && seen.every(id => id.startsWith('good-')), 'the water check sees only depth-eligible atlas marks');
  const atlas = ranking({region: 'cambria-san-simeon', profile: 'spear', target: 'lingcod', coast: 'gopher-rockfish', data: dataOf([...bad, ...good]), screen: SCREEN, terrain: {state: 'idle'}, now: NOW, place: watch});
  assert.equal(atlas.source, 'atlas'); assert.equal(atlas.picks.length, TOP); assert.equal(atlas.withheld, undefined); assert.equal(atlas.pending, undefined);
  // Terrain: the same.
  const seenT = [];
  const watchT = p => { seenT.push(`${p.latitude}`); return {state: 'water'}; };
  const tBad = MALFORMED.map((d, i) => feature(`tbad-${i}`, d[0], d[1], 500 + i)), tGood = Array.from({length: TOP + 2}, (_, i) => feature(`tgood-${i}`, 10, 50, 20 - i));
  assert.deepEqual(terrainIds([...tBad, ...tGood], 60, watchT), tGood.slice(0, TOP).map(f => f.id));
  assert.equal(seenT.length, tGood.length, 'the water check sees only depth-eligible terrain');
  const terr = ranking({region: REGION, profile: 'spear', target: 'lingcod', coast: 'lingcod', data: dataOf([]), screen: SCREEN, now: NOW, place: WATER,
    terrain: {state: 'ready', features: [...tBad, ...tGood], expiresAt: NOW + 3600000, rank: f => [...f]}});
  assert.equal(terr.source, 'terrain'); assert.equal(terr.picks.length, TOP); assert.equal(terr.withheld, undefined); assert.equal(terr.pending, undefined);
  // Publication: malformed places are neither counted as withheld nor reach the water check.
  const seenP = [];
  const loaded = publicationOf([...Array.from({length: 6}, (_, i) => pub(i, `rev-${i}`, [400, 40], 3, 99)), pub(20, 'good', [50, 90], 2, 70)]);
  const r = fromPublication(loaded, {place: p => { seenP.push(p.id); return {state: 'water'}; }});
  assert.deepEqual(r.picks.map(p => p.id), ['good']); assert.deepEqual(seenP, ['good']);
  assert.equal(r.withheld, undefined, 'malformed depths are not counted as land/water withheld'); assert.equal(r.pending, undefined);
});

test('source_empty_and_other_filters_are_preserved', () => {
  const allBad = MALFORMED.map((d, i) => mark(`bad-${i}`, d, i));
  const atlas = ranking({region: 'cambria-san-simeon', profile: 'spear', target: 'lingcod', coast: 'lingcod', data: dataOf(allBad), screen: SCREEN, terrain: {state: 'idle'}, now: NOW, place: WATER});
  assert.equal(atlas.source, 'atlas'); assert.deepEqual(atlas.picks, []); assert.equal(atlas.empty, 'No surveyed reef marks within 60 ft for this target.');
  const terr = ranking({region: REGION, profile: 'spear', target: 'lingcod', coast: 'lingcod', data: dataOf([]), screen: SCREEN, now: NOW, place: WATER,
    terrain: {state: 'ready', features: MALFORMED.map((d, i) => feature(`tbad-${i}`, d[0], d[1], i)), expiresAt: NOW + 3600000, rank: f => [...f]}});
  assert.equal(terr.source, 'terrain'); assert.deepEqual(terr.picks, []);
  assert.equal(terr.empty, 'No reviewed terrain habitat passes the current protected-area and closure check within 60 ft for this target.');
  const pubEmpty = fromPublication(publicationOf(MALFORMED.map((d, i) => pub(i, `bad-${i}`, d))), {profile: 'spear'});
  assert.equal(pubEmpty.source, 'publication'); assert.deepEqual(pubEmpty.picks, []);
  assert.equal(pubEmpty.empty, 'No ranked reef places pass the current protected-area check within 60 ft for this target.');
  // Valid but over-depth, protected, land, wrong-region, out-of-range and too-far-to-swim entries stay out.
  const fenced = {...SCREEN, boundaries: [{name: 'Synthetic MPA', federal: false, geometry: box(-121.1, 35.35, -120.8, 35.45)}]};
  const marks = [mark('deep', [10, 90], 9), mark('inside', [10, 40], 8, {latitude: 35.4, longitude: -120.95}), mark('land', [10, 40], 7), mark('far', [10, 40], 6, {latitude: 36.3}), mark('ok', [10, 40], 1)];
  const place = p => ({state: p.t.id === 'land' ? 'land' : 'water'});
  const kept = atlasPicks(dataOf(marks), fenced, 'lingcod', 60, ORIGIN, {maxNm: 20, shore: null}, place);
  assert.deepEqual(kept.map(p => p.id), ['ok']);
  const feats = [feature('deep', 10, 90, 9), feature('other-region', 10, 40, 8, {region: 'cambria-san-simeon'}), feature('ok', 10, 40, 1)];
  assert.deepEqual(terrainIds(feats), ['ok']);
  // Repeated calls give identical answers and leave the inputs alone.
  const input = [mark('bad', [400, 40], 9), mark('ok', [10, 40], 1)], copy = structuredClone(input);
  const first = atlasPicks(dataOf(input), SCREEN, 'lingcod', 60, null, undefined, WATER), second = atlasPicks(dataOf(input), SCREEN, 'lingcod', 60, null, undefined, WATER);
  assert.ok(isDeepStrictEqual(first, second) && isDeepStrictEqual(input, copy), 'repeatable and not mutated');
});
