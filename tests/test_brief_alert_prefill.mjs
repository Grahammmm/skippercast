import assert from 'node:assert/strict';
import test from 'node:test';
import {briefAlertPrefill} from '../web/brief-alerts.ts';

const region = {id: 'fixture', timezone: 'America/Los_Angeles', species: ['reef'], forecast_points: [
  {id: 'incomplete', name: 'Incomplete', latitude: 35},
  {id: 'invalid', name: 'Invalid', latitude: 35, longitude: -181},
  {id: 'first-near', name: 'First Near', latitude: 35, longitude: -121},
  {id: 'second-near', name: 'Second Near', latitude: 35, longitude: -121},
  {id: 'far', name: 'Far', latitude: 38, longitude: -123},
]};
const seed = (date, start, end) => ({region: region.id, date, start: Date.parse(start), end: Date.parse(end),
  profile: 'boat', port: {lat: 35, lon: -121}, target: 'reef', ownLimits: null});

test('date range uses the region’s calendar, including both endpoints and no normalized invalid dates', () => {
  const now = Date.parse('2026-02-23T02:00:00Z'); // still Feb 22 at the port
  for (const [date, expected] of [['2026-02-21', ''], ['2026-02-22', '2026-02-22'],
    ['2026-02-28', '2026-02-28'], ['2026-02-29', ''], ['2026-03-01', '2026-03-01'], ['2026-03-02', '']]) {
    const draft = briefAlertPrefill(seed(date, `${date}T15:00Z`, `${date}T19:00Z`), region, now);
    assert.equal(draft.date, expected, date);
    assert.equal(draft.notes.includes('alerts.problem.date'), !expected, date);
  }
});

test('forecast points keep published tie order and do not substitute a point without a port or valid coordinates', () => {
  const s = seed('2026-02-22', '2026-02-22T15:00Z', '2026-02-22T19:00Z');
  const now = Date.parse('2026-02-22T12:00Z');
  assert.equal(briefAlertPrefill(s, region, now).fields.point, 'first-near');
  for (const draft of [briefAlertPrefill({...s, port: null}, region, now),
    briefAlertPrefill(s, {...region, forecast_points: region.forecast_points.slice(0, 2)}, now)]) {
    assert.equal(draft.fields.point, '');
    assert.ok(draft.notes.includes('alerts.prefill.area'));
  }
});

test('the whole local-hour form keeps exclusive end and refuses ambiguous or unrepresentable windows', () => {
  for (const [name, date, start, end, from, until] of [
    ['exclusive end', '2026-03-07', '2026-03-07T15:00Z', '2026-03-07T19:00Z', 7, 11],
    ['midnight starts at 0', '2026-03-07', '2026-03-07T08:00Z', '2026-03-07T09:00Z', 0, 1],
    ['next midnight cannot end at 24', '2026-03-07', '2026-03-08T06:00Z', '2026-03-08T08:00Z', '', ''],
    ['fractional hour', '2026-03-07', '2026-03-07T15:30Z', '2026-03-07T19:00Z', '', ''],
    ['malformed instant', '2026-03-07', 'bad', '2026-03-07T19:00Z', '', ''],
    ['spring clock jump', '2026-03-08', '2026-03-08T09:00Z', '2026-03-08T11:00Z', '', ''],
    ['spring ordinary hours', '2026-03-08', '2026-03-08T14:00Z', '2026-03-08T18:00Z', 7, 11],
    ['fall clock jump', '2026-11-01', '2026-11-01T07:00Z', '2026-11-01T10:00Z', '', ''],
    ['fall first repeated hour at end', '2026-11-01', '2026-11-01T07:00Z', '2026-11-01T08:00Z', '', ''],
    ['fall second repeated hour at start', '2026-11-01', '2026-11-01T09:00Z', '2026-11-01T10:00Z', '', ''],
    ['fall ordinary hours', '2026-11-01', '2026-11-01T15:00Z', '2026-11-01T19:00Z', 7, 11],
  ]) {
    const {fields, notes} = briefAlertPrefill(seed(date, start, end), region, Date.parse(`${date}T12:00Z`));
    assert.equal(fields.start_hour, from, name);
    assert.equal(fields.end_hour, until, name);
    assert.equal(notes.includes('alerts.prefill.hours'), from === '', name);
  }
});