// SCA-095: exercise the real advisor entry points against a cold packaged client.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {extname, join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {advisorAssetPaths, buildClient} from '../scripts/client-build.mjs';
import {BUILD_PLACEHOLDER} from '../scripts/precache.mjs';
import {advisorDatabase} from './_advisor_d1.mjs';

const DIST = fileURLToPath(new URL('../dist/', import.meta.url));
const ORIGIN = 'https://skippercast.test';
const RAW = ['admin.css', 'chat.css', 'my-data.js', 'pages.css', 'upload.css', 'upload.js'].map(name => `/advisor/${name}`);
const HASHED = /^\/assets\/.+\.[0-9a-f]{10}\.[a-z0-9]+$/;
const PAGES = ['admin.html', 'chat.html', 'my-data.html', 'upload.html'];
const STABLE = ['/vendor/simplewebauthn-browser-14.0.0/index.umd.min.js', '/downloads/spot-notes.html', '/sw.js'];

function resources(html, path) {
  const base = html.includes('<base href="/">') ? ORIGIN : new URL(path, ORIGIN);
  return [...html.matchAll(/<(?:script\b[^>]*\bsrc|link\b(?=[^>]*\brel="(?:stylesheet|modulepreload)")[^>]*\bhref)="([^"]+)"/g)]
    .map(([, href]) => new URL(href, base).pathname);
}

test('the advisor release omits the six raw inputs without losing their consumers', async t => {
  const out = await mkdtemp(join(tmpdir(), 'sca-095-'));
  t.after(() => rm(out, {recursive: true, force: true}));
  // Leave bulky, unrelated static trees out of this test, but run the normal copy/stamp path.
  const {manifest, shells, buildId} = await buildClient({root: DIST, out,
    copy: name => ['advisor', 'vendor', 'downloads', 'sw.js'].includes(name)});
  const ASSETS = {async fetch(request) {
    const path = new URL(request.url).pathname;
    // The assets host serves fingerprinted HTML without its .html suffix.
    const file = Object.values(shells).find(name => name.slice(0, -5) === path) ?? path;
    try { return new Response(await readFile(join(out, file))); }
    catch (error) { if (error.code !== 'ENOENT') throw error; return new Response(null, {status: 404}); }
  }};
  const advisorAssets = advisorAssetPaths(manifest);
  const region = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles', species: [], assets: {}};
  Object.assign(globalThis, {REGIONS: {'morro-bay': region}, DEPLOYMENT: {allowed_origins: []}, SHELLS: shells, BUILD_ID: buildId, ADVISOR_ASSETS: advisorAssets});
  t.mock.method(globalThis, 'fetch', () => assert.fail('this test must not use the network'));
  const {default: worker} = await import('../server/index.ts');
  const {pagesDeps} = await import('../server/routes/advisor.ts');
  pagesDeps.clock = () => Date.UTC(2026, 8, 28);
  pagesDeps.feeds = async () => null;
  const {sql, db} = advisorDatabase();
  t.after(() => sql.close());
  sql.exec(`INSERT INTO advisor_boats(id,slug,name,port,region,status,created_at,updated_at)
    VALUES ('sca-095','synthetic-boat','Synthetic Boat','morro-bay','morro-bay','pending','2026-09-28','2026-09-28')`);
  const get = path => worker.fetch(new Request(new URL(path, ORIGIN)), {ASSETS, DB: db, TEXT_ADVISOR_ENABLED: 'true'});
  async function getBytes(path) {
    const response = await get(path);
    assert.equal(response.status, 200, path);
    return Buffer.from(await response.arrayBuffer());
  }

  await t.test('built advisor HTML and server-rendered routes load existing hashed JS/CSS', async () => {
    const routes = ['/chat.html', '/my-data', '/u', '/ports/morro-bay', '/species/lingcod', '/boats/synthetic-boat'];
    const documents = [['/admin.html', await readFile(join(out, shells['/admin.html']), 'utf8')]];
    for (const path of routes) documents.push([path, (await getBytes(path)).toString()]);
    for (const [path, html] of documents) {
      const refs = resources(html, path);
      for (const ext of ['.js', '.css']) assert.ok(refs.some(ref => HASHED.test(ref) && extname(ref) === ext), `${path} needs a hashed ${ext}`);
      for (const ref of refs) {
        assert.ok(HASHED.test(ref) || ref === STABLE[0], `${path} links non-built resource ${ref}`);
        assert.ok((await getBytes(ref)).length, `${path} links empty resource ${ref}`);
      }
    }
    // The HTML does not name every lazy/shared chunk; verify the rest of the entry graph too.
    const seen = new Set();
    async function walk(key) {
      if (seen.has(key)) return;
      seen.add(key);
      const entry = manifest[key];
      assert.ok(entry, `Vite manifest is missing ${key}`);
      for (const file of [entry.file, ...entry.css ?? [], ...entry.assets ?? []]) {
        assert.match(`/${file}`, HASHED, key);
        assert.ok((await getBytes(`/${file}`)).length, file);
      }
      for (const next of [...entry.imports ?? [], ...entry.dynamicImports ?? []]) await walk(next);
    }
    for (const page of PAGES) await walk(page);
  });

  await t.test('vendor, downloads HTML and the stamped service worker retain stable paths and bytes', async () => {
    for (const path of STABLE) {
      const source = await readFile(join(DIST, path));
      const expected = path === '/sw.js' ? Buffer.from(source.toString().replace(BUILD_PLACEHOLDER, `const BUILD = '${buildId}';`)) : source;
      assert.deepEqual(await getBytes(path), expected, path);
    }
  });

  await t.test('all six inputs are still tracked, but none can be fetched from the package', async () => {
    const tracked = execFileSync('git', ['ls-files', '--', 'dist/advisor'], {cwd: new URL('..', import.meta.url), encoding: 'utf8'}).split('\n');
    for (const path of RAW) assert.ok(tracked.includes(`dist${path}`), `not tracked: dist${path}`);
    const copies = [];
    for (const path of RAW) if ((await ASSETS.fetch(new Request(new URL(path, ORIGIN)))).status !== 404) copies.push(path);
    assert.deepEqual(copies, [], 'raw advisor files in the client package');
  });
});
