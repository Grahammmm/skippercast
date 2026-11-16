// RF0452-5: a successfully decoded feed or tide response whose observation collection is not an array
// reads as that source's unavailable reading; it never throws and never disturbs the other readings.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {buoyReadings, loadReadout, tideReading, tideURL} from '../web/landing/readings.ts';

const NOW = Date.parse('2026-10-07T20:00:00Z');
const ago = min => new Date(NOW - min * 60000).toISOString();
const source = (name, station, units, rows) => ({name, status: 'ok', max_age_hours: 2, data: {station, units, observations: rows}});
const feed = () => ({
  schema_version: 1, generated_at: ago(12),
  sources: {
    offshore: source('Cape San Martin offshore', '46028', {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, [{time: ago(20), WDIR: 320, WSPD: 7, GST: 9}]),
    'diablo-spectrum': source('Diablo Canyon swell and wind waves', '46215', {SwH: 'm', SwP: 'sec', SwD: '-'}, [{time: ago(34), SwH: 0.7, SwP: 10.5, SwD: 'WNW'}]),
    diablo: source('Diablo Canyon', '46215', {WTMP: 'degC'}, [{time: ago(30), WTMP: 14.5}]),
  },
});
const coops = minutes => minutes.map(([min, v]) => ({t: new Date(NOW - min * 60000).toISOString().slice(0, 16).replace('T', ' '), v}));
const TIDE = {data: coops([[114, '2.10'], [60, '2.52'], [6, '3.04']])};
const BAD = [{}, 'bad', 42, true, false];
const same = (a, b, msg) => assert.ok(isDeepStrictEqual(a, b), msg);

for (const lang of ['en', 'es']) {
  test(`non-array tide data reads as the empty-array tide reading (${lang})`, () => {
    const empty = tideReading({data: []}, '9412110', 'x', NOW, undefined, lang);
    assert.equal(empty.stale, true);
    for (const data of BAD) same(tideReading({data}, '9412110', 'x', NOW, undefined, lang), empty, JSON.stringify(data));
    same(tideReading({}, '9412110', 'x', NOW, undefined, lang), empty, 'missing');
    same(tideReading({data: null}, '9412110', 'x', NOW, undefined, lang), empty, 'null');
    const ok = tideReading(TIDE, '9412110', 'x', NOW, undefined, lang);
    assert.equal(ok.stale, false);
    assert.equal(ok.detail === undefined, false, 'trend control');
  });

  test(`a non-array observation collection only blanks its own buoy reading (${lang})`, () => {
    const healthy = buoyReadings(feed(), {}, NOW, lang);
    for (const [key, index] of [['offshore', 0], ['diablo-spectrum', 1], ['diablo', 2]]) {
      const emptied = feed();
      emptied.sources[key].data.observations = [];
      const expected = buoyReadings(emptied, {}, NOW, lang);
      for (const bad of BAD) {
        const f = feed();
        f.sources[key].data.observations = bad;
        const got = buoyReadings(f, {}, NOW, lang);
        same(got, expected, `${key} ${JSON.stringify(bad)}`);
        got.forEach((r, i) => { if (i !== index) same(r, healthy[i], `${key} sibling ${i}`); });
      }
      for (const missing of [undefined, null]) {
        const f = feed();
        f.sources[key].data.observations = missing;
        same(buoyReadings(f, {}, NOW, lang), expected, `${key} ${missing}`);
      }
    }
  });
}

test('loadReadout resolves four readings when the feed or tide collection is malformed', async () => {
  const reply = body => ({ok: true, status: 200, json: async () => body});
  const run = (feedBody, tideBody) => loadReadout(async url => {
    if (url.startsWith('/feeds/')) return reply(feedBody);
    if (url === tideURL('9412110')) return reply(tideBody);
    return reply({});
  }, 'morro-bay', () => NOW);
  const healthy = await run(feed(), TIDE);
  const badFeed = feed();
  for (const k of Object.keys(badFeed.sources)) badFeed.sources[k].data.observations = {};
  const a = await run(badFeed, TIDE);
  assert.equal(a.readings.length, 4);
  same(a.readings[3], healthy.readings[3], 'healthy tide survives');
  assert.ok(a.readings.slice(0, 3).every(r => r.reading === 'No reading' && r.stale));
  const b = await run(feed(), {data: 'bad'});
  assert.equal(b.readings.length, 4);
  same(b.readings.slice(0, 3), healthy.readings.slice(0, 3), 'healthy buoys survive');
  assert.equal(b.readings[3].reading, 'No reading');
});
