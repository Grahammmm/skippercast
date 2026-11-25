// MORRO-M3: closing Layers on a phone puts the sheet back where the layers button raised it from.
// Found in the local integrated-Chart rehearsal on merged main 3a54ab65: switching survey detail on from
// Layers and closing Layers left the brief at the half detent, covering about 86% of the map canvas
// (47-51 of 361 sample points exposed vs 158-162 before), so the survey-gap cue sat under the sheet.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'layers-return-')), 'mobile.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: "export {toggleLayers, layersOpenedFrom, afterDetent} from './web/app/Mobile.tsx';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** The Mobile shell's layers button and sheet, as pure state: the same calls flipLayers and onDetent make. */
function shell({toggleLayers, layersOpenedFrom, afterDetent}) {
  let panel = 'brief', detent = 'peek', from = null;
  return {
    get state() { return {panel, detent}; },
    flip() { const next = toggleLayers(panel, detent, from); from = layersOpenedFrom(panel, detent); ({panel, detent} = next); },
    drag(to) { from = null; ({panel, detent} = afterDetent(panel, to)); },
  };
}

test('closing Layers returns a sheet the button raised from peek back to peek', async () => {
  const s = shell(await load());
  s.flip();
  assert.deepEqual(s.state, {panel: 'layers', detent: 'half'});
  s.flip();   // e.g. after switching survey detail on: the map, and its gap cue, are uncovered again
  assert.deepEqual(s.state, {panel: 'brief', detent: 'peek'});
});

test('a sheet the user placed stays where they put it', async () => {
  const m = await load();
  const s = shell(m);
  s.flip();
  s.drag('full');   // the user moved the sheet while Layers was open: their choice wins
  s.flip();
  assert.deepEqual(s.state, {panel: 'brief', detent: 'full'});
  const t = shell(m);
  t.drag('half');   // opened from half, Layers keeps half and closing keeps half
  t.flip();
  assert.deepEqual(t.state, {panel: 'layers', detent: 'half'});
  t.flip();
  assert.deepEqual(t.state, {panel: 'brief', detent: 'half'});
});

test('the two-argument form is unchanged', async () => {
  const {toggleLayers, layersOpenedFrom} = await load();
  assert.deepEqual(toggleLayers('layers', 'half'), {panel: 'brief', detent: 'half'});
  assert.deepEqual(toggleLayers('brief', 'peek'), {panel: 'layers', detent: 'half'});
  assert.deepEqual(toggleLayers('layers', 'half', 'peek'), {panel: 'brief', detent: 'peek'});
  assert.equal(layersOpenedFrom('brief', 'peek'), 'peek');
  assert.equal(layersOpenedFrom('brief', 'half'), null);
  assert.equal(layersOpenedFrom('layers', 'half'), null);
});
