#!/usr/bin/env node
// Offline MB-08 renderer QA (not the authenticated app shell).
// Usage: qa_shots.mjs RELEASE_JSON BASEMAP_PMTILES NEW_SHOT_DIR [LON LAT]
import {createHash} from 'node:crypto';
import {createReadStream} from 'node:fs';
import {mkdir, open, readFile, realpath, writeFile} from 'node:fs/promises';
import {basename, dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from '@playwright/test';
import {build} from 'esbuild';

const [manifest, basemap, output, lonArg, latArg] = process.argv.slice(2);
if (!manifest || !basemap || !output || (lonArg == null) !== (latArg == null)) {
  throw new Error('usage: qa_shots.mjs RELEASE_JSON BASEMAP_PMTILES NEW_SHOT_DIR [LON LAT]');
}
const origin = 'http://127.0.0.1'; // All requests are fulfilled locally; no listening service.
const repo = fileURLToPath(new URL('../../', import.meta.url));
const sha = data => createHash('sha256').update(data).digest('hex');
const raw = await readFile(manifest);
const release = JSON.parse(raw);
const digest = sha(raw);
const root = resolve(dirname(manifest), '../..');
const archive = 'layers/public/tiles/relief.pmtiles'; // the tiles stage's own leaf (package.ARCHIVE)
const index = 'layers/public/relief.digests/';
const layers = new Map(release.layers.map(row => [row.path, row]));
if (release.schema !== 'sc-relief-release/1' || release.private !== false ||
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(release.region) || !release.sources?.length ||
    !release.sources.every(s => s.rights_class === 'public' && s.rights?.public_display === 'allowed') ||
    layers.size !== release.layers.length || layers.get(`${index}root.json`)?.sha256 !== release.digest_root_sha256) {
  throw new Error('expected a byte-pinned public relief package');
}
async function pinnedPath(key) {
  const path = join(root, key);
  if (!layers.has(key) || await realpath(path) !== path) throw new Error(`unbound release layer: ${key}`);
  return path;
}
async function pinnedBytes(key) {
  const body = await readFile(await pinnedPath(key));
  if (body.length !== layers.get(key).bytes || sha(body) !== layers.get(key).sha256) {
    throw new Error(`release layer hash mismatch: ${key}`);
  }
  return body;
}
const archivePath = await pinnedPath(archive);
const archiveRef = layers.get(archive);
async function verifyArchive() {
  const hash = createHash('sha256');
  let size = 0;
  for await (const block of createReadStream(archivePath)) { hash.update(block); size += block.length; }
  if (size !== archiveRef.bytes || hash.digest('hex') !== archiveRef.sha256) throw new Error('relief archive hash mismatch');
}
await verifyArchive();
const [w, s, e, n] = release.bounds;
const lon = lonArg == null ? (w + e) / 2 : Number(lonArg);
const lat = latArg == null ? (s + n) / 2 : Number(latArg);
if (!(w <= lon && lon <= e && s <= lat && lat <= n) ||
    !Number.isInteger(release.minzoom) || !Number.isInteger(release.maxzoom) ||
    release.minzoom < 8 || release.maxzoom > 17 || release.minzoom > release.maxzoom) throw new Error('invalid fixed camera or zoom range');
const cameras = [...new Set([release.minzoom, 10, 13, 15, release.maxzoom]
  .filter(z => z >= release.minzoom && z <= release.maxzoom))].sort((a, b) => a - b);

// Only the loopback browser sees this adapter. QA precedes review: the sentinel
// is not an envelope, approval, or on-disk/public pointer.
const pointer = {...release, sha256: archiveRef.sha256, bytes: archiveRef.bytes,
  release_sha256: digest, envelope_sha256: '0'.repeat(64)};
const object = `/feeds/tiles/relief/${release.region}/${archiveRef.sha256}`;
const digestBase = `${object}.digests/${release.digest_root_sha256}/`;
const detailKey = 'layers/public/zone/detail.geojson'; // the zone stage's own leaf
const detail = layers.has(detailKey) ? JSON.parse(await pinnedBytes(detailKey)) : undefined;
const digestRoot = await pinnedBytes(`${index}root.json`);
const [chart, worker] = await Promise.all([
  build({absWorkingDir: repo, write: false, bundle: true, format: 'esm', outdir: 'qa', loader: {'.woff2': 'file'},
    stdin: {resolveDir: repo, contents: `
      import * as library from './web/map/maplibre.js';
      import './web/tokens.css';
      import {createEngine} from './web/map/engine.ts';
      import {attachBottomRelief} from './web/map/bottom-relief.ts';
      import {basemapStyle} from './web/map/style.ts';
      import {readPalette} from './web/map/palette.ts';
      const zoom = Number(new URL(location.href).searchParams.get('zoom'));
      const showError = e => { window.qaError = String(e); };
      let tileLoaded = false;
      const engine = createEngine(library, {host: document.querySelector('main'),
        camera: {latitude: ${lat}, longitude: ${lon}, zoom},
        style: basemapStyle(readPalette(), {archive: location.origin + '/basemap.pmtiles', assets: '/'}),
        onMove() {}, onLayerError: (_, error) => showError(error),
        onSourceTileLoaded: id => { if (id.startsWith('bottom-relief-')) tileLoaded = true; },
        onIdle: () => { window.qaReady = tileLoaded; }});
      const layer = attachBottomRelief({engine, region: ${JSON.stringify(release.region)}, library: library.lib,
        unavailable: showError, seafloorOn: () => false, fieldOn: () => false,
        surveyDetail: ${JSON.stringify(detail)}});
      addEventListener('pagehide', () => { layer.destroy(); engine.destroy(); });
    `}, plugins: [{name: 'local-chart-worker', setup(b) {
      b.onResolve({filter: /maplibre-gl-worker\.mjs\?worker&url$/}, () => ({path: 'worker', namespace: 'qa'}));
      b.onLoad({filter: /^worker$/, namespace: 'qa'}, () => ({contents: 'export default "/worker.js";'}));
    }}]}),
  build({absWorkingDir: repo,
    entryPoints: [fileURLToPath(import.meta.resolve('maplibre-gl/dist/maplibre-gl-worker.mjs'))],
    write: false, bundle: true, format: 'esm'}),
]);
const assets = new Map(chart.outputFiles.map(f => [`/${basename(f.path)}`, Buffer.from(f.contents)]));
assets.set('/worker.js', Buffer.from(worker.outputFiles[0].contents));
const folder = resolve(output);
await mkdir(folder);
await mkdir(join(folder, 'shots'));
const shots = [];

async function rangeResponse(route, fd, size) {
  const range = /^bytes=(\d+)-(\d+)$/.exec(route.request().headers().range || '');
  if (!range) throw new Error('archive read without a bounded Range');
  const start = Number(range[1]), end = Math.min(Number(range[2]), size - 1);
  if (start > end || end - start >= 16 * 1024 * 1024) throw new Error('invalid archive Range');
  const body = Buffer.alloc(end - start + 1);
  if ((await fd.read(body, 0, body.length, start)).bytesRead !== body.length) throw new Error('short archive Range');
  return route.fulfill({status: 206, body, headers: {'content-range': `bytes ${start}-${end}/${size}`}});
}

async function capture(browser, archives, device, width, height, theme, zoom) {
  const ctx = await browser.newContext({viewport: {width, height}, colorScheme: theme, serviceWorkers: 'block'});
  const errors = [];
  try {
    const page = await ctx.newPage();
    await ctx.route('**/*', async route => {
      const {origin: host, pathname: path} = new URL(route.request().url());
      try {
        if (host !== origin) throw new Error('off-loopback request blocked');
        if (path === '/') return await route.fulfill({contentType: 'text/html', body: `<!doctype html>
          <html lang="en" data-theme="${theme}"><meta charset="utf-8"><link rel="stylesheet" href="/stdin.css">
          <style>body{margin:0}main{height:100vh}aside{position:absolute;bottom:1rem;left:1rem;
          color:var(--text);background:var(--panel);padding:.5rem;font:14px system-ui}</style>
          <main></main><aside>NOT FOR NAVIGATION · MB-08 Chart QA</aside><script type="module" src="/stdin.js"></script>`});
        if (assets.has(path)) return await route.fulfill({body: assets.get(path),
          contentType: path.endsWith('.woff2') ? 'font/woff2' : path.endsWith('.css') ? 'text/css' : 'text/javascript'});
        if (path === `/catalog/relief/${release.region}.json`) return await route.fulfill({json: pointer});
        if (archives.has(path)) return await rangeResponse(route, ...archives.get(path));
        if (path === `${digestBase}root.json`) return await route.fulfill({body: digestRoot});
        if (path.startsWith(digestBase)) {
          const chunk = path.slice(digestBase.length);
          if (/^\d+\/\d+_\d+\.json$/.test(chunk)) return await route.fulfill({body: await pinnedBytes(index + chunk)});
        }
        const glyph = /^\/glyphs\/v\/[0-9a-f]+\/(dm-sans-medium\/\d+-\d+\.pbf)$/.exec(path);
        if (glyph) return await route.fulfill({body: await readFile(join(repo, 'dist/basemap/glyphs', glyph[1]))});
        throw new Error('unexpected request');
      } catch (error) {
        errors.push(`${path}: ${error.message}`);
        await route.abort();
      }
    });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${origin}/?zoom=${zoom}`, {timeout: 30000});
    await page.waitForFunction(() => window.qaReady || window.qaError, null, {timeout: 30000});
    const error = await page.evaluate(() => window.qaError);
    if (error || errors.length) throw new Error(error || errors[0]);
    const notice = page.getByText('NOT FOR NAVIGATION · MB-08 Chart QA', {exact: true});
    if (!(await notice.isVisible()) || !(await page.locator('main canvas').isVisible())) throw new Error('missing notice or Chart canvas');
    // The box lets QA check the notice's actual pixels in the PNG rather than trust the flag below.
    const box = await notice.boundingBox();
    if (!box) throw new Error('notice has no box');
    const x = Math.max(0, Math.floor(box.x)), y = Math.max(0, Math.floor(box.y));
    const notice_box = [x, y, Math.min(width, Math.ceil(box.x + box.width)) - x, Math.min(height, Math.ceil(box.y + box.height)) - y];
    const path = `shots/${theme}-${device}-z${zoom}.png`;
    const png = await page.screenshot({path: join(folder, path)});
    shots.push({path, sha256: sha(png), theme, device, zoom, viewport: [width, height], navigation_visible: true, notice_box});
  } catch (error) {
    throw new Error(`${theme}/${device}/z${zoom}: ${errors[0] || error.message}`, {cause: error});
  } finally { await ctx.close(); }
}

const baseFile = await open(basemap, 'r');
try {
  const reliefFile = await open(archivePath, 'r');
  try {
    const archives = new Map([['/basemap.pmtiles', [baseFile, (await baseFile.stat()).size]],
      [`${object}.pmtiles`, [reliefFile, archiveRef.bytes]]]);
    const browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
    try {
      for (const [device, width, height] of [['desktop', 1200, 800], ['phone', 390, 844]]) {
        for (const theme of ['dark', 'light']) {
          for (const zoom of cameras) await capture(browser, archives, device, width, height, theme, zoom);
        }
      }
    } finally { await browser.close(); }
  } finally { await reliefFile.close(); }
} finally { await baseFile.close(); }
await verifyArchive();
if (sha(await readFile(manifest)) !== digest) throw new Error('release bytes changed during capture');
await writeFile(join(folder, 'shots.json'), JSON.stringify({renderer: 'mb08-chart', release_sha256: digest,
  center: [lon, lat], cameras, shots}, null, 2) + '\n', {flag: 'wx'});
