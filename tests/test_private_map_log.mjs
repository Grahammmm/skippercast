// Synthetic device-only records. No account API or live position is used.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createEntry, readEntries, saveEntry, LOG_KEY} from '../web/private-map-log.ts';
import {parseConditionsForecast} from '../web/conditions.ts';

const NOW = Date.parse('2026-11-07T18:00:00Z');
const mark = {name: 'Synthetic reef', position: {latitude: 35, longitude: -121}};
function store(raw = null) {
  let value = raw;
  return {getItem: key => { assert.equal(key, LOG_KEY); return value; }, setItem: (key, v) => { assert.equal(key, LOG_KEY); value = v; }};
}
function forecast(age = 0) {
  const sec = NOW / 1000, time = [sec - 3600, sec, sec + 3600];
  return parseConditionsForecast({region_id: 'fixture', retrieved: NOW - age,
    requested_points: [['regional', 35.1, -121.1]], models: {gfs_global: {
      meta: {last_run_initialisation_time: sec - 3600, data_end_time: sec + 3600},
      data: [{utc_offset_seconds: 0, hourly_units: {time: 'unixtime', wind_speed_10m: 'kn'}, hourly: {time, wind_speed_10m: [11, 12, 13]}}],
    }}}, 'fixture', [35.1, -121.1]);
}
const entry = (kind = 'catch', f = null) => createEntry(mark, kind, 'fixture', f, NOW, 'UTC');

test('catch and blank persist exact selected position and capture time across reload', () => {
  const storage = store();
  for (const kind of ['catch', 'blank']) assert.equal(saveEntry(entry(kind), storage), 'saved');
  const rows = readEntries(storage);
  assert.deepEqual(rows.map(r => r.kind), ['catch', 'blank']);
  assert.deepEqual(rows[0].position, mark.position);
  assert.equal(rows[0].recordedAt, new Date(NOW).toISOString());
  assert.equal(rows[0].positionBasis, 'Selected map position; not live GPS');
  assert.equal(rows[0].conditions, null);
  assert.equal(rows[0].region, 'fixture');
});

test('snapshot uses capture hour, names regional model source and preserves gaps and freshness', () => {
  const r = entry('catch', forecast());
  assert.equal(r.conditions.at, NOW);
  assert.equal(r.conditions.retrievedAt, NOW);
  const wind = r.conditions.forecast.families[0].rows[0];
  assert.equal(wind.value, '12 kt');
  assert.equal(wind.point, 'regional');
  assert.equal(wind.cell, null);
  assert.equal(wind.validAt, NOW);
  assert.equal(wind.issuedAt, NOW - 3600000);
  assert.match(wind.model, /GFS/);
  assert.equal(r.conditions.forecast.families[0].rows[1].value, null);
  const storage = store();
  assert.equal(saveEntry(r, storage), 'saved');
  assert.deepEqual(readEntries(storage)[0], r);
  assert.equal(entry('blank', forecast(7 * 3600000)).conditions.forecast.families[0].rows[0].value, null);
  assert.equal(createEntry(mark, 'catch', 'other-region', forecast(), NOW, 'UTC').conditions, null);
});

test('withheld, missing and invalid positions cannot create a log', () => {
  for (const bad of [{...mark, withheld: true}, {name: 'no position'}, {...mark, position: {latitude: NaN, longitude: -121}}, {...mark, position: {latitude: 91, longitude: -121}}]) {
    assert.equal(createEntry(bad, 'catch', 'fixture', null, NOW, 'UTC'), null);
  }
});

test('blocked, full or corrupt storage fails honestly without overwriting earlier records', () => {
  const blocked = {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }};
  assert.equal(saveEntry(entry(), blocked), 'unavailable');
  const quota = {...store(), setItem() { throw Error('quota'); }};
  assert.equal(saveEntry(entry(), quota), 'unavailable');
  for (const raw of ['broken', '{}', '[{}]', JSON.stringify([{...entry(), conditions: {at: NOW, retrievedAt: NOW, forecast: {families: [{rows: [null]}], current: {}}}}])]) {
    const storage = store(raw);
    assert.equal(saveEntry(entry(), storage), 'unavailable');
    assert.equal(storage.getItem(LOG_KEY), raw);
  }
  const storage = store(JSON.stringify(Array.from({length: 500}, () => entry())));
  assert.equal(saveEntry(entry(), storage), 'full');
  assert.equal(readEntries(storage).length, 500);
});
