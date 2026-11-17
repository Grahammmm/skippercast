// RF2040-10: JSON null region metadata takes the same fallback as empty/failed metadata.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {loadReadout} from '../web/landing/readings.ts';

const NOW = Date.parse('2026-10-07T20:00:00Z');
const ago = min => new Date(NOW - min * 60000).toISOString();
const feed = () => ({schema_version: 1, generated_at: ago(12), sources: {
  offshore: {name: 'Offshore', status: 'ok', max_age_hours: 2, data: {station: '46028', units: {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, observations: [{time: ago(20), WDIR: 320, WSPD: 7, GST: 9}]}}}});
const tide = {data: [[114, '2.10'], [60, '2.52'], [6, '3.04']].map(([m, v]) => ({t: new Date(NOW - m * 60000).toISOString().slice(0, 16).replace('T', ' '), v}))};
const same = (a, b, msg) => assert.ok(isDeepStrictEqual(a, b), msg);

// region: a body, or 'fail' (request rejects), or 'badjson' (decode rejects)
async function run(region, lang, withData = true) {
  const urls = [];
  const out = await loadReadout(async url => {
    urls.push(url);
    if (url.includes('region.json')) {
      if (region === 'fail') throw Error('offline');
      return {ok: true, status: 200, json: async () => { if (region === 'badjson') throw SyntaxError('bad'); return region; }};
    }
    if (!withData) return {ok: false, status: 404, json: async () => null};
    return {ok: true, status: 200, json: async () => (url.includes('feed') || url.includes('conditions') ? feed() : tide)};
  }, 'central-coast', () => NOW, lang);
  return {out, urls};
}

for (const lang of ['en', 'es']) {
  for (const withData of [false, true]) {
    test(`null region metadata matches the empty-object control (${lang}, data=${withData})`, async () => {
      const control = await run({}, lang, withData);
      const got = await run(null, lang, withData);
      assert.equal(got.out.readings.length, 4);
      same(got.out, control.out, 'readout');
      same(got.urls, control.urls, 'urls');
      assert.equal(got.urls.length, 3);
      for (const bad of ['fail', 'badjson']) same((await run(bad, lang, withData)).out, control.out, bad);
    });
  }
}

test('healthy region metadata still selects its tide station and name', async () => {
  const info = {name: ' Synthetic bay ', stations: {tide: 'synthetic-station'}};
  const copy = JSON.parse(JSON.stringify(info));
  const {out, urls} = await run(info, 'en');
  assert.equal(out.place, 'Synthetic bay');
  assert.ok(urls.some(u => u.includes('synthetic-station')), urls.join());
  same(info, copy, 'input not mutated');
});
