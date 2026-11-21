import test from 'node:test';
import assert from 'node:assert/strict';
import {dataAlertRows, validateDataAlerts} from '../server/region-data-alerts.ts';

const region = 'test-bay';
const owner = 'test-owner';
const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const today = '2026-11-21';
const known = id => id === region;
const validate = body => validateDataAlerts(region, body, known);
const unknownRegion = {ok: false, field: 'region', error: 'unknown-region'};
const notObject = {ok: false, field: 'body', error: 'not-object'};
const unexpectedKey = {ok: false, field: 'body', error: 'unexpected-key'};
const unknownLayer = {ok: false, field: 'layers', error: 'unknown-layer'};

// Reject malformed values before lookup, even when the lookup would accept them.
test('C1: malformed IDs do not reach the region lookup', () => {
  const calls = [];
  for (const id of [null, 12, '', 'a'.repeat(65), 'Test-bay', 'test_bay', 'test/bay', ' test-bay']) {
    assert.deepEqual(validateDataAlerts(id, {layers: []}, key => {
      calls.push(key);
      return true;
    }), unknownRegion, String(id));
  }
  assert.deepEqual(calls, []);
});

test('C1: boundary-length IDs reach the lookup unchanged', () => {
  for (const id of ['0', 'a'.repeat(63) + '-']) {
    assert.deepEqual(validateDataAlerts(id, {layers: []}, key => key === id),
      {ok: true, region: id, layers: []});
  }
});

test('C1: an unknown well-formed region wins over invalid body and layers', () => {
  assert.deepEqual(validateDataAlerts('other-bay', null, known), unknownRegion);
  assert.deepEqual(validateDataAlerts('other-bay', {layers: 42}, known), unknownRegion);
});

test('C1: a throwing region lookup is an unknown region, not an exception', () => {
  assert.deepEqual(validateDataAlerts(region, {layers: []}, () => {
    throw new Error('lookup failed');
  }), unknownRegion);
});

test('C2: non-plain bodies are rejected before their keys or layer value', () => {
  for (const body of [null, undefined, '', 42, true, [], () => {}, new Date(0), Object.create({layers: []})]) {
    assert.deepEqual(validate(body), notObject);
  }
});

test('C2: requires exactly one own key, including symbol and non-enumerable keys', () => {
  assert.deepEqual(validate({}), unexpectedKey);
  assert.deepEqual(validate({layer: []}), unexpectedKey);
  assert.deepEqual(validate({layers: 42, extra: true}), unexpectedKey);
  assert.deepEqual(validate({layers: [], [Symbol('extra')]: true}), unexpectedKey);
  assert.deepEqual(validate(Object.defineProperty({layers: []}, 'extra', {value: true})), unexpectedKey);
});

test('C2: rejects extra keys before reading a getter; a throwing getter alone is not-object', () => {
  let reads = 0;
  const body = {get layers() { reads++; throw new Error('unreadable'); }};
  assert.deepEqual(validate(body), notObject);
  assert.deepEqual(reads, 1);
  assert.deepEqual(validate(Object.assign(body, {extra: true})), unexpectedKey);
  assert.deepEqual(reads, 1);
});

test('C2: an own layers key is valid on a null-prototype record', () => {
  const body = Object.assign(Object.create(null), {layers: []});
  assert.deepEqual(validate(body), {ok: true, region, layers: []});
});

test('C2: list validation rejects strings, null, and array-like objects', () => {
  for (const layers of [sst, null, undefined, {0: sst, length: 1}]) {
    assert.deepEqual(validate({layers}), {ok: false, field: 'layers', error: 'not-list'});
  }
});

test('C2: the count limit precedes item validation and deduplication', () => {
  const tooMany = {ok: false, field: 'layers', error: 'too-many'};
  assert.deepEqual(validate({layers: Array(9).fill(sst)}), tooMany);
  assert.deepEqual(validate({layers: Array(9).fill('wave-forecast')}), tooMany);
  assert.deepEqual(validate({layers: Array(8).fill(sst)}), {ok: true, region, layers: [sst]});
});

test('C2: rejects non-analysis, non-string, and missing list entries', () => {
  for (const layers of [[sst, 'wave-forecast'], [42], [Object(sst)], Array(1)]) {
    assert.deepEqual(validate({layers}), unknownLayer);
  }
});

test('C2: returns canonical order without mutating input; an empty list turns all off', () => {
  const body = Object.freeze({layers: Object.freeze([chl, sst, chl])});
  assert.deepEqual(validate(body), {ok: true, region, layers: [sst, chl]});
  assert.deepEqual(validate({layers: []}), {ok: true, region, layers: []});
});

// Replacing choices must retain a selected layer's send history without carrying other rows forward.
test('C3: retains matching sent days, omits unchosen rows, and does not mutate inputs', () => {
  const layers = Object.freeze([chl, sst, chl]);
  const existing = Object.freeze([
    Object.freeze({layer: chl, lastSentDay: null}),
    Object.freeze({layer: 'wave-forecast', lastSentDay: today}),
    Object.freeze({layer: sst, lastSentDay: today}),
  ]);
  assert.deepEqual(dataAlertRows(owner, region, layers, existing), [
    {owner, region, layer: sst, lastSentDay: today},
    {owner, region, layer: chl, lastSentDay: null},
  ]);
  assert.deepEqual(dataAlertRows(owner, region, [], existing), []);
});

test('C3: new layers get null rather than borrowing an unchosen layer’s day', () => {
  const row = {owner, region, layer: chl, lastSentDay: null};
  assert.deepEqual(dataAlertRows(owner, region, [chl], [{layer: sst, lastSentDay: today}]), [row]);
  assert.deepEqual(dataAlertRows(owner, region, [chl], []), [row]);
});
