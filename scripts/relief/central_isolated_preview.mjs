#!/usr/bin/env node
// C48: special-purpose, loopback-only Chart build and acceptance runner. Never invoked by the normal build.
import {createHash} from 'node:crypto';
import {cp, lstat, mkdir, readFile, realpath, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {extname, resolve, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {clientAsset} from './central_built_navigation.mjs';
import {PHONE, PROFILE, TERRAIN_ONLY} from './central_preview_cameras.mjs';
import {classify, visibleLinesInView, visibleOthersInView} from './central_arrival_audit.mjs';

const IDs = [...Object.keys(PROFILE), ...TERRAIN_ONLY].sort();
const SHA = /^[0-9a-f]{64}$/;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const contourPath = /^\/regions\/([^/]+)\/depth-contours(?:-overview)?\.geojson$/;
const terrainPath = /^\/feeds\/tiles\/relief\/([^/]+)\//;
const archiveWitness = (row, id) => terrainPath.exec(row.path)?.[1] === id && row.status === 206;
const media = {'.html':'text/html; charset=utf-8', '.js':'text/javascript', '.css':'text/css', '.json':'application/json',
  '.geojson':'application/json', '.png':'image/png', '.svg':'image/svg+xml', '.woff2':'font/woff2'};

export function previewOrigin(origin) {
  return /^http:\/\/127\.0\.0\.1:[1-9]\d{0,4}$/.test(origin) && Number(origin.split(':').at(-1)) <= 65535;
}

// This exact function is compiled into the isolated client, not a production flag or global fetch hook.
export async function previewContourDigest(rows, origin, id, path, bytes) {
  if (!previewOrigin(origin) || !path.startsWith(`/regions/${id}/`) || !Object.hasOwn(rows, id)) return null;
  const row = rows[id];
  if (!Object.hasOwn(row.contours, path)) return null;
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('') === row.contours[path]
    ? row.style : null;
}

export function scopeRoute(path, build, files, regions) {
  if (/^\/(?:catalog|api)(?:\/|$)|^\/(?:sw\.js|precache\.json)$/.test(path)) return null;
  const region = /^\/regions\/([^/]+)\//.exec(path)?.[1] ?? terrainPath.exec(path)?.[1];
  if (region && !regions.has(region)) return null;
  const file = path.startsWith('/feeds/') ? `feeds/${clientAsset(path, build)?.slice('client/feeds/'.length) ?? ''}` : clientAsset(path, build);
  return file && files.has(file) ? file : null;
}

function replaceOne(source, from, to, name) {
  if (source.split(from).length !== 2) throw Error(`Central preview build seam changed: ${name}`);
  return source.replace(from, () => to);
}

function previewBinding(repo, rows) {
  const contours = resolve(repo, 'web/map/depth-contours.ts');
  const relief = resolve(repo, 'web/map/bottom-relief.ts');
  const touched = new Set();
  return {
    name: 'skippercast:central-loopback-only', enforce: 'pre',
    transform(code, id) {
      if (id === contours) {
        // Keep the production validator, all tier rules and expiry checks. Only the isolated build
        // can calculate the extra argument, using the requested path and exact downloaded bytes.
        code = replaceOne(code, 'pointer?: unknown): ContourAssessment', 'pointer?: unknown, previewDigest?: string | null): ContourAssessment', 'contour validator');
        code = replaceOne(code, 'const digest = anchor?.region', 'const digest = previewDigest !== undefined ? previewDigest : anchor?.region', 'style lookup');
        code = replaceOne(code,
          'await assessContourResponse(await response.json(), id, new Date(now()).toISOString().slice(0, 10), fetchFn, page());',
          `await assessLocal(response, id, path, new Date(now()).toISOString().slice(0, 10), page());`, 'contour fetch');
        const pins = Object.fromEntries(Object.entries(rows).map(([key, {style, contours}]) => [key, {style, contours}]));
        code += `\n${previewOrigin}\n${previewContourDigest}\nconst previewContourPins = ${JSON.stringify(pins)};\n`
          + `async function assessLocal(response: Response, id: string, path: string, day: string, page: string) {
              const bytes = await response.arrayBuffer();
              const digest = await previewContourDigest(previewContourPins, new URL(page).origin, id, '/' + path, bytes);
              return digest ? assessContours(JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes)), id, day, undefined, digest) : FAILED;
            }\n`;
      } else if (id === relief) {
        // Embed metadata from the six pinned envelopes, not a reviewed pointer or a provisioned tile endpoint.
        const metadata = Object.fromEntries(Object.entries(rows).map(([key, row]) => [key, row.terrain]));
        code = replaceOne(code, `const path = \`catalog/relief/\${encodeURIComponent(o.region)}.json\`;
    const response = await fetchFn(new URL(path, page), {signal, redirect: 'error'});
    if (!response.ok) throw new Error(\`Relief pointer unavailable (HTTP \${response.status})\`);
    const pointer = await response.json();`,
        `const pointer = previewOrigin(new URL(page).origin) && Object.hasOwn(localTerrain, o.region) ? localTerrain[o.region] : null;`, 'terrain fetch');
        code += `\n${previewOrigin}\nconst localTerrain: Record<string, unknown> = ${JSON.stringify(metadata)};\n`;
      } else return null;
      touched.add(id);
      return {code, map: null};
    },
    generateBundle() {
      if (touched.size !== 2) throw Error('the local Chart did not bind both preview inputs');
    },
  };
}

async function buildLocal(bindingsPath) {
  // C48 owns only this preview entry; ordinary Vite/client sources are read-only.
  const repo = resolve(import.meta.dirname, '../..');
  for (let parent = repo; ; parent = resolve(parent, '..')) {
    const git = await lstat(resolve(parent, '.git')).catch(error => {
      if (error.code !== 'ENOENT') throw error;
      return null;
    });
    if (git) throw Error('Central preview builder requires a disposable archive outside any Git checkout');
    if (parent === resolve(parent, '..')) break;
  }
  const root = resolve(repo, 'dist'), outDir = resolve(root, 'client');
  if (resolve(bindingsPath) !== resolve(repo, 'CENTRAL-LOOPBACK-BINDINGS.json')) throw Error('preview bindings must come from the isolated archive');
  const rows = JSON.parse(await readFile(bindingsPath, 'utf8'));
  if (Object.keys(rows).sort().join() !== IDs.join()) throw Error('expected the six Central regions');
  const [{build}, {clientConfig, pages}, client, {generate}, {writePrecache}] = await Promise.all([
    import('vite'), import('../../vite.config.mjs'), import('../client-build.mjs'),
    import('../build_landing_strings.mjs'), import('../precache.mjs'),
  ]);
  generate();
  const config = clientConfig({root, outDir});
  config.plugins.push(previewBinding(repo, rows));
  await build({configFile:false, ...config});
  await client.copyStatic(root, outDir, {only: name => name !== 'regions'});
  await mkdir(resolve(outDir, 'regions'));
  await cp(resolve(root, 'regions/index.json'), resolve(outDir, 'regions/index.json'));
  for (const id of IDs) await cp(resolve(root, 'regions', id), resolve(outDir, 'regions', id), {recursive:true});
  await client.versionGlyphs(outDir);
  const {buildId} = await client.hashPages(outDir, pages(root));
  await writeFile(resolve(outDir, '.assetsignore'), '.vite\n');
  await writeFile(resolve(outDir, '_headers'), client.IMMUTABLE_ASSETS + client.IMMUTABLE_GLYPHS + client.STATIC_DATA + client.SAFETY_FILES);
  await writePrecache(outDir, buildId);
}

export async function openPreview(root, sha) {
  root = await realpath(root);
  const raw = await readFile(resolve(root, 'manifest.json'));
  if (!SHA.test(sha ?? '') || hash(raw) !== sha) throw Error('expected independently pinned preview manifest');
  const manifest = JSON.parse(raw);
  if (manifest.schema !== 'sc-central-isolated-preview/1' || manifest.scope !== 'loopback-only'
      || Object.keys(manifest.regions).sort().join() !== IDs.join()) throw Error('not a local Central preview');
  const files = new Map();
  for (const [key, pin] of Object.entries(manifest.files)) {
    const path = resolve(root, key);
    if (!path.startsWith(root + sep) || path !== await realpath(path)) throw Error(`not a local regular file: ${key}`);
    const raw = await readFile(path);
    if (raw.length !== pin.bytes || hash(raw) !== pin.sha256) throw Error(`asset differs from manifest: ${key}`);
    files.set(key, raw);
  }
  return {manifest, files};
}

async function loopback(manifest, files) {
  const requests = [];
  const regions = new Set(IDs);
  const listener = createServer((req, res) => {
    // No proxy, host override, forwarding, or fallback, including for a host with a local-looking URL.
    if (req.headers.host !== `127.0.0.1:${listener.address().port}` || !['GET', 'HEAD'].includes(req.method)) {
      return res.writeHead(421).end();
    }
    const path = req.url.split('?')[0];
    const key = scopeRoute(path, manifest.build, files, regions);
    let body = files.get(key), status = body ? 200 : 404;
    const headers = {'Content-Type':media[extname(key ?? path)] ?? 'application/octet-stream', 'Cache-Control':'no-store'};
    if (body && key.endsWith('.pmtiles') && req.headers.range) {
      const range = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range);
      const start = Number(range?.[1]), end = Math.min(Number(range?.[2]), body.length - 1);
      if (!range || start > end || end - start >= 16 * 1024 * 1024) return res.writeHead(416).end();
      headers['Content-Range'] = `bytes ${start}-${end}/${body.length}`;
      body = body.subarray(start, end + 1); status = 206;
    }
    if (contourPath.test(path) || terrainPath.test(path) || path === '/sources') {
      requests.push({path, status, sha256:status === 200 ? manifest.files[key].sha256 : null});
    }
    res.writeHead(status, headers).end(req.method === 'GET' ? body : undefined);
  });
  await new Promise((done, fail) => listener.once('error', fail).listen(0, '127.0.0.1', done));
  const origin = `http://127.0.0.1:${listener.address().port}`;
  return {origin, requests, close: () => new Promise(done => {listener.close(done); listener.closeAllConnections();})};
}

async function run(root, sha, output) {
  if (!output) throw Error('usage: central_isolated_preview.mjs check ROOT MANIFEST_SHA RECEIPT');
  const {manifest, files} = await openPreview(root, sha);
  const server = await loopback(manifest, files);
  const {origin, requests} = server;
  const receipt = {schema:'sc-central-local-browser/1', reviewed:false, hosted:false, manifest_sha256:sha, rows:[], problems:[]};
  let browser;
  try {
    const {chromium} = await import('@playwright/test');
    browser = await chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
    const context = await browser.newContext({viewport:PHONE, deviceScaleFactor:1, isMobile:true, hasTouch:true, serviceWorkers:'block'});
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    const page = await context.newPage();
    page.on('pageerror', error => receipt.problems.push(String(error)));
    for (const id of IDs) {
      const terrainOnly = TERRAIN_ONLY.includes(id);
      const config = JSON.parse(files.get(`client/regions/${id}/region.json`));
      const center = (PROFILE[id] ?? config.map).center;
      for (const [band, zoom] of terrainOnly ? [['absent', 13]] : [['overview', 11], ['detail', 13]]) {
        const path = band === 'absent' ? null : `/regions/${id}/depth-contours${band === 'overview' ? '-overview' : ''}.geojson`;
        const mark = requests.length;
        const view = `${center.join(',')},${zoom}`;
        const problems = [];
        const firstRange = page.waitForResponse(response => archiveWitness({path:new URL(response.url()).pathname, status:response.status()}, id),
          {timeout:12000}).then(() => true, () => false);
        await page.goto(`${origin}/map?region=${id}&layout=chart&presentation=chart&profile=boat&diagnostics=1&view=${view}`);
        await page.locator(`.app-location[data-region="${id}"]`).waitFor({timeout:15000});
        const keep = page.getByRole('button', {name:'Keep Boat for now', exact:true});
        if (await keep.isVisible()) await keep.click();
        await page.getByRole('button', {name:'Layers', exact:true}).first().click();
        await page.locator('li.app-legend-relief:visible').waitFor({timeout:15000}).catch(() => problems.push('no depth shading'));
        if (!await firstRange) problems.push('no own relief archive read');
        if (path) await page.locator('[data-contours-drawn]:not([data-contours-drawn="0"])').first().waitFor({state:'attached', timeout:6000}).catch(() => {});
        const seen = await page.evaluate(() => ({
          view:new URL(location.href).searchParams.get('view'),
          drawn:Number(document.querySelector('[data-contours-drawn]')?.dataset.contoursDrawn ?? 0),
          accepted:!!document.querySelector('li.app-legend-depth-contours [data-stamp="depth-contours"]'),
          reason:document.querySelector('li.app-legend-depth-contours [data-reason="depth-contours"]')?.textContent?.trim() ?? null,
        }));
        const reads = requests.slice(mark), docs = path ? [JSON.parse(files.get(`client${path}`))] : [];
        const expected = Object.fromEntries(Object.entries(manifest.regions[id].contours));
        const verdict = classify({...seen, region:id, terrainOnly, reads, expected,
          listed:config.chart_files.filter(name => name.startsWith('depth-contours')),
          inView:visibleLinesInView(docs, center, zoom), othersInView:visibleOthersInView(docs, center, zoom)});
        if (seen.view !== view) problems.push('camera changed');
        if (!reads.some(row => terrainPath.exec(row.path)?.[1] === id && row.status === 206)) problems.push('no own relief archive read');
        if (path && (verdict.result !== 'rendered' || !reads.some(row => row.path === path && row.status === 200 && row.sha256 === expected[path]))) {
          problems.push('requested band did not draw at the fixed camera');
        }
        const row = {id, band, ...seen, reads, classification:verdict.result, problems:[...problems,...verdict.problems]};
        receipt.rows.push(row);
        console.log(`${row.problems.length ? 'HOLD' : 'ok'} ${id} ${band}: ${seen.drawn} ${row.problems.join('; ')}`);
      }
    }
    const history = [];
    async function onRegion(step, id, action, navigation) {
      const mark = requests.length;
      await action();
      await page.waitForURL(url => url.searchParams.get('region') === id, {timeout:15000});
      await page.locator(`.app-location[data-region="${id}"]`).waitFor({timeout:15000});
      const layers = page.getByRole('button', {name:'Layers', exact:true}).first();
      await layers.click();
      await page.locator('li.app-legend-relief:visible').waitFor({timeout:15000});
      if (!TERRAIN_ONLY.includes(id)) {
        await page.locator('li.app-legend-depth-contours [data-stamp="depth-contours"]').waitFor({state:'attached',timeout:10000});
      }
      const seen = await page.evaluate(() => ({credit:!!document.querySelector('[data-stamp="depth-contours"]'),
        drawn:Number(document.querySelector('[data-contours-drawn]')?.dataset.contoursDrawn ?? 0),
        type:performance.getEntriesByType('navigation')[0]?.type}));
      const reads = requests.slice(mark).filter(row => contourPath.test(row.path));
      const terrainOnly = TERRAIN_ONLY.includes(id);
      if ((navigation && seen.type !== navigation) || (terrainOnly && (seen.credit || seen.drawn || reads.length))
        || (!terrainOnly && (!seen.credit || reads.some(row => contourPath.exec(row.path)[1] !== id)))) {
        receipt.problems.push(`${step}: stale or wrong region shown`);
      }
      history.push({step, id, ...seen, reads});
    }
    // The previous step is South Big Sur with Layers open. Use the normal region picker,
    // then the browser's own history in both directions; no app-state injection.
    const before = 'south-big-sur-san-simeon', target = 'monterey-point-sur';
    await page.getByRole('button', {name:'Layers', exact:true}).first().click();
    await onRegion('pick', target, async () => {
      const sheet = page.locator('section.ui-sheet').first();
      for (let i = 0; i < 3 && await sheet.getAttribute('data-detent') !== 'full'; i++) {
        await sheet.locator('button.ui-sheet-handle').click();
        await page.waitForTimeout(500);
      }
      await page.locator('button.app-port').first().click();
      await page.locator('summary', {hasText:'Browse California regions and coverage'}).click();
      await page.locator('section.region-picker select').selectOption(target);
      await page.locator('section.region-picker').getByRole('button', {name:/^Open/}).click();
    });
    await onRegion('back', before, () => page.goBack({timeout:15000}), 'back_forward');
    await onRegion('forward', target, () => page.goForward({timeout:15000}), 'back_forward');
    receipt.history = history;
    const source = await page.goto(`${origin}/sources`);
    const credits = await page.evaluate(ids => Object.fromEntries(ids.map(id => {
      const labels = [];
      for (let el = document.getElementById(`region-${id}`)?.nextElementSibling; el && el.tagName !== 'H4'; el = el.nextElementSibling) {
        if (el.tagName === 'H5') labels.push(el.textContent.trim());
      }
      return [id, {shading:labels.includes('Depth shading'), contours:labels.includes('Depth contours')}];
    })), IDs);
    receipt.sources = {credits, sha256:hash(await source.body())};
    if (receipt.sources.sha256 !== manifest.files[`client/sources.${manifest.build}.html`].sha256 || IDs.some(id => !credits[id].shading || credits[id].contours === TERRAIN_ONLY.includes(id))) {
      receipt.problems.push('wrong served /sources identity or scope');
    }
    for (const path of ['/regions/morro-bay/region.json', '/feeds/tiles/relief/morro-bay/other.pmtiles', '/catalog/relief/cambria-san-simeon.json', '/sw.js']) {
      if ((await context.request.get(origin + path)).status() !== 404) receipt.problems.push(`forbidden route available: ${path}`);
    }
  } catch (error) {receipt.problems.push(String(error));}
  finally {await browser?.close(); await server.close();}
  const pass = receipt.rows.length === 10 && receipt.rows.every(row => row.problems.length === 0) && receipt.problems.length === 0;
  await writeFile(output, JSON.stringify(receipt, null, 2) + '\n', {flag:'wx'});
  console.log(`${pass ? 'PASS' : 'HOLD'} ${receipt.rows.length}/10 Chart observations; ${output}`);
  return pass;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [, , action, ...args] = process.argv;
  if (action === 'build-local' && args.length === 1) await buildLocal(...args);
  else if (action === 'check' && args.length === 3) process.exitCode = await run(...args) ? 0 : 2;
  else if (action === 'verify' && args.length === 2) {
    const {files} = await openPreview(...args);
    console.log(`PASS ${files.size} pinned Central preview files`);
  } else throw Error('expected build-local, check or verify');
}
