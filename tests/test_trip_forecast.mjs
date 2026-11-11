// SC2252-05: the regional forecast at each stop's arrival hour in the trip plan. The adapter is checked on synthetic /api/forecast feeds
// (values invented, differing by hour and by model), then the real Planner page: the one shared read, its request count, a failed read
// said once, and that no export carries a forecast. The reader is the mark card's own (web/brief/mark-forecast.ts).
import './helpers/spanish-ready.mjs';   // the Spanish table, before the Spanish renders
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from '@playwright/test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {parseConditionsForecast} = await import('../web/conditions.ts');
const {markForecast, runText} = await import('../web/brief/mark-forecast.ts');
const {tripStopForecast} = await import('../web/trip-forecast.ts');

const LA = 'America/Los_Angeles', H = 3_600_000, ROOT = new URL('..', import.meta.url).pathname;
const NOW = Date.parse('2026-11-10T14:30:00Z'), T0 = Date.parse('2026-11-10T06:00:00Z') / 1000;
const POINTS = [['north', 35.45, -121.02], ['central', 35.36, -120.94], ['south', 35.24, -120.94], ['avila', 35.1, -120.82]];
const CENTER = [35.34, -120.965], REGION = 'morro-bay';
const UNITS = {wind_speed_10m: 'kn', wind_gusts_10m: 'kn', wind_direction_10m: '°', wave_height: 'ft', wave_period: 's', wave_direction: '°'};
/** Words that would read a forecast as a go/no-go call, a score or a ranking. */
const VERDICT = /\b(?:safe|unsafe|go\b|no-go|good to go|fishable|favou?rable|recommended|best|score|rank\w*)\b/i;

/** One point's series, hourly (or every `step` hours) from T0 for 72 hours, values from `fn(hour)`; `hole` hours of `holeVar` are null. */
function series(fn, {step = 1, hole = [], holeVar = null} = {}) {
  const hours = Array.from({length: Math.ceil(72 / step)}, (_, k) => k * step), time = hours.map(h => T0 + h * 3600), keys = Object.keys(fn(0));
  return {latitude: 35, longitude: -121, utc_offset_seconds: 0, hourly_units: {time: 'unixtime', ...Object.fromEntries(keys.map(k => [k, UNITS[k]]))},
    hourly: {time, ...Object.fromEntries(keys.map(k => [k, hours.map(h => k === holeVar && hole.includes(h) ? null : fn(h)[k])]))}};
}
// Values differ by hour and by family: NOAA wind 10 + hour, ECMWF wind 20 + hour; seas 2 + hour/2 (NOAA) and 3 + hour/2 (ECMWF).
const wind = (base, frac) => h => ({wind_speed_10m: base + h + frac, wind_gusts_10m: base + 6 + h + frac, wind_direction_10m: 300});
const wave = (base, period) => h => ({wave_height: base + h / 2, wave_period: period, wave_direction: 290});
function feed({runAgeH = 4, retrievedAgeH = 0.3, frac = 0, step = 1, windHole = null, gustLow = false} = {}) {
  const meta = {last_run_initialisation_time: NOW / 1000 - runAgeH * 3600, data_end_time: T0 + 71 * 3600};
  const model = (fn, opts) => ({meta, data: POINTS.map(() => series(fn, {step, ...opts}))});
  const gfsWind = gustLow ? h => ({...wind(10, frac)(h), wind_gusts_10m: 5}) : wind(10, frac);
  return {region_id: REGION, retrieved: NOW - retrievedAgeH * H, requested_points: POINTS, models: {
    gfs_global: model(gfsWind, windHole ? {hole: windHole, holeVar: 'wind_speed_10m'} : {}), ncep_gfswave016: model(wave(2, 11)),
    ecmwf_ifs025: model(wind(20, frac)), ecmwf_wam: model(wave(3, 9))}};
}
const forecastOf = f => parseConditionsForecast(f, REGION, CENTER);
const stopList = [{id: 'a', lat: 35.1, lon: -121}, {id: 'b', lat: 35.2, lon: -120.9}, {id: 'c', lat: 35.1, lon: -121}];
const ready = arrivals => ({state: 'ready', departAt: 0, sunsetAt: null, firstOccurrence: false, backAt: 0, backAfterSunset: false,
  stops: Object.entries(arrivals).map(([id, arriveAt]) => ({id, arriveAt, leaveAt: arriveAt, arriveAfterSunset: false, leaveAfterSunset: false}))});
