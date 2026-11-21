import test from 'node:test';
import assert from 'node:assert/strict';
import {shorterRunOrder} from '../web/planner-run-order.ts';
import {tripLegs} from '../web/trip-legs.ts';

const point = (id, lat, lon) => Object.freeze({id, lat, lon});
const start = {lat: 0, lon: 0};
const fixture = Object.freeze([
  point('a', 0, 1), point('b', 2, 3), point('c', 1, 0),
  point('d', 0, 3), point('e', 3, 0), point('f', 3, 3),
]);
const plannerTotal = (stops, origin = start) => tripLegs(
  origin && {...origin, name: 'Origin'}, stops.map(stop => ({...stop, name: stop.id})), null,
).totalNm;

test('C1: the returned round trip sums the planner straight legs including the return', () => {
  const ids = ['a', 'd', 'b', 'f', 'e', 'c'];
  const ordered = ids.map(id => fixture.find(stop => stop.id === id));
  assert.deepEqual(shorterRunOrder(fixture, start), {ids, totalNm: plannerTotal(ordered), improved: true});
});

test('C2: equally near stops retain input priority, not ID sort order', () => {
  const far = point('far', 0, 4), z = point('z', 0, 1), a = point('a', 0, 1), mid = point('mid', 0, 2);
  assert.deepEqual(shorterRunOrder([far, z, a, mid], start), {
    ids: ['z', 'a', 'mid', 'far'], totalNm: plannerTotal([z, a, mid, far]), improved: true,
  });
});

test('C2: no start keeps the first stop and charges no return leg', () => {
  const first = point('first', 0, 0), far = point('far', 0, 8), near = point('near', 0, 1), west = point('west', 0, -2);
  // Nearest neighbour visits near before west; open-path 2-opt can shorten that path.
  assert.deepEqual(shorterRunOrder([first, far, near, west], null), {
    ids: ['first', 'west', 'near', 'far'], totalNm: plannerTotal([first, west, near, far], null), improved: true,
  });
});

test('C3: a different equally short candidate does not replace an already-optimal order', () => {
  const stops = [point('a', 0, 1), point('b', 0, 1), point('c', 0, 0)];
  assert.deepEqual(shorterRunOrder(stops, start), {
    ids: ['a', 'b', 'c'], totalNm: plannerTotal(stops), improved: false,
  });
});

test('C3: zero, one and two stops keep their order and report only existing legs', () => {
  const a = point('a', 0, 2), b = point('b', 0, 1);
  for (const [stops, ids] of [[[], []], [[a], ['a']], [[a, b], ['a', 'b']]]) {
    for (const origin of [start, null]) {
      assert.deepEqual(shorterRunOrder(stops, origin), {ids, totalNm: plannerTotal(stops, origin), improved: false});
    }
  }
});

test('C3: non-finite coordinates preserve the entire input rather than dropping a stop', () => {
  const a = point('a', 0, 2), b = point('b', 0, 1);
  for (const bad of [point('bad', NaN, 0), point('bad', 0, Infinity)]) {
    assert.deepEqual(shorterRunOrder([a, bad, b], start), {ids: ['a', 'bad', 'b'], totalNm: NaN, improved: false});
  }
  assert.deepEqual(shorterRunOrder([a], {lat: 0, lon: -Infinity}), {ids: ['a'], totalNm: NaN, improved: false});
});

test('C4: six stops beat both rank order and the nearest-neighbour-only tour', () => {
  const result = shorterRunOrder(fixture, start);
  assert.deepEqual({...result, totalNm: result.totalNm.toFixed(3)}, {
    ids: ['a', 'd', 'b', 'f', 'e', 'c'], totalNm: '720.239', improved: true,
  });
  assert.ok(result.totalNm < plannerTotal(fixture));
  const nearest = [0, 2, 4, 5, 1, 3].map(i => fixture[i]);
  assert.ok(result.totalNm < plannerTotal(nearest));
});
