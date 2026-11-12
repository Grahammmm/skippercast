// SC2252-04: clock times for the trip plan's stops and the return. The arithmetic is checked on its own (instants pinned as ISO strings),
// then the real Planner page: arrive/leave lines, the missing-input line, and that the timing stays in the browser draft only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {tripLegs} from '../web/trip-legs.ts';
import {clockText, parseTiming, sunsetAt, timingInputs, tripTimes} from '../web/trip-times.ts';

const LA = 'America/Los_Angeles', port = {name: 'Home', lat: 35, lon: -121};
const stops = [1, 2, 3].map(n => ({id: String(n), name: `Stop ${n}`, lat: 35 + n * 0.01, lon: -121}));
const iso = ms => new Date(ms).toISOString();
const MIN = 60000;
/** A route with chosen run minutes per leg, for exact arithmetic. */
const fakeRoute = runs => ({legs: runs.map((runMin, i) => ({from: `a${i}`, to: `b${i}`, nm: 1, runMin, basis: 'straight', screen: null})), totalNm: runs.length, totalRunMin: runs.reduce((a, b) => a + b, 0), skipped: []});
const input = (over = {}) => ({date: '2026-11-10', zone: LA, timing: {leavePortAt: '07:00', fishMin: 60}, port, stops: stops.map(s => ({id: s.id, fishing: true})), route: tripLegs(port, stops, 20), ...over});
const ready = r => { assert.equal(r.state, 'ready', JSON.stringify(r)); return r; };
const reasons = r => { assert.equal(r.state, 'unavailable'); return r.reasons; };

test('normal_and_single_stop_sums: the legs\' own run minutes plus the minutes fishing, stop by stop', () => {
  const route = tripLegs(port, stops, 20), r = ready(tripTimes(input({route})));
  const depart = Date.parse('2026-11-10T07:00:00-08:00');
  assert.equal(r.departAt, depart);
  let at = depart;
  route.legs.slice(0, 3).forEach((leg, i) => { at += leg.runMin * MIN; assert.equal(r.stops[i].arriveAt, at); at += 60 * MIN; assert.equal(r.stops[i].leaveAt, at); });
  assert.equal(r.backAt, at + route.legs[3].runMin * MIN);
  assert.equal(r.backAt - depart, (route.totalRunMin + 180) * MIN, 'sum of rounded legs, not a re-rounded total');
  assert.deepEqual(r.stops.map(s => s.id), ['1', '2', '3']);
  // zero and the 600 minute ends of the fishing range
  assert.equal(ready(tripTimes(input({route, timing: {leavePortAt: '07:00', fishMin: 0}}))).backAt - depart, route.totalRunMin * MIN);
  assert.equal(ready(tripTimes(input({route, timing: {leavePortAt: '07:00', fishMin: 600}}))).backAt - depart, (route.totalRunMin + 1800) * MIN);
  // one stop: port -> stop -> port, one dwell
  const one = tripLegs(port, stops.slice(0, 1), 20), s = ready(tripTimes(input({route: one, stops: [{id: '1', fishing: true}]})));
  assert.equal(one.legs.length, 2);
  assert.equal(s.backAt - depart, (one.totalRunMin + 60) * MIN);
  // the launch tail (fishing: false) is reached and left at the same instant
  const tail = ready(tripTimes(input({route: fakeRoute([10, 20, 30]), stops: [{id: 'a', fishing: true}, {id: 'user:launch-x', fishing: false}]})));
  assert.equal(tail.stops[1].arriveAt, tail.stops[1].leaveAt);
  assert.equal(tail.backAt - depart, (10 + 60 + 20 + 30) * MIN);
});

