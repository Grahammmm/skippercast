import assert from 'node:assert/strict';
import test from 'node:test';
import {planView, trustworthy, PLAN_COPY} from '../web/plan.ts';

const withheld = (name) => ({kind: 'withheld', name, reason: PLAN_COPY.withheld});
const good = {name: 'Halibut', life_stage: 'adult', search_for: 'Sand flats', numeric_bite_model: false,
  required_to_confirm: ['Check rules'], tactics_basis: 'Reviewed',
  source_links: [{title: 'Source', url: 'https://example.org/a'}]};

test('null and undefined owned entries are withheld without throwing', () => {
  for (const bad of [null, undefined]) {
    const plans = Object.freeze({x: bad});
    assert.deepEqual(planView(plans, 'x', 'plan'), withheld('x'));
    assert.deepEqual(Object.keys(plans), ['x']);
    assert.equal(plans.x, bad);
  }
});

test('other malformed non-record entries are withheld with the id as name', () => {
  for (const bad of [[], ['a'], 'plan', 7, true, false]) {
    assert.deepEqual(planView({x: bad}, 'x', 'plan'), withheld('x'));
  }
});

test('records without exact false approval stay withheld', () => {
  for (const approval of [undefined, null, 'false', true, 0, 1]) {
    const entry = {name: 'Named', numeric_bite_model: approval};
    assert.deepEqual(planView({x: entry}, 'x', 'plan'), withheld('Named'));
  }
  assert.deepEqual(planView({x: {}}, 'x', 'plan'), withheld('x'));
});

test('trustworthy refuses malformed inputs and accepts only exact false', () => {
  for (const bad of [null, undefined, [], 'x', 0, true, {}, {numeric_bite_model: null}, {numeric_bite_model: 0}]) {
    assert.equal(trustworthy(bad), false);
  }
  assert.equal(trustworthy({numeric_bite_model: false}), true);
});

test('precedence of existing refusals is unchanged', () => {
  assert.deepEqual(planView({}, 'x', null), {kind: 'unknown', id: 'x'});
  assert.deepEqual(planView({}, 'x', 'unresearched'), {kind: 'unresearched', reason: PLAN_COPY.unresearched});
  assert.deepEqual(planView(null, 'x', 'plan'), {kind: 'loading'});
  assert.deepEqual(planView({y: null}, 'toString', 'plan'), {kind: 'unknown', id: 'toString'});
  assert.deepEqual(planView({y: null}, '  ', 'plan'), {kind: 'unknown', id: '  '});
  assert.deepEqual(planView({}, 'toString', 'plan'), {kind: 'unknown', id: 'toString'});
  assert.deepEqual(planView({x: null}, 'x', 'plan', {x: 'Not offered here.'}), {kind: 'unresearched', reason: 'Not offered here.'});
  const inherited = Object.create({x: good});
  assert.deepEqual(planView(inherited, 'x', null), {kind: 'unknown', id: 'x'});
});

test('a valid reviewed plan is unchanged, also beside a malformed sibling', () => {
  const plans = {halibut: good, bad: null};
  const v = planView(plans, 'halibut', 'plan', {}, '2026-09-01');
  assert.deepEqual(v, {kind: 'plan', name: 'Halibut', lifeStage: 'adult',
    sections: [{title: 'What to search for', text: 'Sand flats'}], confirm: ['Check rules'],
    evidence: {basis: 'Reviewed', links: [{title: 'Source', href: 'https://example.org/a'}]}, reviewedAt: '2026-09-01'});
  assert.deepEqual(planView(plans, 'bad', 'plan'), withheld('bad'));
});
