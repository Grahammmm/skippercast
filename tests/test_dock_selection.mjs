// SC1407-05 (#1762 R3): the time dock answers a step at once and the evidence settles once. The real
// dock, sheet edge, verdict and first answer are bundled with esbuild and rendered against the real store;
// node's mock timers stand in for the 100 ms pause, and an effect on the canonical day/hour counts the
// update waves the brief, map overlays and tide would follow.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const TZ = 'America/Los_Angeles';
const ORIGIN = 'https://s.test/map';
/** Monday 2026-10-05, 1 pm Pacific. */
const NOW = new Date('2026-10-05T20:00:00Z');
const HOUR = 3_600_000;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'dock-selection-')), 'm.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/dock-selection.ts';
      export {TimeDock, dockState, selectHour} from './web/app/TimeDock.tsx';
      export {HourEdge} from './web/app/Mobile.tsx';
      export {Verdict} from './web/brief/Brief.tsx';
      export {FirstAnswerLine} from './web/app/FirstAnswerLine.tsx';
      export {horizonDays, dockTime} from './web/hour.ts';
      export {language, prepareCatalogue} from './web/i18n.ts';
      export * as state from './web/state.ts';
      export {effect, signal} from '@preact/signals';
      export {render} from 'preact-render-to-string';
      export {h, Fragment} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };

/** A page at `href` whose history counts replacements; the controller held as a mounted dock would hold it; a counter of canonical day/hour waves. */
async function page(t, href = ORIGIN) {
  const m = await load();
  const writes = [];
  globalThis.location = {href, search: new URL(href).search};
  globalThis.history = {state: null, pushState: () => assert.fail('the dock never pushes history'), replaceState: (_s, _t, url) => { writes.push(url); globalThis.location.href = new URL(url, href).href; }};
  m.state.configureStore({storage: memory()});
  m.state.syncFromURL(href);
  m.language.value = 'en';
  t.mock.timers.enable({apis: ['setTimeout']});
  const release = m.dockSelection.retain();
  let waves = 0;
  const stop = m.effect(() => { void m.state.day.value; void m.state.hour.value; waves++; });
  t.after(() => { release(); stop(); m.dockSelection.cancel(); delete globalThis.location; delete globalThis.history; });
  return {m, writes, waves: () => waves - 1, release};
}

const readout = html => /<output class="ui-dock-readout ui-mono" aria-live="off">([^<]+)</.exec(html)?.[1];
const valueText = html => /aria-valuetext="([^"]+)"/.exec(html)?.[1];
/** The hours after the current one today. */
const later = m => m.horizonDays(NOW, TZ)[0].hours.slice(1);

test('burst_moves_before_frame_settles_once: a quick run of steps moves the label at once and settles one wave 100 ms after the last', async t => {
  const {m, writes, waves} = await page(t);
  const hours = later(m).slice(0, 5);
  for (const [i, at] of hours.entries()) {
    assert.equal(m.requestDockHour(NOW, TZ, at), true);
    // The dock reads the new hour before any timer runs: thumb, readout and aria-valuetext together.
    const dock = m.render(m.h(m.TimeDock, {now: NOW})), edge = m.render(m.h(m.HourEdge, {now: NOW}));
    const label = `Today · ${2 + i} pm`;
    assert.equal(readout(dock), label);
    assert.equal(valueText(dock), label);
    assert.match(dock, new RegExp(`aria-label="Hour"[^>]*value="${1 + i}"`));
    assert.equal(readout(edge), label, 'the phone edge follows the same preview');
    t.mock.timers.tick(40);
  }
  assert.equal(waves(), 0, 'no canonical update wave per passed hour');
  assert.equal(writes.length, 0, 'no URL write per passed hour');
  assert.equal(location.href, ORIGIN);
  assert.equal(m.dockPending.value, true);
  t.mock.timers.tick(59);
  assert.equal(waves(), 0, '99 ms after the last input nothing has settled');
  t.mock.timers.tick(1);
  assert.equal(waves(), 1, 'exactly one settled wave');
  assert.equal(writes.length, 1, 'exactly one URL replacement');
  assert.equal(m.state.hour.value, m.state.hourParam(hours.at(-1) / 1000), 'the URL holds the settled (last) hour, never an intermediate one');
  assert.equal(new URL(location.href).searchParams.get('hour'), '2026-10-06T01:00Z');
  assert.equal(m.dockPending.value, false);
  assert.equal(readout(m.render(m.h(m.TimeDock, {now: NOW}))), 'Today · 6 pm');
  t.mock.timers.tick(1000);
  assert.equal(waves(), 1, 'nothing settles again');
});

