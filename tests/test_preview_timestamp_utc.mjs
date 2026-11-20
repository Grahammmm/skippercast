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
