import test from 'node:test';
import assert from 'node:assert/strict';
import {utc, freshWithin} from '../web/map/preview/common.ts';

const WANT = '2026-11-17 00:30 UTC';
const FORMS = ['2026-11-17T00:30:00Z', '2026-11-16T16:30:00-08:00', '2026-11-17T06:00:00+05:30'];

test('equivalent_offsets_share_utc_label', () => {
  for (const iso of FORMS) assert.equal(utc(iso), WANT, iso);
});

test('positive_offset_rolls_to_previous_utc_date', () => {
  assert.equal(utc('2026-11-17T00:15:00+05:30'), '2026-11-16 18:45 UTC');
});

test('z_format_and_invalid_fallback_are_preserved', () => {
  assert.equal(utc('2026-11-17T00:30:59Z'), WANT);
  assert.equal(utc('not-a-time'), 'not-a-time UTC');
});

test('admission_and_source_identity_stay_unchanged', () => {
  const now = new Date('2026-11-17T01:00:00Z');
  for (const iso of FORMS) {
    const copy = String(iso);
    assert.equal(freshWithin(iso, 6, now), true);
    assert.equal(iso, copy);
  }
});

// Contract: freshness only admits a sample whose calendar date and clock exist, so the age and the UTC label shown are true.
// Date.parse normalises Feb 30 to Mar 2, so without the check a malformed sample is reported fresh under the wrong date.
const NOW = new Date('2026-03-02T12:00:00Z');

test('valid_march_2_control_stays_fresh_with_its_label', () => {
  // Control: the date Date.parse would normalise Feb 30 to. Catches an over-broad guard that rejects real March 2 data.
  assert.equal(freshWithin('2026-03-02T11:00:00Z', 48, NOW), true);
  assert.equal(utc('2026-03-02T11:00:00Z'), '2026-03-02 11:00 UTC');
});

test('calendar_impossible_dates_are_not_fresh', () => {
  // Catches Date.parse normalisation (Feb 30 -> Mar 2, Apr 31 -> May 1, non-leap Feb 29 -> Mar 1) being trusted.
  for (const iso of ['2026-02-30T11:00:00Z', '2026-02-29T11:00:00Z', '2026-04-31T11:00:00Z', '2026-02-30 11:00 UTC', '2026-00-10T11:00:00Z', '2026-13-10T11:00:00Z', '2026-03-00T11:00:00Z', '2026-03-32T11:00:00Z']) {
    assert.equal(freshWithin(iso, 10_000, NOW), false, iso);
  }
});

test('leap_day_is_still_a_real_date', () => {
  // Catches a month-length table that forgets leap years (a rejection of real Feb 29 data).
  assert.equal(freshWithin('2028-02-29T11:00:00Z', 48, new Date('2028-02-29T12:00:00Z')), true);
});

test('impossible_clock_times_are_not_fresh', () => {
  // Catches a guard that checks the date but lets hour 25 / minute 60 / second 60 through if the engine ever normalises them.
  for (const iso of ['2026-03-02T25:00:00Z', '2026-03-02T11:60:00Z', '2026-03-02T11:00:60Z']) {
    assert.equal(freshWithin(iso, 48, NOW), false, iso);
  }
});

test('zone_age_limit_and_future_slack_are_unchanged', () => {
  // Catches the new check altering the existing rules: zone still required, 48 h limit inclusive, 5 min future slack.
  assert.equal(freshWithin('2026-03-02T11:00:00', 48, NOW), false, 'zone required');
  assert.equal(freshWithin('2026-02-28T12:00:00Z', 48, NOW), true, 'exactly at the age limit');
  assert.equal(freshWithin('2026-02-28T11:59:00Z', 48, NOW), false, 'past the age limit');
  assert.equal(freshWithin('2026-03-02T12:05:00Z', 48, NOW), true, 'exactly at the future slack');
  assert.equal(freshWithin('2026-03-02T12:06:00Z', 48, NOW), false, 'beyond the future slack');
});
