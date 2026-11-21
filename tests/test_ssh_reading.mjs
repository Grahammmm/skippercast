import assert from 'node:assert/strict';
import test from 'node:test';
import {sshReader} from '../web/map/ssh-reading.ts';

const issuedAt = '2026-11-19T03:00:00Z';
const firstHour = '2026-11-19T06:00:00Z';
const secondHour = '2026-11-18T21:00:00-08:00';
const sw = {lat: 35.025, lon: -120.975};
const ne = {lat: 35.075, lon: -120.925};

function forecast(...frames) {
  return {product: 'WCOFS', issuedAt, resolution: [0.05, 0.05], frames};
}

function value(sshCm, validAt, cell = sw) {
  return {kind: 'value', sshCm, validAt, issuedAt, product: 'WCOFS', cell};
}

// C1's types are checked by tsc; this pins the runtime result, including a real zero.
test('C1: return the whole value with provenance and the cell centre, not the tap', () => {
  const read = sshReader(forecast({validAt: firstHour, cells: [{...sw, sshCm: 0}]}));
  assert.deepEqual(read({lat: 35.01, lon: -120.99}, firstHour), value(0, firstHour));
});

// A frame-level failure must not abort construction or poison the other index.
test('C2: a duplicate-cell frame is bad-grid beside a good frame', () => {
  const read = sshReader(forecast(
    {validAt: firstHour, cells: [{...sw, sshCm: 13}, {...sw, sshCm: 24}]},
    {validAt: secondHour, cells: [{...sw, sshCm: -3.75}]},
  ));
  assert.deepEqual(read(sw, firstHour), {kind: 'none', reason: 'bad-grid'});
  assert.deepEqual(read(sw, secondHour), value(-3.75, secondHour));
});

// A lazy index build or per-call rebuild would see the inserted cell.
test('C2: index the input cells at reader creation', () => {
  const cells = [{...sw, sshCm: 13}, {...ne, sshCm: -5}];
  const read = sshReader(forecast({validAt: firstHour, cells}));
  const missing = {lat: sw.lat, lon: ne.lon};
  cells.push({...missing, sshCm: 6});
  assert.deepEqual(read(missing, firstHour), {kind: 'none', reason: 'gap'});
  assert.deepEqual(read(sw, firstHour), value(13, firstHour));
});

// String equality would miss the offset frame; nearest-hour selection would fill the time gap.
test('C3: choose each exact instant, without taking the nearest hour', () => {
  const read = sshReader(forecast(
    {validAt: firstHour, cells: [{...sw, sshCm: 13}]},
    {validAt: secondHour, cells: [{...sw, sshCm: -3.75}]},
  ));
  assert.deepEqual(read(sw, firstHour), value(13, firstHour));
  assert.deepEqual(read(sw, '2026-11-19T05:00:00Z'), value(-3.75, secondHour));
  assert.deepEqual(read(sw, '2026-11-19T05:59:59.999Z'), {kind: 'none', reason: 'no-frame'});
});

// A raw-string match or NaN map key lookup would select the invalid frame.
test('C3: unparseable query time is no-frame even with an unparseable frame time', () => {
  const validAt = 'not a date';
  const read = sshReader(forecast({validAt, cells: [{...sw, sshCm: 13}]}));
  assert.deepEqual(read(sw, validAt), {kind: 'none', reason: 'no-frame'});
});

// An inclusive upper edge or nearest-centre fallback would sample pixels outside the footprint.
test('C4: native cells use half-open edges and do not extend beyond the grid', () => {
  const read = sshReader(forecast({validAt: firstHour, cells: [{...sw, sshCm: 13}, {...ne, sshCm: -5.25}]}));
  assert.deepEqual(read({lat: 35, lon: -121}, firstHour), value(13, firstHour));
  assert.deepEqual(read({lat: 35.05, lon: -120.95}, firstHour), value(-5.25, firstHour, ne));
  assert.deepEqual(read({lat: 35.1, lon: ne.lon}, firstHour), {kind: 'none', reason: 'outside'});
  assert.deepEqual(read({lat: sw.lat, lon: -120.89}, firstHour), {kind: 'none', reason: 'outside'});
});

// Keep an explicit null (in this JS fixture) distinct at ingest from a bad grid or a numeric zero.
test('C4: a missing cell and an explicit null both read gap', () => {
  const read = sshReader(forecast({validAt: firstHour, cells: [{...sw, sshCm: null}, {...ne, sshCm: 9}]}));
  assert.deepEqual(read(sw, firstHour), {kind: 'none', reason: 'gap'});
  assert.deepEqual(read({lat: sw.lat, lon: ne.lon}, firstHour), {kind: 'none', reason: 'gap'});
});

// An exception while reading a point must not leak into the tap caller.
test('C4: a failed point lookup returns bad-grid rather than throwing', () => {
  const read = sshReader(forecast({validAt: firstHour, cells: [{...sw, sshCm: 13}]}));
  const point = {get lat() { throw new Error('unreadable coordinate'); }, lon: sw.lon};
  assert.deepEqual(read(point, firstHour), {kind: 'none', reason: 'bad-grid'});
});
