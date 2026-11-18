// RF1230-14: a regional tide event without a readable time is dropped, so the brief's tide list never throws.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {sparkArgs} from '../web/tides.ts';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {regionalReport} = await import('../web/brief/model.ts');

const montereyPlace = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
const eventsOf = daily => regionalReport(daily, montereyForecast, montereyPlace).report.tideEvents;
const withPredictions = edit => {
  const daily = structuredClone(montereyDaily);
  edit(daily.sources.tides.data);
  return daily;
};
const hour = new Intl.DateTimeFormat('en-US', {hour: 'numeric', timeZone: 'America/Los_Angeles'});
const readable = events => {
  for (const e of events) {
    assert.ok(Number.isFinite(Date.parse(e.at)), e.at);
    assert.doesNotThrow(() => hour.format(new Date(e.at)), e.at);
  }
};

// Golden taken from origin/main (be4cefab) for the unchanged fixture.
const GOLDEN = [
  ['2026-10-08T01:10:00Z', 4.9, 'H'], ['2026-10-08T07:22:00Z', 0.6, 'L'], ['2026-10-08T13:34:00Z', 4.9, 'H'],
  ['2026-10-08T19:46:00Z', 0.6, 'L'], ['2026-10-09T01:58:00Z', 4.9, 'H'], ['2026-10-09T08:10:00Z', 0.6, 'L'],
  ['2026-10-09T14:22:00Z', 4.9, 'H'], ['2026-10-09T20:34:00Z', 0.6, 'L'], ['2026-10-10T02:46:00Z', 4.9, 'H'],
  ['2026-10-10T08:58:00Z', 0.6, 'L'],
].map(([at, heightFt, type]) => ({at, heightFt, type}));

test('edge 1: the unchanged fixture maps exactly as on main', () => {
  const events = eventsOf(montereyDaily);
  assert.deepEqual(events, GOLDEN);
  readable(events);
});

test('edge 2: rows with a missing, null, unreadable or numeric time are dropped; the rest keep their order', () => {
  const daily = withPredictions(data => {
    delete data.predictions[1].time;
    data.predictions[3].time = null;
    data.predictions[5].time = 'soon';
    data.predictions[7].time = 12345;
  });
  const events = eventsOf(daily);
  assert.deepEqual(events, GOLDEN.filter((_, i) => ![1, 3, 5, 7].includes(i)));
  for (const at of ['undefined', 'null', 'soon', '12345']) assert.ok(!events.some(e => e.at === at), at);
  readable(events);
});

test('edge 2b: a list made only of unreadable times yields no events and no throw', () => {
  const daily = withPredictions(data => {
    data.predictions = [{height_ft: 1, type: 'H'}, {time: null, height_ft: 1, type: 'L'}, {time: '', height_ft: 1, type: 'H'}, {time: {}, height_ft: 1, type: 'L'}];
  });
  assert.deepEqual(eventsOf(daily), []);
});

test('edge 3: a readable time does not rescue a row the height/type rules already drop', () => {
  const daily = withPredictions(data => {
    data.predictions[0].height_ft = NaN;
    data.predictions[2].type = 'X';
    data.predictions[4].height_ft = '4.9';
  });
  const events = eventsOf(daily);
  assert.deepEqual(events, GOLDEN.filter((_, i) => ![0, 2, 4].includes(i)));
  readable(events);
});

test('edge 4: every kept event formats as an hour without throwing', () => {
  const daily = withPredictions(data => {
    data.predictions.push({time: 'not a date', height_ft: 3, type: 'H'}, {time: '2026-10-10T15:10:00Z', height_ft: 3.2, type: 'H'});
  });
  const events = eventsOf(daily);
  assert.equal(events.length, GOLDEN.length + 1);
  assert.deepEqual(events.at(-1), {at: '2026-10-10T15:10:00Z', heightFt: 3.2, type: 'H'});
  readable(events);
});

