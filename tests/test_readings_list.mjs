import test from 'node:test';
import assert from 'node:assert/strict';
import {firstMark, readingsAt} from '../web/map/readings-list.ts';

const point = Object.freeze({lon: -122, lat: 37});

/** @param {string} layer @returns {import('../web/map/coastline.ts').ChartMark} */
function markFor(layer) {
  return Object.freeze({id: layer, name: layer, kind: 'field', reading: 'Synthetic value', source: 'Fixture', basis: 'Synthetic sample'});
}

const wind = markFor('wind');
const sst = markFor('sst');
const currentsMark = markFor('currents');
const throws = () => { throw new Error('Fixture unavailable'); };

// An adapter must pass through the tap and the source's original mark, not rebuild it.
test('C1: source callbacks and entries use the point and ChartMark contracts', () => {
  const taps = [];
  /** @type {readonly import('../web/map/readings-list.ts').ReadingSource[]} */
  const sources = [{layer: 'sst', reading: at => { taps.push(at); return sst; }}];
  /** @type {import('../web/map/readings-list.ts').FieldReading[]} */
  const readings = readingsAt(sources, point);
  assert.deepEqual(readings, [{layer: 'sst', mark: sst}]);
  assert.equal(readings[0].mark, sst);
  assert.deepEqual(taps, [point]);
});

// Sorting, dropping nulls, or treating a skipped row as the first layer occurrence changes the rail.
test('C2: retains rail order and the first eligible occurrence, including null marks', () => {
  const omittedCalls = [];
  const sources = [
    {layer: 'depth', reason: () => omittedCalls.push('no reader')},
    {layer: 'wind', reading: null},
    {layer: 'wind', reading: () => wind},
    {layer: 'chlorophyll', reading: () => null},
    {layer: 'sst', reading: () => sst},
    {layer: 'chlorophyll', reading: () => omittedCalls.push('duplicate reader'), reason: () => omittedCalls.push('duplicate reason')},
  ];
  assert.deepEqual(readingsAt(sources, point), [
    {layer: 'wind', mark: wind}, {layer: 'chlorophyll', mark: null}, {layer: 'sst', mark: sst},
  ]);
  assert.deepEqual(omittedCalls, []);
});

test('C2: no eligible layers produces an empty list', () => {
  assert.deepEqual(readingsAt([{layer: 'depth'}], point), []);
});

// A gap, failed callback or malformed JS return must not hide the next usable reading.
for (const [label, reading] of [
  ['null', () => null], ['undefined', () => undefined], ['throwing', throws], ['primitive', () => 'not a mark'],
]) {
  test(`C3: ${label} reader leaves a null entry and preserves later marks`, () => {
    assert.deepEqual(readingsAt([{layer: 'wind', reading}, {layer: 'sst', reading: () => sst}], point), [
      {layer: 'wind', mark: null}, {layer: 'sst', mark: sst},
    ]);
  });
}

// Check each coordinate independently: skipping the reading is stronger than discarding its result.
for (const coordinate of ['lon', 'lat']) {
  for (const value of [NaN, Infinity, -Infinity]) {
    test(`C3: ${coordinate} ${value} skips all readers but still reports layer status`, () => {
      const calls = [];
      const sources = [
        {layer: 'wind', reading: () => { calls.push('wind'); return wind; }},
        {layer: 'sst', reading: () => { calls.push('sst'); return sst; }, reason: () => 'Offline'},
      ];
      assert.deepEqual(readingsAt(sources, {...point, [coordinate]: value}), [
        {layer: 'wind', mark: null}, {layer: 'sst', mark: null, reason: 'Offline'},
      ]);
      assert.deepEqual(calls, []);
    });
  }
}

// Trimming or substituting generic text loses the source's wording, including whitespace.
for (const reason of ['  Source is stale.  ', ' ']) {
  test(`C4: keeps non-empty source status ${JSON.stringify(reason)} verbatim`, () => {
    assert.deepEqual(readingsAt([{layer: 'wind', reading: () => null, reason: () => reason}], point), [
      {layer: 'wind', mark: null, reason},
    ]);
  });
}

// These must omit the key entirely, not set it to undefined, null, or a fallback string.
for (const [label, reason] of [
  ['empty', () => ''], ['null', () => null], ['undefined', () => undefined], ['non-string', () => 42], ['throwing', throws],
]) {
  test(`C4: ${label} status leaves the reason key absent`, () => {
    assert.deepEqual(readingsAt([{layer: 'wind', reading: () => null, reason}], point), [{layer: 'wind', mark: null}]);
  });
}

test('C4: a mark suppresses even an available status', () => {
  const calls = [];
  const sources = [{layer: 'wind', reading: () => wind, reason: () => { calls.push('reason'); return 'Offline'; }}];
  assert.deepEqual(readingsAt(sources, point), [{layer: 'wind', mark: wind}]);
  assert.deepEqual(calls, []);
});

const sourceOf = (layer, mark) => ({layer, reading: () => mark});
const noCurrents = sourceOf('currents', null);
const noWind = sourceOf('wind', null);
const windSource = sourceOf('wind', wind);
const sstSource = sourceOf('sst', sst);

// Chart's legacy selector is the oracle for finite taps on distinct, well-behaved sources.
// A last-mark selector or one that stops at a gap would disagree with these fakes.
for (const [label, currents, drawn, expected] of [
  ['currents wins', sourceOf('currents', currentsMark), [windSource, sstSource], currentsMark],
  ['null currents falls through in rail order', noCurrents, [sstSource, windSource], sst],
  ['absent currents with an omitted layer and a gap', undefined, [{layer: 'depth'}, noWind, sstSource], sst],
  ['all marks missing', noCurrents, [noWind], null],
  ['no sources', undefined, [], null],
]) {
  test(`C5: matches the legacy Chart selector when ${label}`, () => {
    const reference = currents?.reading(point) ?? drawn.map(l => l.reading?.(point) ?? null).find(m => m !== null) ?? null;
    const readings = readingsAt(currents ? [currents, ...drawn] : drawn, point);
    assert.equal(reference, expected);
    assert.equal(firstMark(readings), reference);
  });
}
