// RF1810-5: cadenceLine returns '' for inherited Object.prototype names. Offline, synthetic ids only.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'layer-cadence-names-'));
  const out = join(dir, 'fresh.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: "export * from './web/map/freshness.ts'; export * as state from './web/state.ts'; export {Legend} from './web/app/Legend.tsx';"},
    jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent'});
  return {m: await import(pathToFileURL(out).href), dir};
}

test('cadence_inherited_names_are_unknown', async () => {
  const {m, dir} = await load();
  try {
    for (const id of ['constructor', '__proto__', 'toString', 'valueOf', 'hasOwnProperty']) {
      for (const lang of ['en', 'es']) assert.equal(m.cadenceLine(id, lang), '', `${id}/${lang}`);
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('cadence_unknown_boundaries_remain_empty', async () => {
  const {m, dir} = await load();
  try {
    for (const id of ['', 'no-such-layer', ' water-temp ', 'Water-Temp', 'CLOUDS']) {
      for (const lang of ['en', 'es']) assert.equal(m.cadenceLine(id, lang), '', JSON.stringify(id));
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('cadence_supported_entries_keep_output', async () => {
  const {m, dir} = await load();
  try {
    const ids = Object.keys(m.LAYER_FRESHNESS);
    assert.equal(ids.length, 11);
    for (const id of ids) {
      assert.match(m.cadenceLine(id, 'en'), /^Updates: /, id);
      assert.match(m.cadenceLine(id, 'es'), /^Actualización: /, id);
    }
    assert.equal(m.cadenceLine('water-temp', 'en'), 'Updates: daily · age limit 72 h');
    assert.equal(m.cadenceLine('clouds', 'en'), 'Updates: about every 5 min · age limit 90 min');
  } finally { await rm(dir, {recursive: true, force: true}); }
});
