import test from 'node:test';
import assert from 'node:assert/strict';
import {withTideSelection} from '../web/tide-stations.ts';
import {buildCoastBrief} from '../web/brief/model.ts';
import {slo} from '../packages/coast/src/counties.ts';
import fixture from './fixtures/coast/skippercast-report.json' with {type: 'json'};

const station = {id: '9000002', name: 'Synthetic station'};
const clock = new Date('2026-10-08T17:00:00Z');
const brief = buildCoastBrief({report: fixture, county: slo, areaId: 'central', profile: 'boat', date: '2026-10-08', now: clock});
const iso = (h, m, s = 0, ms = 0) => new Date(Date.UTC(2026, 9, 8, h, m, s, ms)).toISOString();
const pt = (h, m, heightFt, ms = 0) => ({at: iso(h, m, 0, ms), heightFt});
const reading = (points, events = [], extra = {}) => ({station: {...station, lat: 35, lng: -121, type: 'S'}, points, events, fetchedAt: clock.toISOString(), failed: false, ...extra});
const tile = b => b.tiles.find(t => t.id === 'tide');
const run = (points, at, events = [], now = clock, r = reading(points, events)) => tile(withTideSelection(brief, station, r, slo.timezone, now, at));
const synthetic = [pt(18, 0, 1), pt(18, 6, 4), pt(18, 12, 2)];

globalThis.fetch = () => { throw new Error('unexpected fetch: these tests are offline'); };

test('chosen_tide_nearest_sample_and_trend_agree', () => {
  const t = run(synthetic, iso(18, 4));
  assert.equal(t.value, 4);
  assert.equal(t.detail, 'Falling · Synthetic station · MLLW');
  const n = run(synthetic, null, [], new Date(iso(18, 4)));
  assert.equal(n.value, 4);
  assert.equal(n.detail, 'Falling · Synthetic station · MLLW');
});

test('chosen_tide_tie_is_earlier_and_exact_wins', () => {
  const tie = run(synthetic, iso(18, 3));
  assert.equal(tie.value, 1); assert.equal(tie.detail, 'Rising · Synthetic station · MLLW');
  const exact = run(synthetic, iso(18, 6));
  assert.equal(exact.value, 4); assert.equal(exact.detail, 'Falling · Synthetic station · MLLW');
  // Denser curve: 18:02 (3 ft, rising to 18:03 5 ft) is earlier than 18:03 but farther from 18:04 than 18:03.
  const dense = [pt(18, 1, 2), pt(18, 2, 3), pt(18, 3, 5), pt(18, 5, 4), pt(18, 8, 4)];
  const picked = run(dense, iso(18, 4, 30));
  assert.equal(picked.value, 4, 'nearest to 18:04:30 is 18:05 (30 s) not 18:03 (90 s)');
  assert.equal(picked.detail.split(' · ')[0], 'Turning', '18:05 -> 18:08 is flat 4 -> 4');
  const early = run(dense, iso(18, 3, 20));
  assert.equal(early.value, 5);
  assert.equal(early.detail.split(' · ')[0], 'Falling', 'trend starts at 18:03 (5 -> 4), not at the earlier 18:02 (3 -> 5)');
  // Equal-time duplicates keep the first input occurrence.
  const dup = run([pt(18, 0, 1), pt(18, 0, 9), pt(18, 6, 4)], iso(18, 1));
  assert.equal(dup.value, 1);
  // Input is not sorted or mutated.
  const input = [pt(18, 12, 2), pt(18, 0, 1), pt(18, 6, 4)], before = JSON.stringify(input);
  const unsorted = run(input, iso(18, 5));
  assert.equal(unsorted.value, 4);
  assert.equal(JSON.stringify(input), before);
});

test('chosen_tide_match_boundary_and_last_point', () => {
  for (const sign of [-1, 1]) {
    const base = [pt(18, 10, 3), pt(18, 20, 5)];
    const at = new Date(Date.parse(base[0].at) + sign * 4 * 60000).toISOString();
    const ok = run(base, at);
    assert.equal(ok.value, 3, `sole candidate at ${sign * 4} minutes matches`);
    const over = new Date(Date.parse(base[0].at) + sign * (4 * 60000 + 1)).toISOString();
    const no = run(base, over);
    assert.equal(no.value, null, 'one ms beyond tolerance is not eligible');
    assert.equal(no.detail.split(' · ')[0], 'Predictions unavailable');
  }
  // The closest point is last: height, no trend; do not retreat to a farther pair.
  const last = run([pt(18, 0, 1), pt(18, 3, 2), pt(18, 6, 7)], iso(18, 7));
  assert.equal(last.value, 7);
  assert.equal(last.detail, 'Synthetic station · MLLW');
  // Invalid timestamp or height is not a usable curve value.
  const bad = run([{at: 'not-a-time', heightFt: 8}, {at: iso(18, 2), heightFt: Number.NaN}, pt(18, 4, 3), pt(18, 10, 6)], iso(18, 2));
  assert.equal(bad.value, 3);
  assert.equal(bad.detail.split(' · ')[0], 'Rising');
});

