import test from 'node:test';
import assert from 'node:assert/strict';
import {aerialBase} from '../web/aerial-base.ts';

const region = (first, last, checked, extra = {}) => ({
  basemap: {default: 'aerial', aerial: {source: 'usgs-naip', checked_at: checked, acquired: {first, last}, note: 'synthetic', ...extra}},
});

test('aerial_impossible_calendar_dates_are_absent', () => {
  const bad = ['2024-00-15', '2024-13-01', '2024-01-00', '2024-01-32', '2024-04-31', '2023-02-29'];
  for (const d of bad) {
    // Surrounding dates keep the ordering valid so only the calendar check can reject.
    assert.equal(aerialBase(region(d, '2099-01-01', '2099-12-31')), null, `first ${d}`);
    assert.equal(aerialBase(region('0099-01-01', d, '2099-12-31')), null, `last ${d}`);
    assert.equal(aerialBase(region('0099-01-01', '0099-01-02', d)), null, `checked ${d}`);
  }
  assert.equal(aerialBase(region('2024-02-29', '2024-02-29', '2025-99-99')), null);
});

test('aerial_leap_and_early_year_controls', () => {
  for (const d of ['2000-02-29', '2024-02-29', '0099-03-04']) {
    const r = aerialBase(region(d, d, d));
    assert.ok(r, d);
    assert.equal(r.first, d);
  }
  assert.equal(aerialBase(region('1900-02-29', '1900-02-29', '1900-02-29')), null);
});

test('aerial_valid_metadata_is_unchanged', () => {
  assert.ok(require_equal(aerialBase(region('2020-05-01', '2021-06-02', '2022-07-03')),
    {source: 'usgs-naip', first: '2020-05-01', last: '2021-06-02', checkedAt: '2022-07-03', note: 'synthetic', byDefault: true}));
  assert.equal(aerialBase(region('2021-06-02', '2020-05-01', '2022-07-03')), null);
  assert.equal(aerialBase(region(' 2020-05-01', '2021-06-02', '2022-07-03')), null);
  assert.equal(aerialBase(region('2020-5-1', '2021-06-02', '2022-07-03')), null);
  assert.equal(aerialBase(region('2020-05-01', '2021-06-02', '2022-07-03', {source: 'other'})), null);
  assert.equal(aerialBase(region('2020-05-01', '2021-06-02', undefined)), null);
});

function require_equal(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