const at = (hour, minute = 0) => T0 * 1000 + hour * H + minute * 60_000;
const run = (input = {}) => tripStopForecast({forecast: forecastOf(feed()), region: REGION, stops: stopList, times: ready({a: at(11), b: at(14, 20), c: at(17)}),
  now: NOW, zone: LA, language: 'en', ownLimits: null, ...input});

test('values_at_arrival: each stop reads its own arrival hour from both families, joined by id, at the one regional point, with its runs', () => {
  const f = forecastOf(feed()), result = run();
  assert.equal(result.point, f.point.id);
  const issued = runText(NOW - 4 * H, LA);
  // stop a arrives on a listed hour; NOAA 10 + 11, ECMWF 20 + 11; seas 2 + 5.5 and 3 + 5.5
  const a = result.stops.get('a').line;
  assert.ok(a.startsWith('Forecast at arrival · NOAA: wind 21 kt, gusts 27 kt (run ' + issued + '); seas 7.5 ft, 11 s (run ' + issued + ') | ECMWF: wind 31 kt, gusts 37 kt'), a);
  assert.ok(a.includes('seas 8.5 ft, 9 s'), a);
  assert.ok(!a.includes('valid '), 'an arrival on a listed hour names no other hour');
  // stop b arrives 20 minutes after hour 14: the listed hour read is named
  const b = result.stops.get('b').line;
  assert.ok(b.includes('wind 24 kt, gusts 30 kt (valid ') && b.includes('wind 34 kt'), b);
  assert.match(b, /seas 9.0 ft, 11 s/);
  // stop c, at its own hour, reads that hour's numbers
  assert.ok(result.stops.get('c').line.includes('wind 27 kt'), result.stops.get('c').line);
  // the same hour at two different places reads the same regional point's numbers
  const same = run({times: ready({a: at(11), b: at(11), c: at(11)})});
  assert.equal(same.stops.get('a').line, same.stops.get('b').line);
  // joined by id, not position or name: reordering the stops or an unknown id in the times changes nothing
  const reordered = run({stops: [...stopList].reverse(), times: ready({zzz: at(2), c: at(17), a: at(11), b: at(14, 20)})});
  for (const id of ['a', 'b', 'c']) assert.equal(reordered.stops.get(id).line, result.stops.get(id).line, id);
  assert.equal(reordered.stops.has('zzz'), false);
  assert.equal(run({times: ready({a: at(11)})}).stops.has('b'), false, 'a stop with no arrival has no line');
  // the cells are the mark card's own rows at that hour (same reader, same models, same runs)
  const card = markForecast(f, REGION, stopList[0], at(11), NOW, LA, 'en');
  assert.equal(card.families[0].rows[0].sampled.windKn, 21);
  assert.equal(result.stops.get('a').families[1].wind.sampled.windKn, 31);
  for (const s of result.stops.values()) assert.doesNotMatch(s.line, VERDICT);
  // nothing without ready times, this region's feed, or a feed at all
  assert.equal(run({times: {state: 'unavailable', reasons: ['no-port']}}), null);
  assert.equal(run({forecast: null}), null);
  assert.equal(run({region: 'monterey-bay'}), null, 'another region\'s feed is no answer');
});