test('sunset_uses_plan_date_port: marks are against sunset on the plan date at the port, strictly later', () => {
  const nov = sunsetAt('2026-11-10', LA, 35, -121), jun = sunsetAt('2026-06-21', LA, 35, -121), north = sunsetAt('2026-11-10', LA, 45, -121);
  assert.ok(nov !== null && jun !== null && north !== null);
  assert.ok(jun - Date.parse('2026-06-21T00:00:00-07:00') > nov - Date.parse('2026-11-10T00:00:00-08:00'), 'June sunset is later in the day than November');
  assert.notEqual(north - nov, 0, 'a different port gives a different sunset');
  const depart = Date.parse('2026-11-10T07:00:00-08:00'), m = Math.floor((nov - depart) / MIN);
  const at = runMin => ready(tripTimes(input({route: fakeRoute([runMin, 5]), stops: [{id: 'a', fishing: true}], timing: {leavePortAt: '07:00', fishMin: 0}})));
  assert.equal(at(m).stops[0].arriveAfterSunset, false, 'not after at the minute before sunset');
  assert.equal(at(m + 1).stops[0].arriveAfterSunset, true, 'after one minute later');
  assert.equal(at(m).backAfterSunset, true, 'the return five minutes on is after');
  // dinner-time departure: dark in November, light in June
  const evening = date => ready(tripTimes(input({date, timing: {leavePortAt: '19:30', fishMin: 0}, route: fakeRoute([5, 5]), stops: [{id: 'a', fishing: true}]})));
  assert.equal(evening('2026-11-10').stops[0].arriveAfterSunset, true);
  assert.equal(evening('2026-06-21').stops[0].arriveAfterSunset, false);
  assert.equal(evening('2026-11-10').sunsetAt, nov);
  assert.equal(sunsetAt('2026-02-30', LA, 35, -121), null, 'an impossible date yields no sunset');
  assert.equal(sunsetAt('2026-11-10', LA, NaN, -121), null, 'a nonfinite port yields no sunset');
});

test('overnight_and_multiday: midnight, next day, later dates, the zone not the device', () => {
  const run = runs => ready(tripTimes(input({route: fakeRoute(runs), stops: [{id: 'a', fishing: true}], timing: {leavePortAt: '23:00', fishMin: 0}})));
  assert.equal(iso(run([60, 5]).stops[0].arriveAt), '2026-11-11T08:00:00.000Z', '23:00 PST + 60 min = midnight PST');
  assert.equal(clockText(run([60, 5]).stops[0].arriveAt, LA, '2026-11-10', 'en', 'next day').includes('next day'), true);
  assert.equal(clockText(run([30, 5]).stops[0].arriveAt, LA, '2026-11-10', 'en', 'next day').includes('next day'), false, '23:30 is still the plan day');
  const far = run([3000, 5]);
  assert.match(clockText(far.stops[0].arriveAt, LA, '2026-11-10', 'en', 'next day'), /\(2026-11-13\)/);
  assert.match(clockText(Date.parse('2026-11-10T07:05:00-08:00'), LA, '2026-11-10', 'en', 'next day').replace(/\s/g, ' '), /^7:05 AM PST$/);
  assert.match(clockText(Date.parse('2026-11-10T07:05:00-08:00'), 'Asia/Tokyo', '2026-11-10', 'en', 'next day'), /\(next day\)/, 'the zone argument decides the date, not the host');
});

