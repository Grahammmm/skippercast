import test from 'node:test';
import assert from 'node:assert/strict';
import {admitShore, shoreContext, shoreEvidence, sourceReview, unreviewedStatus} from '../../packages/coast/src/shore-review.ts';

const NOW = Date.parse('2026-11-05T00:00:00Z');
const line = {type: 'MultiLineString'};
const run = (id: string, reviewExpiresAt: unknown, substrate = 'sand') => ({id, geometry: line, properties: {substrate, reviewExpiresAt}}) as any;

test('only an explicit null source clock is never reviewed; expired and malformed stay distinct', () => {
  assert.equal(sourceReview(null, NOW), 'unreviewed');
  assert.equal(sourceReview('2026-11-06T00:00:00Z', NOW), 'current');
  assert.equal(sourceReview('2026-11-04T00:00:00Z', NOW), 'expired');
  assert.equal(sourceReview('2026-11-05T00:00:00Z', NOW), 'expired', 'the expiry instant itself is no longer current');
  for (const bad of [undefined, '', 'soon', 0, {}]) assert.equal(sourceReview(bad as any, NOW), 'unknown');
});

test('admission keeps current runs, counts never-reviewed ones, and drops expired, malformed and non-line features', () => {
  const features = [run('a', '2026-12-01T00:00:00Z'), run('r', null, 'rocky'), run('x', '2026-01-01T00:00:00Z'), run('m', 'soon'), run('u', undefined),
    {id: 'p', geometry: {type: 'Point'}, properties: {reviewExpiresAt: null}}] as any[];
  const {shown, unreviewed} = admitShore(features, NOW);
  assert.deepEqual(shown.map(f => f.id), ['a']);
  assert.equal(unreviewed, 1);
  assert.deepEqual(admitShore([], NOW), {shown: [], unreviewed: 0});
});

test('status and labels: sand copy is unchanged, rocky and mixed are named, unreviewed is said when present', () => {
  assert.equal(shoreContext([]), 'sandy-shore');
  assert.equal(shoreContext(['sand', undefined, 'sand']), 'sandy-shore');
  assert.equal(shoreContext(['rocky']), 'rocky-shore');
  assert.equal(shoreContext(['sand', 'rocky']), 'shore');
  assert.equal(unreviewedStatus(0), '');
  assert.equal(unreviewedStatus(1), ' 1 shore run not yet reviewed is withheld.');
  assert.equal(unreviewedStatus(3), ' 3 shore runs not yet reviewed are withheld.');
});

test('evidence never turns an absent clock into a date, "checked" or "expired"', () => {
  const none = shoreEvidence({checkedAt: null, legalReviewExpiresAt: null});
  assert.match(none, /Access inventory not yet reviewed\. Current legal\/access conditions require rechecking; legal review: not yet reviewed\.$/);
  assert.doesNotMatch(none, /1970|1969|Invalid Date|expired|checked/);
  const dated = shoreEvidence({checkedAt: '2026-09-01', legalReviewExpiresAt: '2026-09-30'});
  assert.equal(dated, 'Original NOAA shoreline vertices; no offshore depth or species fit inferred. Physical context only. Access inventory checked '
    + new Date('2026-09-01').toLocaleDateString() + '. Current legal/access conditions require rechecking; the prior legal review expired ' + new Date('2026-09-30').toLocaleDateString() + '.');
});
