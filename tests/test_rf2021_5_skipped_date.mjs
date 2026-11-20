// RF2021-5: a date the region skipped stays as the original ISO text instead of showing another day.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readableDate, readableDates} from '../web/dates.ts';

const APIA = 'Pacific/Apia';

test('skipped_apia_date_stays_literal', () => {
  assert.equal(readableDate('2011-12-30', 'en', APIA), '2011-12-30');
  assert.equal(readableDate('2011-12-30', 'es', APIA), '2011-12-30');
});

test('adjacent_apia_dates_are_not_rejected', () => {
  assert.equal(readableDate('2011-12-29', 'en', APIA), 'Thu 29 Dec');
  assert.equal(readableDate('2011-12-31', 'en', APIA), 'Sat 31 Dec');
  for (const d of ['2011-12-29', '2011-12-31']) {
    const es = readableDate(d, 'es', APIA);
    assert.notEqual(es, d);
    assert.match(es, /dic/);
  }
});

test('representable_dates_and_embedded_text_are_preserved', () => {
  for (const zone of ['UTC', 'America/Los_Angeles', 'Pacific/Auckland']) {
    assert.equal(readableDate('2026-11-10', 'en', zone), 'Tue 10 Nov', zone);
  }
  assert.equal(readableDates('Plan for 2011-12-30 and 2011-12-31.', 'en', APIA), 'Plan for 2011-12-30 and Sat 31 Dec.');
});
