import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {precacheManifest, writePrecache, BUILD_PLACEHOLDER, reachable, v2Only} from '../scripts/precache.mjs';

// check_client's precache and worker checks run against a real Vite build in
// tests/test_client_build.mjs; this file covers scripts/precache.mjs itself.
const BUILD = 'abc1234567';

async function site() {
  const dir = await mkdtemp(join(tmpdir(), 'precache-'));
  await mkdir(join(dir, 'vendor/images'), {recursive: true});
  await mkdir(join(dir, 'assets'), {recursive: true});
  await writeFile(join(dir, `index.${BUILD}.html`), '<script type="module" src="./assets/index.0123456789.js"></script>');
  await writeFile(join(dir, 'assets/index.0123456789.js'), "import './app.abcdef0123.js';");
  await writeFile(join(dir, 'assets/app.abcdef0123.js'), "navigator.serviceWorker.register('/sw.js');");
  await writeFile(join(dir, 'assets/styles.fedcba9876.css'), 'body{}');
  await writeFile(join(dir, 'assets/notes.txt'), 'not a script or style');
  await writeFile(join(dir, 'sw.js'), `${BUILD_PLACEHOLDER}\nself.addEventListener('push',()=>{});`);
  await writeFile(join(dir, 'manifest.webmanifest'), '{}');
  await writeFile(join(dir, 'app-icon-192.png'), 'png');
  await writeFile(join(dir, 'regulations.json'), '{}');
  await writeFile(join(dir, 'vendor/leaflet.js'), '');
  await writeFile(join(dir, 'vendor/leaflet.css'), '');
  await writeFile(join(dir, 'vendor/images/marker-icon.png'), '');
  return dir;
}

test('precache.json lists the shell, every hashed asset of the build and the static shell files', async () => {
  const dir = await site();
  const manifest = await writePrecache(dir, BUILD);
  assert.deepEqual(JSON.parse(await readFile(join(dir, 'precache.json'), 'utf8')), manifest);
  assert.equal(manifest.build, BUILD);
  assert.deepEqual(manifest.shells, ['/']);
  assert.deepEqual(manifest.assets, ['/assets/app.abcdef0123.js', '/assets/index.0123456789.js', '/assets/styles.fedcba9876.css']);
  assert.deepEqual(manifest.static, ['/app-icon-192.png', '/manifest.webmanifest', '/vendor/leaflet.js', '/vendor/leaflet.css', '/vendor/images/marker-icon.png']);
  assert.ok(!manifest.assets.some(a => a.endsWith('.html')), 'pages are served only from their stable paths');
  assert.ok(!JSON.stringify(manifest).includes('regulations.json'), 'data is never precached; it is network-first');
  // The worker carries the build id, so a deploy changes its bytes and reinstalls it.
  const sw = await readFile(join(dir, 'sw.js'), 'utf8');
  assert.ok(sw.startsWith(`const BUILD = '${BUILD}';`));
});

test('the build refuses a worker without the build placeholder, and a missing vendor file', async () => {
  const dir = await site();
  await writeFile(join(dir, 'sw.js'), 'self.x=1');
  await assert.rejects(writePrecache(dir, 'abc1234567'), /must declare/);
  const other = await site();
  await rm(join(other, 'vendor/leaflet.css'));
  await assert.rejects(precacheManifest(other, 'abc1234567'));
});

test('the committed worker declares the placeholder the build replaces', async () => {
  const sw = await readFile(new URL('../dist/sw.js', import.meta.url), 'utf8');
  assert.ok(sw.includes(BUILD_PLACEHOLDER));
});

// FE-51: the v2-only chunks leave the install list; the v2 list is what the app needs offline.
test('only-v2 files leave the install precache; the v2 list is the app graph without the terrain renderer, plus the glyphs', async () => {
  const dir = await site();
  const manifest = {
    'index.html': {file: 'assets/index.0123456789.js', isEntry: true, imports: ['_shared.js'], dynamicImports: ['three.js']},
    'app.html': {file: 'assets/app.1111111111.js', isEntry: true, css: ['assets/app.2222222222.css'], assets: ['assets/font.3333333333.woff2'],
      imports: ['_shared.js'], dynamicImports: ['../web/map/maplibre.js', '../web/map/terrain.js']},
    'landing.html': {file: 'assets/landing.4444444444.js', isEntry: true},
    '_shared.js': {file: 'assets/shared.5555555555.js'},
    '../web/map/maplibre.js': {file: 'assets/maplibre.6666666666.js', assets: ['assets/maplibre-gl-worker.7777777777.js'], isDynamicEntry: true},
    '../web/map/terrain.js': {file: 'assets/terrain.8888888888.js', imports: ['three.js'], isDynamicEntry: true},
    'three.js': {file: 'assets/three.9999999999.js'},
  };
  await mkdir(join(dir, '.vite'), {recursive: true});
  await mkdir(join(dir, 'basemap/glyphs/dm-sans-medium'), {recursive: true});
  await writeFile(join(dir, 'basemap/glyphs/dm-sans-medium/0-255.pbf'), 'pbf');
  await writeFile(join(dir, 'basemap/glyphs/DM-SANS-OFL.txt'), 'licence');
  await writeFile(join(dir, '.vite/manifest.json'), JSON.stringify(manifest));
  for (const e of Object.values(manifest)) for (const f of [e.file, ...(e.css || []), ...(e.assets || [])]) await writeFile(join(dir, f), '');
  assert.deepEqual([...v2Only(manifest)].sort(), ['/assets/app.1111111111.js', '/assets/app.2222222222.css', '/assets/font.3333333333.woff2', '/assets/landing.4444444444.js',
    '/assets/maplibre-gl-worker.7777777777.js', '/assets/maplibre.6666666666.js', '/assets/terrain.8888888888.js'], 'three is shared with v1 (its coast workspace)');
  const out = await precacheManifest(dir, BUILD);
  assert.ok(out.assets.includes('/assets/shared.5555555555.js') && out.assets.includes('/assets/three.9999999999.js') && out.assets.includes('/assets/index.0123456789.js'));
  assert.ok(!out.assets.some(a => v2Only(manifest).has(a)) && out.assets.includes('/assets/app.abcdef0123.js'), 'a v1 visitor never stores the v2-only chunks');
  assert.deepEqual(out.v2.assets, [...reachable(manifest, ['app.html'], new Set(['../web/map/terrain.js']))].sort());
  assert.deepEqual(out.v2.assets, ['/assets/app.1111111111.js', '/assets/app.2222222222.css', '/assets/font.3333333333.woff2', '/assets/maplibre-gl-worker.7777777777.js',
    '/assets/maplibre.6666666666.js', '/assets/shared.5555555555.js']);
  assert.deepEqual(out.v2.static, ['/basemap/glyphs/dm-sans-medium/0-255.pbf']);
});