test('chosen_tide_day_cut_and_event_fallback', () => {
  // 2026-10-08 in Pacific time ends at 07:00Z on the 9th: neighbouring local-day samples cannot win.
  const edge = '2026-10-09T06:59:00.000Z';
  const next = {at: '2026-10-09T07:01:00.000Z', heightFt: 9};
  const t = run([{at: '2026-10-09T06:56:00.000Z', heightFt: 2}, next], '2026-10-09T07:00:00.000Z', [], new Date(edge));
  assert.equal(t.value, 2, 'the in-day point wins within tolerance; the next-day sample is cut');
  const none = run([next], '2026-10-09T07:00:00.000Z', [], new Date(edge));
  assert.equal(none.value, null);
  // Event-only subordinate keeps next high/low.
  const events = [{at: iso(20, 0), type: 'L', heightFt: 0.4}, {at: iso(23, 0), type: 'H', heightFt: 5.5}];
  const ev = run([], iso(19, 0), events);
  assert.equal(ev.value, 0.4); assert.equal(ev.detail, 'next low · Synthetic station · MLLW');
  const nothing = run([], iso(23, 30), events);
  assert.equal(nothing.value, null); assert.equal(nothing.state, 'unavailable');
  assert.equal(nothing.detail, 'Predictions unavailable · Synthetic station · MLLW');
  // A valid curve point takes precedence over an upcoming event.
  const both = run(synthetic, iso(18, 4), [{at: iso(19, 0), type: 'H', heightFt: 6}]);
  assert.equal(both.value, 4); assert.equal(both.detail, 'Falling · Synthetic station · MLLW');
  // No eligible curve point falls back to the event.
  const far = run([pt(17, 0, 1)], iso(18, 4), [{at: iso(19, 0), type: 'H', heightFt: 6}]);
  assert.equal(far.value, 6); assert.match(far.detail, /^next high/);
  // An invalid selected time falls back to now.
  const invalid = run(synthetic, 'not-a-time', [], new Date(iso(18, 4)));
  assert.equal(invalid.value, 4);
  assert.equal(invalid.detail, 'Falling · Synthetic station · MLLW');
});

test('chosen_tide_overlay_preserves_reviewed_assessments', () => {
  const r = reading(synthetic, [{at: iso(19, 0), type: 'H', heightFt: 6}]);
  const out = withTideSelection(brief, station, r, slo.timezone, clock, iso(18, 4));
  for (const key of ['shore', 'bar', 'windows', 'missing', 'deck', 'headline', 'status', 'confidence']) assert.deepEqual(out[key], brief[key], key);
  assert.deepEqual(out.tiles.filter(t => t.id !== 'tide'), brief.tiles.filter(t => t.id !== 'tide'));
  assert.equal(out.tides.length, 3); assert.equal(out.tideEvents.length, 1); assert.equal(out.tideDatum, 'MLLW');
  const t = tile(out);
  assert.equal(t.source, 'NOAA 9000002 Synthetic station'); assert.equal(t.unit, 'ft'); assert.equal(t.at, r.fetchedAt);
  assert.equal(t.state, 'fresh');
  assert.equal(tile(withTideSelection(brief, station, {...r, failed: true}, slo.timezone, clock, iso(18, 4))).state, 'stale');
  assert.equal(tile(withTideSelection(brief, station, {...r, fetchedAt: '2026-10-01T00:00:00Z'}, slo.timezone, clock, iso(18, 4))).state, 'stale');
  const empty = tile(withTideSelection(brief, station, reading([], []), slo.timezone, clock, iso(18, 4)));
  assert.equal(empty.value, null); assert.equal(empty.state, 'unavailable');
  const missing = withTideSelection(brief, station, null, slo.timezone, clock, iso(18, 4));
  assert.equal(tile(missing).value, null); assert.equal(tile(missing).state, 'unavailable'); assert.deepEqual(missing.tides, []);
});
