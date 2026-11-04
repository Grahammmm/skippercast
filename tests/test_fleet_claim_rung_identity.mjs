// claimLine admits only genuine evidence rungs: a string that merely names an inherited Object property is no rung.
import test from 'node:test';
import assert from 'node:assert/strict';
import {RUNG_LABELS, claimLine} from '../web/fleet.ts';

const CAVEAT = 'Synthetic coverage caveat.';

test('inherited Object property names are not evidence rungs', () => {
  for (const rung of ['toString', 'constructor', '__proto__', 'valueOf', 'hasOwnProperty', 'isPrototypeOf',
    'propertyIsEnumerable', 'toLocaleString', '__defineGetter__', '__lookupGetter__']) {
    assert.equal(claimLine({rung, count: 1, caveat: CAVEAT}), null, rung);
    assert.equal(claimLine({rung, count: 5, caveat: CAVEAT}), null, rung);
  }
});

test('empty, made-up, wrong-case and padded rung strings are not normalised into a rung', () => {
  for (const rung of ['', 'made-up', 'Named-Report', 'NAMED-REPORT', ' named-report', 'named-report ', 'ais_linger'])
    assert.equal(claimLine({rung, count: 1, caveat: CAVEAT}), null, JSON.stringify(rung));
});

test('every genuine rung keeps its exact sentence, singular and plural', () => {
  const labels = {'named-report': 'One named report', 'repeated-report': 'Repeated reports',
    'ais-linger': 'AIS linger', 'ais-linger-verified': 'AIS linger, boat confirmed'};
  assert.deepEqual(Object.keys(RUNG_LABELS).sort(), Object.keys(labels).sort());
  for (const [rung, label] of Object.entries(labels)) {
    assert.equal(claimLine({rung, count: 1, caveat: CAVEAT}), `${label} (1 piece of evidence). ${CAVEAT}`);
    assert.equal(claimLine({rung, count: 2, caveat: CAVEAT}), `${label} (2 pieces of evidence). ${CAVEAT}`);
  }
});

test('a known rung with no positive count or no caveat is still refused', () => {
  assert.equal(claimLine({rung: 'named-report', count: 0, caveat: CAVEAT}), null);
  assert.equal(claimLine({rung: 'named-report', count: -1, caveat: CAVEAT}), null);
  assert.equal(claimLine({rung: 'named-report', count: 1, caveat: ''}), null);
});

test('claimLine does not change its input', () => {
  const claim = Object.freeze({rung: 'toString', count: 1, caveat: CAVEAT});
  const good = Object.freeze({rung: 'ais-linger', count: 3, caveat: CAVEAT});
  assert.equal(claimLine(claim), null);
  assert.ok(claimLine(good));
  assert.deepEqual({...claim}, {rung: 'toString', count: 1, caveat: CAVEAT});
  assert.deepEqual({...good}, {rung: 'ais-linger', count: 3, caveat: CAVEAT});
});
