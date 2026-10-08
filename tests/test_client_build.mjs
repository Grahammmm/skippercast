// The Vite client build contract (P4-01a): hashed assets from the Vite
// manifest, pages served from stable paths, a stable /sw.js, vendored files
// with SRI left in place, and the boot chain modulepreloaded. Replaces the
// tests of the retired scripts/fingerprint.mjs.
import assert from 'node:assert/strict';
import test from 'node:test';
import {execFile} from 'node:child_process';
import {mkdtemp, mkdir, readdir, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {promisify} from 'node:util';
import {buildClient, hashName} from '../scripts/client-build.mjs';
import {BUILD_PLACEHOLDER} from '../scripts/precache.mjs';
import {bootPreloadRoots, preloadChunks} from '../scripts/vite-preload.mjs';
import {STATIC_REF} from '../vite.config.mjs';

const run = promisify(execFile);
const CHECK = new URL('../scripts/check_client.mjs', import.meta.url).pathname;
const DIST = new URL('../dist/', import.meta.url).pathname;
const SRI = 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=';

async function site({app = 'export const ready = true;'} = {}) {
  const root = await mkdtemp(join(tmpdir(), 'client-src-'));
  await mkdir(join(root, 'vendor'), {recursive: true});
  await mkdir(join(root, 'data'), {recursive: true});
  await writeFile(join(root, 'index.html'), `<!doctype html><html><head>
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="vendor/leaflet.css" integrity="${SRI}">
<script src="vendor/leaflet.js" integrity="${SRI}" defer></script>
<link rel="manifest" href="manifest.webmanifest"/>
<link rel="apple-touch-icon" href="apple-touch-icon.png"/>
<script type="module" src="boot.js"></script></head><body><a href="about.html">About</a></body></html>`);
  await writeFile(join(root, 'about.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>About</body></html>');
  await writeFile(join(root, 'boot.js'), "void (async()=>{await import('./app.js');void import('./coastal-discovery.js');})();");
  await writeFile(join(root, 'app.js'), `import {helper} from './helper.js';\n${app}\nhelper();\nnavigator.serviceWorker?.register('/sw.js');`);
  await writeFile(join(root, 'helper.js'), 'export function helper() { return 1; }');
  await writeFile(join(root, 'coastal-discovery.js'), 'export const coast = 1;');
  await writeFile(join(root, 'styles.css'), 'body{color:#082e3b}');
  await writeFile(join(root, 'sw.js'), `${BUILD_PLACEHOLDER}\nself.addEventListener('push',()=>{});`);
  await writeFile(join(root, 'manifest.webmanifest'), '{}');
  await writeFile(join(root, 'app-icon-192.png'), 'png');
  await writeFile(join(root, 'apple-touch-icon.png'), 'png');
  await writeFile(join(root, 'data/regulations.json'), '{}');
  await writeFile(join(root, 'vendor/leaflet.js'), '');
  await writeFile(join(root, 'vendor/leaflet.css'), '');
  return root;
}

const built = async (options) => {
  const root = await site(options);
  const out = join(root, 'client');
  return {root, out, ...(await buildClient({root, out, headers: '/*\n'}))};
};

test('hashName inserts the build id before the extension', () => {
  assert.equal(hashName('index.html', 'abc1234567'), 'index.abc1234567.html');
});

test('the build hashes scripts and styles, renames pages and keeps sw.js, vendor files and data stable', async () => {
  const {out, buildId, shells} = await built();
  const top = (await readdir(out)).sort();
  assert.ok(top.includes(`index.${buildId}.html`) && top.includes(`about.${buildId}.html`));
  assert.ok(!top.includes('index.html') && !top.includes('app.js') && !top.includes('styles.css'), 'no authored source is published raw');
  assert.deepEqual(shells, {'/': `/index.${buildId}.html`, '/index.html': `/index.${buildId}.html`, '/about.html': `/about.${buildId}.html`});
  for (const name of await readdir(join(out, 'assets'))) assert.match(name, /^[\w.-]+\.[0-9a-f]{10}\.(?:js|css)$/);
  assert.equal(await readFile(join(out, 'data/regulations.json'), 'utf8'), '{}');
  assert.ok((await readFile(join(out, 'sw.js'), 'utf8')).startsWith(`const BUILD = '${buildId}';`));
  assert.equal(await readFile(join(out, '.assetsignore'), 'utf8'), '.vite\n');
  assert.equal(await readFile(join(out, '_headers'), 'utf8'), '/*\n/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n');
  const html = await readFile(join(out, `index.${buildId}.html`), 'utf8');
  // Vendored files keep their stable path and SRI; the manifest and icons are not hashed.
  assert.match(html, new RegExp(`<script\\s+src="vendor/leaflet\\.js" integrity="${SRI.replace(/[+/]/g, '\\$&')}" defer>`));
  assert.match(html, /<link\s+rel="stylesheet" href="vendor\/leaflet\.css" integrity=/);
  assert.match(html, /<link\s+rel="manifest" href="manifest\.webmanifest"\/>/);
  assert.match(html, /<link\s+rel="apple-touch-icon" href="apple-touch-icon\.png"\/>/);
  assert.doesNotMatch(html, /vite-ignore/);
  assert.ok(html.includes(`<meta name="skippercast-build" content="${buildId}">\n</head>`), 'the page names its build for error reports');
  assert.match(html, /<script type="module" crossorigin src="\.\/assets\/index\.[0-9a-f]{10}\.js">/);
  // The page link stays a stable path; the Worker maps it to the hashed page.
  assert.match(html, /href="about\.html"/);
  const precache = JSON.parse(await readFile(join(out, 'precache.json'), 'utf8'));
  assert.equal(precache.build, buildId);
  assert.ok(precache.assets.length >= 3 && precache.assets.every(a => /^\/assets\/[\w.-]+\.[0-9a-f]{10}\.(?:js|css)$/.test(a)));
  assert.ok(!JSON.stringify(precache).includes('regulations.json'), 'data is never precached; it is network-first');
});

test('the boot chain is modulepreloaded, except ?coast= discovery', async () => {
  const {out, buildId, manifest} = await built();
  const html = await readFile(join(out, `index.${buildId}.html`), 'utf8');
  const preloaded = [...html.matchAll(/rel="modulepreload"[^>]*href="\.\/([^"]+)"/g)].map(m => m[1]);
  assert.ok(preloaded.includes(manifest['app.js'].file), 'app.js chunk');
  for (const key of manifest['app.js'].imports || []) assert.ok(preloaded.includes(manifest[key].file), key);
  assert.ok(!preloaded.includes(manifest['coastal-discovery.js'].file));
  assert.equal(new Set(preloaded).size, preloaded.length, 'duplicate modulepreload');
});

test('the build id changes when any module changes', async () => {
  const a = await built(), b = await built({app: 'export const ready = false;'});
  assert.notEqual(a.buildId, b.buildId);
});

test('check_client passes a good build and fails on missing chunks, raw sources, stale precache and a worker without the build id', async () => {
  const {root, out, buildId} = await built();
  const {stdout} = await run(process.execPath, [CHECK, out, root]);
  assert.match(stdout, new RegExp(`precached for build ${buildId}`));
  const precache = JSON.parse(await readFile(join(out, 'precache.json'), 'utf8'));

  await writeFile(join(out, 'app.js'), '');
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /app\.js \(unbundled script or stylesheet/);
  await rm(join(out, 'app.js'));

  await writeFile(join(out, 'precache.json'), JSON.stringify({...precache, assets: precache.assets.slice(1)}));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /precache\.json assets differ/);
  await writeFile(join(out, 'precache.json'), JSON.stringify(precache));

  const sw = await readFile(join(out, 'sw.js'), 'utf8');
  await writeFile(join(out, 'sw.js'), `const BUILD = 'old1234567';`);
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /sw\.js does not carry the precache build id/);
  await writeFile(join(out, 'sw.js'), sw);

  const page = join(out, `index.${buildId}.html`), html = await readFile(page, 'utf8');
  await writeFile(page, html.replace(/ integrity="[^"]+"/, ''));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /without an integrity attribute/);
  await writeFile(page, html.replace('</head>', '<script type="module" src="plain.js"></script></head>'));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /plain\.js \(missing\)/);
  await writeFile(page, html.replace(/<link rel="modulepreload"[^>]*>/, ''));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /does not modulepreload/);
  await writeFile(page, html);

  const [chunk] = (await readdir(join(out, 'assets'))).filter(n => n.startsWith('helper.') || n.startsWith('app.'));
  await rm(join(out, 'assets', chunk));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /\(missing\)/);
});