test('outside_hours_and_missing_samples: no forecast for that hour instead of a value; other gaps keep their own reason; siblings survive', () => {
  const outside = run({times: ready({a: at(-2), b: at(80), c: at(71)})});
  for (const id of ['a', 'b']) {
    const line = outside.stops.get(id).line;
    assert.equal((line.match(/no forecast for that hour/g) || []).length, 4, line);
    assert.doesNotMatch(line, /\d+ kt|\d ft/);
    assert.deepEqual(outside.stops.get(id).families.map(fam => [fam.wind.state, fam.seas.state]), [['no-hour', 'no-hour'], ['no-hour', 'no-hour']]);
  }
  assert.match(outside.stops.get('c').line, /wind 81 kt/, 'the last listed hour is read, not refused');
  // no listed hour within 90 minutes of the arrival (a 6-hourly feed)
  const sparse = run({forecast: forecastOf(feed({step: 6})), times: ready({a: at(9), b: at(12), c: at(14)})});
  assert.match(sparse.stops.get('a').line, /no forecast for that hour/);
  assert.match(sparse.stops.get('b').line, /wind 22 kt/);
  assert.match(sparse.stops.get('c').line, /no forecast for that hour/, 'two hours from a listed hour');
  // a run past its age limit is a different reason, never "no forecast for that hour"
  const old = run({forecast: forecastOf(feed({runAgeH: 40}))}).stops.get('a').line;
  assert.match(old, /past its 36-hour age limit/);
  assert.doesNotMatch(old, /no forecast for that hour/);
  assert.match(run({forecast: forecastOf(feed({retrievedAgeH: 8}))}).stops.get('a').line, /retrieved more than 6 hours ago/);
  // one field hole: that value says so; the other family and the seas stay
  const hole = run({forecast: forecastOf(feed({windHole: [11]}))}).stops.get('a');
  assert.deepEqual([hole.families[0].wind.state, hole.families[0].seas.state, hole.families[1].wind.state], ['gap', 'value', 'value']);
  assert.match(hole.line, /NOAA: wind not available: the NOAA GFS sample has no wind value/);
  assert.match(hole.line, /seas 7.5 ft, 11 s/);
  // a gust below the sustained wind is left out, as on the card
  const low = run({forecast: forecastOf(feed({gustLow: true}))}).stops.get('a');
  assert.equal(low.families[0].wind.sampled.gustKn, null);
  assert.match(low.line, /NOAA: wind 21 kt \(/);
});

test('own_limits_exact: strictly over, unrounded, per value and per family, in the brief\'s words; none without own limits', () => {
  const limits = {wind: 10, gust: 16, seas: 2};
  // hour 0: NOAA wind 10.4 (shows 10 kt), gust 16.4, seas 2; ECMWF 20.4 / 26.4 / 3
  const fraction = forecastOf(feed({frac: 0.4})), over = run({forecast: fraction, times: ready({a: at(0)}), ownLimits: limits}).stops.get('a');
  assert.match(over.line, /NOAA: wind 10 kt, gusts 16 kt/, 'the displayed numbers are rounded');
  assert.deepEqual(over.families[0].over, ['wind over your 10 kt', 'gusts over your 16 kt']);
  assert.deepEqual(over.families[1].over, ['wind over your 10 kt', 'gusts over your 16 kt', 'seas over your 2 ft']);
  assert.ok(over.line.includes('· wind over your 10 kt, gusts over your 16 kt (your limits) |'), over.line);
  assert.ok(over.line.endsWith('· wind over your 10 kt, gusts over your 16 kt, seas over your 2 ft (your limits)'), over.line);
  // equality is not over, and the families are independent
  const exact = run({forecast: forecastOf(feed()), times: ready({a: at(0)}), ownLimits: {wind: 10, gust: 16, seas: 2}}).stops.get('a');
  assert.deepEqual(exact.families[0].over, []);
  assert.deepEqual(exact.families[1].over, ['wind over your 10 kt', 'gusts over your 16 kt', 'seas over your 2 ft']);
  assert.doesNotMatch(exact.families[0].over.join(), /your/);
  const mixed = run({forecast: fraction, times: ready({a: at(0)}), ownLimits: {wind: 15, gust: 30, seas: 2.5}}).stops.get('a');
  assert.deepEqual([mixed.families[0].over, mixed.families[1].over], [[], ['wind over your 15 kt', 'seas over your 2.5 ft']]);
  // no own limits (a profile on its defaults), or a gap, no marker; a looser own limit still marks what it is over
  const none = run({forecast: fraction, times: ready({a: at(0)}), ownLimits: null}).stops.get('a');
  assert.doesNotMatch(none.line, /your limits|over your/);
  assert.doesNotMatch(run({times: ready({a: at(-2)}), ownLimits: limits}).stops.get('a').line, /your limits/);
  assert.deepEqual(run({forecast: fraction, times: ready({a: at(0)}), ownLimits: {wind: 40, gust: 50, seas: 9}}).stops.get('a').families.map(f => f.over), [[], []]);
  assert.deepEqual(run({forecast: fraction, times: ready({a: at(0)}), ownLimits: {wind: 20.3, gust: 99, seas: 99}}).stops.get('a').families.map(f => f.over), [[], ['wind over your 20.3 kt']]);
  // the same words in Spanish; a language change recomputes from the same numbers
  const es = run({forecast: fraction, times: ready({a: at(0)}), ownLimits: limits, language: 'es'}).stops.get('a');
  assert.match(es.line, /^Pronóstico a la llegada · NOAA: viento 10 kt, ráfagas de 16 kt/);
  assert.match(es.line, /viento por encima de tu límite de 10 kt, ráfagas por encima de tu límite de 16 kt \(tus límites\)/);
  assert.match(run({times: ready({a: at(-2)}), language: 'es'}).stops.get('a').line, /sin pronóstico para esa hora/);
  assert.doesNotMatch(over.line, VERDICT);
});

const needsChromium = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed'};
const entry = `
  export {Planner, arrivalRead, readArrivalForecast, resetArrivalRead} from './web/app/Planner.tsx';
  export {createPlanner} from './web/planner.ts';
  export {cruiseSpeed, savedLimits} from './web/limits.ts';
  export {regionInfo} from './web/app/region-info.ts';
  export {ensureRegionalForecast, regionalForecast} from './web/brief/Brief.tsx';
  export {buildExport} from './dist/trip-export.js';
  export {render as renderString} from 'preact-render-to-string'; export {render, h} from 'preact';`;
const targets = [1, 2, 3, 4, 5, 6].map(n => ({id: String(n), label: `Stop ${n}`, latitude: 35 + n * 0.01, longitude: -121, neighborhood_depth_ft: [90, 110]}));
const INFO = {id: REGION, name: 'Morro Bay', center: CENTER, timezone: LA};
const deps = (store = new Map()) => ({atlas: {targets, areas: []}, screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true},
  region: {id: REGION, timezone: LA, mpa: {bounds: [-180, -90, 180, 90]}}, storage: {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }, removeItem: k => { store.delete(k); }},
  emit() {}, map: {getSize: () => ({x: 1}), getBounds: () => ({getWest: () => -180, getSouth: () => -90, getEast: () => 180, getNorth: () => 90})},
  getVisible: () => [], nav: {open() {}, showMap() {}, conditions() {}}, loadPorts: async () => ({ports: []})});
