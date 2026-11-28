// Fishing-friend "best bets" engine, slice 1 (server/advisor/score/best-bets.ts, issue #3845):
// conditions fit from the advisor's one comfort model per 3-hour block at each public ground's
// nearest coastal forecast point, habitat fit from the mapped reef targets, gates for Rough and
// boating advisories, stale forecasts never ranked, and no coordinate in the output.
// Synthetic forecast feeds, values invented; the region, allowlist, charter grounds and atlas are
// the repository's own reviewed files. Offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {execFileSync} from 'node:child_process';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
const {buildScores, bestBets, reefGrounds, habitatFit, nearestPoint, WEIGHTS_V1, BLOCKS} = await import('../server/advisor/score/best-bets.ts');
const {COORDINATE} = await import('../server/advisor/answers/advice.ts');

const REGION = REGIONS['morro-bay'];
const PUBLIC = read('../catalog/advisor/public-grounds.json').regions['morro-bay'];
const CHARTER = read('../dist/data/charter-grounds.json').grounds;
const TARGETS = read('../dist/data/atlas.json').targets;
const GROUNDS = reefGrounds(REGION, PUBLIC, CHARTER);
const DATE = '2026-09-28', NEXT = '2026-09-29';               // PDT: UTC-7
const NOW = Date.parse('2026-09-28T12:00:00Z');                 // 05:00 local, before the first block
const POINTS = REGION.forecast_points.map(p => p.id);
const CALM = {wind_speed_10m: 6, wind_gusts_10m: 9, wind_direction_10m: 315, ecmwf_wind: 6, ecmwf_gust: 9, wave_height: 2, wave_period: 10, wind_wave_height: 0.3,
  wind_wave_period: 4, swell_wave_height: 2, swell_wave_period: 10, swell_wave_direction: 300, secondary_swell_wave_height: 0.5, secondary_swell_wave_direction: 200, wam: 2};
const ROUGH = {wind_speed_10m: 30, wind_gusts_10m: 38, ecmwf_wind: 30, ecmwf_gust: 38, wave_height: 12, wam: 12, wind_wave_height: 6, wind_wave_period: 5};
const UNIT = k => /direction/.test(k) ? '°' : /period/.test(k) ? 's' : /height/.test(k) ? 'ft' : 'kn';
const HOURS = Array.from({length: 24 * 4}, (_, i) => Date.parse('2026-09-28T00:00:00Z') / 1000 + i * 3600);
const at = (date, h) => Date.UTC(+date.slice(0, 4), +date.slice(5, 7) - 1, +date.slice(8, 10), h + 7) / 1000;

/** An intelligence feed whose every hour at every point reads CALM plus `by(pointId, t)`; `ageH` is each run's age at NOW. */
function feed({by = () => ({}), ageH = 4} = {}) {
  const series = (keys, point) => ({hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(([k]) => [k, UNIT(k)]))},
    hourly: {time: HOURS, ...Object.fromEntries(keys.map(([k, src]) => [k, HOURS.map(t => ({...CALM, ...by(point, t)})[src ?? k])]))}});
  const model = keys => ({meta: {last_run_initialisation_time: NOW / 1000 - ageH * 3600}, data: POINTS.map(p => series(keys, p))});
  const wave = ['wave_height', 'wave_period', 'wind_wave_height', 'wind_wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction',
    'secondary_swell_wave_height', 'secondary_swell_wave_direction'].map(k => [k]);
  return {region_id: 'morro-bay', completed_at: new Date(NOW - 3600000).toISOString(), forecast: {requested_points: REGION.forecast_points.map(p => [p.id, p.latitude, p.longitude]), models: {
    gfs_global: model([['wind_speed_10m'], ['wind_gusts_10m'], ['wind_direction_10m']]), ncep_gfswave016: model(wave),
    ecmwf_ifs025: model([['wind_speed_10m', 'ecmwf_wind'], ['wind_gusts_10m', 'ecmwf_gust']]), ecmwf_wam: model([['wave_height', 'wam']]),
  }}};
}
/** A daily feed with a complete alert check for both zones; `alerts` go to the coastal zone. */
const daily = (alerts = []) => ({sources: Object.fromEntries(Object.values(REGION.marine_zones).map((z, i) =>
  [`alerts-${z}`, {status: 'ok', checked_at: new Date(NOW - 1800000).toISOString(), data: {alerts: i === 0 ? alerts : []}}]))});
const build = (opts = {}, extra = {}) => buildScores({region: REGION, intel: feed(opts), daily: daily(), grounds: GROUNDS, targets: TARGETS, dates: [DATE, NEXT], now: NOW, ...extra});
const row = (file, area, date, block) => file.rows.find(r => r.area === area && r.date === date && r.block === block);
const H = Object.fromEntries(GROUNDS.map(g => [g.name, habitatFit(g, TARGETS).value]));

