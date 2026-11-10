// SC1722-10: day-qualified controls, without changing the canonical time or legacy headings.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
const out = join(await mkdtemp(join(tmpdir(), 'dock-day-')), 'm.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
export * from './web/app/TimeDock.tsx';
export {HourEdge} from './web/app/Mobile.tsx';
export {windowText} from './web/app/CommandBar.tsx';
export {Dock} from './web/ui/Dock.tsx';
export {regionInfo} from './web/app/App.tsx';
export * from './web/dock-selection.ts';
export * as state from './web/state.ts';
export {dockTime, horizonDays} from './web/hour.ts';
export {language} from './web/i18n.ts';
export {render} from 'preact-render-to-string';
export {h} from 'preact';`}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const m = await import(pathToFileURL(out).href);
const TZ = 'America/Los_Angeles', now = new Date('2026-10-31T19:00:00Z');
m.regionInfo.value = {id: 'morro-bay', timezone: TZ};
m.state.configureStore({v2: true, storage: null});
const visible = html => html.match(/<output[^>]*>([^<]+)</)?.[1];
function surfaces(clock, expected) {
  for (const component of [m.TimeDock, m.HourEdge]) {
    const html = m.render(m.h(component, {now: clock}));
    assert.equal(visible(html), expected);
    assert.equal(html.match(/aria-valuetext="([^"]+)"/)?.[1], expected);
    assert.match(html, /aria-live="off"/);
  }
}
const cases = [
  ['2026-10-31T23:00Z', 'Today · 4 pm', 'Hoy · 16'],
  ['2026-11-01T08:00Z', 'Tomorrow · 1 am', 'Mañana · 1'],
  ['2026-11-01T09:00Z', 'Tomorrow · 1 am', 'Mañana · 1'],
  ['2026-11-03T14:00Z', 'Tue · 6 am', 'mar · 6'],
  ['2026-11-07T14:00Z', 'Sat 7 · 6 am', 'sáb 7 · 6'],
  ['2026-10-30T20:00Z', '10-30 · 1 pm · outside the forecast', '10-30 · 13 · fuera del pronóstico'],
  ['2026-12-01T20:00Z', '12-01 · 12 pm · outside the forecast', '12-01 · 12 · fuera del pronóstico'],
  ['broken', 'Today · 12 pm', 'Hoy · 12'],
];
for (const [hour, en, es] of cases) test(`both surfaces: ${hour}, bilingual and read-only`, () => {
  m.state.syncFromURL(`https://s.test/map?day=2026-11-05&hour=${hour}`.replace(hour === 'broken' ? 'day=2026-11-05&' : 'NO_MATCH', ''));
  const before = [m.state.day.value, m.state.hour.value, m.state.urlEpoch.value].join('|');
  for (const [lang, expected] of [['en', en], ['es', es], ['en', en]]) {
    m.language.value = lang;
    surfaces(now, expected);
    assert.equal([m.state.day.value, m.state.hour.value, m.state.urlEpoch.value].join('|'), before);
  }
});
test('spring gap, noon/midnight and region rather than host day', () => {
  for (const [clock, at, tz, en, es] of [
    ['2026-03-07T20:00Z', '2026-03-08T09:00Z', TZ, 'Tomorrow · 1 am', 'Mañana · 1'],
    ['2026-03-07T20:00Z', '2026-03-08T10:00Z', TZ, 'Tomorrow · 3 am', 'Mañana · 3'],
    ['2026-11-01T06:30Z', '2026-11-01T07:00Z', TZ, 'Tomorrow · 12 am', 'Mañana · 0'],
    ['2026-11-01T06:30Z', '2026-11-01T07:00Z', 'UTC', 'Today · 7 am', 'Hoy · 7'],
    ['2026-10-31T19:00Z', '2026-11-01T20:00Z', TZ, 'Tomorrow · 12 pm', 'Mañana · 12'],
  ]) {
    const n = new Date(clock), s = m.dockTime(null, at, n, tz);
    assert.equal(m.dockValueText(n, tz, s, 'en'), en);
    assert.equal(m.dockValueText(n, tz, s, 'es'), es);
  }
  assert.equal(m.horizonDays(new Date('2026-03-07T20:00Z'), TZ)[1].hours.length, 23);
  assert.equal(new Set(m.horizonDays(now, TZ)[1].hours).size, 25);
});
test('preview stays bilingual through duplicate, settlement, invalid and cancelled requests', t => {
  m.state.syncFromURL('https://s.test/map'); m.language.value = 'en';
  t.mock.timers.enable({apis: ['setTimeout']});
  const release = m.dockSelection.retain();
  t.after(() => { release(); m.dockSelection.cancel(); });
  globalThis.location = {href: 'https://s.test/map'};
  let writes = 0;
  globalThis.history = {replaceState: (_s, _t, url) => { writes++; location.href = String(url); }};
  t.after(() => { delete globalThis.location; delete globalThis.history; });
  const at = Date.parse('2026-11-01T09:00Z');
  m.requestDockHour(now, TZ, at);
  surfaces(now, 'Tomorrow · 1 am');
  t.mock.timers.tick(60);
  m.language.value = 'es'; surfaces(now, 'Mañana · 1');
  assert.equal(m.requestDockHour(now, TZ, at), true);
  assert.equal(m.requestDockHour(now, TZ, at + 1), false);
  assert.equal(m.state.hour.value, null); assert.equal(writes, 0);
  t.mock.timers.tick(40);
  surfaces(now, 'Mañana · 1');
  assert.equal(m.state.hour.value, '2026-11-01T09:00Z');
  assert.equal(m.state.day.value, '2026-11-01'); assert.equal(writes, 1);
  m.requestDockDay(now, TZ, '2026-11-03', m.previewDockState(now, TZ));
  surfaces(now, 'mar · 1');
  m.state.syncFromURL('https://s.test/map?hour=2026-10-31T23:00Z');
  t.mock.timers.tick(100);
  surfaces(now, 'Hoy · 16'); assert.equal(writes, 1);
});
test('compatibility helpers, chip labels and generic Dock stay caller-controlled', () => {
  m.language.value = 'en'; m.state.syncFromURL('https://s.test/map');
  assert.equal(m.readout(m.dockState(now, TZ), TZ), '12 pm');
  assert.equal(m.windowText(now, TZ), 'Today · 12 pm');
  assert.equal(m.hourText(12), '12 pm');
  assert.equal(m.dayOptions(now, TZ, null)[1].label, 'Sun');
  const html = m.render(m.h(m.Dock, {days: [], day: '', onDay() {}, hour: 0, hours: 2, onHour() {}, hourText: () => 'custom value', playing: false, onPlay() {}}));
  assert.equal(visible(html), 'custom value');
  assert.match(html, /aria-valuetext="custom value"/);
});
