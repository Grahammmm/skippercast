#!/usr/bin/env node
// After `pnpm build`: manifest-integrity check of dist/client (P4-01a).
// Usage: node scripts/check_client.mjs [client-dir] [source-dir]
//
// - Every script and stylesheet is a hashed file in assets/ (NAME.<10 hex>.ext)
//   named by .vite/manifest.json, or a vendored file under vendor/ loaded with
//   an SRI integrity attribute. No authored module source is published raw.
// - Every page is NAME.<buildId>.html (served by the Worker from its stable
//   path), and every <script>, <link> and <img> reference in it resolves.
// - Every relative import and asset URL inside the hashed scripts resolves.
// - index.html modulepreloads the boot chain (scripts/vite-preload.mjs).
// - sw.js stays at /sw.js, unhashed, and carries the build id; precache.json
//   lists exactly this build's hashed scripts and styles.
// - The v2 pages stay within their gzipped JavaScript and CSS budgets
//   (scripts/startup-budget.json "bundles"; FE-09, front-end design § 13).
//   Usage: node scripts/check_client.mjs [client-dir] [source-dir] [budget-file]
import {readdir, readFile} from 'node:fs/promises';
import {join, posix} from 'node:path';
import {gzipSync} from 'node:zlib';
import {MANIFEST, STABLE} from './client-build.mjs';
import {FINGERPRINTED} from './precache.mjs';
import {bootPreloadRoots} from './vite-preload.mjs';

const dir = process.argv[2] || 'dist/client';
const source = process.argv[3] || join(dir, '..');
const budgetFile = process.argv[4] || new URL('./startup-budget.json', import.meta.url).pathname;
const problems = [];
const exists = path => readFile(join(dir, path)).then(() => true, () => false);
const HASHED = /^assets\/[\w.-]+\.[0-9a-f]{10}\.[a-z0-9]+$/;

let manifest = {};
try { manifest = JSON.parse(await readFile(join(dir, MANIFEST), 'utf8')); } catch { problems.push(`${MANIFEST} missing or invalid`); }
let precache = null;
try { precache = JSON.parse(await readFile(join(dir, 'precache.json'), 'utf8')); } catch { problems.push('precache.json missing or invalid'); }
const build = precache?.build;

// 1. Manifest entries point at hashed files that exist.
const named = new Set();
for (const [key, entry] of Object.entries(manifest)) {
  for (const file of [entry.file, ...(entry.css || []), ...(entry.assets || [])].filter(Boolean)) {
    named.add(file);
    if (!HASHED.test(file)) problems.push(`manifest ${key} -> ${file} (not hashed)`);
    else if (!await exists(file)) problems.push(`manifest ${key} -> ${file} (missing)`);
  }
}

// 2. assets/ holds only hashed files; nothing authored is published raw.
const assets = (await readdir(join(dir, 'assets')).catch(() => [])).map(n => `assets/${n}`);
for (const file of assets) if (!HASHED.test(file)) problems.push(`${file} (not hashed)`);
for (const file of named) if (!assets.includes(file)) problems.push(`manifest names ${file} outside assets/`);
const top = (await readdir(dir, {withFileTypes: true})).filter(e => e.isFile()).map(e => e.name);
const pages = top.filter(n => n.endsWith('.html'));
for (const name of top.filter(n => /\.(?:js|css)$/.test(n) && !STABLE.has(n))) problems.push(`${name} (unbundled script or stylesheet at the site root)`);
for (const name of pages) if (!build || !name.endsWith(`.${build}.html`)) problems.push(`${name} (page not named NAME.<build>.html)`);
if (!pages.some(n => n.startsWith('index.'))) problems.push('index page missing');

