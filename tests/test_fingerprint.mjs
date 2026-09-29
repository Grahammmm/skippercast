import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, writeFile, readdir, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fingerprint, hashName, rewrite} from '../scripts/fingerprint.mjs';

test('rewrites only references to known assets and drops legacy ?v= queries', () => {
  const names = new Set(['app.js', 'styles.css', 'worker.js']);
  const out = rewrite(`import x from './app.js?v=8.14';\nnew URL('./worker.js',import.meta.url);\n<link href="styles.css?v=1">\nfetch('data/app.js.json');\nimport y from './other.js';`, names, 'abc1234567');
  assert.match(out, /'\.\/app\.abc1234567\.js'/);
  assert.match(out, /'\.\/worker\.abc1234567\.js'/);
  assert.match(out, /href="styles\.abc1234567\.css"/);
  assert.match(out, /'data\/app\.js\.json'/);
  assert.match(out, /'\.\/other\.js'/);
  assert.equal(hashName('index.html', 'abc1234567'), 'index.abc1234567.html');
});

test('fingerprint renames assets, maps stable page paths and changes id with content', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'fp-'));
  await writeFile(join(dir, 'index.html'), '<script type="module" src="boot.js"></script>');
  await writeFile(join(dir, 'boot.js'), "import './app.js';");
  await writeFile(join(dir, 'app.js'), 'export default 1;');
  await writeFile(join(dir, 'data.json'), '{}');
  const {buildId, shells} = await fingerprint(dir);
  const files = (await readdir(dir)).sort();
  assert.deepEqual(files, [`app.${buildId}.js`, `boot.${buildId}.js`, 'data.json', `index.${buildId}.html`].sort());
  assert.equal(shells['/'], `/index.${buildId}.html`);
  assert.match(await readFile(join(dir, `boot.${buildId}.js`), 'utf8'), new RegExp(`app\\.${buildId}\\.js`));
  const other = await mkdtemp(join(tmpdir(), 'fp-'));
  await writeFile(join(other, 'app.js'), 'export default 2;');
  assert.notEqual((await fingerprint(other)).buildId, buildId);
});

test('the service worker keeps its stable URL so /sw.js registration works', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'fp-'));
  await writeFile(join(dir, 'trip-alerts.js'), "navigator.serviceWorker.register('/sw.js');");
  await writeFile(join(dir, 'sw.js'), "self.addEventListener('push',()=>{});");
  const {buildId} = await fingerprint(dir);
  const files = (await readdir(dir)).sort();
  assert.deepEqual(files, ['sw.js', `trip-alerts.${buildId}.js`].sort());
  assert.match(await readFile(join(dir, `trip-alerts.${buildId}.js`), 'utf8'), /register\('\/sw\.js'\)/);
});
