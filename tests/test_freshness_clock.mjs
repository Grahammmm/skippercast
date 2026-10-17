// P02 deterministic shell clock/source freshness; no browser or provider requests.
import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'p02-clock-')), 'clock.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {App, appNow, startAppClock, freshness, freshnessFrom} from './web/app/App.tsx';
  export {FreshnessDot} from './web/app/Masthead.tsx';
  export {dockState, dayOptions} from './web/app/TimeDock.tsx';
  export {TILE_LIMIT_MS} from './web/brief/model.ts';
  export {configureStore, setParams, hour} from './web/state.ts';
  export {effect} from '@preact/signals';
  export {render} from 'preact-render-to-string';
  export {h} from 'preact';`}, bundle: true, format: 'esm', platform: 'node', outfile: out,
  logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const m = await import(pathToFileURL(out).href);
const NOW = new Date('2026-10-08T23:59:00Z');
const HOUR = 3_600_000;
const tiles = (age = 60_000) => ['wind', 'swell', 'water', 'tide'].map(id => ({id, at: new Date(+NOW - age).toISOString(),
  limitMs: m.TILE_LIMIT_MS[id], state: 'fresh', value: 1, ageMs: 0}));

// URL environment for the real setParams -> navigate -> syncFromURL path.
function installURLFixture(t) {
  const names = ['location', 'history', 'HashChangeEvent', 'dispatchEvent'];
  const saved = new Map(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const address = new URL('https://s.test/map?region=morro-bay&profile=boat#clock');
  const writes = [], reloads = [], events = new EventTarget();
  const location = {
    get href() { return address.href; },
    set href(next) { address.href = new URL(next, address).href; },
    assign(next) { reloads.push('assign'); this.href = next; },
    replace(next) { reloads.push('replace'); this.href = next; },
  };
  const history = {
    state: {fixture: 'clock'},
    replaceState(state, _title, next) { this.state = state; location.href = next; writes.push({kind: 'replace', href: location.href}); },
    pushState(state, _title, next) { this.state = state; location.href = next; writes.push({kind: 'push', href: location.href}); },
  };
  class HashChangeEvent extends Event {
    constructor(type, init = {}) { super(type, init); this.oldURL = init.oldURL ?? ''; this.newURL = init.newURL ?? ''; }
  }
  const globals = {location, history, HashChangeEvent, dispatchEvent: event => events.dispatchEvent(event)};
  for (const name of names) Object.defineProperty(globalThis, name, {configurable: true, writable: true, value: globals[name]});
  t.after(() => {
    for (const [name, descriptor] of saved) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete globalThis[name];
    }
  });
  return {location, history, writes, reloads, events};
}
// End URL environment.

test('empty to loaded uses the original oldest source clock and accessible status', () => {
  assert.deepEqual(m.freshnessFrom(null, NOW), {state: 'unknown', age: null});
  const readings = tiles(); readings[2].at = new Date(+NOW - 45 * 60_000).toISOString();
  m.freshness.value = m.freshnessFrom(readings, NOW);
  assert.deepEqual(m.freshness.peek(), {state: 'ok', age: '45 min'});
  const html = m.render(m.h(m.FreshnessDot));
  assert.match(html, /role="status"/); assert.match(html, /data-state="ok"/); assert.match(html, /45 min/);
});

test('mixed source ages retain each tile limit, including nearshore', () => {
  const readings = tiles();
  readings[0].at = new Date(+NOW - 17 * HOUR).toISOString();
  readings[1].at = new Date(+NOW - 17 * HOUR).toISOString();
  readings[3].at = new Date(+NOW - 35 * HOUR).toISOString();
  assert.equal(m.freshnessFrom(readings, NOW).state, 'ok');
  readings[2].at = new Date(+NOW - 3 * HOUR - 1).toISOString();
  assert.equal(m.freshnessFrom(readings, NOW).state, 'stale');
  readings[2].at = NOW.toISOString(); readings[1].limitMs = m.TILE_LIMIT_MS.nearshore;
  assert.equal(m.freshnessFrom(readings, NOW).state, 'stale');
});

test('missing, invalid, future and unavailable clocks cannot become ok', () => {
  assert.equal(m.freshnessFrom(tiles().slice(1), NOW).state, 'stale');
  for (const at of [null, 'not-a-clock', new Date(+NOW + HOUR + 1).toISOString()]) {
    const readings = tiles(); readings[2].at = at;
    assert.equal(m.freshnessFrom(readings, NOW).state, 'stale');
  }
  const readings = tiles(); readings[2].state = 'unavailable';
  assert.equal(m.freshnessFrom(readings, NOW).state, 'stale');
});

test('offline, failed refresh and retained readings preserve age; refetch does not renew it', () => {
  const readings = tiles(2 * HOUR);
  assert.deepEqual(m.freshnessFrom(readings, NOW, false), {state: 'offline', age: '2 h'});
  assert.equal(m.freshnessFrom(readings, NOW, true, true).state, 'stale');
  readings[2].lastGood = true;
  assert.equal(m.freshnessFrom(readings, NOW).state, 'stale');
  delete readings[2].lastGood;
  // A new response with the same original source timestamps is still old.
  const later = new Date(+NOW + 2 * HOUR);
  assert.deepEqual(m.freshnessFrom(structuredClone(readings), later), {state: 'stale', age: '4 h'});
  assert.equal(m.freshnessFrom(tiles(), NOW).state, 'ok');
});

test('a region transition withholds prior tiles until matching inputs arrive', () => {
  // The startup effect supplies null while regionInfo.id differs from the selected region.
  assert.deepEqual(m.freshnessFrom(null, NOW), {state: 'unknown', age: null});
  assert.equal(m.freshnessFrom(tiles(), NOW).state, 'ok');
});

test('elapsed age crosses its boundary and midnight without a data reload', () => {
  const readings = tiles(3 * HOUR - 60_000);
  assert.equal(m.freshnessFrom(readings, NOW).state, 'ok');
  assert.deepEqual(m.freshnessFrom(readings, new Date(+NOW + 120_000)), {state: 'stale', age: '3 h'});
});

test('the shared shell clock ticks, catches up on resume, and disposes listeners', () => {
  let now = NOW, tick, canceled = false;
  const events = new EventTarget();
  const stop = m.startAppClock({read: () => now, repeat: fn => {tick = fn; return 42;}, cancel: id => {assert.equal(id, 42); canceled = true;}, events});
  assert.equal(+m.appNow.peek(), +NOW);
  now = new Date(+NOW + 120_000); tick();
  assert.equal(+m.appNow.peek(), +now);
  const shell = m.App();
  assert.equal(+shell.props.children[0].props.children[2].props.now, +now, 'Desktop receives advancing time without resize');
  now = new Date(+NOW + 8 * HOUR); events.dispatchEvent(new Event('focus'));
  assert.equal(+m.appNow.peek(), +now);
  stop(); assert.ok(canceled);
  now = new Date(+NOW + 9 * HOUR); events.dispatchEvent(new Event('pageshow'));
  assert.notEqual(+m.appNow.peek(), +now);
});

test('clock controls cross local midnight while an explicit historical hour remains selected', t => {
  const browser = installURLFixture(t);
  m.configureStore({v2: true, storage: null}); m.setParams({day: null, hour: null});
  const before = new Date('2026-10-09T06:59:00Z'), after = new Date('2026-10-09T07:01:00Z'), tz = 'America/Los_Angeles';
  assert.equal(m.dockState(before, tz).day, '2026-10-08');
  assert.equal(m.dockState(after, tz).day, '2026-10-09');
  m.setParams({hour: '2026-10-08T22:00:00Z'});
  const selected = m.dockState(before, tz).at;
  assert.equal(m.dockState(after, tz).at, selected);
  assert.equal(m.hour.peek(), '2026-10-08T22:00:00Z');
  assert.equal(new URL(browser.location.href).searchParams.get('hour'), '2026-10-08T22:00:00Z');
  assert.equal(new URL(browser.location.href).hash, '#clock');
  assert.deepEqual(browser.reloads, []);
  assert.ok(browser.writes.every(write => write.kind === 'replace'));
  m.setParams({day: null, hour: null});
  assert.equal(new URL(browser.location.href).searchParams.has('hour'), false);
});

test('body-12-03: a shared-clock tick advances the dock and source age while preserving a pinned hour', t => {
  const browser = installURLFixture(t);
  m.configureStore({v2: true, storage: null}); m.setParams({day: null, hour: null});
  let now = new Date('2026-10-09T06:59:00Z'), tick;
  const tz = 'America/Los_Angeles', snapshots = [];
  const readings = tiles().map(tile => ({...tile, at: new Date(+now - 2 * HOUR - 59 * 60_000).toISOString()}));
  const stopClock = m.startAppClock({read: () => now, repeat: fn => {tick = fn; return 43;}, cancel: () => {}, events: new EventTarget()});
  t.after(stopClock);
  // Read App's real default clock and follow Desktop's actual TimeDock prop.
  // The signal effect reruns this composition on a clock tick, with no resize.
  const stopView = m.effect(() => {
    const desktop = m.App().props.children[0].props.children[2];
    const dock = desktop.type(desktop.props).props.children[1].props.children[1];
    snapshots.push({html: m.render(dock), state: m.dockState(dock.props.now, tz),
      fresh: m.freshnessFrom(readings, dock.props.now)});
  });
  t.after(stopView);
  assert.match(snapshots.at(-1).html, /aria-valuetext="11 pm"/);
  assert.equal(snapshots.at(-1).state.day, '2026-10-08');
  assert.deepEqual(snapshots.at(-1).fresh, {state: 'ok', age: '2 h'});
  const renders = snapshots.length, writes = browser.writes.length;
  now = new Date('2026-10-09T07:01:00Z'); tick();
  assert.ok(snapshots.length > renders, 'clock signal alone republishes the dock composition');
  assert.match(snapshots.at(-1).html, /aria-valuetext="12 am"/);
  assert.equal(snapshots.at(-1).state.day, '2026-10-09');
  assert.equal(snapshots.at(-1).state.at, Date.parse('2026-10-09T07:00:00Z'));
  assert.deepEqual(snapshots.at(-1).fresh, {state: 'stale', age: '3 h'});
  assert.equal(browser.writes.length, writes, 'elapsed time does not write a selected hour to the URL');
  m.setParams({hour: '2026-10-08T22:00:00Z'});
  const pinnedURL = browser.location.href, pinned = snapshots.at(-1).state.at;
  now = new Date('2026-10-09T08:01:00Z'); tick();
  assert.equal(snapshots.at(-1).state.at, pinned);
  assert.equal(snapshots.at(-1).state.index, -1, 'the historical hour remains outside the advancing horizon');
  assert.match(snapshots.at(-1).html, /aria-valuetext="3 pm · outside the forecast"/);
  assert.equal(m.hour.peek(), '2026-10-08T22:00:00Z');
  assert.equal(browser.location.href, pinnedURL);
  assert.deepEqual(browser.reloads, []);
  stopView(); stopClock(); m.setParams({day: null, hour: null});
});
