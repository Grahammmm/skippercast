// BF-skill-scorecard: the public forecast skill page (dist/skill.html) and its publisher (scripts/publish_forecast_skill.py).
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {cell, percent, readScorecard, renderScorecard, UNREADABLE} from '../dist/skill-page.js';

const NOW = Date.parse('2026-11-01T12:00:00Z');
const index = {regions: [{id: 'morro-bay', name: 'Morro Bay'}]};
const row = (extra = {}) => ({port: 'morro-bay', station: '46028', variable: 'wind_speed_10m', lead_hours: 24, window_days: 7, n: 45, within: 36,
  tolerance: 'within 5 kn', enough: true, ...extra});
const file = (extra = {}) => ({schema_version: 1, generated_at: '2026-11-01T11:00:00Z', minimum: {valid_times: 30, days: 7, runs: 3},
  ports: [{id: 'morro-bay', name: 'Morro Bay', stations: [{id: '46028', name: 'Cape San Martin'}]}], scores: [row(), row({window_days: 30, n: 120, within: 90})], ...extra});
const page = (f, i = index) => { const card = readScorecard(f, i, NOW); return card ? renderScorecard(card) : UNREADABLE; };

test('a port row shows the hit rate with its tolerance, sample size and window', () => {
  const html = page(file());
  assert.match(html, /Wind speed/);
  assert.match(html, /within 5 kn/);
  assert.match(html, /<strong>80%<\/strong> <small>\(36 of 45 checked, last 7 days\)/);
  assert.match(html, /<strong>75%<\/strong> <small>\(90 of 120 checked, last 30 days\)/);
  assert.match(html, /Up to 24 h ahead/);
  assert.equal(html.match(/<tr><th scope="row">/g).length, 1, 'one row per variable and lead time');
});

test('below the minimum sample no percentage is shown: zero, minimum minus one, and the minimum', () => {
  for (const n of [0, 29]) {
    // Even a publisher that wrongly sent a count must not get a percentage out of the page.
    for (const r of [row({n, within: null, enough: false}), row({n, within: Math.min(n, 5), enough: true})]) {
      const html = cell(r, 30, 7);
      assert.match(html, /Not enough data yet/, `n=${n}`);
      assert.ok(!html.includes('%'), `n=${n}: ${html}`);
    }
  }
  assert.match(cell(row({n: 30, within: 24}), 30, 7), /<strong>80%<\/strong>/);
  assert.ok(!cell(row({n: 30, within: null, enough: false}), 30, 7).includes('%'), 'enough days and runs are separate from n');
  assert.match(cell(undefined, 30, 30), /Not enough data yet <small>\(last 30 days\)/, 'a missing row is not a score and not zero');
});

