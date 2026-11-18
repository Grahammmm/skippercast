import test from 'node:test';
import assert from 'node:assert/strict';
import {weekendDigest, toText} from '../web/digest.ts';
import {t} from '../web/i18n.ts';

// F14-09: one malformed stored hazard entry must not hide the valid warnings or leave a clean-looking status.
const names = {point: new Map([['a', 'Alpha']]), species: new Map([['reef', 'Rockfish']])};
const trip = last_assessment => ({id: 'f', date: '2026-11-07', point: 'a', species: 'reef', start_hour: 7, end_hour: 13, enabled: 1, last_assessment});
const lineOf = (last_assessment, lang) => weekendDigest([trip(last_assessment)], names, '2026-11-04', lang).days[0].lines[0];
const assessed = (status, hazards) => JSON.stringify({status, hazards});
const SWELL = 'Long-period swell is forecast.';
const BAR = 'Harbour bar crossing may be rough.';

for (const lang of ['en', 'es']) {
  const note = t('digest.hazard', lang);
  const within = t('digest.within', lang);
  const incomplete = t('digest.unverified', lang);
  const tail = line => line.split(' — ')[1];

  test(`${lang}: mixed list keeps every valid warning and downgrades to incomplete`, () => {
    for (const bad of ['', '   ', 5, null, {}, ['x']]) {
      const out = tail(lineOf(assessed('within limits', [SWELL, bad, BAR]), lang));
      assert.equal(out, `${incomplete} ${note} ${SWELL} ${note} ${BAR}`, JSON.stringify(bad));
      assert.ok(!out.includes(within));
    }
    assert.equal(tail(lineOf(assessed('above limits', ['', BAR]), lang)), `${incomplete} ${note} ${BAR}`);
  });

  test(`${lang}: list with no valid entry, or a non-list value, is incomplete rather than clean`, () => {
    for (const hazards of [[''], [5], 'Long-period swell.', {note: SWELL}, 5, true]) {
      assert.equal(tail(lineOf(assessed('within limits', hazards), lang)), incomplete, JSON.stringify(hazards));
    }
  });

  test(`${lang}: well-formed empty or absent list stays a distinct clean status`, () => {
    assert.equal(tail(lineOf(assessed('within limits', []), lang)), within);
    assert.equal(tail(lineOf(JSON.stringify({status: 'within limits'}), lang)), within);
    assert.equal(tail(lineOf(assessed('within limits', null), lang)), within);
    assert.notEqual(within, incomplete);
  });

  test(`${lang}: positive control, all-valid list is unchanged and toText carries it`, () => {
    assert.equal(tail(lineOf(assessed('within limits', [SWELL, BAR]), lang)), `${within} ${note} ${SWELL} ${note} ${BAR}`);
    const digest = weekendDigest([trip(assessed('within limits', [SWELL, 7]))], names, '2026-11-04', lang);
    assert.ok(toText(digest, lang).includes(`${note} ${SWELL}`));
  });
}
