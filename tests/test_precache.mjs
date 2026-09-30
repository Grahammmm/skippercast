import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {precacheManifest, writePrecache, BUILD_PLACEHOLDER} from '../scripts/precache.mjs';

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