test('a single step still settles, and a step back to the settled hour sends nothing', async t => {
  const {m, writes, waves} = await page(t);
  const [next] = later(m);
  m.requestDockHour(NOW, TZ, next);
  t.mock.timers.tick(100);
  assert.deepEqual([waves(), writes.length, m.state.hour.value], [1, 1, '2026-10-05T21:00Z']);
  m.requestDockHour(NOW, TZ, later(m)[3]);
  assert.equal(m.dockPending.value, true);
  m.requestDockHour(NOW, TZ, next);
  assert.equal(m.dockPending.value, false, 'back on the settled hour: no pending work');
  t.mock.timers.tick(500);
  assert.deepEqual([waves(), writes.length], [1, 1], 'no redundant recompute or write');
  assert.equal(m.requestDockHour(NOW, TZ, NOW.getTime() - 3 * HOUR), false, 'an hour outside the horizon is refused');
  assert.equal(m.requestDockHour(NOW, TZ, next + 30 * 60_000), false, 'a non-hour instant is refused');
  assert.equal(m.dockPending.value, false);
});

test('no_old_answer_under_preview: the verdict and first answer say Updating, unannounced, until the hour settles', async t => {
  const {m} = await page(t);
  const view = () => m.render(m.h(m.Fragment, null, m.h(m.TimeDock, {now: NOW}), m.h(m.Verdict, {now: NOW}), m.h(m.FirstAnswerLine, {now: NOW})));
  const settled = view();
  assert.doesNotMatch(settled, /Updating/);
  assert.doesNotMatch(settled, /app-hour-settled" hidden/);
  m.requestDockHour(NOW, TZ, later(m)[2]);
  const pending = view();
  assert.equal(readout(pending), 'Today · 4 pm');
  assert.equal(pending.match(/<p class="app-hour-updating ui-mono" aria-live="off">Updating…<\/p>/g)?.length, 2, 'both verdict surfaces say Updating');
  assert.equal(pending.match(/<div class="app-hour-guard" aria-busy="true" data-pending="true">/g)?.length, 2);
  // The old answers stay mounted but hidden and inert: removed from sight and the accessibility tree.
  assert.equal(pending.match(/<div class="app-hour-settled" hidden inert>/g)?.length, 2);
  const shown = pending.replace(/<div class="app-hour-settled" hidden inert>[\s\S]*?<\/div><\/div>(?=<div class="app-hour-guard"|<section|$)/g, '');
  assert.doesNotMatch(shown, /Waiting for readings|app-first-answer-line/, 'no previous answer is visible under the new label');
  assert.doesNotMatch(pending, /role="(?:status|alert)"[^>]*>Updating|aria-live="(?:polite|assertive)"[^>]*>Updating/);
  await m.prepareCatalogue('es');   // SC1407-09: the Spanish table loads on demand
  m.language.value = 'es';
  assert.match(view(), /aria-live="off">Actualizando…<\/p>/);
  m.language.value = 'en';
  t.mock.timers.tick(100);
  const after = view();
  assert.doesNotMatch(after, /Updating|hidden inert|aria-busy/, 'after settling, the answer shows for the dock hour');
  assert.equal(readout(after), 'Today · 4 pm');
});

test('pending_actions_use_settled_context: the canonical time, URL and print stay settled while a step is pending', async t => {
  const {m} = await page(t, `${ORIGIN}?hour=2026-10-05T22:00Z`);
  m.requestDockHour(NOW, TZ, later(m)[5]);
  assert.equal(m.dockState(NOW, TZ).at, Date.parse('2026-10-05T22:00Z'), 'share, planner and export read the settled dock time');
  assert.equal(m.previewDockState(NOW, TZ).at, later(m)[5]);
  assert.equal(new URL(location.href).searchParams.get('hour'), '2026-10-05T22:00Z', 'a share link made now carries the settled hour');
  const css = await readFile(new URL('../web/brief/brief-print.css', import.meta.url), 'utf8');
  const print = css.slice(css.indexOf('@media print'));
  assert.match(print, /\.app-hour-updating \{ display: none !important; \}/, 'Updating never prints');
  assert.match(print, /\.app-hour-settled\[hidden\] \{ display: contents !important; \}/, 'the settled answer prints');
});

test('day chips and play follow the same rule: preview at once, settle once, keep the local hour', async t => {
  const {m, writes, waves} = await page(t);
  const shown = m.previewDockState(NOW, TZ);
  m.requestDockDay(NOW, TZ, '2026-10-07', shown);
  let dock = m.render(m.h(m.TimeDock, {now: NOW}));
  assert.match(dock, /aria-pressed="true" data-on="true">Wed · Unknown</, 'the pressed chip moves at once');
  assert.equal(readout(dock), 'Wed · 1 pm', 'same local hour on the new day');
  m.requestDockDay(NOW, TZ, '2026-10-08', m.previewDockState(NOW, TZ));
  assert.equal(waves(), 0);
  t.mock.timers.tick(100);
  assert.deepEqual([waves(), writes.length], [1, 1]);
  const url = new URL(location.href).searchParams;
  assert.deepEqual([url.get('day'), url.get('hour')], ['2026-10-08', '2026-10-08T20:00Z']);
  // A play or reduced-motion step requests the next hour from the shown preview.
  m.requestDockHour(NOW, TZ, m.previewDockState(NOW, TZ).at + HOUR);
  dock = m.render(m.h(m.TimeDock, {now: NOW}));
  assert.equal(readout(dock), 'Thu · 2 pm');
  t.mock.timers.tick(100);
  assert.equal(m.state.hour.value, '2026-10-08T21:00Z');
});

test('both repeated 1 am instants of the fall-back day settle exactly', async t => {
  const now = new Date('2026-10-31T19:00:00Z');
  const {m} = await page(t);
  m.requestDockHour(now, TZ, Date.parse('2026-11-01T08:00Z'));
  assert.equal(m.render(m.h(m.TimeDock, {now})).match(/class="app-dock-zone ui-mono">([^<]+)/)[1], 'PDT');
  m.requestDockHour(now, TZ, Date.parse('2026-11-01T09:00Z'));
  const dock = m.render(m.h(m.TimeDock, {now}));
  assert.deepEqual([readout(dock), dock.match(/class="app-dock-zone ui-mono">([^<]+)/)[1]], ['Tomorrow · 1 am', 'PST']);
  t.mock.timers.tick(100);
  assert.deepEqual([m.state.day.value, m.state.hour.value], ['2026-11-01', '2026-11-01T09:00Z']);
});

test('external_navigation_and_lifecycle_win: URL sync, clock or zone change, hiding and unmount drop the preview', async t => {
  const {m, writes, waves, release} = await page(t);
  const [a, b] = later(m);
  // A same-valued URL sync (reload, Back/Forward) wins over the pending step.
  m.requestDockHour(NOW, TZ, a);
  m.state.syncFromURL(location.href);
  assert.equal(m.dockPending.value, false);
  // A programmatic selection is immediate and is never overwritten later.
  m.requestDockHour(NOW, TZ, b);
  m.selectHour(NOW, TZ, a);
  t.mock.timers.tick(500);
  assert.equal(m.state.hour.value, m.state.hourParam(a / 1000));
  assert.equal(writes.length, 1, 'only the programmatic write');
  // A new clock hour or zone drops the preview.
  m.requestDockHour(NOW, TZ, b);
  m.dockSelection.observe(new Date(NOW.getTime() + HOUR), TZ);
  assert.equal(m.dockPending.value, false);
  m.requestDockHour(NOW, TZ, b);
  m.dockSelection.observe(NOW, 'UTC');
  assert.equal(m.dockPending.value, false);
  // A hidden page drops it (the dock mounts again, now in a page with a document).
  release();
  const doc = Object.assign(new EventTarget(), {hidden: false});
  globalThis.document = doc;
  t.after(() => { delete globalThis.document; });
  const held = m.dockSelection.retain();
  m.requestDockHour(NOW, TZ, b);
  doc.hidden = true;
  doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(m.dockPending.value, false);
  // The last dock surface unmounting drops it; remounting does not revive the old step.
  m.requestDockHour(NOW, TZ, b);
  assert.equal(m.dockPending.value, true);
  held();
  assert.equal(m.dockPending.value, false);
  const again = m.dockSelection.retain();
  t.after(again);
  t.mock.timers.tick(500);
  assert.equal(writes.length, 1);
  assert.equal(waves(), 1, 'only the programmatic wave');
  release();
});

test('the factory: pending changes on entry and exit only; a stale timer or an unheld controller commits nothing', async () => {
  const {createDockSelection, effect, signal, dockTime, horizonDays} = await load();
  const queue = [], commits = [], context = signal('a'), at = signal(null);
  const c = createDockSelection({schedule: run => { queue.push(run); return queue.length; }, cancel: () => {}, context: () => context.value, commit: (_n, _z, x) => commits.push(x),
    settled: (now, tz) => dockTime(null, at.value, now, tz), doc: () => null});
  const hours = horizonDays(NOW, TZ)[0].hours;
  let flips = 0;
  const stop = effect(() => { void c.pending.value; flips++; });
  const release = c.retain();
  for (const x of hours.slice(1, 6)) c.request(NOW, TZ, x);
  assert.equal(flips, 2, 'one entry, not one per sample');
  for (const run of queue.slice(0, -1)) run();
  assert.equal(commits.length, 0, 'superseded timers are stale');
  queue.at(-1)();
  assert.deepEqual(commits, [hours[5]]);
  assert.equal(flips, 3);
  // A context change (another URL, region or pair) between input and timeout cancels it.
  c.request(NOW, TZ, hours[2]);
  context.value = 'b';
  queue.at(-1)();
  assert.equal(commits.length, 1);
  // Without a mounted dock nothing commits.
  release();
  c.request(NOW, TZ, hours[3]);
  queue.at(-1)();
  assert.equal(commits.length, 1);
  stop();
});

test('urlEpoch counts every URL sync, same values included', async () => {
  const {state} = await load();
  state.configureStore({storage: memory()});
  const before = state.urlEpoch.value;
  state.syncFromURL(`${ORIGIN}?hour=2026-10-05T22:00Z`);
  state.syncFromURL(`${ORIGIN}?hour=2026-10-05T22:00Z`);
  assert.equal(state.urlEpoch.value, before + 2);
  assert.equal(state.hour.value, '2026-10-05T22:00Z');
});