test('0% and 100% are real results and neither is rounded into the other', () => {
  assert.match(cell(row({n: 40, within: 0}), 30, 7), /<strong>0%<\/strong> <small>\(0 of 40 checked/);
  assert.match(cell(row({n: 40, within: 40}), 30, 7), /<strong>100%<\/strong>/);
  assert.equal(percent(399, 400), 99);
  assert.equal(percent(1, 400), 1);
  assert.equal(percent(39, 40), 98);
});

test('an absent, malformed or incomplete file reads as unreadable, with no scores', () => {
  const bad = [null, undefined, {}, [], 'text', 7, file({schema_version: 2}), file({ports: 'x'}), file({scores: {}}), file({minimum: null}),
    file({minimum: {valid_times: 0}}), file({generated_at: 'yesterday'}), file({generated_at: undefined})];
  for (const f of bad) assert.equal(page(f), UNREADABLE, JSON.stringify(f)?.slice(0, 60));
  for (const i of [null, {}, {regions: 'x'}]) assert.equal(page(file(), i), UNREADABLE, 'without the region list the ports cannot be checked');
  assert.match(UNREADABLE, /could not be read/);
  assert.ok(!UNREADABLE.includes('%'));
});

test('a port outside the region list is left out and counted; unreadable rows are counted', () => {
  const f = file({ports: [...file().ports, {id: 'atlantis', name: 'Atlantis', stations: []}], scores: [...file().scores, row({port: 'atlantis'}), row({n: -1}),
    row({variable: 'swell_period'}), row({lead_hours: 12}), row({window_days: 3}), row({within: 99}), 'junk', null]});
  const html = page(f);
  assert.ok(!html.includes('Atlantis'));
  assert.match(html, /1 port\(s\) left out because they are not in the region list/);
  assert.match(html, /7 row\(s\) could not be read/);
  assert.match(html, /80%/, 'the good rows still show');
});

test('a publish time in the future is called unusable, not fresh', () => {
  const html = page(file({generated_at: '2026-11-02T12:00:00Z'}));
  assert.match(html, /in the future, so its age and windows cannot be trusted/);
  assert.ok(!html.includes('Published'));
  assert.match(page(file()), /Published <time datetime="2026-11-01T11:00:00.000Z">2026-11-01 11:00 UTC/);
  assert.ok(!page(file({generated_at: '2026-11-01T12:05:00Z'})).includes('future'), 'within the 10 minute clock tolerance of the status page');
});

test('markup in a port, buoy or tolerance renders as text', () => {
  const evil = '<img src=x onerror=alert(1)>';
  const html = page(file({ports: [{id: 'morro-bay', name: evil, stations: [{id: '46028', name: evil}]}], scores: [row({tolerance: evil})]}));
  assert.ok(!html.includes('<img'), html);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
});

test('the page says swell period and water temperature are not scored, and the status page links to it once', () => {
  const html = readFileSync(new URL('../dist/skill.html', import.meta.url), 'utf8');
  assert.match(html, /Swell period and water temperature are not scored yet/);
  assert.ok(html.includes('id="skill-rows"') && html.includes('skill-page.js'));
  const status = readFileSync(new URL('../dist/status.html', import.meta.url), 'utf8');
  assert.equal(status.match(/href="\/skill\.html"/g).length, 1);
  const published = JSON.parse(readFileSync(new URL('../dist/data/forecast-skill.json', import.meta.url), 'utf8'));
  assert.deepEqual(published.minimum, {valid_times: 30, days: 7, runs: 3});
  assert.ok(published.scores.every(r => !('swell_period' === r.variable || 'water_temperature' === r.variable)));
});

// ---- the publisher, run on constructed archives ----
const SCRIPT = new URL('../scripts/publish_forecast_skill.py', import.meta.url).pathname;
const nowS = NOW / 1000;
const COORDS = [35.763, -121.9];

/** An archive of `count` valid times `spacingH` apart before NOW, each forecast `leadH` ahead of its run; pairs(i) -> [observed, forecast]. */
function publish({count, spacingH = 6, leadH = 18, variable = 'wave_height', pairs}) {
  const dir = mkdtempSync(join(tmpdir(), 'skill-'));
  mkdirSync(join(dir, 'morro-bay'));
  const forecasts = [], observations = [], unit = variable === 'wave_height' ? 'ft' : 'kn';
  for (let i = 0; i < count; i++) {
    const time = nowS - 3600 - i * spacingH * 3600, cycle = time - leadH * 3600, [observed, predicted] = pairs(i);
    forecasts.push({id: `f${i}`, model: 'gfs_global', cycle, acquired_at: cycle + 3600, station: '46028', time, variable, value: predicted, unit, grid: COORDS, station_coordinates: COORDS});
    observations.push({id: `o${i}`, station: '46028', time, variable, value: observed, unit, received_at: time + 600, qa: 'provisional_automated', station_coordinates: COORDS, measurement_height_m: 10});
  }
  writeFileSync(join(dir, 'morro-bay', 'verification-state.json'), JSON.stringify({schema_version: 1, region_id: 'morro-bay', forecasts, observations}));
  const out = join(dir, 'skill.json');
  execFileSync('python3', [SCRIPT, '--regions-dir', dir, '--out', out, '--now', String(nowS)], {stdio: 'pipe'});
  const scores = JSON.parse(readFileSync(out, 'utf8')).scores;
  return (lead, window, v = variable) => scores.find(r => r.station === '46028' && r.variable === v && r.lead_hours === lead && r.window_days === window);
}

test('publisher: the wind tolerance is 5 kn and the limit itself counts', () => {
  const at = publish({count: 40, variable: 'wind_speed_10m', pairs: i => [10, i < 25 ? 15 : 15.5]})(24, 30);
  assert.deepEqual([at.n, at.within, at.enough, at.tolerance], [40, 25, true, 'within 5 kn']);
});

test('publisher: wave tolerance is 1 ft up to 3 ft and 25 percent above', () => {
  const hit = (pair, count = 40) => publish({count, pairs: () => pair})(24, 30).within;
  assert.equal(hit([3, 4]), 40);            // at 3 ft, 1 ft counts
  assert.equal(hit([3, 4.2]), 0);           // 0 hits is a result, not a missing figure
  assert.equal(hit([2, 3]), 40);            // 1 ft counts at 2 ft seas
  assert.equal(hit([8, 10]), 40);           // 2 ft counts at 8 ft seas (25%)
  assert.equal(hit([8, 10.5]), 0);
  assert.equal(hit([8, 9]), 40);
});

test('publisher: no figure below the pipeline minimum of 30 valid times, 7 days and 3 runs', () => {
  const at = (count, spacingH, window = 30) => publish({count, spacingH, pairs: () => [2, 2]})(24, window);
  assert.deepEqual([at(29, 6).enough, at(29, 6).within, at(29, 6).n], [false, null, 29]);
  assert.deepEqual([at(30, 6).enough, at(30, 6).within], [true, 30]);
  const short = at(30, 4);                  // 30 valid times but only ~5 days
  assert.deepEqual([short.n, short.enough, short.within, short.valid_times >= 30, short.days < 7], [30, false, null, true, true]);
  const none = publish({count: 0, pairs: () => [0, 0]})(24, 7);
  assert.deepEqual([none.n, none.within, none.enough], [0, null, false]);
});

test('publisher: the 7-day window counts only the last 7 days, the 30-day window all of them', () => {
  const at = publish({count: 80, spacingH: 4, pairs: i => [2, i < 42 ? 2 : 6]});
  assert.deepEqual([at(24, 7).n, at(24, 7).within], [42, 42]);
  assert.deepEqual([at(24, 30).n, at(24, 30).within], [80, 42]);
});

test('publisher: lead times are 24, 48 and 72 hours apart, and a longer lead is not published', () => {
  for (const [leadH, lead] of [[6, 24], [18, 24], [30, 48], [60, 72]]) {
    const at = publish({count: 31, leadH, pairs: () => [2, 2]});
    assert.equal(at(lead, 30).n, 31, `lead ${leadH} h`);
    assert.equal(at(lead === 24 ? 48 : 24, 30).n, 0);
  }
  assert.deepEqual([24, 48, 72].map(l => publish({count: 31, leadH: 100, pairs: () => [2, 2]})(l, 30).n), [0, 0, 0]);
});