test('dst_spring_elapsed and dst_fall_elapsed: elapsed time across the change, pinned instants', () => {
  const one = date => ({date, timing: {leavePortAt: '01:00', fishMin: 0}, route: fakeRoute([90, 30]), stops: [{id: 'a', fishing: true}]});
  const spring = ready(tripTimes(input(one('2026-03-08'))));
  assert.equal(iso(spring.departAt), '2026-03-08T09:00:00.000Z');
  assert.equal(iso(spring.stops[0].arriveAt), '2026-03-08T10:30:00.000Z', '01:00 PST + 90 min is 03:30 PDT');
  assert.equal(clockText(spring.stops[0].arriveAt, LA, '2026-03-08', 'en', 'next day').replace(/\s/g, ' '), '3:30 AM PDT');
  assert.equal(iso(spring.backAt), '2026-03-08T11:00:00.000Z');
  const fall = ready(tripTimes(input(one('2026-11-01'))));
  assert.equal(iso(fall.departAt), '2026-11-01T08:00:00.000Z', '01:00 is the first (PDT) one');
  assert.equal(fall.firstOccurrence, true);
  assert.equal(iso(fall.stops[0].arriveAt), '2026-11-01T09:30:00.000Z', '01:00 PDT + 90 min is 01:30 PST');
  assert.equal(clockText(fall.stops[0].arriveAt, LA, '2026-11-01', 'en', 'next day').replace(/\s/g, ' '), '1:30 AM PST');
  // a whole day across the spring change: dwell is elapsed time too
  const day = ready(tripTimes(input({date: '2026-03-08', timing: {leavePortAt: '00:30', fishMin: 600}, route: fakeRoute([60, 60]), stops: [{id: 'a', fishing: true}]})));
  assert.equal(day.backAt - day.departAt, 720 * MIN);
  assert.equal(iso(day.backAt), '2026-03-08T20:30:00.000Z', '00:30 PST + 12 h is 13:30 PDT');
  // the missing hour refuses, the repeated one takes the first occurrence
  assert.deepEqual(reasons(tripTimes(input({...one('2026-03-08'), timing: {leavePortAt: '02:30', fishMin: 0}}))), ['invalid-departure']);
  assert.equal(iso(ready(tripTimes(input({...one('2026-11-01'), timing: {leavePortAt: '01:30', fishMin: 0}}))).departAt), '2026-11-01T08:30:00.000Z');
  assert.equal(ready(tripTimes(input({...one('2026-11-02'), timing: {leavePortAt: '01:30', fishMin: 0}}))).firstOccurrence, false);
});

test('missing_inputs_and_bad_chain: nothing partial, nothing NaN', () => {
  assert.deepEqual(reasons(tripTimes(input({route: tripLegs(port, stops, null)}))), ['no-speed']);
  assert.deepEqual(reasons(tripTimes(input({port: null, route: tripLegs(null, stops, 20)}))), ['no-port']);
  assert.deepEqual(reasons(tripTimes(input({port: null, route: tripLegs(null, stops, null)}))), ['no-port', 'no-speed']);
  assert.deepEqual(reasons(tripTimes(input({port: {lat: NaN, lon: -121}}))), ['no-port']);
  for (const speed of [0, NaN, -3]) assert.deepEqual(reasons(tripTimes(input({route: tripLegs(port, stops, speed)}))), ['no-speed']);
  assert.deepEqual(reasons(tripTimes(input({stops: []}))), ['no-stops']);
  assert.deepEqual(reasons(tripTimes(input({route: tripLegs(port, [...stops, {id: 'bad', name: 'Bad', lat: NaN, lon: 0}], 20), stops: [...stops, {id: 'bad', fishing: true}].map(s => ({id: s.id, fishing: true}))}))), ['invalid-route']);
  assert.deepEqual(reasons(tripTimes(input({route: fakeRoute([5, 5])}))), ['invalid-route'], 'legs must be stops + 1');
  const nulled = fakeRoute([5, 5, 5, 5]); nulled.legs[2].runMin = null;
  assert.deepEqual(reasons(tripTimes(input({route: nulled}))), ['invalid-route']);
  const infinite = fakeRoute([5, 5, 5, 5]); infinite.legs[1].runMin = Infinity;
  assert.deepEqual(reasons(tripTimes(input({route: infinite}))), ['invalid-route']);
  for (const date of ['2026-02-30', '', 'tomorrow', '2026-1-1']) assert.deepEqual(reasons(tripTimes(input({date}))), ['invalid-departure'], date);
  assert.deepEqual(reasons(tripTimes(input({zone: 'Mars/Base'}))), ['invalid-departure']);
  assert.deepEqual(reasons(tripTimes(input({timing: {leavePortAt: '7:00', fishMin: 60}}))), ['invalid-departure']);
  assert.deepEqual(reasons(tripTimes(input({timing: {leavePortAt: '07:00', fishMin: 601}}))), ['invalid-departure']);
  // duplicate ids count once, as tripLegs does
  const dupe = [...stops, {...stops[0], name: 'Again'}];
  assert.equal(ready(tripTimes(input({route: tripLegs(port, dupe, 20), stops: dupe.map(s => ({id: s.id, fishing: true}))}))).stops.length, 3);
});