/** A plan of six stops from a home port at 20 kt, leaving 07:00 on 2026-11-10. */
async function sixStopPlan(m, store) {
  const model = m.createPlanner(deps(store));
  await new Promise(resolve => setTimeout(resolve, 0));
  model.setResearch(true);
  for (const t of targets) model.toggleSpot(t.id, true);
  model.edit({date: '2026-11-10'});
  model.ports.value = [{id: 'home', name: 'Home', match: [35, -121]}]; model.setFilter('port', 'home');
  m.cruiseSpeed.value = 20; m.regionInfo.value = INFO;
  return model;
}
/** A /api/forecast stub that answers when the test says: the forecast calls so far, each with its resolve. Anything else the page asks for is a 404. */
function deferredFetch() {
  const calls = [];
  const fetchFn = url => /\/api\/forecast\?/.test(String(url)) ? new Promise(resolve => calls.push({url: String(url), resolve})) : Promise.resolve(new Response('', {status: 404}));
  return {calls, fetchFn, ok: (i, body = feed()) => calls[i].resolve(new Response(JSON.stringify(body), {status: 200})), refuse: i => calls[i].resolve(new Response('', {status: 503}))};
}
const tick = () => new Promise(resolve => setTimeout(resolve, 20));
const count = (text, re) => (text.match(re) || []).length;

