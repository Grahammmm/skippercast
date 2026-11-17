import test from 'node:test';
import assert from 'node:assert/strict';
import {nearshoreAt} from '../packages/coast/src/nearshore.ts';

const rows = [{at: '2026-01-01T12:00:00Z', waveFt: 1}, {at: '2026-01-01T14:00:00Z', waveFt: 2}];
const site = (validThrough) => ({hours: rows, ...(validThrough === undefined ? {} : {validThrough})});
const Q = '2026-01-01T13:00:00Z';

test('nearshore_declared_unreadable_end_is_not_unbounded', () => {
  for (const bad of ['not-a-date', '', '   ', '2026-13-45T99:00:00Z', 5, {}, true]) {
    assert.equal(nearshoreAt(site(bad), Q), undefined, String(JSON.stringify(bad)));
  }
});

test('nearshore_null_or_omitted_end_keeps_sample_span', () => {
  for (const s of [site(null), site(undefined)]) {
    assert.equal(nearshoreAt(s, Q), rows[0]);
    assert.equal(nearshoreAt(s, '2026-01-01T11:59:59Z'), undefined);
    assert.equal(nearshoreAt(s, '2026-01-01T14:00:01Z'), undefined);
  }
});

test('nearshore_declared_end_boundary_is_inclusive', () => {
  assert.equal(nearshoreAt(site('2026-01-01T13:00:00Z'), Q), rows[0]);
  assert.equal(nearshoreAt(site('2026-01-01T12:59:59.999Z'), Q), undefined);
  assert.equal(nearshoreAt(site('2026-01-01T05:00:00-08:00'), Q), rows[0]);
  assert.equal(nearshoreAt(site('2026-01-01T12:30:00Z'), Q), undefined);
});

test('nearshore_nearest_controls_and_purity', () => {
  const s = site('2026-01-02T00:00:00Z');
  Object.freeze(s); Object.freeze(rows); rows.forEach(Object.freeze);
  assert.equal(nearshoreAt(s, '2026-01-01T14:00:00Z'), rows[1]);
  assert.equal(nearshoreAt(s, '2026-01-01T12:00:00Z'), rows[0]);
  assert.equal(nearshoreAt({hours: [], validThrough: null}, Q), undefined);
  assert.equal(nearshoreAt(s, 'nope'), undefined);
});