test('edge 5: missing or empty predictions give no events', () => {
  assert.deepEqual(eventsOf(withPredictions(data => { delete data.predictions; })), []);
  assert.deepEqual(eventsOf(withPredictions(data => { data.predictions = []; })), []);
});

test('regional datum: both tide lists retain the clocks but only show heights with a supported datum', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'tide-datum-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const outfile = join(dir, 'views.mjs');
  await build({
    stdin: {resolveDir: fileURLToPath(new URL('..', import.meta.url)), loader: 'ts', contents: `
      export {Conditions} from './web/app/views/Conditions.tsx';
      export {currentBrief, dailyFeed} from './web/brief/Brief.tsx';
      export {TideSpark} from './web/brief/TideSpark.tsx';
      export {regionInfo} from './web/app/App.tsx';
      export {language} from './web/i18n.ts';
      export {configureStore, region} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile, jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  const m = await import(pathToFileURL(outfile).href);
  const now = new Date('2026-10-08T18:00:00Z');
  const info = {...montereyPlace, id: montereyDaily.region_id, center: [montereyPlace.lat, montereyPlace.lon]};
  m.configureStore({v2: true, storage: null});
  m.language.value = 'en';
  m.region.value = info.id;
  m.regionInfo.value = info;
  // 1:00 PM high and 8:00 PM low in Monterey. The source link already requests MLLW;
  // it isn't a substitute for datum metadata on the regional payload itself.
  const predictions = [
    {time: '2026-10-08T20:00:00Z', type: 'H', height_ft: 3.3},
    {time: '2026-10-09T03:00:00Z', type: 'L', height_ft: -0.4},
  ];
  const renderList = (component, props, className) => {
    const html = m.render(m.h(component, props));
    const list = html.match(new RegExp(`<ul class="${className}">(.*?)</ul>`, 's'));
    assert.ok(list, `missing ${className}`);
    return [...list[1].matchAll(/<li>(.*?)<\/li>/gs)].map(([, row]) => row.replace(/<[^>]*>/g, '').replace(/[\u202f\u00a0]/g, ' '));
  };
  for (const [label, datum] of [['explicit MLLW', 'MLLW'], ['missing', undefined], ['blank', '   '], ['unrecognised', 'chart-zero'], ['non-string', ['MLLW']]]) {
    await t.test(label, () => {
      m.dailyFeed.value = withPredictions(data => {
        data.predictions = predictions;
        if (datum === undefined) delete data.datum; else data.datum = datum;
      });
      const brief = m.currentBrief(now);
      const known = datum === 'MLLW';
      const expected = clocks => clocks.map((clock, i) => `${i ? 'Low' : 'High'} ${clock}${known ? ` · ${i ? '-0.4' : '3.3'} ft MLLW` : ''}`);
      assert.deepEqual({
        brief: renderList(m.TideSpark, {brief, now}, 'app-spark-events'),
        conditions: renderList(m.Conditions, {now}, 'app-conditions-tides'),
      }, {brief: expected(['1:00 pm', '8:00 pm']), conditions: expected(['1:00 PM PDT', '8:00 PM PDT'])});
      assert.equal(brief.tideDatum, known ? 'MLLW' : null);
      const tide = brief.tiles.find(tile => tile.id === 'tide');
      assert.equal(tide.value, known ? 3.3 : null);
      assert.equal(tide.display.datum, known ? 'MLLW' : undefined);
    });
  }
});

test('the sparkline does not chart heights without a datum, even with enough curve points', () => {
  const day = {tides: GOLDEN.slice(0, 2), tideEvents: [], sunrise: null, sunset: null};
  const chart = tideDatum => sparkArgs({...day, tideDatum}, day.tides[0].at, montereyPlace.timezone);
  assert.equal(chart(null), null);
  assert.equal(chart('MLLW')[0][0].unit, 'ft MLLW');
});