test('timing inputs are strict: HH:mm and a whole number 0..600; stored junk falls back per field', () => {
  assert.deepEqual(parseTiming('06:45', '90'), {leavePortAt: '06:45', fishMin: 90});
  assert.deepEqual(parseTiming('06:45', 0), {leavePortAt: '06:45', fishMin: 0});
  for (const [time, fish] of [['', '60'], ['24:00', '60'], ['7:00', '60'], ['07:60', '60'], ['07:00', ''], ['07:00', '1.5'], ['07:00', '-1'], ['07:00', '601'], ['07:00', 'abc'], ['07:00', NaN]]) assert.equal(parseTiming(time, fish), null, `${time}/${fish}`);
  assert.deepEqual(timingInputs(undefined), {leavePortAt: '07:00', fishMin: 60});
  assert.deepEqual(timingInputs({leavePortAt: '25:00', fishMin: 45}), {leavePortAt: '07:00', fishMin: 45});
  assert.deepEqual(timingInputs({leavePortAt: '05:15', fishMin: 9999}), {leavePortAt: '05:15', fishMin: 60});
  assert.deepEqual(timingInputs('junk'), {leavePortAt: '07:00', fishMin: 60});
});

test('the real Planner page shows the times, hides them without speed or port, and keeps timing out of every export', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'trip-times-')), out = join(dir, 'ui.mjs');
  try {
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {Planner, timingTyped} from './web/app/Planner.tsx';
      export {createPlanner} from './web/planner.ts';
      export {cruiseSpeed} from './web/limits.ts';
      export {buildExport} from './dist/trip-export.js';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href);
    const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
    const targets = stops.map(p => ({id: p.id, label: p.name, latitude: p.lat, longitude: p.lon, neighborhood_depth_ft: [90, 110]}));
    const store = new Map(), storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }, removeItem: k => { store.delete(k); }};
    const deps = {atlas: {targets, areas: []}, screen, region: {id: 'test', timezone: LA, mpa: {bounds: [-180, -90, 180, 90]}}, storage, emit() {},
      map: {getSize: () => ({x: 1}), getBounds: () => ({getWest: () => -180, getSouth: () => -90, getEast: () => 180, getNorth: () => 90})},
      getVisible: () => [], nav: {open() {}, showMap() {}, conditions() {}}, loadPorts: async () => ({ports: []})};
    const model = m.createPlanner(deps);
    try {
      await new Promise(resolve => setTimeout(resolve, 0));
      model.setResearch(true);
      for (const id of ['1', '2', '3']) model.toggleSpot(id, true);
      model.edit({date: '2026-11-10'});
      const html = () => m.render(m.h(m.Planner, {model, open: false})).replace(/\s/g, ' ');
      m.cruiseSpeed.value = null;
      assert.match(html(), /Clock times are not shown: no home port is chosen, no cruise speed is saved\./);
      assert.doesNotMatch(html(), /arrive about/);
      model.ports.value = [{id: 'home', name: 'Home', match: [port.lat, port.lon]}]; model.setFilter('port', 'home');
      assert.match(html(), /Clock times are not shown: no cruise speed is saved\./);
      m.cruiseSpeed.value = 20;
      let markup = html();
      assert.match(markup, /id="export-leave-time"[^>]*value="07:00"/); assert.match(markup, /id="export-fish-min"[^>]*value="60"/);
      assert.match(markup, /arrive about 7:05 AM PST · leave 8:05 AM PST/); assert.match(markup, /arrive about 9:15 AM PST · leave 10:15 AM PST/);
      assert.match(markup, /Back at port about 10:25 AM PST/);
      assert.match(markup, /sea state, the bar and fuel are not included/);
      assert.doesNotMatch(markup, /after sunset/); assert.doesNotMatch(markup, /next day/);
      const request = {atlas: model.tripAtlas.value, screen, ids: model.draft.value.ids, allowResearch: true, region: model.region, now: new Date('2026-11-01T00:00:00Z')};
      const gpx = m.buildExport(request).gpx, alertBefore = JSON.stringify(model.alertPreview(() => ({legs: [], totalNm: 0, totalRunMin: null, skipped: []})));
      // edits: change the pair, drive the stops into the evening and past midnight
      assert.equal(model.editTiming({leavePortAt: '16:30', fishMin: 120}), true);
      markup = html();
      assert.match(markup, /arrive about 4:35 PM PST · leave 6:35 PM PST \(after sunset\)/);
      assert.match(markup, /arrive about 6:40 PM PST \(after sunset\) · leave 8:40 PM PST \(after sunset\)/);
      assert.match(markup, /Back at port about 10:55 PM PST \(after sunset\)/);
      model.editTiming({leavePortAt: '20:00', fishMin: 120});
      assert.match(html(), /Back at port about 2:25 AM PST \(next day\) \(after sunset\)/);
      // half-typed or out-of-range text: the reason shows and no (stale) time does
      m.timingTyped.value = {leave: '20:00', fish: '1.5'};
      markup = html();
      assert.match(markup, /id="export-times-invalid"[^>]*>Leave port at needs an hour and minute, and minutes fishing a whole number from 0 to 600\./);
      assert.doesNotMatch(markup, /arrive about|Back at port/); assert.match(markup, /id="export-fish-min"[^>]*value="1.5"/);
      m.timingTyped.value = null;
      assert.match(html(), /Back at port about 2:25 AM PST/);
      assert.equal(model.editTiming({fishMin: 601}), false, 'out of range is refused and not saved');
      assert.deepEqual(JSON.parse(store.get([...store.keys()][0])).timing, {leavePortAt: '20:00', fishMin: 120});
      // privacy: the file, the alert preview and the saved draft's export projection carry no timing
      assert.ok(m.buildExport(request).gpx === gpx, 'GPX bytes unchanged by timing edits');
      assert.ok(JSON.stringify(model.alertPreview(() => ({legs: [], totalNm: 0, totalRunMin: null, skipped: []}))) === alertBefore, 'alert preview unchanged');
      assert.doesNotMatch(gpx, /20:00|leavePortAt|fishMin/);
      // reopened from the browser draft: restored, malformed stored timing falls back
      const again = m.createPlanner(deps);
      assert.deepEqual(again.draft.value.timing, {leavePortAt: '20:00', fishMin: 120}); again.dispose();
      const key = [...store.keys()][0], saved = JSON.parse(store.get(key));
      store.set(key, JSON.stringify({...saved, timing: {leavePortAt: 'late', fishMin: -5}}));
      const bad = m.createPlanner(deps);
      assert.deepEqual(bad.draft.value.timing, {leavePortAt: '07:00', fishMin: 60}); bad.dispose();
      store.set(key, JSON.stringify((({timing, ...rest}) => rest)(saved)));
      const legacy = m.createPlanner(deps);
      assert.equal('timing' in legacy.draft.value, false, 'a legacy draft keeps its shape until timing is edited'); legacy.dispose();
    } finally { model.dispose(); }
  } finally { await rm(dir, {recursive: true, force: true}); }
});
