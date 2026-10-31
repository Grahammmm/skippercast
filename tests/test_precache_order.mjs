import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, mkdir, writeFile, readFile, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {writePrecache, BUILD_PLACEHOLDER} from '../scripts/precache.mjs';

// writePrecache checks sw.js before it writes either file, so a refusal
// leaves the folder byte-identical.
const BUILD = 'abc1234567';

async function site(sw = `${BUILD_PLACEHOLDER}\nself.addEventListener('push',()=>{});`) {
  const dir = await mkdtemp(join(tmpdir(), 'precache-order-'));
  await mkdir(join(dir, 'assets'), {recursive: true});
  await writeFile(join(dir, `index.${BUILD}.html`), '<script type="module" src="./assets/index.0123456789.js"></script>');
  await writeFile(join(dir, 'assets/index.0123456789.js'), "import './app.abcdef0123.js';");
  await writeFile(join(dir, 'assets/app.abcdef0123.js'), "navigator.serviceWorker.register('/sw.js');");
  await writeFile(join(dir, 'assets/styles.fedcba9876.css'), 'body{}');
  if (sw !== null) await writeFile(join(dir, 'sw.js'), sw);
  await writeFile(join(dir, 'manifest.webmanifest'), '{}');
  await writeFile(join(dir, 'app-icon-192.png'), 'png');
  return dir;
}

const exists = path => access(path).then(() => true, () => false);
const bytes = path => readFile(path);

test('a worker without the placeholder or a stamp is refused before precache.json is written', async () => {
  const dir = await site('self.x=1');
  await assert.rejects(writePrecache(dir, BUILD), /must declare const BUILD = 'dev';/);
  assert.equal(await exists(join(dir, 'precache.json')), false);
  assert.equal(await readFile(join(dir, 'sw.js'), 'utf8'), 'self.x=1');
});

test('an already stamped worker is named and neither file changes', async () => {
  const dir = await site();
  await writePrecache(dir, BUILD);
  const precache = await bytes(join(dir, 'precache.json'));
  const sw = await bytes(join(dir, 'sw.js'));
  await assert.rejects(writePrecache(dir, 'bcd2345678'),
    /^Error: sw\.js is already stamped with build abc1234567; rebuild into a clean folder$/);
  assert.ok(precache.equals(await bytes(join(dir, 'precache.json'))), 'precache.json changed');
  assert.ok(sw.equals(await bytes(join(dir, 'sw.js'))), 'sw.js changed');
});

test('a stale precache.json is left untouched when the worker is refused', async () => {
  const dir = await site("self.addEventListener('push',()=>{});");
  const stale = Buffer.from('{"build":"old0000000"}\n');
  await writeFile(join(dir, 'precache.json'), stale);
  await assert.rejects(writePrecache(dir, BUILD), /must declare/);
  assert.ok(stale.equals(await bytes(join(dir, 'precache.json'))), 'stale precache.json changed');
});

test('a missing sw.js rejects with ENOENT and creates no precache.json', async () => {
  const dir = await site(null);
  await assert.rejects(writePrecache(dir, BUILD), {code: 'ENOENT'});
  assert.equal(await exists(join(dir, 'precache.json')), false);
  assert.equal(await exists(join(dir, 'sw.js')), false);
});

test('a fresh site still writes the manifest and stamps the worker', async () => {
  const dir = await site();
  const manifest = await writePrecache(dir, BUILD);
  assert.deepEqual(JSON.parse(await readFile(join(dir, 'precache.json'), 'utf8')), manifest);
  assert.equal(manifest.build, BUILD);
  assert.ok((await readFile(join(dir, 'sw.js'), 'utf8')).startsWith(`const BUILD = '${BUILD}';\n`));
});

test('the placeholder wins over a later stamp-like comment', async () => {
  const dir = await site(`${BUILD_PLACEHOLDER}\n// const BUILD = 'x';\nself.y=1;`);
  await writePrecache(dir, BUILD);
  const sw = await readFile(join(dir, 'sw.js'), 'utf8');
  assert.equal(sw, `const BUILD = '${BUILD}';\n// const BUILD = 'x';\nself.y=1;`);
  assert.equal(await exists(join(dir, 'precache.json')), true);
});

test('a stamp-like line inside a comment is not reported as a stamp', async () => {
  const dir = await site("  // const BUILD = 'x';\nself.y=1;");
  await assert.rejects(writePrecache(dir, BUILD), /must declare/);
  assert.equal(await exists(join(dir, 'precache.json')), false);
});
