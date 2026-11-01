// SCJ-3: on a phone the History view lives in the bottom sheet, whose peek
// detent clips its body below the hour control, so the series was never in
// view. Entering History opens a peeked sheet to full (viewDetent); every
// other view and every detent the user already chose is left alone.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const DETENTS = ['peek', 'half', 'full'];

let mod;
async function load() {
  if (mod) return mod;
  const outfile = join(await mkdtemp(join(tmpdir(), 'history-sheet-')), 'mobile.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {viewDetent} from './web/app/Mobile.tsx';
    export {APP_VIEWS} from './web/state.ts';`},
  outfile, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, logLevel: 'silent'});
  mod = await import(pathToFileURL(outfile).href);
  return mod;
}

test('entering History opens a peeked sheet to full and keeps half or full as chosen', async () => {
  const {viewDetent} = await load();
  assert.equal(viewDetent('history', 'peek'), 'full');
  assert.equal(viewDetent('history', 'half'), 'half');
  assert.equal(viewDetent('history', 'full'), 'full');
});

test('every other view keeps its detent at all three detents', async () => {
  const {viewDetent, APP_VIEWS} = await load();
  const others = APP_VIEWS.filter(view => view !== 'history');
  assert.deepEqual([...others].sort(), ['coast', 'conditions', 'fleet', 'reports']);
  for (const view of others) for (const detent of DETENTS) assert.equal(viewDetent(view, detent), detent, `${view} at ${detent}`);
});

test('the sheet applies viewDetent only when the view changes, so a later drag down is not forced back up', async () => {
  const source = await readFile(join(ROOT, 'web/app/Mobile.tsx'), 'utf8');
  const effects = source.match(/useEffect\([^\n]*\);/g) ?? [];
  assert.equal(effects.length, 1);
  assert.match(effects[0], /setDetent\(d => viewDetent\(appView\.value, d\)\), \[appView\.value\]\)/);
});
