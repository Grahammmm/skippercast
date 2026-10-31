// Service-worker precache manifest for one build.
//
// After the Vite build, dist/client/precache.json lists what the offline shell
// needs: the stable shell '/', every hashed script and stylesheet of this
// build (dist/client/assets/), and the few unhashed static files the shell
// loads (icons, the web manifest). The worker (dist/sw.js) fetches it at
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
//
// #497: `/` is the landing, so the install list also holds the landing's
// first-paint graph (its static imports, styles and fonts; about 105 KB
// gzipped, not the night map, which loads MapLibre by dynamic import and leaves
// the static shoreline in place when that fails). FE-61 dropped the v1 shell
// and its `/?ui=v1` key with the switch. The app at /map stays out: it opens
// offline only from a pack saved from it.
//
// #617: `warm` lists the app's first-paint files the landing does not load
// itself (appWarm); the landing fetches them into the browser cache after its
// own first paint, unless the visitor asked to save data, so opening /map
// does not wait on them.
import {readdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

export const FINGERPRINTED = /\.[0-9a-f]{10}\.(?:js|css)$/;
const STATIC = /^(?:app-icon[\w-]*\.(?:png|svg)|apple-touch-icon\.png|manifest\.webmanifest)$/;
export const BUILD_PLACEHOLDER = "const BUILD = 'dev';";
const HASHED = /\.[0-9a-f]{10}\.[a-z0-9]+$/;
export const V2_PAGES = ['app.html', 'landing.html'];
export const LANDING_PAGE = 'landing.html';
export const SHELLS = ['/'];
const OFFLINE_SKIP = new Set(['../web/map/terrain.js']);

/** /assets/ paths of the hashed files `roots` load, statically or (unless `dynamic` is false) by dynamic import, skipping `skip`'s subtrees. */
export function reachable(manifest, roots, skip = new Set(), dynamic = true) {
  const files = new Set(), seen = new Set();
  const walk = key => {
    const e = manifest[key];
    if (!e || seen.has(key) || skip.has(key)) return;
    seen.add(key);
    // CSS imported with ?url is only a reference (e.g. a panel's shadow-root
    // stylesheet), not a first-paint load. Keep it for offline packs, but not
    // static shell/warm graphs. Actual stylesheet dependencies live in e.css.
    const assets = (e.assets || []).filter(f => dynamic || !f.endsWith('.css'));
    for (const f of [e.file, ...(e.css || []), ...assets]) if (HASHED.test(f)) files.add(`/${f}`);
    for (const next of [...(e.imports || []), ...(dynamic ? e.dynamicImports || [] : [])]) walk(next);
  };
  roots.forEach(walk);
  return files;
}

/** Hashed files that only the v2 pages load. */
export function v2Only(manifest) {
  const others = reachable(manifest, Object.keys(manifest).filter(k => manifest[k].isEntry && !V2_PAGES.includes(k)));
  return new Set([...reachable(manifest, V2_PAGES)].filter(f => !others.has(f)));
}

/** #497: what the landing needs to paint offline (no dynamic imports, so no MapLibre). */
export function landingShell(manifest) {
  return reachable(manifest, [LANDING_PAGE], new Set(), false);
}

/**
 * #617: the app's first-paint files the landing warms after its own first paint (web/landing/warm.ts): the app
 * page's static graph (no dynamic imports) without what the landing already loaded for its own first paint.
 */
export function appWarm(manifest) {
  const landing = landingShell(manifest);
  return [...reachable(manifest, ['app.html'], new Set(), false)].filter(f => !landing.has(f)).sort();
}

/** The install list's hashed files: every script and style a non-v2 page can load, plus the landing's first paint. */
export function installAssets(manifest, files) {
  const only = v2Only(manifest);
  const shared = files.filter(n => FINGERPRINTED.test(n)).map(n => `/assets/${n}`).filter(n => !only.has(n));
  return [...new Set([...shared, ...landingShell(manifest)])].sort();
}

export async function precacheManifest(dir, buildId) {
  const top = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile()).map(e => e.name).sort();
  const manifest = JSON.parse(await readFile(join(dir, '.vite/manifest.json'), 'utf8').catch(() => '{}'));
  const glyphs = await readdir(join(dir, 'basemap/glyphs'), {recursive: true}).catch(() => []);
  return {
    schema_version: 1,
    build: buildId,
    shells: SHELLS,
    assets: installAssets(manifest, await readdir(join(dir, 'assets')).catch(() => [])),
    static: top.filter(n => STATIC.test(n)).map(n => `/${n}`),
    warm: appWarm(manifest),
    v2: {
      assets: [...reachable(manifest, ['app.html'], OFFLINE_SKIP)].sort(),
      static: glyphs.filter(n => n.endsWith('.pbf')).sort().map(n => `/basemap/glyphs/${n}`),
    },
  };
}

export async function writePrecache(dir, buildId) {
  // Check the worker before writing anything, so a refusal leaves the folder as it was.
  const sw = await readFile(join(dir, 'sw.js'), 'utf8');
  if (!sw.includes(BUILD_PLACEHOLDER)) {
    const stamped = sw.match(/^const BUILD = '([^'\n]*)';/m);
    if (stamped) throw new Error(`sw.js is already stamped with build ${stamped[1]}; rebuild into a clean folder`);
    throw new Error(`sw.js must declare ${BUILD_PLACEHOLDER}`);
  }
  const manifest = await precacheManifest(dir, buildId);
  await writeFile(join(dir, 'precache.json'), JSON.stringify(manifest) + '\n');
  await writeFile(join(dir, 'sw.js'), sw.replace(BUILD_PLACEHOLDER, `const BUILD = '${buildId}';`));
  return manifest;
}
