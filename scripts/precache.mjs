// Service-worker precache manifest for one build.
//
// After the Vite build, dist/client/precache.json lists what the offline shell
// needs: the stable app shell '/', every hashed script and stylesheet of this
// build (dist/client/assets/), and the few unhashed static files the shell
// loads (vendored Leaflet, icons, the web manifest). The worker (dist/sw.js) fetches it at
// install, so no hashed name is ever hard-coded in sw.js. Fingerprinted pages
// are not listed: the Worker serves them only from their stable paths.
// The build id is written into sw.js so every deploy installs a new worker.
//
// FE-51: hashed files that only the v2 pages load (MapLibre and its worker, the
// app and landing chunks, about 1.9 MB) are left out of the install list, so the
// worker's install no longer stores them for every visitor. `v2` lists what the
// app needs to open offline (its page graph without the terrain renderer, which
// streams online only, and the basemap glyphs); web/trip.ts stores those files
// inside a trip pack when someone saves a region for offline from the v2 app.
// A v2 page the worker controls (after such a save, or because a classic-map
// visit registered it) still adds each hashed file it loads to the build's
// shell cache at run time (sw.js cacheFirst), as every page does.
import {readdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

export const FINGERPRINTED = /\.[0-9a-f]{10}\.(?:js|css)$/;
const STATIC = /^(?:app-icon[\w-]*\.(?:png|svg)|apple-touch-icon\.png|manifest\.webmanifest)$/;
const VENDOR = ['vendor/leaflet.js', 'vendor/leaflet.css'];
export const BUILD_PLACEHOLDER = "const BUILD = 'dev';";
const HASHED = /\.[0-9a-f]{10}\.[a-z0-9]+$/;
export const V2_PAGES = ['app.html', 'landing.html'];
const OFFLINE_SKIP = new Set(['../web/map/terrain.js']);

/** /assets/ paths of the hashed files `roots` load, statically or by dynamic import, skipping `skip`'s subtrees. */
export function reachable(manifest, roots, skip = new Set()) {
  const files = new Set(), seen = new Set();
  const walk = key => {
    const e = manifest[key];
    if (!e || seen.has(key) || skip.has(key)) return;
    seen.add(key);
    for (const f of [e.file, ...(e.css || []), ...(e.assets || [])]) if (HASHED.test(f)) files.add(`/${f}`);
    for (const next of [...(e.imports || []), ...(e.dynamicImports || [])]) walk(next);
  };
  roots.forEach(walk);
  return files;
}

/** Hashed files that only the v2 pages load. */
export function v2Only(manifest) {
  const others = reachable(manifest, Object.keys(manifest).filter(k => manifest[k].isEntry && !V2_PAGES.includes(k)));
  return new Set([...reachable(manifest, V2_PAGES)].filter(f => !others.has(f)));
}

export async function precacheManifest(dir, buildId) {
  const top = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile()).map(e => e.name).sort();
  const images = await readdir(join(dir, 'vendor/images')).catch(() => []);
  const vendor = [...VENDOR, ...images.sort().map(n => `vendor/images/${n}`)];
  for (const path of vendor) await readFile(join(dir, path)); // fail the build if a listed file is missing
  const manifest = JSON.parse(await readFile(join(dir, '.vite/manifest.json'), 'utf8').catch(() => '{}'));
  const only = v2Only(manifest);
  const glyphs = await readdir(join(dir, 'basemap/glyphs'), {recursive: true}).catch(() => []);
  return {
    schema_version: 1,
    build: buildId,
    shells: ['/'],
    assets: (await readdir(join(dir, 'assets')).catch(() => [])).filter(n => FINGERPRINTED.test(n)).sort().map(n => `/assets/${n}`).filter(n => !only.has(n)),
    static: [...top.filter(n => STATIC.test(n)), ...vendor].map(n => `/${n}`),
    v2: {
      assets: [...reachable(manifest, ['app.html'], OFFLINE_SKIP)].sort(),
      static: glyphs.filter(n => n.endsWith('.pbf')).sort().map(n => `/basemap/glyphs/${n}`),
    },
  };
}

export async function writePrecache(dir, buildId) {
  const manifest = await precacheManifest(dir, buildId);
  await writeFile(join(dir, 'precache.json'), JSON.stringify(manifest) + '\n');
  const sw = await readFile(join(dir, 'sw.js'), 'utf8');
  if (!sw.includes(BUILD_PLACEHOLDER)) throw new Error(`sw.js must declare ${BUILD_PLACEHOLDER}`);
  await writeFile(join(dir, 'sw.js'), sw.replace(BUILD_PLACEHOLDER, `const BUILD = '${buildId}';`));
  return manifest;
}