test('six_stops_one_request, failed_once and stale completion: the plan shares the mark card\'s one read; a failure is said once', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-forecast-')), out = join(dir, 'ui.mjs');
  const saved = {fetch: globalThis.fetch, location: globalThis.location};
  try {
    await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: entry}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
      jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href), net = deferredFetch();
    globalThis.fetch = net.fetchFn; globalThis.location = {href: 'https://skippercast.test/map'};
    const model = await sixStopPlan(m, new Map());
    try {
      const html = () => m.renderString(m.h(m.Planner, {model, open: true, now: () => NOW})).replace(/\s/g, ' ');
      // cold: the mark card asks, the plan joins the same pending request
      const card = m.ensureRegionalForecast(INFO.id, INFO.center);
      m.readArrivalForecast(INFO.id, INFO.center);
      assert.equal(net.calls.length, 1);
      assert.match(net.calls[0].url, /\/api\/forecast\?region=morro-bay$/);
      let markup = html();
      assert.match(markup, /Reading the regional forecast/);
      assert.doesNotMatch(markup, /could not be read|data-stop-forecast/, 'a pending read is never a failure');
      net.ok(0); await card; await tick();
      assert.equal(m.arrivalRead.value.status, 'done');
      markup = html();
      assert.equal(count(markup, /data-stop-forecast=/g), 6, 'one line per stop');
      assert.equal(count(markup, /Forecast at arrival · NOAA: wind \d+ kt/g), 6);
      assert.match(markup, /Regional model values at forecast point central, not readings at these stops\./);
      assert.match(markup, /Sea state, the bar and fuel are not included in run-time estimates\./);
      assert.doesNotMatch(markup, /conditions at each stop are not included/);
      // arrival hour: stop 1 arrives 7:05 AM PST = 15:05Z = hour 9; NOAA wind 19 kt
      assert.match(markup, /data-stop-forecast="1">Forecast at arrival · NOAA: wind 19 kt, gusts 25 kt/);
      assert.doesNotMatch([...markup.matchAll(/data-stop-forecast="\d">([^<]*)</g)].map(x => x[1]).join(' ') + markup.match(/id="export-forecast-basis">([^<]*)</)[1], VERDICT);
      // six stops, any number of redraws, edits, reorders and repeated asks: still the one GET
      for (let i = 0; i < 3; i++) html();
      model.editTiming({leavePortAt: '08:30', fishMin: 30}); html();
      model.moveStop('3', 'up'); html();
      m.readArrivalForecast(INFO.id, INFO.center); m.readArrivalForecast(INFO.id, INFO.center);
      assert.equal(net.calls.length, 1, 'six stops, one request');
      // close and open again with the cache warm: no further request
      m.resetArrivalRead(); m.readArrivalForecast(INFO.id, INFO.center); await tick();
      assert.equal(net.calls.length, 1, 'warm cache, zero requests');
      assert.equal(m.arrivalRead.value.status, 'done');
      // own limits mark a value in the brief's words and change nothing else; none on defaults
      assert.doesNotMatch(html(), /your limits/);
      m.savedLimits.value = {boat: {wind: 5, gust: 8, seas: 1}};
      assert.match(html(), /wind over your 5 kt, gusts over your 8 kt, seas over your 1 ft \(your limits\)/);
      m.savedLimits.value = {};
      // nothing about a forecast reaches a file, the alert preview or the saved plan
      const request = {atlas: model.tripAtlas.value, screen: deps().screen, ids: model.draft.value.ids, allowResearch: true, region: model.region, now: new Date('2026-11-01T00:00:00Z')};
      assert.doesNotMatch(m.buildExport(request).gpx, /[Ff]orecast|model values|run Nov/);
      const preview = JSON.stringify(model.alertPreview(() => ({legs: [], totalNm: 0, totalRunMin: null, skipped: []})));
      assert.doesNotMatch(preview + JSON.stringify(model.draft.value), /[Ff]orecast|model values|run Nov|sampled/);

      // a failed read, said once for the plan: no feed, the one read refused
      m.regionalForecast.value = null; m.resetArrivalRead();
      m.readArrivalForecast(INFO.id, [36, -121]);
      assert.equal(net.calls.length, 2);
      markup = html(); assert.match(markup, /Reading the regional forecast/); assert.doesNotMatch(markup, /could not be read/);
      m.resetArrivalRead(); net.ok(1);  // closed before it answered: the late answer is ignored
      await tick();
      assert.equal(m.arrivalRead.value, null, 'a completion after close is ignored');
      m.regionalForecast.value = null;
      m.readArrivalForecast(INFO.id, [36.5, -121]);
      assert.equal(net.calls.length, 3);
      net.refuse(2); await tick();
      assert.equal(m.arrivalRead.value.status, 'failed');
      markup = html();
      assert.equal(count(markup, /The forecast could not be read\./g), 1, 'once for the plan, not once per stop');
      assert.doesNotMatch(markup, /data-stop-forecast=/);
      assert.equal(count(markup, /data-stop-id=/g), 6, 'the stops are still listed');
      assert.match(markup, /arrive about/, 'the arrival times are unchanged by a failed read');
      // redraws, edits, reorders and limit or language changes do not retry it
      for (let i = 0; i < 3; i++) html();
      model.editTiming({leavePortAt: '09:00', fishMin: 30}); model.moveStop('2', 'down');
      m.savedLimits.value = {boat: {wind: 5, gust: 8, seas: 1}}; html(); m.savedLimits.value = {};
      m.readArrivalForecast(INFO.id, [36.5, -121]);
      assert.equal(net.calls.length, 3, 'a failed read is not retried by a redraw');
      // reopening asks again, and a good answer brings the lines back
      m.resetArrivalRead(); m.readArrivalForecast(INFO.id, [36.5, -121]);
      assert.equal(net.calls.length, 4);
      net.ok(3); await tick();
      assert.equal(count(html(), /data-stop-forecast=/g), 6);
    } finally { model.dispose(); }
  } finally { globalThis.fetch = saved.fetch; globalThis.location = saved.location; await rm(dir, {recursive: true, force: true}); }
});

