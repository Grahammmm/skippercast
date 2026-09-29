import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, readFile, rm} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fingerprint} from '../scripts/fingerprint.mjs';
import {precacheManifest, writePrecache, BUILD_PLACEHOLDER} from '../scripts/precache.mjs';

const run = promisify(execFile);
const CHECK = new URL('../scripts/check_client.mjs', import.meta.url).pathname;

async function site() {
  const dir = await mkdtemp(join(tmpdir(), 'precache-'));
  await mkdir(join(dir, 'vendor/images'), {recursive: true});
  await writeFile(join(dir, 'index.html'), '<link rel="stylesheet" href="styles.css"><script type="module" src="boot.js"></script>');
  await writeFile(join(dir, 'boot.js'), "import './app.js';");
  await writeFile(join(dir, 'app.js'), "navigator.serviceWorker.register('/sw.js');");
  await writeFile(join(dir, 'styles.css'), 'body{}');
  await writeFile(join(dir, 'sw.js'), `${BUILD_PLACEHOLDER}\nself.addEventListener('push',()=>{});`);
  await writeFile(join(dir, 'manifest.webmanifest'), '{}');
  await writeFile(join(dir, 'app-icon-192.png'), 'png');
  await writeFile(join(dir, 'regulations.json'), '{}');
  await writeFile(join(dir, 'vendor/leaflet.js'), '');
  await writeFile(join(dir, 'vendor/leaflet.css'), '');
  await writeFile(join(dir, 'vendor/images/marker-icon.png'), '');
  return dir;
}

test('precache.json lists the shell, every fingerprinted asset of the build and the static shell files', async () => {
  const dir = await site();
  const {buildId} = await fingerprint(dir);
  const manifest = await writePrecache(dir, buildId);
  assert.deepEqual(JSON.parse(await readFile(join(dir, 'precache.json'), 'utf8')), manifest);
  assert.equal(manifest.build, buildId);
  assert.deepEqual(manifest.shells, ['/']);
  assert.deepEqual(manifest.assets, [`/app.${buildId}.js`, `/boot.${buildId}.js`, `/styles.${buildId}.css`]);
  assert.deepEqual(manifest.static, ['/app-icon-192.png', '/manifest.webmanifest', '/vendor/leaflet.js', '/vendor/leaflet.css', '/vendor/images/marker-icon.png']);
  assert.ok(!manifest.assets.some(a => a.endsWith('.html')), 'pages are served only from their stable paths');
  assert.ok(!JSON.stringify(manifest).includes('regulations.json'), 'data is never precached; it is network-first');
  // The worker carries the build id, so a deploy changes its bytes and reinstalls it.
  const sw = await readFile(join(dir, 'sw.js'), 'utf8');
  assert.ok(sw.startsWith(`const BUILD = '${buildId}';`));
  const {stdout} = await run(process.execPath, [CHECK, dir]);
  assert.match(stdout, new RegExp(`precached for build ${buildId}`));
});

test('check_client fails on a stale precache list or a worker without the build id', async () => {
  const dir = await site();
  const {buildId} = await fingerprint(dir);
  const manifest = await writePrecache(dir, buildId);
  await writeFile(join(dir, 'precache.json'), JSON.stringify({...manifest, assets: manifest.assets.slice(1)}));
  await assert.rejects(run(process.execPath, [CHECK, dir]), /precache\.json assets differ/);
  await writeFile(join(dir, 'precache.json'), JSON.stringify(manifest));
  await writeFile(join(dir, 'sw.js'), `const BUILD = 'old1234567';`);
  await assert.rejects(run(process.execPath, [CHECK, dir]), /sw\.js does not carry the precache build id/);
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
