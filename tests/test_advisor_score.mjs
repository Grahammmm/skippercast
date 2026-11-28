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
const {buildScores, bestBets, reefGrounds, habitatFit, nearestPoint, alertCheckCurrent, ALERT_CHECK_MAX_HOURS, WEIGHTS_V1, BLOCKS} = await import('../server/advisor/score/best-bets.ts');
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

test('a forecast past the drop age is never a best bet; model disagreement lowers conditions and evidence', () => {
  const stale = build({ageH: 40});
  assert.ok(stale.rows.every(r => r.conditions.value === null && r.conditions.evidence === 'Insufficient' && r.rank === null && r.evidence === 'Insufficient'));
  assert.deepEqual(bestBets(stale), []);
  // The second model 5 kt windier (MODEL_GAP.wind is 4): the comfort word comes from the rougher model as always, then disagreement scales it.
  const split = build({by: p => p === 'central' ? {ecmwf_wind: 11} : {}});
  const r = row(split, 'Morro Bay coast', DATE, 'morning');
  const raw = {comfortable: 1, bumpy: 0.5}[r.conditions.comfort];
  assert.deepEqual([r.conditions.value, r.conditions.evidence, r.evidence], [Math.round(raw * WEIGHTS_V1.models_disagree * 100) / 100, 'Low', 'Low']);
  assert.ok(r.conditions.reasons.includes('forecast models disagree'));
});