test('check_client fails a v2 page over its gzipped JavaScript or CSS budget (FE-09)', async () => {
  const root = await site();
  await writeFile(join(root, 'app.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"><script type="module" src="shell.js"></script></head><body>v2</body></html>');
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nexport const pad = ${JSON.stringify(Array.from({length: 400}, (_, i) => `${i}-${Math.sin(i)}`))};\nhelper(pad);`);
  const out = join(root, 'client');
  await buildClient({root, out, headers: '/*\n'});
  const budget = join(root, 'budget.json'), check = b => { return writeFile(budget, JSON.stringify({bundles: {'app.html': b}})).then(() => run(process.execPath, [CHECK, out, root, budget])); };
  const {stdout} = await check({js_gzip_max: 100000, css_gzip_max: 1000});
  assert.match(stdout, /Budgets: app\.html js \d+ B, css \d+ B gzipped/);
  await assert.rejects(check({js_gzip_max: 500}), /app\.html: initial JavaScript \d+ B gzipped exceeds its budget of 500 B/);
  await assert.rejects(check({css_gzip_max: 1}), /app\.html: initial CSS \d+ B gzipped exceeds its budget of 1 B/);
  await rm(root, {recursive: true, force: true});
});

test('check_client fails when the v2 app entry statically imports three (FE-71)', async () => {
  const root = await site();
  const renderer = 'export const make = () => { throw new Error("THREE.WebGLRenderer: Error creating WebGL context."); };';
  await writeFile(join(root, 'renderer.js'), renderer);
  await writeFile(join(root, 'app.html'), '<!doctype html><html><head><script type="module" src="shell.js"></script></head><body>v2</body></html>');
  const out = join(root, 'client');
  // A dynamic import keeps the renderer out of the entry's static imports.
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nhelper(1);\nexport const later = () => import('./renderer.js');`);
  await buildClient({root, out, headers: '/*\n'});
  await run(process.execPath, [CHECK, out, root]);
  await rm(out, {recursive: true, force: true});
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nimport {make} from './renderer.js';\nhelper(make);`);
  await buildClient({root, out, headers: '/*\n'});
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /app\.html statically imports assets\/[\w.-]+\.js, which contains three/);
  await rm(root, {recursive: true, force: true});
});

test('the real site builds and passes the client check (static data directories skipped)', async () => {
  const out = await mkdtemp(join(tmpdir(), 'client-real-'));
  const keep = name => !['data', 'regions', 'downloads', 'tiles'].includes(name);
  const {buildId} = await buildClient({root: DIST, out, copy: keep});
  const {stdout} = await run(process.execPath, [CHECK, out, DIST]);
  assert.match(stdout, new RegExp(`precached for build ${buildId}`));
  await rm(out, {recursive: true, force: true});
});

test('boot preload roots are boot.js dynamic imports without coastal discovery', async () => {
  const roots = bootPreloadRoots(await readFile(join(DIST, 'boot.js'), 'utf8'));
  assert.ok(roots.includes('app.js') && roots.includes('home-port.js') && roots.includes('first-run.js'));
  assert.ok(!roots.includes('coastal-discovery.js'));
  const bundle = {
    'a.js': {type: 'chunk', fileName: 'a.js', facadeModuleId: '/r/a.js', moduleIds: ['/r/a.js'], imports: ['s.js']},
    's.js': {type: 'chunk', fileName: 's.js', facadeModuleId: null, moduleIds: ['/r/b.js', '/r/c.js'], imports: []},
    'b.js': {type: 'chunk', fileName: 'b.js', facadeModuleId: '/r/b.js', moduleIds: [], imports: ['s.js']},
  };
  assert.deepEqual(preloadChunks(bundle, ['/r/a.js', '/r/b.js', '/r/c.js']), ['a.js', 's.js', 'b.js']);
  assert.deepEqual(preloadChunks(bundle, ['/r/a.js'], new Set(['s.js'])), ['a.js']);
});

test('only vendor files, the web manifest and icons are left out of the Vite build', () => {
  const mark = html => html.replace(STATIC_REF, '<$1 vite-ignore');
  assert.match(mark('<script src="vendor/leaflet.js" integrity="x" defer></script>'), /^<script vite-ignore src=/);
  assert.match(mark('<link rel="stylesheet" href="vendor/maplibre-5.24.0/maplibre-gl.css" />'), /^<link vite-ignore /);
  assert.match(mark('<link rel="manifest" href="manifest.webmanifest"/>'), /vite-ignore/);
  assert.match(mark('<link rel="apple-touch-icon" href="apple-touch-icon.png"/>'), /vite-ignore/);
  assert.doesNotMatch(mark('<link rel="stylesheet" href="tokens.css" />'), /vite-ignore/);
  assert.doesNotMatch(mark('<script type="module" src="boot.js"></script>'), /vite-ignore/);
});
