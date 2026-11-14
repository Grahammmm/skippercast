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
//    ('/landing.html', '/sources.html') with no-store, via the returned shells map, so a
//    cached page can never pin an old set of assets.
// 4. precache.json and the build id in sw.js (scripts/precache.mjs), _headers
//    (server/security-headers.ts, plus a year's immutable caching for
//    /assets/* and the content-versioned glyphs /basemap/glyphs/v/*) and
//    .assetsignore (keeps .vite/ off the CDN).
//
// The build id hashes every page and every hashed asset name, so any change
// to a module, stylesheet or page gives a new id (and a new service worker).
import {createHash} from 'node:crypto';
import {cp, readdir, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {join, resolve, sep} from 'node:path';
import {build} from 'vite';
import {clientConfig, pages} from '../vite.config.mjs';
import {writePrecache} from './precache.mjs';
import {generate as generateStrings} from './build_landing_strings.mjs';
import {GLYPH_VERSION} from '../web/map/style.ts';

export const STABLE = new Set(['sw.js']);
export const MANIFEST = '.vite/manifest.json';
// Hashed names never change content, so browsers and the edge keep them a year.
export const IMMUTABLE_ASSETS = '/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n';
// R4-SC-08: the label glyphs are also published under their content version,
// basemap/glyphs/v/<GLYPH_VERSION>/<stack>/<range>.pbf, which the Chart style
// loads and browsers keep a year. The unversioned basemap/glyphs/<stack>/ files
// stay, with the assets' default revalidation, for pages and packs that name them.
export const GLYPHS = 'basemap/glyphs';
export const IMMUTABLE_GLYPHS = `/${GLYPHS}/v/*\n  Cache-Control: public, max-age=31536000, immutable\n`;
// Authored module sources: Vite builds these, so they are never copied raw.
const SOURCE = /\.(?:js|css|html)$/;

export function hashName(name, buildId) {
  const dot = name.lastIndexOf('.');
  return `${name.slice(0, dot)}.${buildId}${name.slice(dot)}`;
}

// Local-only build output of scripts/build_bathy_tiles.py (rights under review) and of
// scripts/build_tide_layer.py (MAPLAYER-TIDE-1 test-page data): never published,
// even if someone points --output into dist/.
const PRIVATE_OUTPUT = /(?:^|\/)(?:morro-bay-seafloor-deep(?:-[a-z]+)?\.(?:pmtiles|part)|tide-layer-[^/]*\.(?:json|part))$/;

/** Copy dist's static files (everything but module sources, build output and dot-entries). */
export async function copyStatic(src, out, {only} = {}) {
  for (const entry of await readdir(src, {withFileTypes: true})) {
    const name = entry.name;
    if (name === 'client' || name === 'server' || name.startsWith('.')) continue;
    if (entry.isFile() && SOURCE.test(name) && !STABLE.has(name)) continue;
    if (only && !only(name)) continue;
    await cp(join(src, name), join(out, name), {recursive: true, filter: from => !PRIVATE_OUTPUT.test(from.split(sep).join('/'))});
  }
}

/**
 * The glyph set's content version: the first 16 hex of SHA-256 over every
 * unversioned range file under `dir` (sorted `<stack>/<range>.pbf` path, NUL,
 * bytes, NUL), with those paths; null when `dir` holds no range file.
 */
export async function glyphVersion(dir) {
  const names = (await readdir(dir, {recursive: true}).catch(() => []))
    .map(name => name.split(sep).join('/')).filter(name => name.endsWith('.pbf') && !name.startsWith('v/')).sort();
  if (!names.length) return null;
  const hash = createHash('sha256');
  for (const name of names) hash.update(name).update('\0').update(await readFile(join(dir, name))).update('\0');
  return {version: hash.digest('hex').slice(0, 16), names};
}

/**
 * Copy the glyph ranges in `out` to basemap/glyphs/v/<version>/ and return the
 * version (null without glyphs). Throws when the files no longer hash to
 * `expected` (GLYPH_VERSION), so a versioned URL never names other bytes.
 */
export async function versionGlyphs(out, expected = GLYPH_VERSION) {
  const dir = join(out, GLYPHS), set = await glyphVersion(dir);
  if (!set) return null;
  if (set.version !== expected) throw Error(`${GLYPHS} hashes to ${set.version}, not GLYPH_VERSION ${expected}: set GLYPH_VERSION in web/map/style.ts with the new glyph files`);
  for (const name of set.names) await cp(join(dir, name), join(dir, 'v', set.version, name));
  return set.version;
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
  }
  return {buildId, shells};
}

// TA-W1: the hashed files the Worker's server-rendered advisor pages link
// (docs/plans/text-advisor/01-architecture.md § touch points, ADVISOR_ASSETS).
// dist/chat.html carries advisor/pages.css in its stylesheet set, so its
// built stylesheet and its entry script serve the pages too. FE-55: the page
// links web/tokens.css, which Vite emits as its own chunk when another page
// (app.html) shares it; the pages then link that chunk as advisor/tokens.css.
export const ADVISOR_PAGE = 'chat.html';
const TOKENS_CHUNK = /(?:^|\/)tokens\.[\w-]+\.css$/;
/**
 * {'advisor/tokens.css'?: '/assets/tokens.<hash>.css', 'advisor/pages.css': '/assets/chat.<hash>.css', 'advisor/chat.js': '/assets/chat.<hash>.js'}
 * from the Vite manifest; throws if the entry is missing or has a stylesheet the pages would not link.
 */
export function advisorAssetPaths(manifest) {
  const entry = manifest?.[ADVISOR_PAGE], js = entry?.file;
  const sheets = Array.isArray(entry?.css) ? entry.css : [];
  const tokens = sheets.filter(f => TOKENS_CHUNK.test(f)), own = sheets.filter(f => !TOKENS_CHUNK.test(f));
  if (!entry?.isEntry || own.length !== 1 || tokens.length > 1 || typeof js !== 'string') throw Error(`Vite manifest has no ${ADVISOR_PAGE} entry with one stylesheet (plus the tokens) and a script`);
  return {...(tokens.length ? {'advisor/tokens.css': `/${tokens[0]}`} : {}), 'advisor/pages.css': `/${own[0]}`, 'advisor/chat.js': `/${js}`};
}
// TA-W1 end.

/**
 * Build the client into `out` (default dist/client). `copy` filters which
 * static entries are copied (tests skip the large data directories).
 */
export async function buildClient({root = 'dist', out = join(root, 'client'), copy, headers = ''} = {}) {
  root = resolve(root); out = resolve(out);
  generateStrings();   // SC1407-09: the readers' English and Spanish tables, from catalog/app/strings.json
  await rm(out, {recursive: true, force: true});
  await build({configFile: false, ...clientConfig({root, outDir: out})});
  const manifest = JSON.parse(await readFile(join(out, MANIFEST), 'utf8'));
  await copyStatic(root, out, {only: copy});
  await versionGlyphs(out);
  const {buildId, shells} = await hashPages(out, pages(root));
  await writeFile(join(out, '_headers'), headers + IMMUTABLE_ASSETS + IMMUTABLE_GLYPHS);
  await writeFile(join(out, '.assetsignore'), '.vite\n');
  await writePrecache(out, buildId);
  return {buildId, shells, manifest};
}
