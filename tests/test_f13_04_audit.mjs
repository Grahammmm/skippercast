import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test, {after} from 'node:test';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const dir = await mkdtemp(join(tmpdir(), 'f13-04-'));
after(() => rm(dir, {recursive: true, force: true}));
const entry = fileURLToPath(new URL('../web/app/region-info.ts', import.meta.url));
const outfile = join(dir, 'reader.mjs');
await build({entryPoints: [entry], outfile, bundle: true, platform: 'node', format: 'esm', plugins: rendererPlugins});
const {createRegionReader, REGION_MISSING} = await import(pathToFileURL(outfile).href);

const REGION = {
  id: 'coast-a', name: 'Synthetic coast', map: {center: [1, 2], local_areas: [{id: 'inner', bounds: [0, 1, 2, 3]}]},
  timezone: 'UTC', jurisdiction_id: 'synthetic-jurisdiction', species: ['reef'], assets: {regulations: 'rules.json'},
};
const read = (body) => createRegionReader(async () => Response.json(body))('coast-a');

test('a valid metadata body naming the requested region keeps its metadata and rules', async () => {
  const info = await read(REGION);
  assert.equal(info.id, REGION.id);
  assert.equal(info.name, REGION.name);
  assert.deepEqual(info.center, REGION.map.center);
  assert.deepEqual(info.localAreas, REGION.map.local_areas);
  assert.equal(info.timezone, REGION.timezone);
  assert.deepEqual(info.rules, {
    id: REGION.id, timezone: REGION.timezone, jurisdiction_id: REGION.jurisdiction_id, species: REGION.species,
    assets: REGION.assets, regulatory_authority_hosts: undefined,
  });
});

test('a valid body for a different region is a failed read, not metadata or rules for the requested region', async () => {
  assert.equal(await read({...REGION, id: 'coast-b'}), null);
});

test('a body without a region id cannot be bound to the requested region', async () => {
  const {id: _id, ...body} = REGION;
  assert.equal(await read(body), null);
});

test('an HTTP 404 stays distinguishable from an identity mismatch', async () => {
  const readMissing = createRegionReader(async () => Response.json({...REGION, id: 'coast-b'}, {status: 404}));
  assert.equal(await readMissing('coast-a'), REGION_MISSING);
});