// 3. Every page reference resolves; scripts and styles are hashed or vendored with SRI.
const attr = (tag, name) => tag.match(new RegExp(`\\s${name}\\s*=\\s*"([^"]*)"`))?.[1];
const local = ref => ref && !/^(?:[a-z]+:|\/\/|#)/i.test(ref);
const clean = ref => posix.normalize(ref.replace(/^\.\//, '').replace(/^\//, '').split(/[?#]/)[0]);
let references = 0;
for (const page of pages) {
  const html = await readFile(join(dir, page), 'utf8');
  for (const [tag, kind] of html.matchAll(/<(script|link|img)\b[^>]*>/g)) {
    const ref = attr(tag, kind === 'link' ? 'href' : 'src');
    if (!local(ref)) continue;
    const path = clean(ref), rel = attr(tag, 'rel') || '';
    references++;
    if (!await exists(path)) { problems.push(`${page} -> ${ref} (missing)`); continue; }
    const code = kind === 'script' || /\b(?:stylesheet|modulepreload)\b/.test(rel);
    if (code && !HASHED.test(path)) {
      if (!path.startsWith('vendor/')) problems.push(`${page} -> ${ref} (unhashed script or stylesheet)`);
      else if (!/^sha(?:256|384|512)-/.test(attr(tag, 'integrity') || '')) problems.push(`${page} -> ${ref} (vendored file without an integrity attribute)`);
    }
  }
}

// 4. Relative imports and asset URLs inside hashed scripts resolve.
let imports = 0;
for (const file of assets.filter(n => n.endsWith('.js'))) {
  const text = await readFile(join(dir, file), 'utf8');
  for (const [, ref] of text.matchAll(/["'`](\.{1,2}\/[\w./-]+\.(?:js|css|json|wasm|png|svg))["'`]/g)) {
    imports++;
    if (!await exists(posix.join('assets', ref))) problems.push(`${file} -> ${ref} (missing)`);
  }
  for (const [, ref] of text.matchAll(/["'`]\/(assets\/[\w.-]+)["'`]/g)) {
    imports++;
    if (!await exists(ref)) problems.push(`${file} -> /${ref} (missing)`);
  }
}

// 5. The index page preloads the boot chain and everything it imports statically.
const index = pages.find(n => n.startsWith('index.'));
if (index && Object.keys(manifest).length) {
  const html = await readFile(join(dir, index), 'utf8');
  const preloaded = new Set([...html.matchAll(/<link\b[^>]*rel="modulepreload"[^>]*>/g)].map(([tag]) => clean(attr(tag, 'href') || '')));
  const entry = manifest['index.html'];
  const bootSource = await readFile(join(source, 'boot.js'), 'utf8').catch(() => '');
  if (!bootSource) problems.push(`${join(source, 'boot.js')} not found (pass the source directory as the second argument)`);
  const expected = new Set();
  const walk = key => { const e = manifest[key]; if (!e || expected.has(e.file)) return; expected.add(e.file); (e.imports || []).forEach(walk); };
  for (const root of bootPreloadRoots(bootSource)) {
    if (!manifest[root]) problems.push(`boot.js imports ./${root}, which is not in the manifest`);
    walk(root);
  }
  (entry?.imports || []).forEach(walk);
  for (const file of expected) if (file !== entry?.file && !preloaded.has(file)) problems.push(`${index} does not modulepreload ${file}`);
  for (const file of preloaded) if (!HASHED.test(file)) problems.push(`${index} preloads ${file} (not hashed)`);
}

// 6. Stable service worker and the precache list.
if (precache) {
  const listed = [...(precache.assets || [])].sort();
  const expected = assets.filter(n => FINGERPRINTED.test(n)).map(n => `/${n}`).sort();
  if (JSON.stringify(listed) !== JSON.stringify(expected)) problems.push('precache.json assets differ from the hashed scripts and styles');
  if (JSON.stringify(precache.shells) !== JSON.stringify(['/'])) problems.push('precache.json must list the app shell "/"');
  for (const path of precache.static || []) if (!await exists(path.slice(1))) problems.push(`precache.json -> ${path} (missing)`);
  const sw = await readFile(join(dir, 'sw.js'), 'utf8').catch(() => '');
  if (!sw) problems.push('sw.js missing at the site root');
  if (!sw.includes(`const BUILD = '${precache.build}';`)) problems.push('sw.js does not carry the precache build id');
}
if (!(await readFile(join(dir, '.assetsignore'), 'utf8').catch(() => '')).includes('.vite')) problems.push('.assetsignore must keep .vite/ unpublished');

// 7. v2 page budgets: the entry plus its static imports (what runs before first
// paint) and its stylesheets, gzipped; a page absent from this build is skipped.
const budgets = JSON.parse(await readFile(budgetFile, 'utf8')).bundles || {};
const gzipped = async file => gzipSync(await readFile(join(dir, file)), {level: 9}).length;
const measured = [];
for (const [page, budget] of Object.entries(budgets)) {
  if (page === 'comment' || !manifest[page]) continue;
  const js = new Set(), css = new Set();
  const walk = key => {
    const e = manifest[key];
    if (!e || js.has(e.file) || css.has(e.file)) return;
    (e.file.endsWith('.css') ? css : js).add(e.file);
    for (const file of e.css || []) css.add(file);
    (e.imports || []).forEach(walk);
  };
  walk(page);
  const total = async files => { let n = 0; for (const f of files) n += await exists(f) ? await gzipped(f) : 0; return n; };
  const size = {js: await total(js), css: await total(css)};
  measured.push(`${page} js ${size.js} B, css ${size.css} B gzipped`);
  for (const kind of ['js', 'css']) {
    const max = budget[`${kind}_gzip_max`];
    if (Number.isFinite(max) && size[kind] > max) problems.push(`${page}: initial ${kind === 'js' ? 'JavaScript' : 'CSS'} ${size[kind]} B gzipped exceeds its budget of ${max} B (${budgetFile})`);
  }
}

if (problems.length) {
  console.error(`Client check failed:\n  ${problems.join('\n  ')}`);
  process.exit(1);
}
console.log(`Client check passed: ${assets.length} hashed assets, ${pages.length} pages, ${references} page references and ${imports} script references resolve, ${precache.assets.length + precache.shells.length + precache.static.length} precached for build ${precache.build}.${measured.length ? ` Budgets: ${measured.join('; ')}.` : ''}`);
