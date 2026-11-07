// SCFEAT-FRESH-1: one update-cadence line per legend row, same wording on every layer, and the
// numbers agree with catalog/layer-inventory.json and catalog/feed-health.json. Offline.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
const json = async p => JSON.parse(await readFile(join(root, p), 'utf8'));

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'layer-fresh-'));
  const out = join(dir, 'fresh.mjs');
  await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export * from './web/map/freshness.ts';
    export {Legend} from './web/app/Legend.tsx';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
    jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
  return {m: await import(pathToFileURL(out).href), dir};
}

test('every layer and the rules row has one cadence line in one wording', async () => {
  const {m, dir} = await load();
  try {
    const ids = ['seafloor', 'currents', 'water-temp', 'sst-contrast', 'sst-fronts', 'chlorophyll', 'swell', 'stations', 'fleet', 'clouds', 'mpas'];
    for (const id of ids) {
      const en = m.cadenceLine(id, 'en');
      assert.match(en, /^Updates: /, id);
      assert.ok(!/UNVERIFIED|MEASURED|ESTIMATED/.test(en), `${id}: no internal labels`);
      assert.notEqual(m.cadenceLine(id, 'es'), en, `${id}: Spanish differs`);
      assert.match(m.cadenceLine(id, 'es'), /^Actualización: /, id);
    }
    assert.equal(m.cadenceLine('water-temp', 'en'), 'Updates: daily · age limit 72 h');
    assert.equal(m.cadenceLine('clouds', 'en'), 'Updates: about every 5 min · age limit 90 min');
    assert.equal(m.cadenceLine('nope', 'en'), '');
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('age limits match feed-health.json and the layer inventory', async () => {
  const {m, dir} = await load();
  try {
    const health = await json('catalog/feed-health.json');
    const inv = await json('catalog/layer-inventory.json');
    const byId = Object.fromEntries(inv.layers.map(l => [l.id, l]));
    assert.equal(m.LAYER_FRESHNESS['sst-fronts'].limitHours, health.feeds['sst-fronts'].max_age_hours);
    assert.equal(m.LAYER_FRESHNESS['stations'].limitHours, health.feeds.conditions.max_age_hours);
    for (const [id, f] of Object.entries(m.LAYER_FRESHNESS)) {
      for (const inventoryId of f.inventory) {
        const layer = byId[inventoryId];
        assert.ok(layer, `${id}: inventory layer ${inventoryId} exists`);
        if (f.limitHours !== null && f.checkInventoryLimit) {
          const limits = [...layer.update_cadence.matchAll(/(\d+) h/g)].map(x => Number(x[1]));
          assert.ok(limits.includes(f.limitHours), `${id}: ${f.limitHours} h in "${layer.update_cadence}"`);
        }
      }
    }
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('the legend shows the cadence line under each layer that is on', async () => {
  const {m, dir} = await load();
  try {
    m.state.configureStore({v2: true, storage: null});
    m.state.syncFromURL('https://s.test/map?region=morro-bay&presentation=chart&layers=water-temp,clouds');
    const html = m.render(m.h(m.Legend));
    assert.match(html, /data-cadence="water-temp"><p[^>]*>Updates: daily · age limit 72 h</);
    assert.match(html, /data-cadence="clouds"/);
    assert.match(html, /data-cadence="mpas"/);
    assert.ok(!html.includes('data-cadence="currents"'), 'only layers that are on');
  } finally { await rm(dir, {recursive: true, force: true}); }
});
