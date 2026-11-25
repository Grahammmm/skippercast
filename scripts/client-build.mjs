// Build the static client (P4-01a): Vite, then the Worker-facing contract.
//
// 1. Vite (vite.config.mjs) bundles every page in dist/*.html with its modules
//    and stylesheets into <out>/assets/NAME.<10 hex>.{js,css} and writes
//    <out>/.vite/manifest.json.
// 2. Static files are copied unchanged: data/, regions/, vendor/, non-GPX downloads/,
//    tiles/, icons, the web manifest, and sw.js (STABLE: a service worker's
//    URL is its identity, and the pages register '/sw.js').
// 3. Pages get <meta name="skippercast-build"> and are renamed
//    NAME.<buildId>.html. The Worker serves them only from their stable paths
//    ('/landing.html', '/sources.html') with no-store, via the returned shells map, so a
//    cached page can never pin an old set of assets.
// 4. precache.json and the build id in sw.js (scripts/precache.mjs), _headers
//    (server/security-headers.ts, plus a year's immutable caching for
//    /assets/* and /basemap/glyphs/v/*, and a short cache for region and data
//    files except safety inputs, which still revalidate) and
//    .assetsignore (keeps .vite/ off the CDN).
// 5. Reviewed relief pointers, catalog/relief/<region>.json, are copied byte for
//    byte to the same path (copyReliefPointers). The relief layer and ft-v3 contours
//    fetch them there and live-check compares their SHA-256 with the merged commit.
//
// The build id hashes every page and every hashed asset name, so any change
// to a module, stylesheet or page gives a new id (and a new service worker).
import {createHash} from 'node:crypto';
import {cp, lstat, mkdir, readdir, readFile, rename, rm, writeFile} from 'node:fs/promises';
import {join, relative, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'vite';
import {clientConfig, pages} from '../vite.config.mjs';
import {validateSchema} from './json-schema-lite.mjs';
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

export const STATIC_MAX_AGE_S = 120;
export const STATIC_SWR_S = 300;
export const STATIC_DATA = ['/regions/*', '/data/*'].map(path =>
  `${path}\n  Cache-Control: public, max-age=${STATIC_MAX_AGE_S}, stale-while-revalidate=${STATIC_SWR_S}\n`).join('');
export const REVALIDATE = 'public, max-age=0, must-revalidate';
// Cloudflare joins matching values. Clear the short cache rule before restoring
// the default for each safety path; Cloudflare permits only one splat per rule.
export const SAFETY_FILES = [
  '/data/regulations*.json',
  '/regions/*/regulations.json',
  '/regions/*/regulations-startup.json',
  '/data/protected-areas.geojson',
  '/regions/*/protected-areas.geojson',
  '/data/noaa-federal-areas.json',
  '/data/*-closure-review.json',
  '/regions/*/groundfish-exclusions.geojson',
  '/regions/*/coverage.json',
].map(path => `${path}\n  ! Cache-Control\n  Cache-Control: ${REVALIDATE}\n`).join('');

// Top-level authored module sources: Vite builds these instead of copying them.
const SOURCE = /\.(?:js|css|html)$/;
// These nested inputs are bundled by admin.html, chat.html, my-data.html and
// upload.html. Server-rendered advisor pages reuse chat.html's hashed assets.
const BUNDLED_ADVISOR_SOURCES = new Set([
  'advisor/admin.css', 'advisor/chat.css', 'advisor/my-data.js',
  'advisor/pages.css', 'advisor/upload.css', 'advisor/upload.js',
]);

export function hashName(name, buildId) {
  const dot = name.lastIndexOf('.');
  return `${name.slice(0, dot)}.${buildId}${name.slice(dot)}`;
}

// Local-only build output of scripts/build_bathy_tiles.py (rights under review) and of
// scripts/build_tide_layer.py (MAPLAYER-TIDE-1 test-page data): never published,
// even if someone points --output into dist/.
const PRIVATE_OUTPUT = /(?:^|\/)(?:morro-bay-seafloor-deep(?:-[a-z]+)?\.(?:pmtiles|part)|tide-layer-[^/]*\.(?:json|part))$/;

// collect_shore_habitat.py raw archives, receipts and interrupted atomic writes.
const RAW_SHORE = /(?:^|\/)(?:\.)?(?:ccc-access-(?:points|item|estero)|noaa-esi-shoreline|receipts)\.json(?:\.[0-9a-f]+\.tmp)?$/i;

// E2E-13: defence in depth. Only these dist/tiles archives may ship; any other
// *.pmtiles under dist/ (e.g. a relief or CSUMB-derived laguna-seafloor-deep-medium.pmtiles)
// fails the build instead of being copied. Add a name here only with its rights cleared.
export const PUBLIC_PMTILES = new Set(['tiles/morro-bay-reef-outlines.pmtiles', 'tiles/socal-survey-habitat.pmtiles']);

/** True to copy `from` (under `src`); throws on raw shore data, links or unallowlisted *.pmtiles. */
async function keepStatic(src, from) {
  const posix = from.split(sep).join('/');
  const rel = relative(src, from).split(sep).join('/');
  if (RAW_SHORE.test(rel)) throw Error(`refusing to publish ${rel}: raw shore source artifact`);
  if (/\.pmtiles$/i.test(posix)) {
    if (!PUBLIC_PMTILES.has(rel)) throw Error(`refusing to publish ${rel}: *.pmtiles under dist/ must be on PUBLIC_PMTILES (scripts/client-build.mjs)`);
  }
  if (PRIVATE_OUTPUT.test(posix)) return false;
  if (BUNDLED_ADVISOR_SOURCES.has(rel)) return false;
  // A link can expose a whole private directory without naming a raw artifact.
  if ((await lstat(from)).isSymbolicLink()) throw Error(`refusing to publish ${rel}: symbolic link`);
  // SCA-091: don't ship stale local copies left by an older checkout or generator.
  if (rel.startsWith('downloads/') && /\.gpx$/i.test(rel)) return false;
  return true;
}

/** Copy dist's static files (everything but module sources, build output and dot-entries). */
export async function copyStatic(src, out, {only} = {}) {
  if ((await lstat(src)).isSymbolicLink()) throw Error('refusing to publish from a symbolic link as the static root');
  for (const entry of await readdir(src, {withFileTypes: true})) {
    const name = entry.name;
    if (name === 'client' || name === 'server' || name.startsWith('.')) continue;
    if (entry.isFile() && SOURCE.test(name) && !STABLE.has(name)) continue;
    if (only && !only(name)) continue;
    await cp(join(src, name), join(out, name), {recursive: true, filter: from => keepStatic(src, from)});
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

// The repository's reviewed relief pointers. The README and the schema stay in the repository.
export const RELIEF_POINTERS = 'catalog/relief';
const RELIEF_SOURCE = fileURLToPath(new URL(`../${RELIEF_POINTERS}/`, import.meta.url));
const RELIEF_SCHEMA = join(RELIEF_SOURCE, 'pointer.schema.json');
const RELIEF_KEEP = new Set(['README.md', 'pointer.schema.json']);
const POINTER_LIMIT = 1 << 20;  // the same bound the hosted STAGE job puts on a pointer blob
const REGION_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Copy each reviewed relief pointer in `src` to <out>/catalog/relief/ with its exact bytes; returns the names.
 * Anything else in the directory, a link, an oversized or malformed file, or a pointer that is not a public,
 * reviewed sc-relief-pointer/1 for the region its name says, or that breaks any rule of
 * catalog/relief/pointer.schema.json (hashes, bytes, previous, bounds, sources and their public rights), fails the
 * build instead of being published.
 */
export async function copyReliefPointers(src, out, schemaFile = RELIEF_SCHEMA) {
  const names = await readdir(src).catch(error => { if (error.code === 'ENOENT') return []; throw error; });
  const copied = [];
  // The repository's own schema, never a copy found beside the pointers.
  const schema = names.some(name => !RELIEF_KEEP.has(name)) ? JSON.parse(await readFile(schemaFile, 'utf8')) : null;
  for (const name of names.sort()) {
    if (RELIEF_KEEP.has(name)) continue;
    const rel = `${RELIEF_POINTERS}/${name}`, region = name.endsWith('.json') ? name.slice(0, -5) : '';
    if (!REGION_ID.test(region) || region.length > 64) throw Error(`refusing to publish ${rel}: not a regional relief pointer name`);
    const from = join(src, name), info = await lstat(from);
    if (!info.isFile()) throw Error(`refusing to publish ${rel}: not a regular file`);
    if (info.size > POINTER_LIMIT) throw Error(`refusing to publish ${rel}: larger than ${POINTER_LIMIT} bytes`);
    const bytes = await readFile(from);
    let doc;
    try { doc = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)); } catch { throw Error(`refusing to publish ${rel}: not JSON`); }
    if (doc?.schema !== 'sc-relief-pointer/1' || doc.status !== 'reviewed' || doc.private !== false || doc.region !== region) {
      throw Error(`refusing to publish ${rel}: not a public reviewed relief pointer for ${region}`);
    }
    // The whole contract, including every source's public-rights fields, not just the four checks above.
    const problems = validateSchema(doc, schema);
    if (problems.length) {
      throw Error(`refusing to publish ${rel}: violates ${RELIEF_POINTERS}/pointer.schema.json (${problems.slice(0, 5).join('; ')}${problems.length > 5 ? `; and ${problems.length - 5} more` : ''})`);
    }
    await mkdir(join(out, RELIEF_POINTERS), {recursive: true});
    await writeFile(join(out, RELIEF_POINTERS, name), bytes, {flag: 'wx'});
    copied.push(name);
  }
  return copied;
}

/**
 * Build the client into `out` (default dist/client). `copy` filters which
 * static entries are copied (tests skip the large data directories); `relief`
 * is the directory of reviewed relief pointers (default the repository's).
 */
export async function buildClient({root = 'dist', out = join(root, 'client'), copy, headers = '', relief = RELIEF_SOURCE} = {}) {
  root = resolve(root); out = resolve(out);
  generateStrings();   // SC1407-09: the readers' English and Spanish tables, from catalog/app/strings.json
  await rm(out, {recursive: true, force: true});
  await build({configFile: false, ...clientConfig({root, outDir: out})});
  const manifest = JSON.parse(await readFile(join(out, MANIFEST), 'utf8'));
  await copyStatic(root, out, {only: copy});
  await copyReliefPointers(relief, out);
  await versionGlyphs(out);
  const {buildId, shells} = await hashPages(out, pages(root));
  await writeFile(join(out, '_headers'), headers + IMMUTABLE_ASSETS + IMMUTABLE_GLYPHS + STATIC_DATA + SAFETY_FILES);
  await writeFile(join(out, '.assetsignore'), '.vite\n');
  await writePrecache(out, buildId);
  return {buildId, shells, manifest};
}
