// Roadmap P2: the Boat brief's fishing time and return. The run model
// (web/brief/run.ts) over synthetic windows, the device-only cruise speed with
// no default (web/limits.ts), the place it runs to (web/brief/Run.tsx
// runPlace), and the line rendered to a string for each state: missing speed,
// missing window (stale forecast, alert, own limits), passed, no time, ok.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {planRun, runMinutes, noWindowReason, durationText} = await import('../web/brief/run.ts');
const {configureStore, STORAGE_KEYS} = await import('../web/state.ts');
const cruise = await import('../web/limits.ts');

const ROOT = new URL('..', import.meta.url).pathname;
const TZ = 'America/Los_Angeles';
/** 7 am to noon PDT on 2026-10-12: the owner's sunrise-to-noon morning, invented values. */
const WINDOW = {start: '2026-10-12T14:00:00.000Z', end: '2026-10-12T19:00:00.000Z', label: 'Lower wind & offshore seas', confidence: 'Low', reasons: [], wind: 8, gust: 12, wave: 3, period: 10};
const tile = (state = 'fresh') => ({id: 'wind', state});
const brief = (over = {}) => ({profile: 'boat', windows: [WINDOW], alerts: [], missing: [], tiles: [tile()], limits: {custom: false}, ...over});
const PLACE = {name: 'North reef', nm: 7.4};
const at = iso => new Date(iso);

test('run minutes round up to 5 and need a usable distance and speed', () => {
  assert.equal(runMinutes(7.4, 20), 25, '22.2 min rounds up');
  assert.equal(runMinutes(0.1, 30), 5, 'never under one step');
  assert.equal(runMinutes(10, 20), 30, 'an exact step stays');
  for (const [nm, kt] of [[NaN, 20], [-1, 20], [5, 0], [5, NaN], [5, -3]]) assert.equal(runMinutes(nm, kt), null);
  assert.deepEqual([durationText(45), durationText(120), durationText(110)], ['45 min', '2 h', '1 h 50 min']);
});

test('before the window: leave at its start, turn back so the run ends at its end, fishing time between', () => {
  const run = planRun(brief(), PLACE, 20, at('2026-10-12T12:00:00Z'));
  assert.equal(run.kind, 'ok');
  assert.equal(run.runMin, 25);
  assert.equal(run.depart, '2026-10-12T14:00:00.000Z');
  assert.equal(run.arrive, '2026-10-12T14:25:00.000Z');
  assert.equal(run.turnBack, '2026-10-12T18:35:00.000Z');
  assert.equal(run.back, WINDOW.end, 'in by the window\'s end');
  assert.equal(run.fishMin, 250);
});

test('inside the window: leave now (rounded up), so fishing time shrinks; past the turn-back time the window is over', () => {
  const open = planRun(brief(), PLACE, 20, at('2026-10-12T15:02:00Z'));
  assert.equal(open.depart, '2026-10-12T15:05:00.000Z');
  assert.equal(open.fishMin, 185);
  assert.equal(planRun(brief(), PLACE, 20, at('2026-10-12T18:40:00Z')).kind, 'over');
  // The first window's turn-back time has passed: the next window is planned.
  const later = {...WINDOW, start: '2026-10-12T20:00:00.000Z', end: '2026-10-12T23:00:00.000Z'};
  const next = planRun(brief({windows: [WINDOW, later]}), PLACE, 20, at('2026-10-12T18:40:00Z'));
  assert.equal(next.kind, 'ok');
  assert.equal(next.window, later);
});

test('a run that fills the window leaves no fishing time; it never reads as a negative or zero-minute stop', () => {
  const short = {...WINDOW, end: '2026-10-12T15:00:00.000Z'};
  const run = planRun(brief({windows: [short]}), {name: 'Far reef', nm: 10}, 20, at('2026-10-12T12:00:00Z'));
  assert.equal(run.kind, 'no-time');
  assert.equal(run.runMin, 30);
  // A short first window the run fills does not hide a later window with fishing time.
  const later = {...WINDOW, start: '2026-10-12T18:00:00.000Z', end: '2026-10-13T00:00:00.000Z'};
  const next = planRun(brief({windows: [short, later]}), {name: 'Far reef', nm: 10}, 20, at('2026-10-12T12:00:00Z'));
  assert.equal(next.kind, 'ok');
  assert.equal(next.window, later);
  assert.equal(next.fishMin, 300);
});

test('no speed, no place: the run asks rather than assumes; no default speed exists', () => {
  assert.deepEqual(planRun(brief(), PLACE, null, at('2026-10-12T12:00:00Z')), {kind: 'no-speed'});
  assert.deepEqual(planRun(brief(), PLACE, 0, at('2026-10-12T12:00:00Z')), {kind: 'no-speed'});
  assert.deepEqual(planRun(brief(), null, 20, at('2026-10-12T12:00:00Z')), {kind: 'no-place'});
});

