// Service-worker precache manifest for one build.
//
// After the Vite build, dist/client/precache.json lists what the offline shell
// needs: the stable app shell '/', every hashed script and stylesheet of this
// build (dist/client/assets/), and the few unhashed static files the shell
// loads (vendored Leaflet, icons, the web manifest). The worker (dist/sw.js) fetches it at
// install, so no hashed name is ever hard-coded in sw.js. Fingerprinted pages
// are not listed: the Worker serves them only from their stable paths.
// The build id is written into sw.js so every deploy installs a new worker.
import {readdir, readFile, writeFile} from 'node:fs/promises';
import {join} from 'node:path';

export const FINGERPRINTED = /\.[0-9a-f]{10}\.(?:js|css)$/;
const STATIC = /^(?:app-icon[\w-]*\.(?:png|svg)|apple-touch-icon\.png|manifest\.webmanifest)$/;
const VENDOR = ['vendor/leaflet.js', 'vendor/leaflet.css'];
export const BUILD_PLACEHOLDER = "const BUILD = 'dev';";

export async function precacheManifest(dir, buildId) {
  const top = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile()).map(e => e.name).sort();
  const images = await readdir(join(dir, 'vendor/images')).catch(() => []);
  const vendor = [...VENDOR, ...images.sort().map(n => `vendor/images/${n}`)];
  for (const path of vendor) await readFile(join(dir, path)); // fail the build if a listed file is missing
  return {
    schema_version: 1,
    build: buildId,
    shells: ['/'],
    assets: (await readdir(join(dir, 'assets')).catch(() => [])).filter(n => FINGERPRINTED.test(n)).sort().map(n => `/assets/${n}`),
    static: [...top.filter(n => STATIC.test(n)), ...vendor].map(n => `/${n}`),
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
