import assert from 'node:assert/strict';
import test from 'node:test';
import {sshCells} from '../web/map/ssh-cells.ts';
import {sshOutside} from '../web/map/ssh-scale.ts';

const hour = '2026-11-19T12:00:00Z';
const sameInstant = '2026-11-19T04:00:00-08:00';
const cell = {lat: 34, lon: -120, sshCm: 2.5};

function feed(frames) {
  return {product: 'wcofs-ssh', issuedAt: '2026-11-19T03:00:00Z', resolution: [0.5, 1], frames};
}

function ready(validAt, limitCm, ticks, features) {
  return {state: 'ready', validAt, limitCm, ticks, features: {type: 'FeatureCollection', features}};
}

function feature(sshCm, pos, ring) {
  return {type: 'Feature', geometry: {type: 'Polygon', coordinates: [ring]}, properties: {sshCm, pos}};
}

const ring = [[-120.5, 33.75], [-119.5, 33.75], [-119.5, 34.25], [-120.5, 34.25], [-120.5, 33.75]];

test('C1: a rejected time cannot select even a frame with the same invalid spelling', () => {
  const frames = feed([{validAt: 'invalid time', cells: [cell]}]);
  assert.deepEqual(sshCells(frames, 'invalid time'), {state: 'none', reason: 'bad-time'});
});

test('C1: a missing hour does not fall back to a nearby frame', () => {
  const frames = feed([{validAt: '2026-11-19T11:00:00Z', cells: [cell]}]);
  assert.deepEqual(sshCells(frames, hour), {state: 'none', reason: 'no-frame'});
});

test('C1: malformed resolution cannot yield draw-ready polygons', () => {
  const frames = feed([{validAt: hour, cells: [cell]}]);
  for (const resolution of [null, {0: 0.5, 1: 1, length: 2}, [0.5], [0.5, 1, 2], ['0.5', 1],
    [NaN, 1], [0.5, Infinity], [0, 1], [0.5, -1]]) {
    assert.deepEqual(sshCells({...frames, resolution}, hour), {state: 'none', reason: 'bad-grid'},
      `resolution: ${String(resolution)}`);
  }
});

test('C1: the first equal instant wins over a later exact string match', () => {
  const frames = feed([
    {validAt: '2026-11-19T09:00:00Z', cells: [{...cell, sshCm: 100}]},
    {validAt: sameInstant, cells: [cell]},
    {validAt: hour, cells: [{...cell, sshCm: -50}]},
  ]);
  assert.deepEqual(sshCells(frames, hour), ready(sameInstant, 5, [-5, -2.5, 0, 2.5, 5], [feature(2.5, 0.75, ring)]));
});

const rejected = [
  {...cell, lat: NaN, sshCm: 200},
  {...cell, lon: -Infinity, sshCm: -300},
  {...cell, sshCm: Infinity},
];

test('C2: both an empty frame and an all-rejected frame report no cells', () => {
  for (const cells of [[], rejected]) {
    assert.deepEqual(sshCells(feed([{validAt: hour, cells}]), hour), {state: 'none', reason: 'no-cells'});
  }
});

test('C2: rejected cells neither draw nor widen the scale', () => {
  const frames = feed([{validAt: sameInstant, cells: [...rejected, {...cell, sshCm: -6}]}]);
  assert.deepEqual(sshCells(frames, hour), ready(sameInstant, 10, [-10, -5, 0, 5, 10], [feature(-6, 0.2, ring)]));
});

test('C2: cell extents, not centers, determine geometry and scale eligibility', () => {
  const regional = {lat: 35.25, lon: -120, sshCm: -6};
  const northeast = {lat: 89.5, lon: 179.5, sshCm: 10};
  const southwest = {lat: -89.5, lon: -179.5, sshCm: 0};
  const render = cells => sshCells({...feed([{validAt: hour, cells}]), resolution: [1, 1]}, hour);
  const expected = ready(hour, 10, [-10, -5, 0, 5, 10], [
    feature(-6, 0.2, [[-120.5, 34.75], [-119.5, 34.75], [-119.5, 35.75], [-120.5, 35.75], [-120.5, 34.75]]),
    feature(10, 1, [[179, 89], [180, 89], [180, 90], [179, 90], [179, 89]]),
    feature(0, 0.5, [[-180, -90], [-179, -90], [-179, -89], [-180, -89], [-180, -90]]),
  ]);
  assert.deepEqual(render([regional, northeast, southwest]), expected);

  // A center-only check admits these cells; filtering after scaling still widens the key.
  const crossing = [
    {...northeast, lat: 89.75, sshCm: 200},
    {...southwest, lat: -89.75, sshCm: -200},
    {...northeast, lon: 179.75, sshCm: 200},
    {...southwest, lon: -179.75, sshCm: -200},
  ];
  for (const outside of crossing) {
    assert.deepEqual(render([regional, outside, northeast, southwest]), expected,
      `center ${outside.lat}, ${outside.lon}`);
  }
  assert.deepEqual(render(crossing), {state: 'none', reason: 'no-cells'});
});

test('C3: closed lon/lat squares preserve cell order, overlaps and gaps without mutating input', () => {
  const cells = Object.freeze([
    Object.freeze({...cell, sshCm: 5}),
    Object.freeze({...cell, sshCm: -10}),
    Object.freeze({lat: 35, lon: -118, sshCm: 0}),
  ]);
  const frames = Object.freeze({
    ...feed(Object.freeze([Object.freeze({validAt: hour, cells})])),
    resolution: Object.freeze([0.5, 1]),
  });
  const result = sshCells(frames, hour);
  assert.deepEqual(result, ready(hour, 10, [-10, -5, 0, 5, 10], [
    feature(5, 0.75, ring),
    feature(-10, 0, ring),
    feature(0, 0.5, [[-118.5, 34.75], [-117.5, 34.75], [-117.5, 35.25], [-118.5, 35.25], [-118.5, 34.75]]),
  ]));
  assert.equal(sshOutside(result.features.features[1].properties.sshCm, result.limitCm), null);
});