test('no window: the reason names the missing input, the most material first', () => {
  const none = over => planRun(brief({windows: [], ...over}), PLACE, 20, at('2026-10-12T12:00:00Z'));
  assert.equal(none({alerts: [{event: 'Small Craft Advisory'}]}).reason, 'No return time while a marine alert is in effect.');
  assert.equal(none({tiles: [tile('stale')]}).reason, 'No return time from a stale forecast.');
  assert.equal(none({tiles: [tile('unavailable')]}).reason, 'No return time without a forecast for this day.');
  assert.equal(none({missing: ['Current marine alert check unavailable']}).reason, 'No return time while the marine alert check is unavailable.');
  assert.equal(none({missing: ['Wave period missing for some forecast hours']}).reason, 'No return time: some forecast hours are incomplete.');
  assert.equal(none({limits: {custom: true}}).reason, 'No lower-exposure window within your limits, so no return time.');
  assert.equal(none({}).reason, 'No lower-exposure window for this day, so no return time.');
  // A missing window outranks a missing speed: the speed would not give a return time.
  assert.equal(planRun(brief({windows: []}), PLACE, null, at('2026-10-12T12:00:00Z')).kind, 'no-window');
  assert.equal(noWindowReason(brief({tiles: []})), 'No lower-exposure window for this day, so no return time.');
});

test('cruise speed: device only, no default, bounded, and storage failure keeps it for the page', () => {
  const data = new Map();
  configureStore({storage: {getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v)}});
  assert.equal(cruise.loadCruise(), null, 'nothing stored: no speed');
  assert.equal(cruise.saveCruise('20'), 20);
  assert.equal(JSON.parse(data.get(STORAGE_KEYS.cruise)).knots, 20);
  cruise.cruiseSpeed.value = null;
  assert.equal(cruise.loadCruise(), 20, 'reloads from the device');
  assert.equal(cruise.saveCruise('22.3'), 22.5, 'rounds to the half knot');
  for (const bad of ['', ' ', 'fast', '1', '61', NaN]) assert.equal(cruise.parseCruise(bad), null, `${JSON.stringify(bad)} is no speed`);
  assert.equal(cruise.saveCruise(''), null, 'blank clears it');
  assert.equal(cruise.loadCruise(), null);
  data.set(STORAGE_KEYS.cruise, '{oops');
  assert.equal(cruise.loadCruise(), null, 'unreadable storage: no speed');
  configureStore({storage: {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('quota'); }}});
  assert.equal(cruise.saveCruise('18'), 18);
  assert.equal(cruise.cruiseSpeed.peek(), 18, 'blocked storage still holds the speed for the page');
  configureStore({storage: null});
  cruise.cruiseSpeed.value = null;
});

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'run-')), 'run.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RunLine, runPlace, runText, runBasis} from './web/brief/Run.tsx';
      export {LimitsForm} from './web/app/LimitsPanel.tsx';
      export {cruiseSpeed} from './web/limits.ts';
      export {regionInfo} from './web/app/App.tsx';
      export {profile, selection, habitat} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const pick = (id, nm, kind = 'spot') => ({id, kind, name: `Reef ${id}`, distance: `${nm} nm`, nm, depth: '~60–90 ft', fit: 'Fits', reason: 'Hard bottom.'});
const RANKING = {source: 'atlas', label: 'Survey reef atlas', basis: '', picks: [pick('a', 7.4), pick('b', 3.1)], empty: '', harbor: 'Morro Bay'};

test('the place: the selected pick, else the top pick, said so; none without a distance', async () => {
  const {runPlace} = await load();
  assert.deepEqual(runPlace(RANKING, 'b', null), {name: 'Reef b', nm: 3.1, chosen: true, unranked: false});
  assert.deepEqual(runPlace(RANKING, 'elsewhere', null), {name: 'Reef a', nm: 7.4, chosen: false, unranked: true}, 'a selection outside the screened picks falls back to the top pick, flagged');
  assert.deepEqual(runPlace(RANKING, null, null), {name: 'Reef a', nm: 7.4, chosen: false, unranked: false});
  assert.deepEqual(runPlace({...RANKING, picks: [pick('h1', 2, 'habitat')]}, null, 'h1'), {name: 'Reef h1', nm: 2, chosen: true, unranked: false});
  assert.equal(runPlace({...RANKING, picks: []}, null, null), null);
  assert.equal(runPlace({...RANKING, picks: [{...pick('a', 1), nm: null}]}, null, null), null, 'no harbor, no distance');
});

