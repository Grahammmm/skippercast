// RF0510-2: the region reader keeps a region only when its `timezone` is absent (DEFAULT_ZONE) or a zone
// Intl knows; a bad zone or a JSON body that is not an object is a failed read (null), never a thrown TypeError.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'rf0510-2-')), 'reader.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {createRegionReader, REGION_MISSING, DEFAULT_ZONE} from './web/app/region-info.ts';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}
const BASE = {name: 'Test', map: {center: [35.37, -120.86]}};
/** One fresh reader per body, so no read is shared from a cache. */
const read = async (body, id = 'test') => (await load()).createRegionReader(async () => new Response(body))(id);
const readJson = (json, id) => read(JSON.stringify(json), id);

test('the real morro-bay region.json keeps America/Los_Angeles and its other fields', async () => {
  const bytes = await readFile(join(ROOT, 'regions/morro-bay/region.json'), 'utf8');
  const json = JSON.parse(bytes);
  const info = await read(bytes, 'morro-bay');
  assert.equal(info.timezone, 'America/Los_Angeles');
  assert.equal(info.id, 'morro-bay');
  assert.equal(info.name, json.name);
  assert.deepEqual(info.center, json.map.center);
  if (typeof json.jurisdiction_id === 'string') {
    assert.equal(info.rules.timezone, 'America/Los_Angeles');
    assert.equal(info.rules.jurisdiction_id, json.jurisdiction_id);
  }
});

test('no timezone key reads as DEFAULT_ZONE; rules keep the zone absent', async () => {
  const {DEFAULT_ZONE} = await load();
  const info = await readJson(BASE);
  assert.equal(info.timezone, DEFAULT_ZONE);
  assert.equal(DEFAULT_ZONE, 'America/Los_Angeles');
  const ruled = await readJson({...BASE, jurisdiction_id: 'ca'});
  assert.equal(ruled.timezone, DEFAULT_ZONE);
  assert.equal(ruled.rules.timezone, undefined, 'absent stays absent in rules');
});

test('a zone Intl knows is accepted as given, in timezone and rules', async () => {
  for (const zone of ['UTC', 'America/Denver']) {
    const info = await readJson({...BASE, timezone: zone, jurisdiction_id: 'ca'});
    assert.equal(info.timezone, zone);
    assert.equal(info.rules.timezone, zone);
    assert.equal((await readJson({...BASE, timezone: zone})).timezone, zone, 'a cached answer stays the same');
  }
});

test('a misspelt, empty, non-string, null or over-long zone is a failed read (null), not a throw', async () => {
  for (const zone of ['America/LosAngeles', '', 42, null, 'A'.repeat(200), 'America/' + 'x'.repeat(60), true, {}, ['UTC']]) {
    assert.equal(await readJson({...BASE, timezone: zone}), null, `timezone ${JSON.stringify(zone)}`);
    assert.equal(await readJson({...BASE, timezone: zone}), null, `timezone ${JSON.stringify(zone)} again (cached answer)`);
  }
});

test('a region with jurisdiction_id and a bad zone is null: no rules are built with a bad zone', async () => {
  for (const zone of ['America/LosAngeles', '', 42, null]) {
    assert.equal(await readJson({...BASE, jurisdiction_id: 'ca', species: ['x'], timezone: zone}), null);
  }
});

test('a JSON body that is not an object is null with no TypeError; a 404 is still REGION_MISSING', async () => {
  const {createRegionReader, REGION_MISSING} = await load();
  for (const body of ['null', '[]', '"text"', '7', 'true', '[{"name":"A","map":{"center":[1,2]}}]']) {
    assert.equal(await read(body), null, `body ${body}`);
  }
  assert.equal(await createRegionReader(async () => new Response('nope', {status: 404}))('nowhere'), REGION_MISSING);
  assert.equal(await createRegionReader(async () => new Response('nope', {status: 500}))('broken'), null);
});
