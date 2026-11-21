import test from 'node:test';
import assert from 'node:assert/strict';
import {comfortContext, readComfortContext} from '../server/comfort-context.ts';

const phase = 'outbound';
const points = ['reef', 'bank'];
const context = (fields = {}) => ({
  phase, wind: null, sea: null, period: null, heading: null, point: null,
  boat: null, swell_from: null, ...fields,
});
const saved = fields => ({ok: true, context: context(fields)});
const badFeedback = {ok: false, error: 'invalid feedback'};
const badContext = {ok: false, error: 'invalid feedback context'};
const badPoint = {ok: false, error: 'invalid feedback point'};
const numericLimits = {wind: 200, sea: 100, period: 60, heading: 360, swell_from: 360};
const eightyUnits = '🌊'.repeat(40);

// A truthiness/coercion check would accept bogus phases or reject missing optional fields.
test('C1: reject non-record bodies and invalid phases', () => {
  for (const body of [null, undefined, false, 3, phase, [], {}, ...[null, 'Outbound', '', 1, [phase]].map(phase => ({phase}))]) {
    assert.deepEqual(comfortContext(body, points), badFeedback);
  }
});

test('C1: accept each phase and leave rating and region validation to the route', () => {
  for (const phase of ['outbound', 'fishing', 'return']) {
    assert.deepEqual(comfortContext({phase, rating: -1, region: 'unknown'}, points), saved({phase}));
  }
  assert.deepEqual(comfortContext(context(), points), saved());
});

for (const [key, max] of Object.entries(numericLimits)) {
  // Detect swapped maxima, off-by-one limits and coercion or rounding of measurements.
  test(`C1: ${key} accepts finite numbers from zero through ${max}`, () => {
    for (const value of [0, 0.25, max]) {
      assert.deepEqual(comfortContext({phase, [key]: value}, points), saved({[key]: value}));
    }
    for (const value of [-0.01, max + 0.01, NaN, Infinity, -Infinity, '1', false, [1]]) {
      assert.deepEqual(comfortContext({phase, [key]: value}, points), badContext, String(value));
    }
  });
}

// Count UTF-16 units after trimming, without silently truncating a distinct boat name.
test('C1: trim boat names and reject bad types or names beyond 80 UTF-16 units', () => {
  assert.deepEqual(comfortContext({phase, boat: '  Sample Boat \n'}, points), saved({boat: 'Sample Boat'}));
  for (const boat of ['', ' \n\t ']) {
    assert.deepEqual(comfortContext({phase, boat}, points), saved());
  }
  assert.deepEqual(comfortContext({phase, boat: ` ${eightyUnits} `}, points), saved({boat: eightyUnits}));
  for (const boat of [`${eightyUnits}x`, 3, false, ['Sample Boat'], {}]) {
    assert.deepEqual(comfortContext({phase, boat}, points), badContext);
  }
});

// Membership is exact and depends on the supplied region's forecast points.
test('C1: require exact membership for present forecast points', () => {
  for (const point of points) {
    assert.deepEqual(comfortContext({phase, point}, points), saved({point}));
  }
  for (const point of ['other', 'REEF', ' reef ', '', 0, false, ['reef']]) {
    assert.deepEqual(comfortContext({phase, point}, points), badPoint);
  }
  assert.deepEqual(comfortContext({phase, point: 'reef'}, []), badPoint);
});

// Combined bad fields are needed to detect a change in which error wins.
test('C1: check feedback before context and context before point', () => {
  const badFields = {point: 'other', wind: 201, boat: 3, swell_from: -1};
  assert.deepEqual(comfortContext({phase: 'other', ...badFields}, points), badFeedback);
  for (const key of ['wind', 'boat', 'swell_from']) {
    assert.deepEqual(comfortContext({phase, point: badFields.point, [key]: badFields[key]}, points), badContext);
  }
});

const legacyJson = '{"phase":"outbound","wind":12,"sea":3,"period":7,"heading":340,"point":"reef"}';
const extendedJson = '{"phase":"outbound","wind":12,"sea":3,"period":7,"heading":340,"point":"reef","boat":null,"swell_from":null}';
const measurements = {wind: 12, sea: 3, period: 7, heading: 340, point: 'reef'};

test('C2: append nullable keys without reordering the legacy JSON', () => {
  const result = comfortContext({phase, ...measurements}, points);
  assert.deepEqual(result, saved(measurements));
  const {boat, swell_from, ...legacy} = result.context;
  assert.equal(JSON.stringify(legacy), legacyJson);
  assert.equal(JSON.stringify(result.context), extendedJson);
});

// Legacy rows lack the new keys; a read must not require today's region allowlist.
test('C3: preserve measurements and point in old and new stored rows', () => {
  assert.deepEqual(readComfortContext(legacyJson), context(measurements));
  assert.deepEqual(readComfortContext(extendedJson), context(measurements));
  const json = '{"phase":"return","wind":0,"sea":100,"period":60,"heading":360,"point":"retired","boat":" Sample Boat ","swell_from":360}';
  assert.deepEqual(readComfortContext(json), context({
    phase: 'return', wind: 0, sea: 100, period: 60, heading: 360, point: 'retired',
    boat: 'Sample Boat', swell_from: 360,
  }));
});

test('C3: return null for malformed JSON, non-records and unrecognized or missing phases', () => {
  for (const json of ['', '{', 'null', 'false', '42', '"outbound"', '[]', '{}', '{"phase":"RETURN"}']) {
    assert.deepEqual(readComfortContext(json), null, json);
  }
});

for (const [key, max] of Object.entries(numericLimits)) {
  // One broken reading must not discard the boat, the point, or the rest of the row.
  test(`C3: read invalid ${key} as null without losing other fields`, () => {
    const row = {...measurements, boat: 'Sample Boat', swell_from: 0};
    for (const value of ['1', false, [1], -0.01, max + 0.01]) {
      const json = JSON.stringify({phase, ...row, [key]: value});
      assert.deepEqual(readComfortContext(json), context({...row, [key]: null}), String(value));
    }
    assert.deepEqual(readComfortContext(`{"phase":"fishing","${key}":1e999}`), context({phase: 'fishing'}));
  });
}

test('C3: normalize bad or blank optional text without discarding the row', () => {
  assert.deepEqual(readComfortContext('{"phase":"outbound"}'), context());
  for (const boat of [3, {}, `${eightyUnits}x`, ' \t ']) {
    assert.deepEqual(readComfortContext(JSON.stringify({phase, boat, swell_from: 12, point: ['reef']})),
      context({swell_from: 12}));
  }
});