test('the line renders each state for Boat only, with times in the region\'s zone and the method in a basis', async () => {
  const m = await load();
  const {RunLine, render, h, cruiseSpeed, profile, selection} = m;
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', center: [35.34, -120.965], timezone: TZ};
  profile.value = 'boat';
  selection.value = null;
  const now = at('2026-10-12T12:00:00Z');
  const line = (over = {}, speed = 20) => { cruiseSpeed.value = speed; return render(h(RunLine, {brief: brief(over), ranking: RANKING, now})); };

  const ok = line();
  assert.match(ok, /data-state="ok"/);
  assert.match(ok, /Up to 4 h 10 min fishing at Reef a\./);
  assert.match(ok, /Leave 7 am · there 7:25 am · turn back 11:35 am · in by 12 pm · window 7 am–12 pm/);
  assert.doesNotMatch(ok, /app-run-note|outside the ranked list/);
  assert.match(ok, /7\.4 nm straight line · at least 25 min each way at 20 kt · top pick/);
  assert.match(ok, /<details class="ui-popover"[^>]*>.*straight-line distance from Morro Bay at the cruise speed you set/s, 'the method sits in the basis');

  const ask = line({}, null);
  assert.match(ask, /data-state="no-speed"/);
  assert.match(ask, /Set your cruise speed to see run time and when to turn back\./);
  assert.match(ask, /aria-haspopup="dialog"[^>]*>.*Set cruise speed<\/button>/s);
  assert.doesNotMatch(ask, /\d+ kt/, 'no speed is shown or assumed');

  assert.match(line({windows: [], tiles: [tile('stale')]}), /No return time from a stale forecast\./);
  // A window the bar reads caution or unknown at keeps that note beside the run time.
  const bar = 'Morro Bay: bar caution or unknown at departure or return (estimate); check the bar status';
  assert.match(line({windows: [{...WINDOW, reasons: ['Harbor entrance and full return route need a separate check', bar]}]}), /<p class="app-run-note">Morro Bay: bar caution or unknown at departure or return \(estimate\); check the bar status\.<\/p>/);
  // A selection outside the ranked list: the lead says whose times these are.
  selection.value = 'elsewhere';
  assert.match(line(), /Your selected place is outside the ranked list, so times are for the top pick\. Up to 4 h 10 min fishing at Reef a\./);
  selection.value = null;
  // Places with no distance (no harbor position): said plainly.
  assert.match(render(h(RunLine, {brief: brief(), ranking: {...RANKING, picks: [{...pick('a', 1), nm: null}]}, now})), /No harbor position to measure from, so no run time\./);
  assert.match(line({windows: [{...WINDOW, end: '2026-10-12T14:30:00.000Z'}]}), /The run to Reef a and back fills the 7 am–7:30 am window at 20 kt\./);
  assert.match(render(h(RunLine, {brief: brief(), ranking: RANKING, now: at('2026-10-12T18:50:00Z')})), /Turn-back time for the 7 am–12 pm window has passed\./);
  assert.match(render(h(RunLine, {brief: brief(), ranking: {...RANKING, picks: []}, now})), /Run time shows once a place to look is listed\./);

  // Loading, and the other profiles: nothing.
  assert.equal(render(h(RunLine, {brief: null, ranking: RANKING, now})), '');
  profile.value = 'shore';
  assert.equal(render(h(RunLine, {brief: {...brief(), profile: 'shore'}, ranking: RANKING, now})), '');
  profile.value = 'kayak';
  assert.equal(render(h(RunLine, {brief: {...brief(), profile: 'kayak'}, ranking: RANKING, now})), '');
  profile.value = 'boat';
  cruiseSpeed.value = null;
});

test('the Boat limits form carries the cruise speed field, blank with no default; other profiles do not', async () => {
  const {LimitsForm, render, h, cruiseSpeed} = await load();
  cruiseSpeed.value = null;
  const boat = render(h(LimitsForm, {profile: 'boat'}));
  assert.match(boat, /Cruise speed <span class="ui-mono">\(kt\)<\/span>/);
  assert.match(boat, /<input[^>]*name="cruise"[^>]*value(?:="")? aria-describedby/, 'blank until the user types one');
  assert.match(boat, /No default · 2–60 · run times only/);
  cruiseSpeed.value = 21;
  assert.match(render(h(LimitsForm, {profile: 'boat'})), /name="cruise"[^>]*value="21"/);
  for (const p of ['shore', 'spear', 'kayak']) assert.doesNotMatch(render(h(LimitsForm, {profile: p})), /name="cruise"/);
  cruiseSpeed.value = null;
});