test('the three allowlisted reef grounds map to their nearest coastal forecast point; offshore points are never used', () => {
  assert.deepEqual(GROUNDS.map(g => [g.name, g.point]), [['Pecho Rock', 'avila'], ['Diablo coast', 'avila'], ['Morro Bay coast', 'central']]);
  // On top of an offshore point: still the nearest coastal one.
  assert.equal(nearestPoint(REGION, 35.3, -121.5), 'north');
  assert.equal(nearestPoint({...REGION, forecast_points: REGION.forecast_points.filter(p => p.offshore)}, 35.3, -121.5), null);
  // A ground missing from the charter list, or not a reef ground, is dropped; nothing is invented.
  assert.deepEqual(reefGrounds(REGION, [...PUBLIC, {name: 'Nowhere', charter_ground_id: 'CHARTER-NONE', species: ['lingcod']}], CHARTER).length, 3);
  assert.deepEqual(reefGrounds(REGION, [{...PUBLIC[0], species: ['halibut']}], CHARTER), []);
});

test('habitat fit is the mean of the three best mapped terrain scores, and says it is structure, not fish', () => {
  const g = {name: 'X', ground_id: 'X', point: 'central', target_ids: ['a', 'b', 'c', 'd', 'missing']};
  const t = [{id: 'a', habitat_score: 90, habitat_grade: 'A', confidence: 'Moderate'}, {id: 'b', habitat_score: 80, confidence: 'Moderate'},
    {id: 'c', habitat_score: 70, confidence: 'Moderate'}, {id: 'd', habitat_score: 10, confidence: 'Lower'}];
  assert.deepEqual(habitatFit(g, t), {value: 0.8, evidence: 'Moderate', reasons: ['4 mapped reef search targets, best terrain grade A', 'terrain grade measures structure, not fish']});
  assert.equal(habitatFit(g, [t[0], t[1], {...t[2], confidence: 'Lower'}]).evidence, 'Low');
  assert.deepEqual(habitatFit({...g, target_ids: []}, t), {value: null, evidence: 'Insufficient', reasons: ['no graded reef targets mapped here']});
  // The repository's grounds: every one has graded targets.
  assert.ok(Object.values(H).every(v => v > 0.5 && v <= 1), JSON.stringify(H));
});

test('a calm forecast opens every block and ranks by conditions then habitat; the best bets follow habitat on equal conditions', () => {
  const file = build();
  assert.equal(file.rows.length, GROUNDS.length * BLOCKS.length * 2);
  assert.ok(file.rows.every(r => r.gate === 'pass' && r.conditions.comfort === 'comfortable' && r.conditions.value === 1 && r.conditions.evidence === 'Moderate'));
  const r = row(file, 'Pecho Rock', DATE, 'morning');
  assert.equal(r.rank, Math.round((WEIGHTS_V1.conditions + WEIGHTS_V1.habitat * H['Pecho Rock']) * 1000) / 1000);
  const top = bestBets(file, {n: 3});
  const byHabitat = Object.entries(H).sort((a, b) => b[1] - a[1]).map(([n]) => n);
  assert.deepEqual(top.map(t => [t.area, t.date, t.block]), [[byHabitat[0], DATE, 'morning'], [byHabitat[0], DATE, 'midday'], [byHabitat[0], DATE, 'afternoon']]);
  assert.deepEqual(bestBets(file, {dates: [NEXT], n: 1}).map(t => t.date), [NEXT]);
  assert.equal(file.weights_version, 'v1');
  assert.ok(file.limitations.includes('no recent catch evidence yet'));
});

test('a Rough afternoon at the southern point closes those grounds for that block only; best bets skip closed rows', () => {
  const rough = (p, t) => p === 'avila' && [12, 13, 14].some(h => at(DATE, h) === t) ? ROUGH : {};
  const file = build({by: rough});
  for (const area of ['Pecho Rock', 'Diablo coast']) {
    const r = row(file, area, DATE, 'afternoon');
    assert.deepEqual([r.gate, r.rank, r.conditions.comfort], ['rough', null, 'rough']);
    assert.equal(row(file, area, DATE, 'midday').gate, 'pass');
  }
  assert.equal(row(file, 'Morro Bay coast', DATE, 'afternoon').gate, 'pass');
  assert.ok(bestBets(file, {n: 50}).every(r => r.gate === 'pass' && r.rank !== null));
  // Bumpy beats nothing but loses to Comfortable: a choppy morning at the north ground ranks below calm grounds.
  const bumpy = build({by: (p, t) => p === 'central' && [6, 7, 8].some(h => at(DATE, h) === t) ? {wind_speed_10m: 16, ecmwf_wind: 16, wind_gusts_10m: 20, ecmwf_gust: 20} : {}});
  const m = row(bumpy, 'Morro Bay coast', DATE, 'morning');
  assert.ok(m.conditions.value < 1 && m.rank < row(bumpy, 'Pecho Rock', DATE, 'morning').rank, JSON.stringify(m.conditions));
});

