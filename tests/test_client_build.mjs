// The Vite client build contract (P4-01a): hashed assets from the Vite
// manifest, pages served from stable paths, a stable /sw.js, vendored files
// with SRI left in place. Replaces the tests of the retired
// scripts/fingerprint.mjs. FE-61 retired the v1 shell's boot-chain preload
// (scripts/vite-preload.mjs) with the shell; the fixture page stands in for a v2 page.
import assert from 'node:assert/strict';
import test from 'node:test';
import {execFile} from 'node:child_process';
import {mkdtemp, mkdir, readdir, readFile, rm, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {promisify} from 'node:util';
import {buildClient, copyReliefPointers, copyStatic, glyphVersion, hashName, IMMUTABLE_ASSETS, IMMUTABLE_GLYPHS, REVALIDATE, SAFETY_FILES, STATIC_DATA, STATIC_MAX_AGE_S, STATIC_SWR_S, versionGlyphs} from '../scripts/client-build.mjs';
import {BUILD_PLACEHOLDER} from '../scripts/precache.mjs';
import {GLYPH_VERSION} from '../web/map/style.ts';
import {dropMaplibreLogo, MAPLIBRE_CSS, STATIC_REF} from '../vite.config.mjs';

const run = promisify(execFile);
const CHECK = new URL('../scripts/check_client.mjs', import.meta.url).pathname;
const DIST = new URL('../dist/', import.meta.url).pathname;
const SRI = 'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=';

async function site(t, {app = 'export const ready = true;'} = {}) {
  const fixture = await mkdtemp(join(tmpdir(), 'client-src-'));
  t.after(() => rm(fixture, {recursive: true, force: true}));
  const root = join(fixture, 'dist');
  await mkdir(join(fixture, 'web/app'), {recursive: true});
  await writeFile(join(fixture, 'web/app/early.ts'), "document.documentElement.dataset.early = 'ready';");
  await mkdir(join(root, 'vendor'), {recursive: true});
  await mkdir(join(root, 'data'), {recursive: true});
  await writeFile(join(root, 'landing.html'), `<!doctype html><html><head>
<link rel="stylesheet" href="styles.css">
<link rel="stylesheet" href="vendor/lib.css" integrity="${SRI}">
<script src="vendor/lib.js" integrity="${SRI}" defer></script>
<link rel="manifest" href="manifest.webmanifest"/>
<link rel="apple-touch-icon" href="apple-touch-icon.png"/>
<script type="module" src="main.js"></script></head><body><a href="about.html">About</a></body></html>`);
  // check_client requires both v2 pages.
  await writeFile(join(root, 'app.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"><script type="module" src="app.js"></script></head><body>app</body></html>');
  await writeFile(join(root, 'about.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>About</body></html>');
  await writeFile(join(root, 'main.js'), "void (async()=>{await import('./app.js');})();");
  await writeFile(join(root, 'app.js'), `import {helper} from './helper.js';\n${app}\nhelper();\nnavigator.serviceWorker?.register('/sw.js');`);
  await writeFile(join(root, 'helper.js'), 'export function helper() { return 1; }');
  await writeFile(join(root, 'styles.css'), 'body{color:#082e3b}');
  await writeFile(join(root, 'sw.js'), `${BUILD_PLACEHOLDER}\nself.addEventListener('push',()=>{});`);
  await writeFile(join(root, 'manifest.webmanifest'), '{}');
  await writeFile(join(root, 'app-icon-192.png'), 'png');
  await writeFile(join(root, 'apple-touch-icon.png'), 'png');
  await writeFile(join(root, 'data/regulations.json'), '{}');
  await writeFile(join(root, 'vendor/lib.js'), '');
  await writeFile(join(root, 'vendor/lib.css'), '');
  return root;
}

const built = async (t, options) => {
  const root = await site(t, options);
  const out = join(root, 'client');
  return {root, out, ...(await buildClient({root, out, headers: '/*\n'}))};
};

test('hashName inserts the build id before the extension', () => {
  assert.equal(hashName('index.html', 'abc1234567'), 'index.abc1234567.html');
});

test('copyStatic never publishes local-only seafloor .part files or tide layer data', async () => {
  const src = await mkdtemp(join(tmpdir(), 'sc-static-src-'));
  const out = await mkdtemp(join(tmpdir(), 'sc-static-out-'));
  try {
    await mkdir(join(src, 'tiles'));
    for (const name of ['morro-bay-seafloor-deep.part', 'morro-bay-seafloor-deep-strong.part', 'tide-layer-central-coast.json', 'tide-layer-central-coast.part', 'tide-layer-Central_Coast.json', 'tide-layer-Central_Coast.part', 'socal-survey-habitat.pmtiles']) await writeFile(join(src, 'tiles', name), 'x');
    await copyStatic(src, out);
    assert.deepEqual(await readdir(join(out, 'tiles')), ['socal-survey-habitat.pmtiles']);
  } finally {
    await rm(src, {recursive: true, force: true});
    await rm(out, {recursive: true, force: true});
  }
});

test('copyStatic refuses local-only seafloor Deep archives rather than silently skipping them', async () => {
  const src = await mkdtemp(join(tmpdir(), 'sc-static-src-'));
  const out = await mkdtemp(join(tmpdir(), 'sc-static-out-'));
  try {
    await mkdir(join(src, 'tiles'));
    for (const name of ['morro-bay-seafloor-deep.pmtiles', 'morro-bay-seafloor-deep-mild.pmtiles']) {
      await writeFile(join(src, 'tiles', name), 'x');
      await assert.rejects(copyStatic(src, out), new RegExp(name.replace('.', '\\.')));
      await rm(join(src, 'tiles', name));
    }
  } finally {
    await rm(src, {recursive: true, force: true});
    await rm(out, {recursive: true, force: true});
  }
});

test('copyStatic fails on a *.pmtiles that is not on the allowlist (E2E-13)', async () => {
  const src = await mkdtemp(join(tmpdir(), 'sc-static-src-'));
  const out = await mkdtemp(join(tmpdir(), 'sc-static-out-'));
  try {
    await mkdir(join(src, 'tiles'));
    await writeFile(join(src, 'tiles', 'laguna-seafloor-deep-medium.pmtiles'), 'x');
    await assert.rejects(copyStatic(src, out), /laguna-seafloor-deep-medium\.pmtiles/);
  } finally {
    await rm(src, {recursive: true, force: true});
    await rm(out, {recursive: true, force: true});
  }
});

test('copyStatic refuses raw shore snapshots and linked assets (F20-04)', async () => {
  const root = await mkdtemp(join(tmpdir(), 'sc-static-shore-'));
  const src = join(root, 'dist'), out = join(root, 'client'), privateDir = join(root, 'var');
  const marker = 'SYNTHETIC-RAW-SHORE-MARKER';
  try {
    await mkdir(join(src, 'data', 'nested'), {recursive: true});
    await mkdir(privateDir);
    await writeFile(join(privateDir, 'ccc-access-points.json'), JSON.stringify({Description: marker}));
    const publicName = 'data/shore-habitat.geojson';
    const publicBytes = '{"type":"FeatureCollection","features":[]}';
    await writeFile(join(src, publicName), publicBytes);
    await copyStatic(src, out);
    assert.equal(await readFile(join(out, publicName), 'utf8'), publicBytes);
    assert.deepEqual((await readdir(out, {recursive: true, withFileTypes: true}))
      .filter(e => !e.isDirectory()).map(e => e.name), ['shore-habitat.geojson']);

    // A stale archive dropped into dist (including a leftover atomic-write file) must fail, not copy.
    for (const name of ['ccc-access-points.json', 'data/nested/ccc-access-item.json',
      'data/nested/ccc-access-estero.json', 'data/nested/noaa-esi-shoreline.json',
      'data/nested/receipts.json', 'data/nested/.ccc-access-points.json.123.tmp']) {
      const path = join(src, name);
      await writeFile(path, marker);
      await assert.rejects(copyStatic(src, out), {message: `refusing to publish ${name}: raw shore source artifact`});
      await assert.rejects(readFile(join(out, name)), {code: 'ENOENT'});
      await rm(path);
    }
    // A directory link has no raw filename until followed. Do not stage the link itself.
    await symlink(privateDir, join(src, 'data', 'alias'), 'dir');
    await assert.rejects(copyStatic(src, out), /refusing to publish data\/alias: symbolic link/);
    assert.deepEqual((await readdir(out, {recursive: true, withFileTypes: true}))
      .filter(e => !e.isDirectory()).map(e => e.name), ['shore-habitat.geojson']);
  } finally {
    await rm(root, {recursive: true, force: true});
  }
});

test('C3: the build preserves stable files, hashes scripts and pages, and writes headers in order', async t => {
  const {out, buildId, shells} = await built(t);
  const top = (await readdir(out)).sort();
  assert.ok(top.includes(`landing.${buildId}.html`) && top.includes(`about.${buildId}.html`));
  assert.ok(!top.includes('landing.html') && !top.includes('app.js') && !top.includes('styles.css'), 'no authored source is published raw');
  // '/' and '/map' are chosen by server/routes/assets.ts; the build maps each page's own path.
  assert.deepEqual(shells, {'/about.html': `/about.${buildId}.html`, '/app.html': `/app.${buildId}.html`, '/landing.html': `/landing.${buildId}.html`});
  for (const name of await readdir(join(out, 'assets'))) assert.match(name, /^[\w.-]+\.[0-9a-f]{10}\.(?:js|css)$/);
  assert.equal(await readFile(join(out, 'data/regulations.json'), 'utf8'), '{}');
  assert.ok((await readFile(join(out, 'sw.js'), 'utf8')).startsWith(`const BUILD = '${buildId}';`));
  assert.equal(await readFile(join(out, '.assetsignore'), 'utf8'), '.vite\n');
  assert.equal(await readFile(join(out, '_headers'), 'utf8'), '/*\n/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n'
    + '/basemap/glyphs/v/*\n  Cache-Control: public, max-age=31536000, immutable\n' + EXPECTED_STATIC + EXPECTED_SAFETY);
  const html = await readFile(join(out, `landing.${buildId}.html`), 'utf8');
  // Vendored files keep their stable path and SRI; the manifest and icons are not hashed.
  assert.match(html, new RegExp(`<script\\s+src="vendor/lib\\.js" integrity="${SRI.replace(/[+/]/g, '\\$&')}" defer>`));
  assert.match(html, /<link\s+rel="stylesheet" href="vendor\/lib\.css" integrity=/);
  assert.match(html, /<link\s+rel="manifest" href="manifest\.webmanifest"\/>/);
  assert.match(html, /<link\s+rel="apple-touch-icon" href="apple-touch-icon\.png"\/>/);
  assert.doesNotMatch(html, /vite-ignore/);
  assert.ok(html.includes(`<meta name="skippercast-build" content="${buildId}">\n</head>`), 'the page names its build for error reports');
  assert.match(html, /<script type="module" crossorigin src="\.\/assets\/landing\.[0-9a-f]{10}\.js">/);
  // The page link stays a stable path; the Worker maps it to the hashed page.
  assert.match(html, /href="about\.html"/);
  const precache = JSON.parse(await readFile(join(out, 'precache.json'), 'utf8'));
  assert.equal(precache.build, buildId);
  assert.ok(precache.assets.length >= 2 && precache.assets.every(a => /^\/assets\/[\w.-]+\.[0-9a-f]{10}\.(?:js|css)$/.test(a)));
  // #497 and FE-51: the landing's first paint is installed; the app's own chunks are not.
  assert.ok(precache.assets.some(a => a.startsWith('/assets/landing.')), 'the landing entry');
  assert.ok(!precache.assets.some(a => a.startsWith('/assets/app.')), 'the app opens offline only from a saved pack');
  assert.ok(!JSON.stringify(precache).includes('regulations.json'), 'data is never precached; it is network-first');
});

test('the build id changes when any module changes', async t => {
  const a = await built(t), b = await built(t, {app: 'export const ready = false;'});
  assert.notEqual(a.buildId, b.buildId);
});

/** The joined _headers Cache-Control value, or null if no custom value remains. */
function headerCacheControl(text, path) {
  let rule = null;
  const values = [];
  for (const line of text.split('\n')) {
    if (line.startsWith('/')) rule = new RegExp(`^${line.trim().split('*').map(p => p.replace(/[.?+^$()[\]{}|\\]/g, '\\$&')).join('.*')}$`);
    else if (rule?.test(path)) {
      if (line.trim() === '! Cache-Control') values.length = 0;
      else if (/^\s+Cache-Control:/.test(line)) values.push(line.slice(line.indexOf(':') + 1).trim());
    }
  }
  return values.length ? values.join(', ') : null;
}

const SHORT_CACHE = 'public, max-age=120, stale-while-revalidate=300';
const DEFAULT_CACHE = 'public, max-age=0, must-revalidate';
const EXPECTED_STATIC = `/regions/*\n  Cache-Control: ${SHORT_CACHE}\n/data/*\n  Cache-Control: ${SHORT_CACHE}\n`;
const EXPECTED_SAFETY = [
  '/data/regulations*.json', '/regions/*/regulations.json', '/regions/*/regulations-startup.json',
  '/data/protected-areas.geojson', '/regions/*/protected-areas.geojson', '/data/noaa-federal-areas.json',
  '/data/*-closure-review.json', '/regions/*/groundfish-exclusions.geojson', '/regions/*/coverage.json',
].map(path => `${path}\n  ! Cache-Control\n  Cache-Control: ${DEFAULT_CACHE}\n`).join('');

test('C1: exactly two short-cache rules with bounded lifetimes', () =>
  assert.deepEqual([STATIC_MAX_AGE_S, STATIC_SWR_S, STATIC_DATA], [120, 300, EXPECTED_STATIC]));

test('C2: safety rules detach before restoring the revalidation directive', () =>
  assert.deepEqual([REVALIDATE, SAFETY_FILES], [DEFAULT_CACHE, EXPECTED_SAFETY]));

test('C4: ordinary region and data files use the short cache', async t => {
  const headers = await readFile(join((await built(t)).out, '_headers'), 'utf8');
  const paths = ['/regions/morro-bay/region.json', '/data/atlas.json'];
  assert.deepEqual(paths.map(path => headerCacheControl(headers, path)), [SHORT_CACHE, SHORT_CACHE]);
});

test('C4: safety and unchanged paths retain their previous cache policies', async t => {
  const {out} = await built(t);
  const headers = await readFile(join(out, '_headers'), 'utf8');
  const safety = [
    '/data/regulations.json', '/data/regulations-northern.json', '/regions/morro-bay/regulations.json',
    '/regions/morro-bay/regulations-startup.json', '/data/protected-areas.geojson', '/regions/big-sur-coast/protected-areas.geojson',
    '/data/noaa-federal-areas.json', '/data/cape-mendocino-shortlist-closure-review.json',
    '/regions/southern-california/groundfish-exclusions.geojson', '/regions/morro-bay/coverage.json',
  ];
  for (const path of safety) assert.equal(headerCacheControl(headers, path), DEFAULT_CACHE, path);
  for (const path of ['/assets/x.0123456789.js', `/basemap/glyphs/v/${GLYPH_VERSION}/dm-sans-medium/0-255.pbf`])
    assert.equal(headerCacheControl(headers, path), 'public, max-age=31536000, immutable', path);
  for (const path of ['/basemap/glyphs/dm-sans-medium/0-255.pbf', '/sw.js', '/feeds/conditions/latest.json'])
    assert.equal(headerCacheControl(headers, path), null, path);
  await t.test('C4: no generated rule uses more than one splat', () => {
    assert.deepEqual(headers.split('\n').filter(line => line.startsWith('/') && /\*.*\*/.test(line)), []);
  });
  await t.test('C4: no committed region points at a cacheable safety asset', async () => {
    const repo = join(DIST, '..');
    const {stdout} = await run('git', ['ls-files', '-z', '--', ':(glob)dist/regions/*/region.json'], {cwd: repo});
    const drift = [];
    for (const file of stdout.split('\0').filter(Boolean)) {
      const {assets} = JSON.parse(await readFile(join(repo, file), 'utf8'));
      const region = file.split('/')[2];
      const paths = [assets.regulations, assets.protected_areas, assets.closures, `regions/${region}/regulations-startup.json`, `regions/${region}/coverage.json`];
      drift.push(...paths.filter(p => p != null).map(p => `/${p}`).filter(p => headerCacheControl(headers, p) !== DEFAULT_CACHE));
    }
    assert.deepEqual(drift, []);
  });
});

test('R4-SC-08: the glyphs are copied under their content version, kept a year; a stale version fails the build', async () => {
  const out = await mkdtemp(join(tmpdir(), 'sc-glyphs-'));
  try {
    assert.equal(await versionGlyphs(out, 'unused'), null, 'no glyphs, nothing to version');
    await mkdir(join(out, 'basemap/glyphs/dm-sans-medium'), {recursive: true});
    await writeFile(join(out, 'basemap/glyphs/dm-sans-medium/0-255.pbf'), 'range a');
    await writeFile(join(out, 'basemap/glyphs/DM-SANS-OFL.txt'), 'licence');
    const {version, names} = await glyphVersion(join(out, 'basemap/glyphs'));
    assert.match(version, /^[0-9a-f]{16}$/);
    assert.deepEqual(names, ['dm-sans-medium/0-255.pbf']);
    await assert.rejects(versionGlyphs(out, 'ffffffffffffffff'), new RegExp(`hashes to ${version}, not GLYPH_VERSION ffffffffffffffff`));
    assert.equal(await versionGlyphs(out, version), version);
    assert.equal(await readFile(join(out, `basemap/glyphs/v/${version}/dm-sans-medium/0-255.pbf`), 'utf8'), 'range a');
    assert.equal(await readFile(join(out, 'basemap/glyphs/dm-sans-medium/0-255.pbf'), 'utf8'), 'range a', 'the unversioned file stays');
    assert.equal((await glyphVersion(join(out, 'basemap/glyphs'))).version, version, 'the versioned copy is not part of the hash');
    await writeFile(join(out, 'basemap/glyphs/dm-sans-medium/0-255.pbf'), 'range b');
    await assert.rejects(versionGlyphs(out, version), /not GLYPH_VERSION/, 'changed bytes under the old version are refused');
  } finally { await rm(out, {recursive: true, force: true}); }
  const rules = '/*\n  X-Frame-Options: DENY\n' + IMMUTABLE_ASSETS + IMMUTABLE_GLYPHS;
  assert.equal(headerCacheControl(rules, `/basemap/glyphs/v/${GLYPH_VERSION}/dm-sans-medium/0-255.pbf`), 'public, max-age=31536000, immutable');
  assert.equal(headerCacheControl(rules, '/basemap/glyphs/dm-sans-medium/0-255.pbf'), null, 'unversioned: the assets default, as before');
  assert.equal(headerCacheControl(rules, '/assets/app.0123456789.js'), 'public, max-age=31536000, immutable');
});

test('check_client passes a good build and fails on missing chunks, raw sources, stale precache and a worker without the build id', async t => {
  const {root, out, buildId} = await built(t);
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

  const page = join(out, `landing.${buildId}.html`), html = await readFile(page, 'utf8');
  await writeFile(page, html.replace(/ integrity="[^"]+"/, ''));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /without an integrity attribute/);
  await writeFile(page, html.replace('</head>', '<script type="module" src="plain.js"></script></head>'));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /plain\.js \(missing\)/);
  await writeFile(page, html);

  const [chunk] = (await readdir(join(out, 'assets'))).filter(n => n.startsWith('helper.') || n.startsWith('app.'));
  await rm(join(out, 'assets', chunk));
  await assert.rejects(run(process.execPath, [CHECK, out, root]), /\(missing\)/);
});

test('check_client fails a v2 page over its gzipped JavaScript or CSS budget (FE-09)', async t => {
  const root = await site(t);
  await writeFile(join(root, 'app.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"><script type="module" src="shell.js"></script></head><body>v2</body></html>');
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nexport const pad = ${JSON.stringify(Array.from({length: 400}, (_, i) => `${i}-${Math.sin(i)}`))};\nhelper(pad);`);
  const out = join(root, 'client');
  await buildClient({root, out, headers: '/*\n'});
  const budget = join(root, 'budget.json'), check = b => { return writeFile(budget, JSON.stringify({bundles: {'app.html': b}})).then(() => run(process.execPath, [CHECK, out, root, budget])); };
  const {stdout} = await check({js_gzip_max: 100000, css_gzip_max: 1000});
  assert.match(stdout, /Budgets: app\.html js \d+ B, css \d+ B gzipped/);
  await assert.rejects(check({js_gzip_max: 500}), /app\.html: initial JavaScript \d+ B gzipped exceeds its budget of 500 B/);
  await assert.rejects(check({css_gzip_max: 1}), /app\.html: initial CSS \d+ B gzipped exceeds its budget of 1 B/);
});

test('check_client passes with a WARN from 97% of a budget, and records what it measured (SC-CI-2)', async t => {
  const root = await site(t);
  await writeFile(join(root, 'app.html'), '<!doctype html><html><head><link rel="stylesheet" href="styles.css"><script type="module" src="shell.js"></script></head><body>v2</body></html>');
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nexport const pad = ${JSON.stringify(Array.from({length: 400}, (_, i) => `${i}-${Math.sin(i)}`))};\nhelper(pad);`);
  const out = join(root, 'client'), budget = join(root, 'budget.json'), measured = join(root, 'measured.json');
  await buildClient({root, out, headers: '/*\n'});
  const check = (b, env = {}) => writeFile(budget, JSON.stringify({bundles: {'app.html': b}})).then(() => run(process.execPath, [CHECK, out, root, budget], {env: {...process.env, GITHUB_ACTIONS: 'false', ...env}}));
  const size = Number((await check({js_gzip_max: 100000})).stdout.match(/app\.html js (\d+) B/)[1]);
  // Inside 97%: quiet. At 97% or more but not over: passes and warns. Over: fails as before.
  assert.doesNotMatch((await check({js_gzip_max: Math.ceil(size / 0.96)})).stderr, /WARN/);
  const near = await check({js_gzip_max: size + 1}, {BUDGET_MEASUREMENTS_OUT: measured});
  assert.match(near.stderr, /WARN: app\.html initial JavaScript \(gzipped\) is \d+ B, \d+\.\d% of its \d+ B budget/);
  assert.equal(JSON.parse(await readFile(measured, 'utf8')).bundles['app.html'].js, size);
  assert.match((await check({js_gzip_max: size + 1}, {GITHUB_ACTIONS: 'true'})).stderr, /^::warning title=Client budget near its ceiling::/m);
  await assert.rejects(check({js_gzip_max: size - 1}), /exceeds its budget of/);
});

test('check_client fails when the v2 app entry statically imports three (FE-71)', async t => {
  const root = await site(t);
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
  // three's core as a shared chunk (no `src` in the manifest), as `import {Vector3} from 'three'` builds it when
  // another page shares it: caught by three's __THREE__ marker under any chunk name, and by the chunk name without it.
  await writeFile(join(root, 'other.html'), '<!doctype html><html><head><script type="module" src="other.js"></script></head><body>other</body></html>');
  await writeFile(join(root, 'other.js'), `import {Vector3} from './math.js';\nexport const v = new Vector3();`);
  await writeFile(join(root, 'shell.js'), `import {helper} from './helper.js';\nimport {Vector3} from './math.js';\nhelper(new Vector3());`);
  for (const [file, body, message] of [
    ['math.js', 'export class Vector3 {}\nif (typeof window !== "undefined") window.__THREE__ = "180";', /app\.html statically imports assets\/math\.[0-9a-f]+\.js, which contains three/],
    ['three.core.js', 'export class Vector3 {}', /app\.html statically imports _three\.core\.[0-9a-f]+\.js \(three and the coast renderer load by dynamic import only\)/],
  ]) {
    await rm(out, {recursive: true, force: true});
    await writeFile(join(root, file), body);
    for (const name of ['other.js', 'shell.js']) await writeFile(join(root, name), (await readFile(join(root, name), 'utf8')).replace(/'\.\/(?:math|three\.core)\.js'/, `'./${file}'`));
    await buildClient({root, out, headers: '/*\n'});
    const manifest = JSON.parse(await readFile(join(out, '.vite/manifest.json'), 'utf8'));
    assert.ok(Object.entries(manifest).some(([key, e]) => key.startsWith('_') && !e.src && e.file.includes(file.replace('.js', ''))), `${file} is a shared chunk without src`);
    await assert.rejects(run(process.execPath, [CHECK, out, root]), message);
  }
});

test('the real site builds and passes the client check (static data directories skipped)', async () => {
  const out = await mkdtemp(join(tmpdir(), 'client-real-'));
  const keep = name => !['data', 'regions', 'downloads', 'tiles'].includes(name);
  const {buildId} = await buildClient({root: DIST, out, copy: keep});
  const {stdout} = await run(process.execPath, [CHECK, out, DIST]);
  assert.match(stdout, new RegExp(`precached for build ${buildId}`));
  // SC1407-10: /map's first load (app.html and every script it imports at once) holds no planner or pack implementation;
  // web/trip-runtime.ts arrives by web/trip.ts's dynamic import, and the offline pack's v2 list still carries it.
  const manifest = JSON.parse(await readFile(join(out, '.vite/manifest.json'), 'utf8'));
  const closure = (keys, follow) => { const seen = new Set(); const walk = k => { if (seen.has(k)) return; seen.add(k); for (const i of follow(manifest[k])) walk(i); }; keys.forEach(walk); return seen; };
  const first = closure(['app.html'], e => e.imports ?? []), all = closure(['app.html'], e => [...e.imports ?? [], ...e.dynamicImports ?? []]);
  for (const key of ['../web/trip-runtime.ts', 'offline-pack.js', 'legal-pack.js', 'coastal-offline-core.js', '../web/planner.ts', '../web/app/Planner.tsx'])
    assert.ok(manifest[key] && !first.has(key) && all.has(key), `${key} loads on use, not with /map`);
  const precache = JSON.parse(await readFile(join(out, 'precache.json'), 'utf8'));
  assert.ok(precache.v2.assets.includes(`/${manifest['../web/trip-runtime.ts'].file}`), 'a saved pack can open the planner offline');
  // R4-SC-08: the real glyphs ship under GLYPH_VERSION (kept a year) and unversioned (unchanged); a pack stores the versioned ones.
  const glyphs = ['0-255', '8192-8447'].map(range => `/basemap/glyphs/v/${GLYPH_VERSION}/dm-sans-medium/${range}.pbf`);
  assert.deepEqual(precache.v2.static, glyphs);
  const headers = await readFile(join(out, '_headers'), 'utf8');
  for (const path of glyphs) {
    assert.deepEqual(await readFile(join(out, path)), await readFile(join(out, path.replace(`/v/${GLYPH_VERSION}`, ''))), path);
    assert.equal(headerCacheControl(headers, path), 'public, max-age=31536000, immutable', path);
    assert.equal(headerCacheControl(headers, path.replace(`/v/${GLYPH_VERSION}`, '')), null, `${path} unversioned keeps the default`);
  }
  // SCB-11: /map links its early script (web/app/early.ts) async, at high priority, ahead of the app's own entry; the script
  // imports nothing, so it runs the moment it arrives; the landing warms it and a saved pack carries it with the app.
  const early = manifest['../web/app/early.ts'], page = await readFile(join(out, `app.${buildId}.html`), 'utf8');
  assert.ok(early?.isEntry && !early.imports?.length && !early.dynamicImports?.length, 'the early script is an entry that imports nothing');
  const scripts = [...page.matchAll(/<script ([^>]*)><\/script>/g)].map(m => m[1]).filter(a => a.includes('type="module"'));
  assert.equal(scripts[0], `type="module" async fetchpriority="high" crossorigin src="./${early.file}"`);
  assert.ok(scripts.slice(1).some(a => a.includes(`src="./${manifest['app.html'].file}"`)), 'the app\'s own entry follows');
  assert.ok(precache.warm.includes(`/${early.file}`) && precache.v2.assets.includes(`/${early.file}`), 'warmed by the landing, carried in a pack');
  assert.ok(!precache.assets.includes(`/${early.file}`), 'not in every visitor\'s install list');
  await rm(out, {recursive: true, force: true});
});

test('the bundled MapLibre stylesheet drops only the logo, which no map turns on', async () => {
  const css = '.a{x:1}a.maplibregl-ctrl-logo{b:url("data:x{}")}.b,a.maplibregl-ctrl-logo{c:2}@media(forced-colors:active){a.maplibregl-ctrl-logo{d:3}}@media(x){.c{e:4}a.maplibregl-ctrl-logo{f:5}}';
  assert.equal(dropMaplibreLogo(css), '.a{x:1}.b,a.maplibregl-ctrl-logo{c:2}@media(x){.c{e:4}}');
  assert.ok(MAPLIBRE_CSS.test('/r/node_modules/.pnpm/maplibre-gl@6/node_modules/maplibre-gl/dist/maplibre-gl.css?url'));
  const real = await readFile(new URL('../node_modules/maplibre-gl/dist/maplibre-gl.css', import.meta.url), 'utf8');
  const kept = dropMaplibreLogo(real);
  assert.ok(!kept.includes('maplibregl-ctrl-logo') && kept.includes('.maplibregl-ctrl-attrib-button') && real.length - kept.length > 30000);
  const {stdout} = await run('git', ['grep', '-l', 'maplibreLogo', '--', 'web', 'dist/*.js', 'packages'], {cwd: new URL('..', import.meta.url).pathname}).catch(e => e);
  assert.equal(stdout, '', 'a map that shows the MapLibre logo needs its stylesheet rules back (vite.config.mjs)');
});

test('only vendor files, the web manifest and icons are left out of the Vite build', () => {
  const mark = html => html.replace(STATIC_REF, '<$1 vite-ignore');
  assert.match(mark('<script src="vendor/simplewebauthn-browser-14.0.0/index.umd.min.js" integrity="x" defer></script>'), /^<script vite-ignore src=/);
  assert.match(mark('<link rel="stylesheet" href="vendor/lib/lib.css" />'), /^<link vite-ignore /);
  assert.match(mark('<link rel="manifest" href="manifest.webmanifest"/>'), /vite-ignore/);
  assert.match(mark('<link rel="apple-touch-icon" href="apple-touch-icon.png"/>'), /vite-ignore/);
  assert.doesNotMatch(mark('<link rel="stylesheet" href="tokens.css" />'), /vite-ignore/);
  assert.doesNotMatch(mark('<script type="module" src="../web/app/main.tsx"></script>'), /vite-ignore/);
});

const sha = char => char.repeat(64);
const SOURCE = {
  id: 'noaa-ncei-morro', label: 'NOAA NCEI Morro Bay bathymetry', attribution: 'NOAA NCEI', vertical_datum: 'MLLW',
  survey_dates: ['2019'], rights_class: 'public', review_status: 'approved', private: false, publication_allowed: true,
  rights: {public_display: 'allowed', license: 'US Government work', redistribution_reviewed: true},
};
// A complete pointer that satisfies catalog/relief/pointer.schema.json; the tests below break one rule at a time.
const POINTER = region => ({
  schema: 'sc-relief-pointer/1', status: 'reviewed', private: false, region, generation: sha('a'),
  release_sha256: sha('b'), envelope_sha256: sha('c'), sha256: sha('d'), bytes: 4096, digest_root_sha256: sha('e'),
  previous: null, bounds: [-121.1, 35.2, -120.8, 35.5], minzoom: 10, maxzoom: 16, sources: [structuredClone(SOURCE)],
  detail_summary: {mask: 'transparent-nodata', depth_bands: [{source_id: SOURCE.id, min_depth_m: 0, max_depth_m: 91.44, resolution_m: 2}]},
  native_support_by_zoom: {10: {tiles: 4, sources: [{id: SOURCE.id, resolution_m: 2, tiles: 4}]}},
});
async function reliefDir(t, files) {
  const dir = await mkdtemp(join(tmpdir(), 'relief-src-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  for (const [name, body] of Object.entries(files)) await writeFile(join(dir, name), body);
  return dir;
}

test('relief pointers are published byte for byte at catalog/relief/, with nothing else from the directory', async t => {
  // Bug caught: the browser and live-check fetch /catalog/relief/<region>.json, but the build never shipped it,
  // so a merged pointer drew no relief (and no ft-v3 contours) and live-check could only report a missing pointer.
  const morro = `${JSON.stringify(POINTER('morro-bay'), null, 2)}\n`;
  const src = await reliefDir(t, {'morro-bay.json': morro, 'README.md': '# notes', 'pointer.schema.json': '{}'});
  const out = await mkdtemp(join(tmpdir(), 'relief-out-'));
  t.after(() => rm(out, {recursive: true, force: true}));
  assert.deepEqual(await copyReliefPointers(src, out), ['morro-bay.json']);
  assert.deepEqual(await readdir(join(out, 'catalog/relief')), ['morro-bay.json']);
  assert.equal(await readFile(join(out, 'catalog/relief/morro-bay.json'), 'utf8'), morro, 'exact bytes: live-check compares SHA-256');
  // No directory (the repository before any release) publishes nothing.
  assert.deepEqual(await copyReliefPointers(join(src, 'missing'), out), []);
});

test('a relief pointer that is not public, reviewed and for its own region fails the build', async t => {
  const cases = {
    'wrong region': ['morro-bay.json', JSON.stringify(POINTER('big-sur-coast'))],
    'private': ['morro-bay.json', JSON.stringify({...POINTER('morro-bay'), private: true})],
    'unreviewed': ['morro-bay.json', JSON.stringify({...POINTER('morro-bay'), status: 'draft'})],
    'other schema': ['morro-bay.json', JSON.stringify({...POINTER('morro-bay'), schema: 'sc-relief-release/1'})],
    'not JSON': ['morro-bay.json', '{"schema": '],
    'not UTF-8': ['morro-bay.json', Buffer.from([0x7b, 0xff, 0x7d])],
    'bad name': ['Morro_Bay.json', JSON.stringify(POINTER('Morro_Bay'))],
    'other file': ['morro-bay.geojson', '{}'],
    'oversized': ['morro-bay.json', JSON.stringify({...POINTER('morro-bay'), pad: 'x'.repeat(1 << 20)})],
  };
  for (const [label, [name, body]] of Object.entries(cases)) {
    const src = await reliefDir(t, {[name]: body});
    const out = await mkdtemp(join(tmpdir(), 'relief-out-'));
    t.after(() => rm(out, {recursive: true, force: true}));
    await assert.rejects(copyReliefPointers(src, out), new RegExp(`refusing to publish catalog/relief/${name.replace('.', '\\.')}`), label);
    await assert.rejects(readdir(join(out, 'catalog')), {code: 'ENOENT'}, label);
  }
  // A link could publish any file on the build machine under a pointer's name.
  const elsewhere = await reliefDir(t, {'private.json': JSON.stringify(POINTER('morro-bay'))});
  const linked = await reliefDir(t, {});
  await symlink(join(elsewhere, 'private.json'), join(linked, 'morro-bay.json'));
  await assert.rejects(copyReliefPointers(linked, await mkdtemp(join(tmpdir(), 'relief-out-'))),
    /refusing to publish catalog\/relief\/morro-bay\.json: not a regular file/);
});

test('a relief pointer that breaks catalog/relief/pointer.schema.json fails the build, whatever its four headline fields say', async t => {
  // Bug caught: copyReliefPointers once checked only schema, status, private and region, so a reviewed-looking file
  // with no release hashes, no bytes, a malformed previous, wrong bounds, no sources, or a source whose rights are not
  // public and reviewed was published as a pointer the relief layer and live-check then trusted.
  const withSource = patch => { const doc = POINTER('morro-bay'); Object.assign(doc.sources[0], patch); return doc; };
  const withRights = patch => { const doc = POINTER('morro-bay'); Object.assign(doc.sources[0].rights, patch); return doc; };
  const without = key => { const doc = POINTER('morro-bay'); delete doc[key]; return doc; };
  const dropped = (...path) => { const doc = POINTER('morro-bay'); let node = doc; for (const key of path.slice(0, -1)) node = node[key]; delete node[path.at(-1)]; return doc; };
  const cases = {
    'no release_sha256': without('release_sha256'),
    'no envelope_sha256': without('envelope_sha256'),
    'no sha256': without('sha256'),
    'no digest_root_sha256': without('digest_root_sha256'),
    'no bytes': without('bytes'),
    'zero bytes': {...POINTER('morro-bay'), bytes: 0},
    'fractional bytes': {...POINTER('morro-bay'), bytes: 10.5},
    'upper-case hash': {...POINTER('morro-bay'), release_sha256: sha('B')},
    'short hash': {...POINTER('morro-bay'), sha256: 'd'.repeat(63)},
    'no previous': without('previous'),
    'previous missing a hash': {...POINTER('morro-bay'), previous: {generation: sha('1'), release_sha256: sha('2'), envelope_sha256: sha('3')}},
    'previous with an extra field': {...POINTER('morro-bay'), previous: {generation: sha('1'), release_sha256: sha('2'), envelope_sha256: sha('3'), sha256: sha('4'), note: 'x'}},
    'no bounds': without('bounds'),
    'three bounds': {...POINTER('morro-bay'), bounds: [-121.1, 35.2, -120.8]},
    'bounds out of range': {...POINTER('morro-bay'), bounds: [-121.1, 95, -120.8, 35.5]},
    'zoom out of range': {...POINTER('morro-bay'), maxzoom: 18},
    'no sources': without('sources'),
    'empty sources': {...POINTER('morro-bay'), sources: []},
    'source not public': withSource({rights_class: 'restricted'}),
    'source not approved': withSource({review_status: 'pending'}),
    'source private': withSource({private: true}),
    'source publication not allowed': withSource({publication_allowed: false}),
    'source with an extra field': withSource({note: 'x'}),
    'source without attribution': dropped('sources', 0, 'attribution'),
    'source without rights': dropped('sources', 0, 'rights'),
    'rights display not allowed': withRights({public_display: 'denied'}),
    'rights redistribution not reviewed': withRights({redistribution_reviewed: false}),
    'rights without license': dropped('sources', 0, 'rights', 'license'),
    'rights with an extra field': withRights({note: 'x'}),
    'no detail_summary': without('detail_summary'),
    'unsupported zoom key': {...POINTER('morro-bay'), native_support_by_zoom: {7: {tiles: 1, sources: []}}},
    'survey wire over its limit': {...POINTER('morro-bay'), survey_detail: {wire: {sha256: sha('f'), bytes: 5242881}, decoded: {sha256: sha('f'), bytes: 9}}},
    'unknown top-level field': {...POINTER('morro-bay'), extra: true},
  };
  for (const [label, doc] of Object.entries(cases)) {
    const src = await reliefDir(t, {'morro-bay.json': JSON.stringify(doc)});
    const out = await mkdtemp(join(tmpdir(), 'relief-out-'));
    t.after(() => rm(out, {recursive: true, force: true}));
    await assert.rejects(copyReliefPointers(src, out), /refusing to publish catalog\/relief\/morro-bay\.json: violates catalog\/relief\/pointer\.schema\.json/, label);
    await assert.rejects(readdir(join(out, 'catalog')), {code: 'ENOENT'}, label);
  }
  // The schema checked is the repository's, not a permissive copy placed beside the pointers.
  const src = await reliefDir(t, {'morro-bay.json': JSON.stringify(without('sha256')), 'pointer.schema.json': '{}'});
  await assert.rejects(copyReliefPointers(src, await mkdtemp(join(tmpdir(), 'relief-out-'))), /violates catalog\/relief\/pointer\.schema\.json/);
  // A previous release and the optional style and survey_detail blocks are accepted when they follow the schema.
  const full = {...POINTER('morro-bay'),
    previous: {generation: sha('1'), release_sha256: sha('2'), envelope_sha256: sha('3'), sha256: sha('4')},
    style: {baked: sha('5'), contours: null, habitat: sha('6'), built_with: 'v1.2'},
    survey_detail: {wire: {sha256: sha('7'), bytes: 5242880}, decoded: {sha256: sha('8'), bytes: 16777216}}};
  const okSrc = await reliefDir(t, {'morro-bay.json': JSON.stringify(full)});
  const okOut = await mkdtemp(join(tmpdir(), 'relief-out-'));
  t.after(() => rm(okOut, {recursive: true, force: true}));
  assert.deepEqual(await copyReliefPointers(okSrc, okOut), ['morro-bay.json']);
});

test('the client build serves the reviewed relief pointers', async t => {
  const root = await site(t);
  const out = join(root, 'client');
  const relief = await reliefDir(t, {'morro-bay.json': JSON.stringify(POINTER('morro-bay'))});
  await buildClient({root, out, headers: '/*\n', relief});
  assert.deepEqual(JSON.parse(await readFile(join(out, 'catalog/relief/morro-bay.json'), 'utf8')), POINTER('morro-bay'));
  const precache = JSON.parse(await readFile(join(out, 'precache.json'), 'utf8'));
  assert.ok(!JSON.stringify(precache).includes('catalog/relief'), 'a pointer is never precached; a rollback must reach the next load');
  await rm(out, {recursive: true, force: true});
});
