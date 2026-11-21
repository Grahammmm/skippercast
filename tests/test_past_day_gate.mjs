import test from 'node:test';
import assert from 'node:assert/strict';
import {pastDayGate} from '../web/map/past-day-gate.ts';

const DRAW = {draw: true, reason: null};
const BAD_INPUT = {draw: false, reason: 'bad-input'};
const NO_FRAME = {draw: false, reason: 'no-frame'};
const OTHER_DAY = {draw: false, reason: 'other-day'};
const LA = 'America/Los_Angeles';
const DAY = '2026-11-18';
const SAMPLE = '2026-11-19T07:30:00Z';

test('C1: an Intl zone error becomes the whole bad-input result rather than escaping', () => {
  assert.deepEqual(pastDayGate('observed', DAY, SAMPLE, 'Mars/Olympus'), BAD_INPUT);
});

test('C2: Today bypasses the past-day checks in every layer mode', () => {
  for (const behaviour of ['static', 'hour', 'observed']) {
    assert.deepEqual(pastDayGate(behaviour, null, 'invalid sample', 'invalid zone'), DRAW, behaviour);
  }
});

test('C3: invalid dates fail closed rather than being parsed leniently or rolled forward', () => {
  for (const day of ['', '2026-1-08', '2026-11-18\n', '2026-11-18T00:00Z', '2026-04-31',
    '1900-02-29', '2026-01-00', '2026-13-01']) {
    assert.deepEqual(pastDayGate('static', day, null, LA), BAD_INPUT, JSON.stringify(day));
  }
  assert.deepEqual(pastDayGate('static', '2000-02-29', null, LA), DRAW);
});

test('C3: an unknown behaviour is not treated as observed', () => {
  assert.deepEqual(pastDayGate('unknown', DAY, SAMPLE, LA), BAD_INPUT);
});

test('C3: bad zones still take precedence for static and forecast layers', () => {
  for (const behaviour of ['static', 'hour']) {
    assert.deepEqual(pastDayGate(behaviour, DAY, null, ''), BAD_INPUT, behaviour);
  }
});

test('C3: past-day static and forecast decisions do not depend on a frame', () => {
  assert.deepEqual(pastDayGate('static', DAY, null, LA), DRAW);
  assert.deepEqual(pastDayGate('hour', DAY, SAMPLE, LA), {draw: false, reason: 'forecast-only'});
});

test('C3: missing, naive and malformed samples cannot masquerade as real frames', () => {
  for (const sample of [null, '2026-11-18', '2026-11-18T23:30:00', '2026-11-18 23:30:00Z',
    'Wed, 18 Nov 2026 23:30:00 GMT', '2026-11-18T23:30:00Z\n', '2026-02-30T12:00:00Z',
    '2026-11-18T24:01:00Z', '2026-11-18T23:30:00+01:60']) {
    assert.deepEqual(pastDayGate('observed', DAY, sample, LA), NO_FRAME, JSON.stringify(sample));
  }
});

test('C3: the same UTC sample belongs to November 18 in LA but November 19 in UTC', () => {
  assert.deepEqual(pastDayGate('observed', DAY, SAMPLE, LA), DRAW);
  assert.deepEqual(pastDayGate('observed', '2026-11-19', SAMPLE, LA), OTHER_DAY);
  assert.deepEqual(pastDayGate('observed', '2026-11-19', SAMPLE, 'UTC'), DRAW);
});

test('C3: numeric offsets place the instant, not the printed date, on the region calendar', () => {
  assert.deepEqual(pastDayGate('observed', DAY, '2026-11-19T12:30:00.250+05:00', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', DAY, '2026-11-18T23:30-0900', LA), OTHER_DAY);
  assert.deepEqual(pastDayGate('observed', '2027-01-01', '2026-12-31T23:30:00Z', 'Asia/Tokyo'), DRAW);
});

test('C3: the spring-forward day runs from 08:00Z to the next 07:00Z, not 24 hours', () => {
  const day = '2026-03-08';
  assert.deepEqual(pastDayGate('observed', day, '2026-03-08T07:59:59.999Z', LA), OTHER_DAY);
  assert.deepEqual(pastDayGate('observed', day, '2026-03-08T08:00:00Z', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-03-09T06:59:59.999Z', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-03-09T07:00:00Z', LA), OTHER_DAY);
});

test('C3: the fall-back day includes both 1:30 a.m. instants and lasts 25 hours', () => {
  const day = '2026-11-01';
  assert.deepEqual(pastDayGate('observed', day, '2026-11-01T06:59:59.999Z', LA), OTHER_DAY);
  assert.deepEqual(pastDayGate('observed', day, '2026-11-01T07:00:00Z', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-11-01T01:30:00-07:00', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-11-01T01:30:00-08:00', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-11-02T07:59:59.999Z', LA), DRAW);
  assert.deepEqual(pastDayGate('observed', day, '2026-11-02T08:00:00Z', LA), OTHER_DAY);
});

test('C3: four-digit years keep leading zeroes and do not conflate BC and AD', () => {
  assert.deepEqual(pastDayGate('observed', '0000-01-01', '0000-01-01T00:00:00Z', 'UTC'), DRAW);
  assert.deepEqual(pastDayGate('observed', '0001-01-01', '0000-01-01T00:00:00Z', 'UTC'), OTHER_DAY);
  assert.deepEqual(pastDayGate('observed', '0001-01-01', '0001-01-01T00:00:00Z', 'UTC'), DRAW);
});
