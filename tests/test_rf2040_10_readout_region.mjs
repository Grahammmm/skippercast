// RF2040-10: JSON null region metadata takes the same fallback as empty/failed metadata.
import assert from 'node:assert/strict';
import test from 'node:test';
import {isDeepStrictEqual} from 'node:util';
import {loadReadout} from '../web/landing/readings.ts';
import {prepareCatalogue} from '../web/i18n.ts';

await prepareCatalogue('es');

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
      const [wind, swell, water, level] = got.out.readings;
      assert.deepEqual(got.out.readings.map(r => r.id), ['wind', 'swell', 'water', 'tide']);
      assert.equal(got.out.place, 'Morro Bay & Avila');
      const none = lang === 'es' ? 'Sin lectura' : 'No reading';
      const unavailable = lang === 'es' ? 'no disponible' : 'unavailable';
      if (withData) {
        assert.deepEqual([wind.reading, wind.unit, wind.source, wind.stale], ['14', 'kt', 'NDBC 46028 · 20 min', false]);
        assert.deepEqual([level.reading, level.unit, level.detail, level.source, level.stale],
          [lang === 'es' ? '3' : '3.0', 'ft', lang === 'es' ? 'subiendo' : 'rising', 'NOAA 9412110 · 6 min', false]);
        assert.deepEqual(got.out.feed, {age: '12 min', stale: false});
        for (const missing of [swell, water]) {
          assert.deepEqual([missing.reading, missing.unit, missing.source, missing.stale], [none, undefined, `NDBC — · ${unavailable}`, true]);
        }
      } else {
        assert.deepEqual(got.out.feed, {age: null, stale: true});
        assert.deepEqual(got.out.readings.map(r => [r.reading, r.unit, r.source, r.stale]), [
          [none, undefined, `NDBC — · ${unavailable}`, true], [none, undefined, `NDBC — · ${unavailable}`, true],
          [none, undefined, `NDBC — · ${unavailable}`, true], [none, undefined, `NOAA 9412110 · ${unavailable}`, true],
        ]);
      }
      same(got.out, control.out, 'readout');
      same(got.urls, control.urls, 'urls');
      assert.equal(got.urls.length, 3);
      for (const bad of ['fail', 'badjson']) same((await run(bad, lang, withData)).out, control.out, bad);
    });
  }
}

for (const lang of ['en', 'es']) {
  test(`healthy region metadata forwards custom feed, tide details and language (${lang})`, async () => {
    const info = {
      name: ' Synthetic bay ',
      conditions_feed: 'https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/custom/synthetic.json',
      stations: {tide: 'synthetic-station', tide_name: 'Synthetic pier', tide_note: ' Synthetic reference only. '},
    };
    const copy = JSON.parse(JSON.stringify(info));
    const {out, urls} = await run(info, lang);
    assert.equal(out.place, 'Synthetic bay');
    assert.deepEqual(urls, [
      'regions/central-coast/region.json',
      '/feeds/conditions/custom/synthetic.json',
      'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=SkipperCast&station=synthetic-station&range=2&datum=MLLW&time_zone=gmt&units=english&format=json',
    ]);
    const level = out.readings[3];
    assert.deepEqual([level.label, level.reading, level.detail, level.source, level.stale],
      [lang === 'es' ? 'Marea' : 'Tide', lang === 'es' ? '3' : '3.0', lang === 'es' ? 'subiendo' : 'rising', 'NOAA synthetic-station · 6 min', false]);
    assert.equal(level.basis, lang === 'es'
      ? 'Nivel del agua observado en Synthetic pier, en pies sobre la bajamar media inferior, cada 6 minutos; desactualizado después de 1 h. Synthetic reference only.'
      : 'Observed water level at Synthetic pier, in feet above mean lower low water, every 6 minutes; stale after 1 h. Synthetic reference only.');
    assert.equal(out.readings[1].reading, lang === 'es' ? 'Sin lectura' : 'No reading');
    same(info, copy, 'input not mutated');
  });
}
