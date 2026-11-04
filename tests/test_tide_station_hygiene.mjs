import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {tideRegion, stationsInRegion, parseTidePredictions} from '../web/tide-stations.ts';

const bounds = [-122, 35, -120, 36];
const region = tide_name => ({bounds, stations: {tide: '9412110', ...(tide_name === undefined ? {} : {tide_name})}});
const row = (id, name) => ({id, name, lat: 35.5, lng: -121, type: 'R'});

test('region name falls back to the station id unless tide_name is plain one-line text', () => {
  const bad = [{x: 1}, 42, true, null, [], '', '  ', 'Port\nSan Luis', 'Port\tSan Luis', 'Port\u0007', 'A\u2028B', 'A\u2029B', 'x'.repeat(120), 'x'.repeat(81)];
  for (const name of bad) assert.equal(tideRegion('r', region(name)).name, '9412110', JSON.stringify(name));
  assert.equal(tideRegion('r', region()).name, '9412110', 'absent name');
  assert.equal(tideRegion('r', region('  Port San Luis ')).name, 'Port San Luis');
  assert.equal(tideRegion('r', region(' ' + 'x'.repeat(80) + ' ')).name, 'x'.repeat(80), '80 chars after trim is kept');
  assert.equal(tideRegion('r', region('Port San Luis')).name, 'Port San Luis');
});

test('committed Morro Bay region gives the same TideRegion as before', () => {
  const value = JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json', import.meta.url), 'utf8'));
  assert.deepEqual(tideRegion('morro-bay', value), {id: 'morro-bay', bounds: value.bounds, station: '9412110', name: 'Port San Luis'});
});

test('directory rows with empty, blank or multi-line names are skipped; names trimmed and sorted trimmed', () => {
  const body = {stations: [
    row('9000001', ''), row('9000002', '   '), row('9000003', 'A\u2028B'), row('9000004', 'Port\nSan Luis'),
    row('9000005', 42), row('9000006', {x: 1}), row('9000007', 'y'.repeat(81)),
    row('9000008', 'Morro'), row('9000009', ' Avila '), row('9000010', '\tCayucos'),
  ]};
  const rows = stationsInRegion(body, bounds);
  assert.deepEqual(rows.map(s => [s.id, s.name]), [['9000009', 'Avila'], ['9000010', 'Cayucos'], ['9000008', 'Morro']]);
});

test('a later malformed duplicate id does not replace or remove a valid earlier row', () => {
  const rows = stationsInRegion({stations: [row('9000001', 'Avila'), row('9000001', '  ')]}, bounds);
  assert.deepEqual(rows.map(s => s.name), ['Avila']);
});

