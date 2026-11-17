import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {historyView} from '../packages/coast/src/ui/history.ts';

const HOUR = 3600000, NOW = Date.parse('2026-11-16T12:00:00Z'), CUT = NOW - 7 * 24 * HOUR;
const mk = (extra = {}, from = CUT, n = 169) => Array.from({length: n}, (_, i) => ({at: new Date(from + i * HOUR).toISOString(), waterTempF: 58, sampleCount: 1, ...(extra[i] ?? {})}));
const bundleOf = hours => ({countyId: 'synthetic', recentWindowDays: 7, stations: [{stationId: 'synthetic', name: 'Synthetic buoy', recent: {hours, lastObservedAt: hours.at(-1)?.at ?? null, hourCoverageFraction: 1}, baseline: {months: [], years: []}, archive: {availableYears: []}, sources: []}]});
const render = (bundle, offset = 0, copy) => historyView({county: {id: 'synthetic', timezone: 'UTC'}, now: new Date(NOW + offset)}, bundle, {station: 'synthetic', metric: 'waterTempF', days: 7}, copy);
const cov = html => html.match(/\d[\d,]* \/ [\d,]+ hourly bins · [\d.]+% metric coverage/)?.[0];

test('exact_hour_uses_168_of_168_bins', () => {
  assert.equal(cov(render(bundleOf(mk()))), '168 / 168 hourly bins · 100.0% metric coverage');
});

test('cutoff_observation_is_excluded_from_stats_and_chart', () => {
  const bundle = bundleOf(mk({168: {waterTempF: 99}}));
  const before = structuredClone(bundle);
  const html = render(bundle);
  assert.equal(cov(html), '168 / 168 hourly bins · 100.0% metric coverage');
  assert.ok(!html.includes('99.0'), 'cutoff observation must not become latest/mean');
  assert.ok(!html.includes('>100.0</text>'), 'cutoff observation must not stretch the chart scale');
  assert.ok(isDeepStrictEqual(bundle, before), 'bundle unchanged');
});

test('partial_current_hour_is_still_counted', () => {
  const bundle = bundleOf(mk({168: {waterTempF: 99}}));
  for (const offset of [1, 30 * 60000]) {
    const html = render(bundle, offset);
    assert.equal(cov(html), '169 / 169 hourly bins · 100.0% metric coverage');
    assert.ok(html.includes('99.0'), 'latest hour included');
  }
});

test('left_endpoint_and_missing_metrics_keep_semantics', () => {
  const html = render(bundleOf(mk({0: {waterTempF: null}, 5: {waterTempF: null}}, CUT - HOUR, 170)));
  assert.equal(cov(html), '167 / 168 hourly bins · 99.4% metric coverage');
  assert.equal(cov(render(bundleOf(mk({}, NOW, 1)))), '0 / 168 hourly bins · 0.0% metric coverage');
});

test('translated_counts_use_the_same_population', () => {
  const seen = [];
  const copy = {text: (k, v) => { if (k === 'history.bins') seen.push(v); return k; }, time: at => at, number: n => String(n), age: () => 'ago'};
  render(bundleOf(mk()), 0, copy);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].valid, '168');
  assert.equal(seen[0].expected, '168');
});
