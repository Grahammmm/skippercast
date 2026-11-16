// RF0015-15: a nonfinite clearance never becomes a generated "Passed the protected-area check" reason. Pure, offline, synthetic.
import assert from 'node:assert/strict';
import test from 'node:test';
import {reasonsFor, targetEvidence} from '../web/area-reasons.ts';

const ATLAS = {title: 'Test atlas', source_validation_date: '2026-11-01'};
const NOW = Date.parse('2026-11-16T12:00:00Z');
const screens = (t, atlas = ATLAS) => targetEvidence(t, atlas).filter(r => r.kind === 'screen');
const rv = v => ({id: 'A', recorded_validation: {closed_or_screened_area_clearance_m: v}});
const ql = v => ({id: 'A', qualification: {closure_clearance_m: v}});

test('overflowing JSON and nonfinite clearances produce no screen record on either path', () => {
  const big = JSON.parse('{"v": 1e400}').v;
  assert.equal(big, Infinity);
  for (const v of [big, Infinity, -Infinity, NaN]) {
    assert.deepEqual(screens(rv(v)), [], `recorded ${v}`);
    assert.deepEqual(screens(ql(v)), [], `qualification ${v}`);
    assert.ok(!reasonsFor('A', targetEvidence(rv(v), ATLAS), NOW).some(r => /Infinity|NaN/.test(r.text)));
  }
});

test('zero, negative, strings, booleans, objects and null are not screens and do not throw', () => {
  for (const v of [0, -5, '120', true, {}, null, undefined]) {
    assert.deepEqual(screens(rv(v)), [], `recorded ${String(v)}`);
  }
});

test('finite values keep their exact sentence and descriptor', () => {
  const [s] = screens(rv(123.6));
  assert.equal(s.text, 'Passed the protected-area check with 124 m clearance.');
  assert.equal(screens(rv(0.4))[0].text, 'Passed the protected-area check with 0 m clearance.');
  assert.equal(screens(ql(1e9))[0].text, 'Passed the protected-area check with 1000000000 m clearance.');
  assert.equal(s.date, '2026-11-01');
  assert.equal(s.source, 'Test atlas');
});

test('precedence: recorded beats qualification; null falls back; invalid recorded does not fall back', () => {
  const both = {id: 'A', recorded_validation: {closed_or_screened_area_clearance_m: 123.6}, qualification: {closure_clearance_m: 999}};
  assert.match(screens(both)[0].text, /with 124 m/);
  const fall = {id: 'A', recorded_validation: {closed_or_screened_area_clearance_m: null}, qualification: {closure_clearance_m: 123.6}};
  assert.match(screens(fall)[0].text, /with 124 m/);
  for (const bad of [Infinity, NaN, '5']) {
    const t = {id: 'A', recorded_validation: {closed_or_screened_area_clearance_m: bad}, qualification: {closure_clearance_m: 999}};
    assert.deepEqual(screens(t), [], String(bad));
  }
});

test('invalid clearance keeps the survey record; missing atlas date suppresses the screen; inputs are not mutated', () => {
  const t = {id: 'A', survey_year: 2020, source_name: 'Survey X', source_url: 'https://example.test/s', terrain_interpretation: 'Rocky ledge.',
    recorded_validation: {closed_or_screened_area_clearance_m: Infinity}};
  const out = targetEvidence(t, ATLAS);
  assert.equal(out.length, 1);
  assert.equal(out[0].kind, 'survey');
  assert.equal(out[0].source, 'Survey X');
  assert.equal(out[0].sourceURL, 'https://example.test/s');
  assert.equal(out[0].text, 'Rocky ledge.');
  assert.deepEqual(screens(rv(50), {title: 'T'}), []);
  const ok = rv(123.6);
  Object.freeze(ok.recorded_validation); Object.freeze(ok);
  const a = targetEvidence(ok, ATLAS), b = targetEvidence(ok, ATLAS);
  assert.deepEqual(a, b);
  assert.equal(reasonsFor('A', [], NOW).length, 0);
});