test('the mounted plan reads once when it opens: not per stop, redraw, edit or reorder; a failure shows once and reopening retries', needsChromium, async () => {
  const bundle = await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: entry}, bundle: true, write: false, platform: 'browser', format: 'iife', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
    globalName: 'M', logLevel: 'silent', loader: {'.css': 'empty'}});
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
    await page.goto('https://skippercast.test/map');
    await page.addScriptTag({content: bundle.outputFiles[0].text});
    await page.evaluate(({targets, info, now, bodyOk}) => {
      const M = window.M;
      window.__calls = []; window.__resolve = [];
      window.fetch = url => /\/api\/forecast\?/.test(String(url)) ? new Promise(resolve => { window.__calls.push(String(url)); window.__resolve.push(resolve); }) : Promise.resolve(new Response('', {status: 404}));
      const model = window.model = M.createPlanner({atlas: {targets, areas: []}, screen: {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true},
        region: {id: info.id, timezone: info.timezone, mpa: {bounds: [-180, -90, 180, 90]}}, storage: null, emit() {},
        map: {getSize: () => ({x: 1}), getBounds: () => ({getWest: () => -180, getSouth: () => -90, getEast: () => 180, getNorth: () => 90})},
        getVisible: () => [], nav: {open() {}, showMap() {}, conditions() {}}, loadPorts: async () => ({ports: []})});
      window.mount = open => M.render(M.h(M.Planner, {model, open, now: () => now}), document.getElementById('root'));
      window.answer = (i, status) => window.__resolve[i](new Response(status === 200 ? bodyOk : '', {status}));
    }, {targets, info: INFO, now: NOW, bodyOk: JSON.stringify(feed())});
    await page.evaluate(async ({info}) => {
      const M = window.M, model = window.model;
      await new Promise(r => setTimeout(r, 0));
      model.setResearch(true);
      for (const id of ['1', '2', '3', '4', '5', '6']) model.toggleSpot(id, true);
      model.edit({date: '2026-11-10'});
      model.ports.value = [{id: 'home', name: 'Home', match: [35, -121]}]; model.setFilter('port', 'home');
      M.cruiseSpeed.value = 20; M.regionInfo.value = info;
      window.mount(true);
    }, {info: INFO});
    const calls = () => page.evaluate(() => window.__calls.length), text = () => page.evaluate(() => document.getElementById('root').textContent);
    await page.waitForFunction(() => window.__calls.length >= 1);
    assert.equal(await calls(), 1, 'opening the plan: one request for six stops');
    await page.evaluate(() => { window.mount(true); window.model.editTiming({leavePortAt: '08:00', fishMin: 20}); window.model.moveStop('2', 'up'); window.mount(true); });
    await page.evaluate(() => new Promise(r => setTimeout(r, 50)));
    assert.equal(await calls(), 1, 'edits, reorders and redraws ask nothing');
    assert.match(await text(), /Reading the regional forecast/);
    await page.evaluate(() => window.answer(0, 200));
    await page.waitForFunction(() => document.querySelectorAll('[data-stop-forecast]').length === 6);
    await page.evaluate(() => { window.mount(false); window.mount(true); });
    await page.evaluate(() => new Promise(r => setTimeout(r, 50)));
    assert.equal(await calls(), 1, 'reopened with the cache warm: no request');
    // a cold region key that fails: one notice, no retry until the plan is opened again
    await page.evaluate(() => { window.mount(false); window.M.regionalForecast.value = null; window.M.regionInfo.value = {...window.M.regionInfo.value, center: [36, -121]}; window.mount(true); });
    await page.waitForFunction(() => window.__calls.length === 2);
    await page.evaluate(() => window.answer(1, 503));
    await page.waitForFunction(() => document.getElementById('root').textContent.includes('The forecast could not be read.'));
    const failed = await text();
    assert.equal(count(failed, /The forecast could not be read\./g), 1);
    await page.evaluate(() => { window.model.editTiming({leavePortAt: '09:00', fishMin: 20}); window.mount(true); });
    await page.evaluate(() => new Promise(r => setTimeout(r, 50)));
    assert.equal(await calls(), 2, 'a failed read is not retried by an edit or a redraw');
    await page.evaluate(() => { window.mount(false); window.mount(true); });
    await page.waitForFunction(() => window.__calls.length === 3);
    await page.evaluate(() => window.model.dispose());
  } finally { await browser.close(); }
});
