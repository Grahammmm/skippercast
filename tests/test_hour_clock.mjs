// The shared hour clock (SC0452-05, web/clock.ts): one ticking source for the dock and the map stage. Every test drives
// an injected reader, scheduler and document, so nothing waits on real time.
import assert from 'node:assert/strict';
import test from 'node:test';
import {h} from 'preact';
import {render} from 'preact-render-to-string';
import {appClock, createHourClock, useHourNow} from '../web/clock.ts';

const HOUR = 3_600_000;
const iso = d => d.toISOString();

/** A clock over a fake reader, a manual scheduler and a fake document. */
function rig(start = '2026-10-05T20:17:00Z') {
  let at = new Date(start), next = 1;
  const timers = new Map(), listeners = new Set();
  const doc = {hidden: false, addEventListener: (_t, fn) => listeners.add(fn), removeEventListener: (_t, fn) => listeners.delete(fn)};
  const clock = createHourClock({read: () => new Date(at), doc,
    schedule: (callback, delay) => { const id = next++; timers.set(id, {callback, delay}); return id; },
    cancel: id => { timers.delete(id); }});
  return {
    clock, timers, listeners, doc,
    set(value) { at = new Date(value); },
    /** Run the one waiting timeout, as the browser does at its time. */
    fire() { const [[id, timer]] = [...timers]; timers.delete(id); timer.callback(); },
    show(hidden) { doc.hidden = hidden; for (const fn of [...listeners]) fn(); },
  };
}

test('importing starts nothing; the first retain samples and waits for the next whole UTC hour', () => {
  const r = rig();
  assert.equal(r.timers.size, 0, 'creating a clock schedules nothing');
  assert.equal(r.listeners.size, 0, 'creating a clock listens to nothing');
  const release = r.clock.retain();
  assert.equal(iso(r.clock.now.value), '2026-10-05T20:17:00.000Z');
  assert.deepEqual([...r.timers.values()].map(t => t.delay), [43 * 60_000], 'no extra second after the hour');
  assert.equal(r.listeners.size, 1);
  release();
  const exact = rig('2026-10-05T21:00:00Z');
  exact.clock.retain();
  assert.deepEqual([...exact.timers.values()].map(t => t.delay), [HOUR], 'on the hour the next tick is a full hour away');
});

test('shared_clock tick: the callback publishes the actual time and re-arms from it, never from a stale value', () => {
  const r = rig('2026-10-05T20:59:59.999Z');
  r.clock.retain();
  assert.equal([...r.timers.values()][0].delay, 1);
  r.set('2026-10-05T21:00:00.004Z');
  r.fire();
  assert.equal(iso(r.clock.now.value), '2026-10-05T21:00:00.004Z');
  assert.equal(r.timers.size, 1, 'one timeout waiting');
  assert.equal([...r.timers.values()][0].delay, HOUR - 4);
});

test('clock_resumes_after_delay_and_visibility: a late callback jumps the missed hours; a backward step is followed; one timeout throughout', () => {
  const r = rig('2026-10-05T20:17:00Z');
  r.clock.retain();
  r.set('2026-10-06T00:30:00Z');
  r.fire();
  assert.equal(iso(r.clock.now.value), '2026-10-06T00:30:00.000Z', 'several hours late: straight to the real hour');
  assert.equal([...r.timers.values()][0].delay, 30 * 60_000);
  r.set('2026-10-05T23:10:00Z');
  r.fire();
  assert.equal(iso(r.clock.now.value), '2026-10-05T23:10:00.000Z', 'wall clock stepped back: follows it');
  assert.equal(r.timers.size, 1);
  assert.equal([...r.timers.values()][0].delay, 50 * 60_000);
});

test('clock_resumes_after_delay_and_visibility: a hidden page waits, a shown page resamples and replaces the timeout', () => {
  const r = rig('2026-10-05T20:17:00Z');
  r.clock.retain();
  const old = [...r.timers.values()][0].callback;
  r.set('2026-10-05T23:40:00Z');
  r.show(true);
  assert.equal(iso(r.clock.now.value), '2026-10-05T20:17:00.000Z', 'hidden: no work');
  r.show(false);
  assert.equal(iso(r.clock.now.value), '2026-10-05T23:40:00.000Z', 'visible again: the real time at once');
  assert.equal(r.timers.size, 1, 'the old timeout was cancelled, one re-armed');
  assert.equal([...r.timers.values()][0].delay, 20 * 60_000);
  old();
  assert.equal(r.timers.size, 1, 'an obsolete callback neither publishes nor re-arms');
  assert.equal(iso(r.clock.now.value), '2026-10-05T23:40:00.000Z');
});

