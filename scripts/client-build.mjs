// Build the static client (P4-01a): Vite, then the Worker-facing contract.
//
// 1. Vite (vite.config.mjs) bundles every page in dist/*.html with its modules
//    and stylesheets into <out>/assets/NAME.<10 hex>.{js,css} and writes
//    <out>/.vite/manifest.json.
// 2. Static files are copied unchanged: data/, regions/, vendor/, downloads/,
//    tiles/, icons, the web manifest, and sw.js (STABLE: a service worker's
//    URL is its identity, and the pages register '/sw.js').
// 3. Pages get <meta name="skippercast-build"> and are renamed
//    NAME.<buildId>.html. The Worker serves them only from their stable paths
//    ('/', '/sources.html') with no-store, via the returned shells map, so a
//    cached page can never pin an old set of assets.
// 4. precache.json and the build id in sw.js (scripts/precache.mjs), _headers
//    (server/security-headers.ts, plus a year's immutable caching for
//    /assets/*) and .assetsignore (keeps .vite/ off the CDN).
//
// The build id hashes every page and every hashed asset name, so any change
// to a module, stylesheet or page gives a new id (and a new service worker).
import {createHash} from 'node:crypto';
import {cp, readdir, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {build} from 'vite';
import {clientConfig, pages} from '../vite.config.mjs';
import {writePrecache} from './precache.mjs';

export const STABLE = new Set(['sw.js']);
export const MANIFEST = '.vite/manifest.json';
// Hashed names never change content, so browsers and the edge keep them a year.
export const IMMUTABLE_ASSETS = '/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n';
// Authored module sources: Vite builds these, so they are never copied raw.
const SOURCE = /\.(?:js|css|html)$/;

export function hashName(name, buildId) {
  const dot = name.lastIndexOf('.');
  return `${name.slice(0, dot)}.${buildId}${name.slice(dot)}`;
}

/** Copy dist's static files (everything but module sources, build output and dot-entries). */
export async function copyStatic(src, out, {only} = {}) {
  for (const entry of await readdir(src, {withFileTypes: true})) {
    const name = entry.name;
    if (name === 'client' || name === 'server' || name.startsWith('.')) continue;
    if (entry.isFile() && SOURCE.test(name) && !STABLE.has(name)) continue;
    if (only && !only(name)) continue;
    await cp(join(src, name), join(out, name), {recursive: true});
  }
}

/** `html` with <meta name="skippercast-build"> naming `buildId`, just before </head>. */
export function stampBuild(html, buildId) {
  return html.includes('</head>') ? html.replace('</head>', `<meta name="skippercast-build" content="${buildId}">\n</head>`) : html;
}

/** Rename built pages to NAME.<buildId>.html; return {buildId, shells}. */
export async function hashPages(out, pages) {
  const assets = (await readdir(join(out, 'assets')).catch(() => [])).sort();
  const hash = createHash('sha256');
  for (const name of assets) hash.update(name).update('\0');
  const html = new Map();
  for (const name of pages) {
    const text = await readFile(join(out, name), 'utf8');
    html.set(name, text);
    hash.update(name).update('\0').update(text).update('\0');
  }
  const buildId = hash.digest('hex').slice(0, 10);
  const shells = {};
  for (const name of pages) {
    // The page names its build, so client error reports (web/telemetry.ts) can say which build failed.
    await writeFile(join(out, name), stampBuild(html.get(name), buildId));
    await rename(join(out, name), join(out, hashName(name, buildId)));
    shells[`/${name}`] = `/${hashName(name, buildId)}`;
    if (name === 'index.html') shells['/'] = shells['/index.html'];
  }
  return {buildId, shells};
}

/**
 * Build the client into `out` (default dist/client). `copy` filters which
 * static entries are copied (tests skip the large data directories).
 */
export async function buildClient({root = 'dist', out = join(root, 'client'), copy, headers = ''} = {}) {
  root = resolve(root); out = resolve(out);
  await rm(out, {recursive: true, force: true});
  await build({configFile: false, ...clientConfig({root, outDir: out})});
  const manifest = JSON.parse(await readFile(join(out, MANIFEST), 'utf8'));
  await copyStatic(root, out, {only: copy});
  const {buildId, shells} = await hashPages(out, pages(root));
  await writeFile(join(out, '_headers'), headers + IMMUTABLE_ASSETS);
  await writeFile(join(out, '.assetsignore'), '.vite\n');
  await writePrecache(out, buildId);
  return {buildId, shells, manifest};
}
