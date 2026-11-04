import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {entranceWindow} from '../packages/coast/src/entrance-window.ts';
import {barHours, entranceFor} from '../packages/coast/src/bar-conditions.ts';
const HOUR = 3600000, start = Date.parse('2026-10-12T14:00:00Z');
const entrance = entranceFor('morro-bay', 'morro-bay');
const opts = {entrance};
const iso = n => new Date(n).toISOString();
const hours = bands => bands.map((band, i) => ({at: iso(start + i * HOUR), band,
  tide: {stage: 'flood', midEbb: false, fraction: 0.5},
  swell: {heightFt: 1, periodS: 10, basis: 'offshore', longPeriodS: null}, windAgainst: false, reasons: []}));
const clear = 'No bar flag', bad = 'Hazardous';
const bounds = r => [r.departBy, r.returnBy, r.best, r.judged];

test('longest run, hazardous split, earlier tie and single-hour minimum', () => {
  for (const [bands, first, end] of [
    [[bad, clear, clear, bad, clear], 1, 3],
    [[clear, bad, clear, clear], 2, 4],
    [[clear, clear, bad, clear, clear], 0, 2],
    [[bad, clear, bad], 1, 2],
  ]) assert.deepEqual(bounds(entranceWindow(hours(bands), opts)), [start + first * HOUR, start + end * HOUR, start + first * HOUR, true]);
});
test('all hazardous and empty day never yield times', () => {
  const result = entranceWindow(hours([bad, bad]), opts);
  assert.deepEqual(bounds(result), [null, null, null, true]);
  assert.match(result.reason, /No window today/);
  assert.deepEqual(bounds(entranceWindow([], opts)), [null, null, null, false]);
});
test('caution is included and names the affected hour', () => {
  const result = entranceWindow(hours([clear, 'Caution', clear]), opts);
  assert.deepEqual(bounds(result), [start, start + 3 * HOUR, start, true]);
  assert.match(result.reason, /Caution hours/);
  assert.ok(result.reason.includes(iso(start + HOUR)));
});
test('missing relevant drivers refuse a window, but a missing hazardous driver does not', () => {
  for (const change of [h => {h.tide.stage = null;}, h => {h.swell.heightFt = null;},
    h => {h.swell.periodS = null;}, h => {h.swell.basis = null;}, h => {h.band = 'Unknown';}]) {
    const hs = hours([clear, clear]); change(hs[1]);
    assert.deepEqual(bounds(entranceWindow(hs, opts)), [null, null, null, false]);
    hs[1].band = bad;
    assert.equal(entranceWindow(hs, opts).judged, true);
  }
  const result = entranceWindow(hours([clear]), {entrance: {...entrance, seawardDeg: null}});
  assert.equal(result.judged, false);
  assert.match(result.reason, /wind against the ebb not judged/);
});
test('daylight clips both ends and excludes night-only runs', () => {
  const hs = hours([clear, clear, clear]);
  assert.deepEqual(bounds(entranceWindow(hs, {...opts, sunrise: start + HOUR / 2, sunset: start + 2.5 * HOUR})),
    [start + HOUR / 2, start + 2.5 * HOUR, start + HOUR / 2, true]);
  assert.equal(entranceWindow(hs, {...opts, sunrise: start + 4 * HOUR}).departBy, null);
  assert.equal(entranceWindow(hs, {...opts, sunset: start}).departBy, null);
  for (const extra of [{sunrise: NaN}, {sunset: Infinity}, {sunrise: start, sunset: start}])
    assert.throws(() => entranceWindow(hs, {...opts, ...extra}), /entrance-window: .*daylight/);
});
test('midnight and both DST transitions preserve elapsed hours', () => {
  for (const at of ['2026-10-12T23:00:00-07:00', '2026-11-01T01:00:00-07:00', '2027-03-14T01:00:00-08:00']) {
    const t = Date.parse(at), hs = hours([clear, clear, clear]).map((h, i) => ({...h, at: iso(t + i * HOUR)}));
    assert.deepEqual(bounds(entranceWindow(hs, opts)), [t, t + 3 * HOUR, t, true]);
  }
});
test('mid-ebb boundary uses upstream verdict unchanged', () => {
  const tideEvents = [{at: iso(start), type: 'H', heightFt: 4}, {at: iso(start + 4 * HOUR), type: 'L', heightFt: 0}];
  const hs = barHours({entrance, tideEvents, hours: [0, 1, 2, 3, 4].map(i => ({at: iso(start + i * HOUR), waveFt: 6, wavePeriodS: 10, windKnots: 0}))});
  assert.equal(hs[1].tide.midEbb, true);
  assert.equal(hs[1].band, bad);
  const before = JSON.stringify(hs);
  assert.deepEqual(bounds(entranceWindow(hs, opts)), [start, start + HOUR, start, true]);
  assert.equal(JSON.stringify(hs), before);
});
test('invalid, duplicated and out-of-order times throw named errors; gaps split runs', () => {
  const hs = hours([clear, clear]);
  for (const at of ['NaN', NaN, '2026-10-12T14:00:00'])
    assert.throws(() => entranceWindow([{...hs[0], at}], opts), /entrance-window: invalid hour time/);
  assert.throws(() => entranceWindow([hs[0], hs[0]], opts), /entrance-window: duplicate hour time/);
  assert.throws(() => entranceWindow(hs.toReversed(), opts), /entrance-window: out-of-order hour time/);
  assert.equal(entranceWindow([hs[0], {...hs[1], at: iso(start + 2 * HOUR)}], opts).returnBy, start + HOUR);
});
test('boat entrance line renders timing, no-window and not-judged distinctly', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'entrance-window-')), out = join(dir, 'view.mjs');
  try {
    await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
      export {EntranceLine, RunLine} from './web/brief/Run.tsx';
      export {profile} from './web/state.ts';
      export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
      bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
    const m = await import(pathToFileURL(out).href);
    const brief = hs => ({profile: 'boat', bar: {entrance, hours: hs}, sunrise: null, sunset: null, windows: [], alerts: [], tiles: [], missing: []});
    const line = hs => m.render(m.h(m.EntranceLine, {brief: brief(hs), tz: 'America/Los_Angeles'}));
    assert.match(line(hours([clear, clear])), /Morro Bay entrance: Leave by 7 am · be back by 9 am/);
    assert.match(line(hours([bad])), /No window today/);
    const unknown = hours([clear]); unknown[0].tide.stage = null;
    assert.match(line(unknown), /Entrance not judged/);
    for (const hs of [unknown, hours([bad])]) assert.doesNotMatch(line(hs), /Leave by|be back by/);
    assert.equal(m.render(m.h(m.EntranceLine, {brief: {bar: null}, tz: 'UTC'})), '');
    m.profile.value = 'boat';
    const ranking = {picks: [], harbor: 'Morro Bay'};
    assert.match(m.render(m.h(m.RunLine, {brief: brief(hours([clear])), ranking, now: new Date(start)})), /app-run-entrance/);
    m.profile.value = 'kayak';
    assert.equal(m.render(m.h(m.RunLine, {brief: brief(hours([clear])), ranking, now: new Date(start)})), '');
  } finally {await rm(dir, {recursive: true, force: true});}
});
