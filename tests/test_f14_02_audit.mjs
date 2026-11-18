import assert from 'node:assert/strict';
import test from 'node:test';
import {BADGE_WORD, depthText, spotBadges} from '../web/confidence.ts';

function reading(verticalDatum, nativeDatum, datumLabel) {
  const target = {
    center_depth_ft: 43,
    depth_qualified: true,
    vertical_datum: verticalDatum,
    qualification: {
      full_geometry_screened: true,
      native_datum: nativeDatum,
      maximum_product_uncertainty_m: 1,
    },
  };
  const [badge] = spotBadges(target, datumLabel);
  return {label: BADGE_WORD[badge.state], depth: depthText(target, badge), why: badge.why.text};
}

for (const [reported, native, canonical] of [
  ['MLLW', 'MLLW', 'MLLW'],
  ['  mean LOWER low water  ', 'MLLW depth', 'MLLW'],
  ['NAVD88', 'North American Vertical Datum of 1988', 'NAVD88'],
  ['Mean Sea Level', 'MSL', 'MSL'],
]) {
  test(`${JSON.stringify(reported)} qualifies on matching ${JSON.stringify(native)} survey evidence`, () => {
    const result = reading(reported, native);
    assert.equal(result.label, 'Qualified');
    assert.equal(result.depth, '43 ft');
    assert.ok(result.why.startsWith(`Measured-depth screen on ${canonical}:`));
  });
}

for (const [reason, reported, native, label] of [
  ['audit placeholder without native datum', 'N/A', undefined],
  ['matching placeholders', 'N/A', 'N/A'],
  ['already unqualified unknown datum', 'unknown', undefined],
  ['blank reported datum despite valid survey datum and display label', '   ', 'MLLW', 'MLLW'],
  ['unrecognized matching datum', 'Unlisted local datum', 'Unlisted local datum'],
  ['a recognized substring in ambiguous metadata', 'MLLW or NAVD88', 'MLLW or NAVD88'],
  ['contradictory recognized datums', 'Mean Lower Low Water', 'NAVD88'],
  ['placeholder native datum', 'MLLW', 'N/A'],
  ['blank native datum', 'MLLW', ''],
  ['missing native evidence', 'MLLW', undefined],
]) {
  test(`${reason} keeps the 43 ft depth estimated`, () => {
    const {label: badgeLabel, depth} = reading(reported, native, label);
    assert.deepEqual({label: badgeLabel, depth}, {label: 'Estimated', depth: '~43 ft (estimated)'});
  });
}
