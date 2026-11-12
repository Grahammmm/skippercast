// The dock's zone abbreviation describes the selected forecast instant, not the clock (RF1540-5).
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const out = join(mkdtempSync(join(tmpdir(), 'dock-zone-')), 'bundle.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `
export {TimeDock} from './web/app/TimeDock.tsx';
export {regionInfo} from './web/app/App.tsx';
export * as state from './web/state.ts';
export {render} from 'preact-render-to-string';
export {h} from 'preact';`}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const m = await import(pathToFileURL(out).href);
m.state.configureStore({v2: true, storage: null});

const LA = 'America/Los_Angeles';
const dock = (nowISO, query, tz = LA) => {
  m.regionInfo.value = {id: 'morro-bay', timezone: tz};
  m.state.syncFromURL(`https://s.test/map?region=morro-bay${query}`);
  const html = m.render(m.h(m.TimeDock, {now: new Date(nowISO)}));
  return {
    zone: html.match(/class="app-dock-zone ui-mono">([^<]+)/)?.[1],
    readout: html.match(/<output[^>]*>([^<]+)/)?.[1],
    value: html.match(/aria-label="Hour"[^>]*value="(\d+)"/)?.[1],
    html,
  };
};

test('fall-back: the two 1 am selections read PDT then PST', () => {
  const a = dock('2026-10-31T19:00:00Z', '&hour=2026-11-01T08:00Z');
  const b = dock('2026-10-31T19:00:00Z', '&hour=2026-11-01T09:00Z');
  assert.deepEqual([a.readout, a.value, a.zone], ['1 am', '1', 'PDT']);
  assert.deepEqual([b.readout, b.value, b.zone], ['1 am', '2', 'PST']);
});

test('spring-forward: 1 am PST then 3 am PDT, no invented 2 am', () => {
  const a = dock('2026-03-07T20:00:00Z', '&hour=2026-03-08T09:00Z');
  const b = dock('2026-03-07T20:00:00Z', '&hour=2026-03-08T10:00Z');
  assert.deepEqual([a.readout, a.zone], ['1 am', 'PST']);
  assert.deepEqual([b.readout, b.zone], ['3 am', 'PDT']);
});

test('a retained out-of-horizon hour keeps its own zone and stays disabled', () => {
  const r = dock('2026-11-04T20:00:00Z', '&hour=2026-10-31T20:00Z');
  assert.equal(r.readout, '1 pm · outside the forecast');
  assert.equal(r.zone, 'PDT');
  assert.match(r.html, /aria-label="Hour"[^>]*disabled/);
});

test('missing or malformed hour falls back to the current hour and its zone', () => {
  assert.equal(dock('2026-11-04T20:00:00Z', '').zone, 'PST');
  const bad = dock('2026-11-04T20:00:00Z', '&hour=not-a-date');
  assert.deepEqual([bad.readout, bad.zone], ['12 pm', 'PST']);
});

test('UTC region: selected zone is UTC regardless of hour', () => {
  assert.equal(dock('2026-10-31T19:00:00Z', '&hour=2026-11-01T09:00Z', 'UTC').zone, 'UTC');
});
