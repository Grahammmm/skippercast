// RF2021-6: the qualified depth explanation never claims a non-finite planning allowance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {depthBadge} from '../web/confidence.ts';

const target = margin => ({
  depth_qualified: true, center_depth_ft: 40, vertical_datum: 'MLLW',
  qualification: {full_geometry_screened: true, native_datum: 'MLLW', maximum_product_uncertainty_m: 1, planning_margin_m: margin},
});
const absent = depthBadge(target(undefined));

test('infinite_margin_is_not_a_claim', () => {
  const b = depthBadge(target(Infinity));
  assert.equal(b.state, 'qualified');
  assert.equal(b.why.text, absent.why.text);
  assert.doesNotMatch(b.why.text, /Infinity|NaN|allowance/);
});

test('nonpositive_and_missing_margins_remain_absent', () => {
  for (const m of [0, -1, -Infinity, NaN, null, undefined]) {
    const b = depthBadge(target(m));
    assert.equal(b.state, 'qualified', String(m));
    assert.equal(b.why.text, absent.why.text, String(m));
    assert.doesNotMatch(b.why.text, /allowance/, String(m));
  }
});

test('finite_allowance_and_qualification_controls', () => {
  for (const m of [2, 0.5]) {
    const b = depthBadge(target(m));
    assert.equal(b.state, 'qualified');
    assert.ok(b.why.text.includes(`, and the screen adds a ${m} m planning allowance.`), b.why.text);
    assert.match(b.why.text, /verify on your sounder\.$/);
  }
  const t = target(Infinity);
  assert.notEqual(depthBadge({...t, qualification: {...t.qualification, full_geometry_screened: false}}).state, 'qualified');
  assert.notEqual(depthBadge({...t, qualification: {...t.qualification, maximum_product_uncertainty_m: -1}}).state, 'qualified');
});
