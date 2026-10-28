// Offline build-contract fixtures: no bundling or generated production assets.
import assert from 'node:assert/strict';
import test from 'node:test';
import {spawnSync} from 'node:child_process';
import {mkdtemp, mkdir, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {precacheManifest} from '../scripts/precache.mjs';

const CHECK = new URL('../scripts/check_client.mjs', import.meta.url).pathname;
const file = name => `assets/${name}.0123456789.js`;
async function check(t, {entry = {}, chunks = {}, code = {}, omit = [], invalidManifest = false} = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'client-graph-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  await mkdir(join(dir, '.vite'), {recursive: true});
  await mkdir(join(dir, 'assets'));
  const manifest = {
    'app.html': {file: file('app'), isEntry: true, ...entry},
    'landing.html': {file: file('landing'), isEntry: true},
    ...chunks,
  };
  for (const e of Object.values(manifest)) {
    if (!omit.includes(e.file)) await writeFile(join(dir, e.file), code[e.file] || 'export {};');
  }
  await writeFile(join(dir, '.vite/manifest.json'), JSON.stringify(manifest));
  for (const page of ['app', 'landing']) await writeFile(join(dir, `${page}.fixture.html`), `<script type="module" src="/${file(page)}"></script>`);
  await writeFile(join(dir, '.assetsignore'), '.vite\n');
  await writeFile(join(dir, 'sw.js'), "const BUILD = 'fixture';");
  await writeFile(join(dir, 'precache.json'), JSON.stringify(await precacheManifest(dir, 'fixture')));
  if (invalidManifest) await writeFile(join(dir, '.vite/manifest.json'), '{');
  const result = spawnSync(process.execPath, [CHECK, dir], {encoding: 'utf8'});
  assert.ifError(result.error);
  return {status: result.status, output: result.stdout + result.stderr};
}

for (const dependency of ['maplibre-gl', 'pmtiles']) {
  for (const prefix of ['node_modules/', `node_modules/.pnpm/${dependency}@1.0.0/node_modules/`]) {
    test(`rejects direct static ${prefix}${dependency} source`, async t => {
      const key = `${prefix}${dependency}/index.js`;
      const r = await check(t, {entry: {imports: [key]}, chunks: {[key]: {src: key, file: file('library')}}});
      assert.equal(r.status, 1, r.output);
      assert.match(r.output, /MapLibre and PMTiles load by dynamic import only/);
    });
  }
  for (const field of ['key', 'name', 'file']) {
    test(`rejects transitive shared ${dependency} by ${field}`, async t => {
      const key = field === 'key' ? `_${dependency}.0123456789.js` : '_shared.js';
      const chunk = {file: file(field === 'file' ? dependency : 'library')};
      if (field === 'name') chunk.name = dependency;
      const r = await check(t, {entry: {imports: ['bridge']}, chunks: {
        bridge: {file: file('bridge'), imports: [key, 'app.html']}, [key]: chunk,
      }});
      assert.equal(r.status, 1, r.output);
      assert.match(r.output, /MapLibre and PMTiles load by dynamic import only/);
    });
  }
  test(`allows dynamic ${dependency} including its static subtree`, async t => {
    const r = await check(t, {entry: {dynamicImports: ['chart']}, chunks: {
      chart: {file: file('chart'), imports: [dependency]},
      [dependency]: {file: file(dependency), src: `node_modules/${dependency}/index.js`},
    }});
    assert.equal(r.status, 0, r.output);
  });
}

test('preserves three names, source paths and code markers', async t => {
  for (const chunk of [
    {file: file('three.core')},
    {file: file('library'), src: 'packages/coast/src/coast3d/viewer.ts'},
    {file: file('library'), src: 'node_modules/three/src/Three.js'},
    ...['__THREE__', 'THREE.WebGLRenderer'].map(marker => ({file: file('library'), marker})),
  ]) {
    const r = await check(t, {entry: {imports: ['library']}, chunks: {library: chunk},
      code: {[chunk.file]: chunk.marker || 'export {};'}});
    assert.equal(r.status, 1, r.output);
    assert.match(r.output, /three and the coast renderer load by dynamic import only|which contains three/);
  }
});

test('allows a normal static graph and absent optional graph nodes', async t => {
  const r = await check(t, {entry: {imports: ['missing', 'shared']}, chunks: {shared: {file: file('shared')}}});
  assert.equal(r.status, 0, r.output);
});

test('preserves missing-file and invalid-manifest diagnostics', async t => {
  const missing = await check(t, {entry: {imports: ['shared']}, chunks: {shared: {file: file('shared')}}, omit: [file('shared')]});
  assert.equal(missing.status, 1);
  assert.match(missing.output, /shared.*\(missing\)/);
  const invalid = await check(t, {invalidManifest: true});
  assert.equal(invalid.status, 1);
  assert.match(invalid.output, /manifest.json missing or invalid/);
});