test('repeated hilo rows (same t and type) become one event; first kept', () => {
  const body = {predictions: [
    {t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-08 12:00', v: '0.4', type: 'L'},
    {t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-08 18:00', v: '9.9', type: 'H'},
  ]};
  const {events, points} = parseTidePredictions(body);
  assert.deepEqual(events, [
    {at: '2026-10-08T12:00:00.000Z', heightFt: 0.4, type: 'L'},
    {at: '2026-10-08T18:00:00.000Z', heightFt: 3.2, type: 'H'},
  ]);
  assert.deepEqual(points, []);
});

test('a repeated curve time becomes one point; first kept, order by time', () => {
  const body = {predictions: [
    {t: '2026-10-08 17:06', v: '1.3'}, {t: '2026-10-08 17:00', v: '1.2'}, {t: '2026-10-08 17:06', v: '5.0'},
  ]};
  assert.deepEqual(parseTidePredictions(body).points, [
    {at: '2026-10-08T17:00:00.000Z', heightFt: 1.2}, {at: '2026-10-08T17:06:00.000Z', heightFt: 1.3},
  ]);
});

test('a rejected row does not claim its time; the next valid row at that time is kept', () => {
  const body = {predictions: [{t: '2026-10-08 17:00', v: ''}, {t: '2026-10-08 17:00', v: 'NaN'}, {t: '2026-10-08 17:00', v: '1.2'}]};
  assert.deepEqual(parseTidePredictions(body).points, [{at: '2026-10-08T17:00:00.000Z', heightFt: 1.2}]);
});

test('same time as an H event and as a point keeps one of each (different lists)', () => {
  const body = {predictions: [
    {t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-08 18:00', v: '3.2'},
    {t: '2026-10-08 18:00', v: '3.2'}, {t: '2026-10-08 18:00', v: '3.2', type: 'H'},
  ]};
  const {events, points} = parseTidePredictions(body);
  assert.deepEqual(events, [{at: '2026-10-08T18:00:00.000Z', heightFt: 3.2, type: 'H'}]);
  assert.deepEqual(points, [{at: '2026-10-08T18:00:00.000Z', heightFt: 3.2}]);
});

test('distinct times are all kept and NOAA error bodies still give nothing', () => {
  const body = {predictions: [{t: '2026-10-08 18:00', v: '3.2', type: 'H'}, {t: '2026-10-09 18:00', v: '3.3', type: 'H'}]};
  assert.equal(parseTidePredictions(body).events.length, 2);
  assert.deepEqual(parseTidePredictions({...body, error: {message: 'No data'}}), {points: [], events: []});
});

const iso = t => t.replace(' ', 'T') + ':00.000Z';

test('tide_prediction_minutes_are_real_utc_calendar_minutes', () => {
  const impossible = ['2026-02-29 12:00', '2026-02-30 12:00', '2026-04-31 12:00', '2100-02-29 12:00', '2026-00-10 12:00', '2026-13-10 12:00',
    '2026-03-00 12:00', '2026-03-32 12:00', '2026-03-02 24:00', '2026-03-02 12:60', '2026-3-02 12:00', ' 2026-03-02 12:00', '2026-03-02 12:00 ', '2026-03-02T12:00', 7, null];
  for (const t of impossible) {
    for (const type of ['H', 'L', undefined]) {
      const r = parseTidePredictions({predictions: [{t, v: '1.0', ...(type ? {type} : {})}]});
      assert.deepEqual(r, {points: [], events: []}, `${JSON.stringify(t)} ${type}`);
    }
  }
  const real = ['2028-02-29 12:00', '2000-02-29 00:00', '2026-12-31 23:59', '2027-01-01 00:00', '2026-03-02 12:00', '2026-04-30 00:00'];
  for (const t of real) {
    const pts = parseTidePredictions({predictions: [{t, v: '0'}, {t, v: '-1.5', type: 'L'}]});
    assert.deepEqual(pts.points, [{at: iso(t), heightFt: 0}], t);
    assert.deepEqual(pts.events, [{at: iso(t), heightFt: -1.5, type: 'L'}], t);
  }
});

test('invalid_rollover_cannot_shadow_valid_prediction', () => {
  const body = {predictions: [
    {t: '2026-02-30 12:00', v: '9.9', type: 'H'}, {t: '2026-03-02 12:00', v: '2.0', type: 'H'},
    {t: '2026-02-30 12:00', v: '9.9'}, {t: '2026-03-02 12:00', v: '2.0'},
    {t: '2026-03-01 24:00', v: '8.8', type: 'L'}, {t: '2026-03-02 00:00', v: '0.5', type: 'L'},
    {t: '2026-03-01 24:00', v: '8.8'}, {t: '2026-03-02 00:00', v: '0.5'},
    {t: '2026-03-02 06:00', v: '1.1', type: 'H'}, {t: '2026-03-02 06:00', v: '7.7', type: 'H'},
  ]};
  const before = JSON.stringify(body);
  const {events, points} = parseTidePredictions(body);
  assert.deepEqual(events, [
    {at: '2026-03-02T00:00:00.000Z', heightFt: 0.5, type: 'L'}, {at: '2026-03-02T06:00:00.000Z', heightFt: 1.1, type: 'H'},
    {at: '2026-03-02T12:00:00.000Z', heightFt: 2.0, type: 'H'},
  ]);
  assert.deepEqual(points, [{at: '2026-03-02T00:00:00.000Z', heightFt: 0.5}, {at: '2026-03-02T12:00:00.000Z', heightFt: 2.0}]);
  assert.equal(JSON.stringify(body), before, 'input not mutated');
});
