import assert from 'node:assert/strict';
import test from 'node:test';
import {answer} from '../server/model-api.js';

const store = {manifest: async () => ({tiles: []}), tile: async () => assert.fail('unexpected tile read')};
const hours = Array.from({length: 24}, (_, i) => i);
const labels = (date, localHours) => localHours.map(h => `${date}T${String(h).padStart(2, '0')}:00`);

// A fixed 24 hours per day leaks into tomorrow in spring and drops 23:00 in fall.
// Checking both formats also catches deduplication of the two fall 01:00 labels.
test('F03-12: forecast axes end at local midnight without losing repeated hours', async t => {
  for (const [name, now, start, end, expected, days = 1, zone = 'America/Los_Angeles'] of [
    ['spring', '2026-03-08T12:00Z', '2026-03-08T08:00Z', '2026-03-09T07:00Z',
      labels('2026-03-08', hours.filter(h => h !== 2))],
    ['fall', '2026-11-01T12:00Z', '2026-11-01T07:00Z', '2026-11-02T08:00Z',
      labels('2026-11-01', [0, 1, ...hours.slice(1)])],
    ['ordinary', '2026-11-02T12:00Z', '2026-11-02T08:00Z', '2026-11-03T08:00Z',
      labels('2026-11-02', hours)],
    ['two days crossing spring', '2026-03-07T12:00Z', '2026-03-07T08:00Z', '2026-03-09T07:00Z',
      [...labels('2026-03-07', hours), ...labels('2026-03-08', hours.filter(h => h !== 2))], 2],
    ['skipped midnight', '2026-03-08T12:00Z', '2026-03-08T05:00Z', '2026-03-09T04:00Z',
      labels('2026-03-08', hours.slice(1)), 1, 'America/Havana'],
    ['repeated midnight', '2026-11-01T12:00Z', '2026-11-01T04:00Z', '2026-11-02T05:00Z',
      labels('2026-11-01', [0, ...hours]), 1, 'America/Havana'],
  ]) {
    await t.test(name, async () => {
      const params = new URLSearchParams({latitude: '0', longitude: '0', timezone: zone,
        forecast_days: String(days), hourly: 'temperature_2m'});
      const {hourly: local} = await answer('forecast', params, store, Date.parse(now) / 1000);
      assert.equal(local.time.length, expected.length, 'one entry per elapsed hour until the next midnight');
      assert.deepEqual(local.time, expected);
      assert.equal(local.temperature_2m.length, expected.length, 'hourly values align with the axis');
      params.set('timeformat', 'unixtime');
      const {hourly: utc} = await answer('forecast', params, store, Date.parse(now) / 1000);
      const epochs = [];
      for (let epoch = Date.parse(start) / 1000; epoch < Date.parse(end) / 1000; epoch += 3600) epochs.push(epoch);
      assert.deepEqual(utc.time, epochs, 'real hourly instants, including both epochs for repeated labels');
    });
  }
});