test('an incomplete marine alert check (one zone or both missing) is never ranked; a found advisory still closes; a complete check ranks', () => {
  const full = daily().sources, [first] = Object.keys(full);
  const scores = sources => buildScores({region: REGION, intel: feed(), daily: {sources}, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  // Control: the same calm forecast with every zone checked ranks every block.
  const complete = scores(full);
  assert.equal(complete.advisories_checked, true);
  assert.equal(complete.rows.filter(r => r.rank !== null).length, GROUNDS.length * BLOCKS.length);
  assert.equal(bestBets(complete).length, 3);
  for (const [name, sources] of [['both missing', {}], ['one missing', {[first]: full[first]}], ['one failed', {...full, [first]: {...full[first], status: 'error'}}]]) {
    const file = scores(sources);
    assert.equal(file.advisories_checked, false, name);
    assert.ok(file.rows.every(r => r.gate === 'unchecked' && r.rank === null && r.conditions.value === null && r.evidence === 'Insufficient'), name);
    assert.ok(file.rows.every(r => r.conditions.reasons.some(x => x.includes('the marine alert check is unavailable')) && r.conditions.reasons.some(x => /^wind /.test(x))), name);
    assert.deepEqual(bestBets(file, {n: 50}), [], name);
  }
  // An advisory in the zone that was checked closes the block even though the other zone was not checked.
  const sca = [{event: 'Small Craft Advisory', onset: '2026-09-28T06:00:00-07:00', ends: '2026-09-28T21:00:00-07:00'}];
  const partial = scores({[first]: {...full[first], data: {alerts: sca}}});
  assert.ok(partial.rows.every(r => r.gate === 'advisory' && r.rank === null && r.conditions.reasons[0] === 'Small Craft Advisory'));
});

test('a recommendation needs a current alert check: old or future-dated checks abstain like a missing one; a known advisory still closes', () => {
  const checkedAgo = (hours, alerts = []) => {
    const day = daily(alerts);
    for (const z of Object.values(day.sources)) z.checked_at = new Date(NOW - hours * 3600000).toISOString();
    return buildScores({region: REGION, intel: feed(), daily: day, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  };
  // Fresh controls: half an hour and just inside the limit rank every block.
  for (const h of [0.5, ALERT_CHECK_MAX_HOURS - 1]) {
    const file = checkedAgo(h);
    assert.equal(file.advisories_checked, true, `${h} h`);
    assert.equal(file.rows.filter(r => r.rank !== null).length, GROUNDS.length * BLOCKS.length, `${h} h`);
  }
  // Stale: just past the limit, a week old (the checker's probe), and a check stamped two hours in the future.
  for (const h of [ALERT_CHECK_MAX_HOURS + 1, 7 * 24, -2]) {
    const file = checkedAgo(h);
    assert.equal(file.advisories_checked, false, `${h} h`);
    assert.ok(file.rows.every(r => r.gate === 'unchecked' && r.rank === null && r.conditions.reasons.includes('the marine alert check is unavailable')), `${h} h`);
    assert.deepEqual(bestBets(file, {n: 50}), [], `${h} h`);
  }
  // One zone stale, the other fresh: every required zone must be current.
  const mixed = daily(), [first] = Object.keys(mixed.sources);
  mixed.sources[first].checked_at = new Date(NOW - 7 * 24 * 3600000).toISOString();
  assert.equal(buildScores({region: REGION, intel: feed(), daily: mixed, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW}).advisories_checked, false);
  // The checker's second probe: one zone checked half an hour ago, the other stamped two hours ahead, in both orders, abstains;
  // the same file with both zones half an hour old ranks (the valid control).
  const zoneKeys = Object.keys(daily().sources);
  const stamped = (offsets, alerts = []) => {
    const day = daily(alerts);
    zoneKeys.forEach((k, i) => { day.sources[k].checked_at = new Date(NOW + offsets[i] * 3600000).toISOString(); });
    return buildScores({region: REGION, intel: feed(), daily: day, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  };
  assert.equal(stamped([-0.5, -0.5]).rows.filter(r => r.rank !== null).length, GROUNDS.length * BLOCKS.length, 'valid control');
  for (const offsets of [[-0.5, 2], [2, -0.5]]) {
    const file = stamped(offsets);
    assert.equal(file.advisories_checked, false, `${offsets}`);
    assert.ok(file.rows.every(r => r.gate === 'unchecked' && r.rank === null), `${offsets}`);
    assert.deepEqual(bestBets(file, {n: 50}), [], `${offsets}`);
  }
  // A week-old check that still lists an overlapping advisory closes the block (not merely unchecked).
  const sca = [{event: 'Small Craft Advisory', onset: '2026-09-28T06:00:00-07:00', ends: '2026-09-28T21:00:00-07:00'}];
  assert.ok(checkedAgo(7 * 24, sca).rows.every(r => r.gate === 'advisory' && r.rank === null && r.conditions.reasons[0] === 'Small Craft Advisory'));
  // So does a future-stamped zone next to a valid one.
  assert.ok(stamped([-0.5, 2], sca).rows.every(r => r.gate === 'advisory' && r.rank === null && r.conditions.reasons[0] === 'Small Craft Advisory'));
  const zones = zoneKeys.map(k => k.replace(/^alerts-/, ''));
  assert.equal(alertCheckCurrent(daily().sources, zones, NOW), true);
  assert.equal(alertCheckCurrent(undefined, zones, NOW), false);
  assert.equal(alertCheckCurrent(daily().sources, [], NOW), false);
  const bad = daily();
  bad.sources[zoneKeys[0]].checked_at = 'not a time';
  assert.equal(alertCheckCurrent(bad.sources, zones, NOW), false);
});

test('a block is ranked only when every one of its hours has a rated forecast (missing timestamps or missing values); Rough still closes', () => {
  /** The feed with GFS timestamps removed (set to null, as a gap in the series reads) at these local hours of DATE. */
  const without = (hours, opts = {}) => {
    const intel = feed(opts), drop = new Set(hours.map(h => at(DATE, h)));
    for (const p of intel.forecast.models.gfs_global.data) p.hourly.time = p.hourly.time.map(t => drop.has(t) ? null : t);
    return buildScores({region: REGION, intel, daily: daily(), grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  };
  const morning = file => file.rows.filter(r => r.block === 'morning');
  // Control: the full calm morning ranks at every ground.
  assert.ok(morning(without([])).every(r => r.gate === 'pass' && r.rank !== null));
  for (const [name, hours, gap] of [['two of three missing', [7, 8], '2 of 3'], ['one missing', [6], '1 of 3']]) {
    const file = without(hours);
    assert.ok(morning(file).every(r => r.gate === 'incomplete' && r.rank === null && r.conditions.value === null && r.evidence === 'Insufficient'
      && r.conditions.reasons.includes(`${gap} hours have no forecast`)), name);
    assert.ok(file.rows.filter(r => r.block === 'midday').every(r => r.gate === 'pass' && r.rank !== null), `${name}: other blocks unaffected`);
    assert.ok(bestBets(file, {n: 50}).every(r => r.block !== 'morning'), name);
  }
  // A timestamp present with no usable values is as missing as an absent one.
  const NONE = Object.fromEntries([...Object.keys(CALM), ...Object.keys(ROUGH), 'wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction',
    'secondary_swell_wave_height', 'secondary_swell_wave_direction', 'wind_wave_period'].map(k => [k, null]));
  const blank = build({by: (_, t) => t === at(DATE, 7) ? NONE : {}});
  assert.ok(morning(blank).filter(r => r.date === DATE).every(r => r.gate === 'incomplete' && r.rank === null));
  // Rough in the hour that is there still closes the block as rough, not merely incomplete.
  const rough = without([7, 8], {by: (_, t) => t === at(DATE, 6) ? ROUGH : {}});
  assert.ok(morning(rough).every(r => r.gate === 'rough' && r.rank === null));
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

// ---- slice 1b: the reply-path catalog, the ADVISOR_BEST_BETS switch, the prompt rule and get_best_bets ----

globalThis.DEPLOYMENT = read('../deployments/production.json');
const {groundCatalog, scoresFromCatalog} = await import('../server/advisor/score/best-bets.ts');
const {TOOL_BY_NAME, toolsForRole} = await import('../server/advisor/tools/index.ts');
const {SURE_WORDS} = await import('../server/advisor/tools/get_best_bets.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {systemPrompt, BEST_BETS_RULE} = await import('../server/advisor/prompts/system.ts');
const CATALOG = read('../catalog/advisor/best-bet-grounds.json');
const ON = advisorSettings({ADVISOR_BEST_BETS: 'true'});
const person = (over = {}) => ({id: 'c1', phone_hash: 'h', phone_enc: 'ENC', web_session: null, channel: 'imessage', role: 'angler', language: 'en', status: 'active', home_port: null, ...over});
const valid = d => ({schema_version: 1, region_id: 'morro-bay', generated_at: new Date(NOW - 1800000).toISOString(), reports: [], health: {}, catch_probability: null, bite_score: null, ...d});
const feeds = ({intel = feed(), day = daily()} = {}) => async url => /intelligence\.json$/.test(url) ? intel : /latest\.json$/.test(url) ? valid(day) : Promise.reject(Error('no feed'));
const bets = (input = {}, {language = 'en', ...f} = {}) => TOOL_BY_NAME.get('get_best_bets').run(input, {env: {}, contact: person(), message: {id: 'in1'}, db: null,
  deps: {feeds: feeds(f)}, language, settings: ON, now: NOW}).then(o => o.result);

test('the reply-path ground catalog is the builder\'s output for the reviewed files (drift fails), with no coordinate or target id', () => {
  assert.deepEqual(CATALOG.regions['morro-bay'], groundCatalog(GROUNDS, TARGETS), 'rerun: node scripts/advisor/build-scores.mjs --grounds-out catalog/advisor/best-bet-grounds.json');
  assert.equal(/latitude|longitude|SC26-|target_ids/.test(JSON.stringify(CATALOG)), false);
  assert.equal(COORDINATE.test(JSON.stringify(CATALOG.regions)), false);
  // The catalog path scores exactly as the raw builder does.
  const opts = {region: REGION, intel: feed(), daily: daily(), dates: [DATE, NEXT], now: NOW};
  assert.deepEqual(scoresFromCatalog({...opts, grounds: CATALOG.regions['morro-bay']}), buildScores({...opts, grounds: GROUNDS, targets: TARGETS}));
});

test('get_best_bets and its prompt rule are offered only with ADVISOR_BEST_BETS on; off, the cached prompt is unchanged', () => {
  const names = (c, s) => toolsForRole(person(c), s).map(t => t.name);
  for (const s of [undefined, advisorSettings(), advisorSettings({ADVISOR_BEST_BETS: 'yes'})]) assert.ok(!names({}, s).includes('get_best_bets'));
  for (const role of ['angler', 'skipper', 'crew']) assert.ok(names({role}, ON).includes('get_best_bets'), role);
  assert.deepEqual(names({}, ON).filter(n => n !== 'get_best_bets'), names({}, advisorSettings()), 'the switch adds one tool and removes none');
  for (const lang of ['en', 'es']) {
    assert.equal(systemPrompt(lang, {}), systemPrompt(lang));
    assert.ok(!systemPrompt(lang).includes('get_best_bets') && systemPrompt(lang, {bestBets: true}).includes(BEST_BETS_RULE));
    assert.ok(systemPrompt(lang, {bestBets: true}).includes('Never state odds, chances, percentages or a bite score'), 'the no-odds rule stays');
  }
  assert.match(BEST_BETS_RULE, /never a percentage, odds, a score number/);
});

test('get_best_bets: one clear call per open block, reasons and confidence in words, never a percentage or a coordinate', async () => {
  const r = await bets();
  assert.equal(r.dates.length, 7);
  assert.equal(r.best_bets.length, 3);
  const top = Object.entries(H).sort((a, b) => b[1] - a[1])[0][0];
  assert.deepEqual(r.best_bets.map(b => [b.area, b.date, b.hours]), [[top, DATE, '06:00-09:00'], [top, DATE, '09:00-12:00'], [top, DATE, '12:00-15:00']]);
  assert.ok(r.best_bets.every(b => b.day === 'today' && b.comfort === 'comfortable' && b.confidence_words === SURE_WORDS.en.Moderate
    && b.factors.find(f => f.factor === 'sea comfort').reading.includes('wind ')
    && b.factors.find(f => f.factor === 'reef structure').reading.includes('terrain grade measures structure, not fish') && !('reasons' in b)));
  assert.deepEqual([r.closed_days, r.advisories_checked], [[], true]);
  const text = JSON.stringify(r), data = JSON.stringify({...r, note: undefined});   // the note itself says "Never a percentage"
  assert.equal(/\d\s*%/.test(text), false, text);
  assert.equal(/percent|probability|hotspot|rank|latitude|longitude|SC26-/i.test(data), false, data);
  assert.equal(COORDINATE.test(JSON.stringify(r.best_bets)), false);
  assert.ok(text.length < 4000);
  // A date word narrows the call; Spanish gets Spanish confidence words.
  assert.ok((await bets({date: 'tomorrow'})).best_bets.every(b => b.date === NEXT));
  assert.equal((await bets({}, {language: 'es'})).best_bets[0].confidence_words, SURE_WORDS.es.Moderate);
});

test('get_best_bets: an advisory day is listed closed; a stale forecast or an incomplete alert check makes no call; other regions are not covered', async () => {
  const sca = [{event: 'Small Craft Advisory', onset: '2026-09-29T00:00:00-07:00', ends: '2026-09-29T23:00:00-07:00'}];
  const shut = await bets({}, {day: daily(sca)});
  assert.deepEqual(shut.closed_days, [{date: NEXT, day: 'tomorrow', why: 'Small Craft Advisory'}]);
  assert.ok(shut.best_bets.every(b => b.date !== NEXT) && /closed days/.test(shut.note));
  const stale = await bets({}, {intel: feed({ageH: 40})});
  assert.equal(stale.error, 'forecast not usable');
  assert.equal('best_bets' in stale, false);
  const unchecked = await bets({}, {day: {sources: {}}});
  assert.deepEqual([unchecked.best_bets, unchecked.advisories_checked], [[], false]);
  assert.match(unchecked.note, /could not be checked or the check is old: make no call/);
  // The checker's probe: a fresh forecast with a week-old alert check makes no call.
  const weekOld = daily();
  for (const z of Object.values(weekOld.sources)) z.checked_at = '2026-09-21T12:00:00Z';
  const old = await bets({date: DATE}, {day: {...weekOld, generated_at: '2026-09-21T12:00:00Z'}});
  assert.deepEqual([old.best_bets, old.advisories_checked], [[], false]);
  // The checker's second probe: one zone checked half an hour ago, the other two hours ahead, makes no call.
  const ahead = daily(), [z0, z1] = Object.values(ahead.sources);
  z0.checked_at = new Date(NOW - 1_800_000).toISOString();
  z1.checked_at = new Date(NOW + 2 * 3_600_000).toISOString();
  const future = await bets({date: DATE}, {day: ahead});
  assert.deepEqual([future.best_bets, future.advisories_checked], [[], false]);
  // The checker's probe: 07:00 and 08:00 missing from GFS, so 06:00-09:00 is never a call; the rest of the day still is.
  const thin = feed();
  for (const p of thin.forecast.models.gfs_global.data) p.hourly.time = HOURS.map(t => [at(DATE, 7), at(DATE, 8)].includes(t) ? null : t);
  const gappy = await bets({date: DATE}, {intel: thin});
  assert.ok(gappy.best_bets.length && gappy.best_bets.every(b => b.hours !== '06:00-09:00'));
  assert.equal((await bets({port: 'monterey'})).unavailable, true);
  assert.equal((await bets({date: '2026-09-01'})).error, 'that date has passed');
  assert.equal((await bets({date: '2026-10-20'})).beyond_horizon, true);
});

// ---- slice 3: the per-factor explainer (helps / neutral / hurts) behind every call ----

const {factorsFor, GRADE_A, GRADE_B, UNTESTED, NOT_COMPARED, ALERTS_AT_LAST_CHECK} = await import('../server/advisor/score/explain.ts');
const NAMES = ['sea comfort', 'forecast agreement', 'marine alerts', 'reef structure', 'moon and pressure'];
const effects = fs => Object.fromEntries(fs.map(f => [f.factor, f.effect]));

test('explainer: a calm, agreed, checked block on grade A reef shows every input helping, and moon/pressure as untested', () => {
  const r = row(build(), 'Pecho Rock', DATE, 'morning');
  const fs = factorsFor(r);
  assert.deepEqual(fs.map(f => f.factor), NAMES);
  assert.ok(H['Pecho Rock'] >= GRADE_A, 'the fixture ground is grade A on the atlas cut-offs');
  assert.deepEqual(effects(fs), {'sea comfort': 'helps', 'forecast agreement': 'helps', 'marine alerts': 'helps', 'reef structure': 'helps', 'moon and pressure': 'neutral'});
  assert.match(fs[0].reading, /^comfortable, wind 6 kt NW, seas /);
  assert.match(fs[3].reading, /^best reef marks average grade A, 11 mapped reef search targets/);
  assert.deepEqual(fs[4], UNTESTED);
  assert.ok(fs.every(f => typeof f.source === 'string' && f.source.length && ['helps', 'neutral', 'hurts'].includes(f.effect)));
  assert.equal(/\d\s*%|0\.\d|rank|latitude|longitude/i.test(JSON.stringify(fs)), false, JSON.stringify(fs));
});

test('explainer: a bumpy block is neutral, disagreeing models hurt, and the reef grade follows the atlas cut-offs', () => {
  const bumpy = build({by: (p, t) => p === 'central' && [6, 7, 8].some(h => at(DATE, h) === t) ? {wind_speed_10m: 16, ecmwf_wind: 16, wind_gusts_10m: 20, ecmwf_gust: 20} : {}});
  assert.equal(effects(factorsFor(row(bumpy, 'Morro Bay coast', DATE, 'morning')))['sea comfort'], 'neutral');
  const split = row(build({by: p => p === 'central' ? {ecmwf_wind: 11} : {}}), 'Morro Bay coast', DATE, 'morning');
  const fs = factorsFor(split);
  assert.deepEqual([fs[1].effect, fs[1].reading], ['hurts', 'forecast models disagree']);
  assert.equal(fs[0].reading.includes('disagree'), false, 'disagreement is its own factor, not a sea reading');
  const graded = v => factorsFor({...split, habitat: {...split.habitat, value: v}})[3];
  assert.deepEqual([GRADE_A, GRADE_B].map(graded).map(f => f.effect), ['helps', 'neutral']);
  assert.deepEqual([graded(0.6).reading.split(',')[0], graded(0.6).effect], ['best reef marks average grade B', 'neutral']);
  assert.deepEqual([graded(0.54).reading.split(',')[0], graded(0.54).effect], ['best reef marks average grade C', 'hurts']);
});

test('explainer: forecast agreement is worded for the hours both models could be compared (real partial feeds)', () => {
  const morning = by => row(build({by}), 'Morro Bay coast', DATE, 'morning');
  const agreement = by => { const r = morning(by); assert.notEqual(r.rank, null, 'the block is still ranked'); return [factorsFor(r)[1], r.conditions.models_compared]; };
  const six = t => t === at(DATE, 6);
  // Control: all three hours have both models' wind and seas, and they agree.
  assert.deepEqual(agreement(() => ({})), [{factor: 'forecast agreement', reading: 'forecast models agree', effect: 'helps', source: 'marine forecast'}, {paired: 3, second: 3, hours: 3}]);
  // ECMWF wind present (and used) but no WAM seas in any hour: nothing could be compared; it is not "one model".
  const [noWam, nWam] = agreement(() => ({wam: null, ecmwf_wind: 16, ecmwf_gust: 20}));
  assert.deepEqual([noWam.reading, noWam.effect, nWam], [NOT_COMPARED, 'neutral', {paired: 0, second: 3, hours: 3}]);
  // WAM seas only at 06:00: agreement in one comparable hour of three is reported as such and does not count as help.
  const [oneHour, nOne] = agreement((_, t) => ({wam: six(t) ? 2 : null}));
  assert.deepEqual([oneHour.reading, oneHour.effect, nOne], ['forecast models agree in the 1 of 3 hours both could be compared', 'neutral', {paired: 1, second: 3, hours: 3}]);
  // The one comparable hour disagrees: it hurts, with the same scope.
  const [split] = agreement((_, t) => ({wam: six(t) ? 2 : null, ecmwf_wind: six(t) ? 11 : 6}));
  assert.deepEqual([split.reading, split.effect], ['forecast models disagree in the 1 of 3 hours both could be compared', 'hurts']);
  // No second-model reading at all: only then "one forecast model only".
  const [solo, nSolo] = agreement(() => ({wam: null, ecmwf_wind: null, ecmwf_gust: null}));
  assert.deepEqual([solo.reading, solo.effect, nSolo], ['one forecast model only', 'neutral', {paired: 0, second: 0, hours: 3}]);
});

test('explainer: marine alerts describe the last NWS check, not a live all-clear for a later trip', async () => {
  // An admissible older check (20 h, inside ALERT_CHECK_MAX_HOURS) and a ranked block on the next day.
  const old = {sources: Object.fromEntries(Object.values(REGION.marine_zones).map(z =>
    [`alerts-${z}`, {status: 'ok', checked_at: new Date(NOW - 20 * 3600000).toISOString(), data: {alerts: []}}]))};
  const file = build({}, {daily: old});
  assert.equal(file.advisories_checked, true);
  const later = row(file, 'Pecho Rock', NEXT, 'afternoon');
  assert.notEqual(later.rank, null);
  const alerts = factorsFor(later)[2];
  assert.deepEqual([alerts.factor, alerts.reading, alerts.effect], ['marine alerts', ALERTS_AT_LAST_CHECK, 'helps']);
  assert.match(alerts.reading, /at the last NWS check/);
  assert.match(alerts.reading, /check current NWS marine alerts before leaving/);
  assert.equal(/^no marine advisory for these hours$/.test(alerts.reading), false, 'no unconditional all-clear');
  assert.match(BEST_BETS_RULE, /last NWS check, not a live one: never call the trip clear of advisories; tell them to check current NWS marine alerts before leaving/);
  assert.match((await bets()).note, /as of the last NWS check: never say the trip is clear of advisories/);
});

test('explainer: a row a gate closed or that has no rank explains nothing (no call, no reasons for one)', () => {
  const rough = build({by: (p, t) => p === 'avila' && [12, 13, 14].some(h => at(DATE, h) === t) ? ROUGH : {}});
  assert.deepEqual(factorsFor(row(rough, 'Pecho Rock', DATE, 'afternoon')), []);
  assert.ok(build({ageH: 40}).rows.every(r => factorsFor(r).length === 0));
  const unchecked = buildScores({region: REGION, intel: feed(), daily: {sources: {}}, grounds: GROUNDS, targets: TARGETS, dates: [DATE], now: NOW});
  assert.ok(unchecked.rows.every(r => r.gate === 'unchecked' && factorsFor(r).length === 0));
  // Every open row is explained, and get_best_bets' calls carry exactly the rows' factors.
  assert.ok(build().rows.every(r => factorsFor(r).length === NAMES.length));
  assert.match(BEST_BETS_RULE, /what helps and anything that hurts from its factors/);
});

test('get_best_bets: each call carries its factors, the untested ones neutral, and the whole result stays short', async () => {
  const r = await bets();
  const file = buildScores({region: REGION, intel: feed(), daily: daily(), grounds: GROUNDS, targets: TARGETS, dates: r.dates, now: NOW});
  assert.deepEqual(r.best_bets.map(b => b.factors), bestBets(file, {n: 3}).map(factorsFor));
  assert.ok(r.best_bets.every(b => b.factors.find(f => f.factor === 'moon and pressure').effect === 'neutral'));
  assert.match(r.note, /what helps and anything that hurts from its factors/);
  assert.ok(JSON.stringify(r).length < 4000);
});
