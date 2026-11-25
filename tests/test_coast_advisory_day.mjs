import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { localTargetAdvisory } from '../dist/coasts.js';

const url = 'https://example.test/advisory';
const north = { text: 'North note', url };
const south = { text: 'South note', url };
const expired = { text: 'Expired note', url };
const coast = through => ({
  local_target_advisories: [{
    target: 'salmon', through, north_of_latitude: 38,
    north_note: 'North note', south_note: 'South note', expired_note: 'Expired note', source_url: url,
  }],
});

// C4: Repeat each case under both process defaults to catch accidental use of host time.
for (const tz of ['America/Los_Angeles', 'Asia/Tokyo']) {
  describe(`C4: Advisory day with process TZ=${tz}`, () => {
    const previousTZ = process.env.TZ;
    before(() => { process.env.TZ = tz; });
    after(() => {
      if (previousTZ === undefined) delete process.env.TZ;
      else process.env.TZ = previousTZ;
    });

    // A fixed offset ends the winter date early; whole seconds alone lose the final 999 ms.
    for (const [through, lastSecond, midnight, season] of [
      ['2026-12-15', '2026-12-16T07:59:59', '2026-12-16T08:00:00Z', 'PST'],
      ['2026-07-15', '2026-07-16T06:59:59', '2026-07-16T07:00:00Z', 'PDT'],
      ['2026-03-08', '2026-03-09T06:59:59', '2026-03-09T07:00:00Z', 'spring transition'],
      ['2026-11-01', '2026-11-02T07:59:59', '2026-11-02T08:00:00Z', 'fall transition'],
    ]) {
      test(`C1: ${season} advisory ends at Pacific midnight (C4)`, () => {
        const region = coast(through);
        assert.deepEqual(localTargetAdvisory(region, 'salmon', 38, Date.parse(`${lastSecond}Z`)), north);
        assert.deepEqual(localTargetAdvisory(region, 'salmon', 38, Date.parse(`${lastSecond}.999Z`)), north);
        assert.deepEqual(localTargetAdvisory(region, 'salmon', 38, Date.parse(midnight)), expired);
      });
    }

    const now = Date.parse('2026-02-01T12:00:00Z');
    // Bad input must not stay active because parsing returns NaN or rolls into March.
    for (const through of [undefined, '2026-2-15', '2026-02-31']) {
      test(`C2: invalid through ${through} is expired (C4)`, () => {
        assert.deepEqual(localTargetAdvisory(coast(through), 'salmon', 38, now), expired);
      });
    }

    test('C3: preserve full north and south results at the latitude split', () => {
      const region = coast('2026-02-15');
      assert.deepEqual(localTargetAdvisory(region, 'salmon', 38, now), north);
      assert.deepEqual(localTargetAdvisory(region, 'salmon', 37.99, now), south);
    });

    test('C3: preserve null for no advisory, no match, or a non-finite latitude', () => {
      const region = coast('2026-02-15');
      assert.deepEqual(localTargetAdvisory({}, 'salmon', 38, now), null);
      assert.deepEqual(localTargetAdvisory(region, 'reef', 38, now), null);
      assert.deepEqual(localTargetAdvisory(region, 'salmon', NaN, now), null);
    });
  });
}