test('clock_retains_once_and_disposes: consumers share one timeout; releases are idempotent; the last one stops everything; the next retain is fresh', () => {
  const r = rig('2026-10-05T20:17:00Z');
  const a = r.clock.retain(), b = r.clock.retain();
  assert.equal(r.timers.size, 1);
  assert.equal(r.listeners.size, 1);
  const stale = [...r.timers.values()][0].callback;
  a(); a(); a();
  assert.equal(r.timers.size, 1, 'one consumer left: still ticking, however often the first released');
  b();
  assert.equal(r.timers.size, 0);
  assert.equal(r.listeners.size, 0);
  r.set('2026-10-05T22:00:00Z');
  stale();
  assert.equal(r.timers.size, 0, 'a stale callback after stop does not re-arm');
  assert.equal(iso(r.clock.now.value), '2026-10-05T20:17:00.000Z', 'nor publish');
  r.show(false);
  assert.equal(r.timers.size, 0, 'a stopped clock ignores visibility');
  const again = r.clock.retain();
  assert.equal(iso(r.clock.now.value), '2026-10-05T22:00:00.000Z', 'the next retain samples afresh');
  assert.equal(r.timers.size, 1);
  again();
  assert.equal(r.timers.size, 0);
});

test('a clock with no document (Node, server render) still ticks and releases', () => {
  const timers = new Map();
  let id = 0;
  const clock = createHourClock({read: () => new Date('2026-10-05T20:17:00Z'), schedule: (cb, delay) => { timers.set(++id, delay); return id; }, cancel: i => timers.delete(i)});
  const release = clock.retain();
  assert.equal(timers.size, 1);
  release();
  assert.equal(timers.size, 0);
});

test('clock work makes no network, history or storage call', () => {
  const touched = [];
  const keep = {fetch: globalThis.fetch, history: globalThis.history, localStorage: globalThis.localStorage};
  globalThis.fetch = () => { touched.push('fetch'); };
  globalThis.history = {pushState: () => touched.push('push'), replaceState: () => touched.push('replace')};
  globalThis.localStorage = {getItem: () => touched.push('get'), setItem: () => touched.push('set')};
  try {
    const r = rig();
    const release = r.clock.retain();
    r.set('2026-10-05T21:00:00Z'); r.fire();
    r.show(true); r.show(false);
    release();
  } finally {
    for (const [name, value] of Object.entries(keep)) { if (value === undefined) delete globalThis[name]; else globalThis[name] = value; }
  }
  assert.deepEqual(touched, []);
});

test('useHourNow: a fixed date is returned as is; without one the clock\'s time is returned; rendering starts no timer', () => {
  const r = rig('2026-10-05T20:17:00Z');
  const Show = ({fixed}) => h('p', null, iso(useHourNow(fixed, r.clock)));
  assert.equal(render(h(Show, {fixed: new Date('2026-01-02T03:04:05Z')})), '<p>2026-01-02T03:04:05.000Z</p>');
  assert.equal(render(h(Show, {})), '<p>2026-10-05T20:17:00.000Z</p>');
  assert.equal(r.timers.size, 0, 'a render never schedules');
  const release = r.clock.retain();
  r.set('2026-10-05T21:00:00Z'); r.fire();
  assert.equal(render(h(Show, {})), '<p>2026-10-05T21:00:00.000Z</p>', 'after the tick a render reads the new hour');
  assert.equal(render(h(Show, {fixed: new Date('2026-01-02T03:04:05Z')})), '<p>2026-01-02T03:04:05.000Z</p>', 'a fixed date ignores the tick');
  release();
});

test('the app clock exists without having started', () => {
  assert.equal(typeof appClock.retain, 'function');
  assert.ok(appClock.now.value instanceof Date);
});
