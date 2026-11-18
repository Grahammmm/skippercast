// RF2021-9: the reef download offer never shows a nonfinite size. Offline, synthetic numbers only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {offerMegabytes} from '../web/reef-lazy.ts';

test('nonfinite_offer_size_is_unknown', () => {
  for (const bad of [Infinity, -Infinity, NaN]) assert.equal(offerMegabytes(bad), null);
});

test('offer_size_small_and_rounding_boundaries', () => {
  assert.equal(offerMegabytes(1), 1);
  assert.equal(offerMegabytes(400_000), 1);
  assert.equal(offerMegabytes(1_499_999), 1);
  assert.equal(offerMegabytes(1_500_000), 2);
});

test('healthy_offer_size_unchanged', () => {
  assert.equal(offerMegabytes(15_000_000), 15);
  for (const none of [0, -5, null, undefined]) assert.equal(offerMegabytes(none), null);
  assert.ok(Number.isFinite(offerMegabytes(Number.MAX_VALUE)));
});