test('a small craft advisory closes every overlapping block, even when the forecast is too old to use', () => {
  const sca = [{event: 'Small Craft Advisory', onset: '2026-09-29T06:00:00-07:00', ends: '2026-09-29T21:00:00-07:00'}];
  for (const ageH of [4, 40]) {
    const file = buildScores({region: REGION, intel: feed({ageH}), daily: daily(sca), grounds: GROUNDS, targets: TARGETS, dates: [DATE, NEXT], now: NOW});
    const next = file.rows.filter(r => r.date === NEXT);
    assert.ok(next.every(r => r.gate === 'advisory' && r.rank === null && r.conditions.reasons[0] === 'Small Craft Advisory'), `age ${ageH}`);
  }
  assert.ok(buildScores({region: REGION, intel: feed(), daily: daily(sca), grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW}).rows.every(r => r.gate === 'pass'));
});

test('a forecast past the drop age, or no alert check, is never a best bet; model disagreement lowers conditions and evidence', () => {
  const stale = build({ageH: 40});
  assert.ok(stale.rows.every(r => r.conditions.value === null && r.conditions.evidence === 'Insufficient' && r.rank === null && r.evidence === 'Insufficient'));
  assert.deepEqual(bestBets(stale), []);
  const unchecked = buildScores({region: REGION, intel: feed(), daily: {sources: {}}, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  assert.equal(unchecked.advisories_checked, false);
  assert.ok(unchecked.rows.every(r => r.conditions.comfort === 'bumpy' && r.conditions.reasons.includes('the marine alert check is unavailable')));
  // The second model 5 kt windier (MODEL_GAP.wind is 4): the comfort word comes from the rougher model as always, then disagreement scales it.
  const split = build({by: p => p === 'central' ? {ecmwf_wind: 11} : {}});
  const r = row(split, 'Morro Bay coast', DATE, 'morning');
  const raw = {comfortable: 1, bumpy: 0.5}[r.conditions.comfort];
  assert.deepEqual([r.conditions.value, r.conditions.evidence, r.evidence], [Math.round(raw * WEIGHTS_V1.models_disagree * 100) / 100, 'Low', 'Low']);
  assert.ok(r.conditions.reasons.includes('forecast models disagree'));
});

test('blocks that have already ended today are left out', () => {
  const file = build({}, {now: Date.parse('2026-09-28T19:30:00Z')});   // 12:30 local
  assert.deepEqual([...new Set(file.rows.filter(r => r.date === DATE).map(r => r.block))], ['afternoon', 'evening']);
  assert.equal(file.rows.filter(r => r.date === NEXT).length, GROUNDS.length * BLOCKS.length);
});

test('the score file names only allowlisted grounds and forecast point ids, never a coordinate', () => {
  const file = build({by: (p, t) => p === 'avila' && t === at(DATE, 13) ? ROUGH : {}});
  const text = JSON.stringify(file);
  assert.equal(COORDINATE.test(JSON.stringify(file.rows)), false);   // the header's ISO timestamps (16:05:00.000) look like decimals to it
  assert.equal(/latitude|longitude|SC26-|anchor/.test(text), false);
  assert.ok(file.rows.every(r => PUBLIC.some(g => g.name === r.area) && POINTS.includes(r.point)));
  assert.equal(/probability|percent|%|hotspot/i.test(JSON.stringify(file.rows)), false);
});

test('the offline script writes the score file and prints the top three bets', () => {
  const dir = mkdtempSync(join(tmpdir(), 'advisor-score-'));
  writeFileSync(join(dir, 'intel.json'), JSON.stringify(feed()));
  writeFileSync(join(dir, 'daily.json'), JSON.stringify(daily()));
  const out = execFileSync(process.execPath, [new URL('../scripts/advisor/build-scores.mjs', import.meta.url).pathname, '--intel', join(dir, 'intel.json'),
    '--daily', join(dir, 'daily.json'), '--now', new Date(NOW).toISOString(), '--days', '2', '--out', join(dir, 'scores.json')], {encoding: 'utf8'});
  const file = JSON.parse(readFileSync(join(dir, 'scores.json')));
  assert.deepEqual(file.rows.length, GROUNDS.length * BLOCKS.length * 2);
  assert.match(out, /^morro-bay v1: 24 rows \(24 open\)/);
  assert.equal(out.trim().split('\n').length, 4);
});
