import assert from 'node:assert/strict';
import test from 'node:test';
import {shoreEvidence} from '../packages/coast/src/shore-review.ts';

// C5: Each literal oracle runs in both zones so a browser-local fallback cannot
// accidentally agree with the expected day just because of the host's TZ.
for (const tz of ['America/Los_Angeles', 'Pacific/Kiritimati']) {
  const check = (title, props, expected) => test(`${title} (${tz})`, () => {
    const previous = process.env.TZ;
    process.env.TZ = tz;
    try {
      assert.equal(shoreEvidence(props), expected);
    } finally {
      if (previous === undefined) delete process.env.TZ;
      else process.env.TZ = previous;
    }
  });

  check('C1: stored days do not shift at UTC midnight, including leap day',
    {checkedAt: '2026-09-01', legalReviewExpiresAt: '2028-02-29'},
    'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory checked Sep 1, 2026. Current legal/access conditions require rechecking; the prior legal review expired Feb 29, 2028.');

  check('C2: zoned instants use Los Angeles, not UTC or the host zone',
    {checkedAt: '2026-10-03T02:48:10Z', legalReviewExpiresAt: '2026-10-03T16:48:10+14:00'},
    'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory checked Oct 2, 2026. Current legal/access conditions require rechecking; the prior legal review expired Oct 2, 2026.');

  check('C3: explicit null means never reviewed, not unknown or the epoch',
    {checkedAt: null, legalReviewExpiresAt: null},
    'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory not yet reviewed. Current legal/access conditions require rechecking; legal review: not yet reviewed.');

  const unknown = 'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory check date unknown. Current legal/access conditions require rechecking; legal review date unknown.';
  check('C3: missing and undefined clocks do not print Invalid Date',
    {legalReviewExpiresAt: undefined}, unknown);
  check('C3: unparseable strings are unknown, not checked or expired',
    {checkedAt: '', legalReviewExpiresAt: 'soon'}, unknown);
  check('C3: impossible days cannot roll into the next month',
    {checkedAt: '2026-02-31', legalReviewExpiresAt: '2026-02-29T12:00:00Z'}, unknown);
  check('C3: zone-less times cannot inherit the host zone',
    {checkedAt: '2026-10-03T02:48:10', legalReviewExpiresAt: '2026-10-03T02:48:10'}, unknown);
}

test('C4: mixed clock states keep the evidence wording, order and punctuation', () => {
  assert.equal(shoreEvidence({checkedAt: null, legalReviewExpiresAt: '2026-09-30'}),
    'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory not yet reviewed. Current legal/access conditions require rechecking; the prior legal review expired Sep 30, 2026.');
});
