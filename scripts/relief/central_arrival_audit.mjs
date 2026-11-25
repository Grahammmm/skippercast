#!/usr/bin/env node
// C44: six-region arrival audit on a frozen Central build (local loopback; no hosted requests, no camera or data changes).
//
// Opens each Central region once in a phone-size browser at a FIXED camera (by default the C41 preview profile for a contour
// region and the region's own map camera for a terrain-only one; `region` uses every region's own map camera, i.e. where the
// picker lands) and sorts what the Chart actually did into one class:
//   rendered          the region's own contour pair was read (manifest bytes) and ACCEPTED (the legend shows the drawn
//                     contour credit stamp), the Chart's hit count is > 0, a contour line visible at that zoom crosses the
//                     viewport and no survey edge or unresolved outline does (the hit count includes those, so it is
//                     only attributed to contours when nothing else is in view);
//   out-of-view       the pair was read and accepted and no contour line visible at that zoom crosses the viewport (any
//                     hits are explained by an edge or unresolved outline in view);
//   terrain-only      a terrain-only region: no contour file listed, read, accepted or drawn;
// and HOLD classes:
//   never-requested   a contour region whose pair the Chart never read (C35: chart_files omitted it);
//   not-accepted      the pair was read but the Chart withheld or failed it (no credit stamp; its reason is kept);
//   unexplained-zero  accepted, visible contour lines cross the viewport, but the Chart drew no hit;
//   unattributed-draw accepted, hits drawn, but edges/outlines are also in view, so the count cannot prove a contour;
//   unexplained-draw  accepted, hits drawn, but nothing visible crosses the viewport;
//   terrain-leak      a terrain-only region that lists, reads, accepts or draws contours.
// A foreign region's contour read or bytes that differ from the build manifest are problems in any class.
import {createHash} from 'node:crypto';
import {readFile, realpath, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {extname, resolve, sep} from 'node:path';
import {pathToFileURL} from 'node:url';
import {clientAsset} from './central_built_navigation.mjs';
import {PHONE, PROFILE, TERRAIN_ONLY, linesInView} from './central_preview_cameras.mjs';

export const REGIONS = Object.freeze([...Object.keys(PROFILE), ...TERRAIN_ONLY]);
export const PAIR = Object.freeze(['depth-contours-overview.geojson', 'depth-contours.geojson']);
export const OK = Object.freeze(['rendered', 'out-of-view', 'terrain-only']);
export const HOLD = Object.freeze(['never-requested', 'not-accepted', 'unexplained-zero', 'unattributed-draw', 'unexplained-draw', 'terrain-leak']);
// The Chart's `?view=` zoom is the map library's zoom plus this (web/map/engine.ts ZOOM_OFFSET).
export const ZOOM_OFFSET = 1;
const contourPath = /^\/regions\/([^/]+)\/(depth-contours(?:-overview)?\.geojson)$/;
const pointer = region => `/catalog/relief/${region}.json`;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const mime = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.geojson': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2'};

// The Chart's own tier rule (web/map/depth-contours.ts visibleAt): a line without zoom bounds is always eligible.
export const visibleAt = (p, viewZoom) =>
  (p?.minzoom === undefined || viewZoom >= p.minzoom) && (p?.maxzoom === undefined || viewZoom < p.maxzoom);

// Lines of the given kinds eligible at the `?view=` zoom that cross the phone viewport at the camera. Polygon outlines
// count as lines: the Chart's hit layer is a line layer over every feature.
const outlines = f => {
  const g = f.geometry || {};
  if (g.type === 'Polygon') return {...f, geometry: {type: 'MultiLineString', coordinates: g.coordinates}};
  if (g.type === 'MultiPolygon') return {...f, geometry: {type: 'MultiLineString', coordinates: g.coordinates.flat()}};
  return f;
};
function kindInView(docs, center, viewZoom, size, wantContour) {
  return docs.reduce((n, doc) => n + linesInView({features: (doc.features || []).filter(f =>
    ((f.properties?.kind ?? 'contour') === 'contour') === wantContour && visibleAt(f.properties, viewZoom)).map(outlines)},
  center, viewZoom - ZOOM_OFFSET, size), 0);
}
// Contour lines (kind contour, or no kind).
export const visibleLinesInView = (docs, center, viewZoom, size = PHONE) => kindInView(docs, center, viewZoom, size, true);
// Survey edges and unresolved-area outlines: also click targets, so also in the Chart's hit count.
export const visibleOthersInView = (docs, center, viewZoom, size = PHONE) => kindInView(docs, center, viewZoom, size, false);

// obs: {region, terrainOnly, listed:[file names in chart_files], reads:[{path,status,sha256}], expected:{path: sha256},
//       accepted: the legend shows the drawn-contour credit stamp, reason: the legend's withheld/failed note if any,
//       drawn: number from data-contours-drawn (undefined when the diagnostic never appeared), inView / othersInView:
//       visibleLinesInView / visibleOthersInView of the files the Chart read (null when it read none)}.
export function classify(obs) {
  const problems = [];
  const reads = obs.reads.filter(r => contourPath.test(r.path));
  const own = reads.filter(r => contourPath.exec(r.path)[1] === obs.region);
  if (reads.length > own.length) problems.push('foreign region contour resource requested');
  for (const r of own) {
    if (r.status === 200 && r.sha256 !== obs.expected[r.path]) problems.push(`contour bytes differ from the build manifest: ${r.path}`);
  }
  const fetched = own.filter(r => r.status === 200);
  const drawn = Number.isFinite(obs.drawn) ? obs.drawn : 0;
  let result;
  if (obs.terrainOnly) {
    result = obs.listed.length || own.length || drawn > 0 || obs.accepted ? 'terrain-leak' : 'terrain-only';
    if (result === 'terrain-leak') problems.push('terrain-only region lists, reads, accepts or draws contours');
  } else if (!fetched.length) {
    result = 'never-requested';
    problems.push(obs.listed.length ? 'contour pair listed but never read' : 'contour pair missing from region chart_files');
  } else if (!obs.accepted) {
    // A withheld, expired or invalid pair is not "valid but out of view", whatever its geometry.
    result = 'not-accepted';
    problems.push(`the Chart read the pair but did not accept it${obs.reason ? `: ${obs.reason}` : ''}`);
  } else if (!Number.isFinite(obs.drawn)) {
    result = 'unexplained-zero';
    problems.push('contour diagnostic never reported a draw count');
  } else if (obs.inView > 0 && drawn === 0) {
    result = 'unexplained-zero';
    problems.push(`${obs.inView} visible contour line(s) cross the viewport but none was drawn`);
  } else if (obs.inView > 0 && obs.othersInView > 0) {
    // The hit count includes survey edges and unresolved outlines; with those in view it cannot prove a contour.
    result = 'unattributed-draw';
    problems.push(`${obs.othersInView} survey edge/unresolved outline(s) are also in view; the hit count cannot prove a contour line`);
  } else if (obs.inView > 0) {
    result = 'rendered';
  } else if (drawn === 0 || obs.othersInView > 0) {
    result = 'out-of-view';
  } else {
    result = 'unexplained-draw';
    problems.push(`${drawn} hit(s) drawn but no visible line crosses the viewport`);
  }
  return {result, ok: OK.includes(result) && !problems.length, problems};
}

async function run(root, bundlePath, basemapPath, basemapSha, output, cameras = 'profile') {
  if (!output || !/^[0-9a-f]{64}$/.test(basemapSha ?? '') || !['profile', 'region'].includes(cameras)) {
    throw Error('usage: central_arrival_audit.mjs BUILD_OUT SIX_REGION_BUNDLE BASEMAP BASEMAP_SHA RECEIPT [profile|region]');
  }
  root = await realpath(root);
  const manifestBytes = await readFile(resolve(root, 'manifest.json'));
  const bundleBytes = await readFile(bundlePath);
  const m = JSON.parse(manifestBytes), bundle = JSON.parse(bundleBytes);
  if (m.schema !== 'sc-central-stage-tree/1' || m.sources_shell !== clientAsset('/sources', m.build)) throw Error('wrong build schema or shell identity');
  if ([...Object.keys(bundle.regions ?? {})].sort().join() !== [...REGIONS].sort().join()) throw Error('bundle is not the six Central regions');
  const asset = async key => {
    const file = resolve(root, key);
    if (!file.startsWith(root + sep) || file !== await realpath(file)) throw Error(`unexpected client file: ${key}`);
    const body = await readFile(file);
    if (body.length !== m.files[key].bytes || hash(body) !== m.files[key].sha256) throw Error(`changed client bytes: ${key}`);
    return body;
  };
  const base = await readFile(basemapPath);
  if (hash(base) !== basemapSha) throw Error('changed basemap');
  const feeds = new Map([['/feeds/tiles/basemap/c44.pmtiles', base],
    ['/feeds/tiles/basemap/manifest.json', Buffer.from(JSON.stringify({key: 'tiles/basemap/c44.pmtiles'}))]]);
  const plan = [];
  for (const id of REGIONS) {
    const row = bundle.regions[id];
    if (row?.region !== id || m.files[m.served[pointer(id)]]?.sha256 !== row.served[pointer(id)]?.sha256) throw Error(`build/bundle pointer mismatch: ${id}`);
    for (const [path, pin] of Object.entries(row.served)) {
      if (!path.startsWith(`/feeds/tiles/relief/${id}/`) || !['relief archive', 'digest tree'].includes(pin.role)) continue;
      const body = await readFile(pin.file);
      if (hash(body) !== pin.sha256) throw Error(`changed feed bytes: ${path}`);
      feeds.set(path, body);
    }
    const config = JSON.parse(await asset(`client/regions/${id}/region.json`));
    const terrainOnly = TERRAIN_ONLY.includes(id);
    const camera = terrainOnly || cameras === 'region' ? config.map : PROFILE[id];
    const expected = {}, docs = {};
    for (const name of PAIR) {
      const path = `/regions/${id}/${name}`, key = clientAsset(path, m.build);
      if (!Object.hasOwn(m.files, key)) continue;
      expected[path] = m.files[key].sha256;
      docs[path] = JSON.parse(await asset(key));
    }
    plan.push({id, terrainOnly, camera: {center: camera.center, zoom: camera.zoom}, listed: PAIR.filter(n => (config.chart_files ?? []).includes(n)), expected, docs});
  }

  let requests = [];
  const serverErrors = [];
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    try {
      const file = clientAsset(path, m.build);
      let body = feeds.get(path) ?? (file && Object.hasOwn(m.files, file) ? await asset(file) : null);
      const headers = {'Content-Type': mime[extname(file ?? path)] ?? 'application/octet-stream', 'Cache-Control': 'no-store'};
      let status = body ? 200 : 404;
      if (body && req.headers.range && path.endsWith('.pmtiles')) {
        const match = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range);
        const start = Number(match?.[1]), end = Math.min(Number(match?.[2]), body.length - 1);
        if (!match || start > end || end - start >= 16 * 1024 * 1024) { res.writeHead(416).end(); return; }
        headers['Content-Range'] = `bytes ${start}-${end}/${body.length}`;
        body = body.subarray(start, end + 1); status = 206;
      }
      if (path.startsWith('/catalog/relief/') || contourPath.test(path)) requests.push({path, status, sha256: body ? hash(body) : null});
      res.writeHead(status, headers).end(req.method === 'HEAD' ? undefined : body);
    } catch (error) { serverErrors.push(String(error)); res.writeHead(500).end(); }
  });
  await new Promise((ok, fail) => server.once('error', fail).listen(0, '127.0.0.1', ok));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const rows = [], errors = [];
  const evidence = {scope: 'C44 local arrival audit; unmodified build; fixed cameras; no SW, hosting, visual or R8 verdict',
    build: m.build, cameras, manifestSha: hash(manifestBytes), bundleSha: hash(bundleBytes), basemapSha, rows, errors, serverErrors};
  let browser;
  try {
    const {chromium} = await import('@playwright/test');
    browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
    for (const p of plan) {
      const view = [...p.camera.center, p.camera.zoom].join(',');
      const ctx = await browser.newContext({viewport: PHONE, deviceScaleFactor: 1, isMobile: true, hasTouch: true, serviceWorkers: 'block'});
      await ctx.route('**/*', r => new URL(r.request().url()).origin === origin ? r.continue() : r.abort());
      const page = await ctx.newPage();
      const pageErrors = [];
      page.on('pageerror', e => pageErrors.push(e.message));
      requests = [];
      const row = {region: p.id, terrainOnly: p.terrainOnly, view, listed: p.listed};
      try {
        await page.goto(`${origin}/map?region=${p.id}&layout=chart&presentation=chart&diagnostics=1&profile=boat&view=${view}`, {timeout: 20000});
        await page.locator(`.app-location[data-region="${p.id}"]`).waitFor({timeout: 15000});
        const keep = page.getByRole('button', {name: 'Keep Boat for now', exact: true});
        if (await keep.isVisible()) await keep.click();
        await page.getByRole('button', {name: 'Layers', exact: true}).first().click();
        await page.locator('li.app-legend-relief:visible').waitFor({timeout: 22000}).catch(() => {});
        if (p.listed.length) {
          // The legend row appears once the Chart has judged the pair: a credit stamp when drawn, a reason when not.
          await page.locator('li.app-legend-depth-contours').first().waitFor({state: 'attached', timeout: 10000}).catch(() => {});
          await page.locator('[data-contours-drawn]').first().waitFor({state: 'attached', timeout: 10000}).catch(() => {});
          await page.locator('[data-contours-drawn]:not([data-contours-drawn="0"])').first().waitFor({state: 'attached', timeout: 6000}).catch(() => {});
        }
        const seen = await page.evaluate(() => {
          const marks = Array.from(document.querySelectorAll('[data-contours-drawn]'), el => Number(el.dataset.contoursDrawn) || 0);
          return {appliedView: new URL(location.href).searchParams.get('view'), drawn: marks.length ? Math.max(0, ...marks) : null,
            shading: !!document.querySelector('li.app-legend-relief')?.getClientRects().length,
            contourRows: Array.from(document.querySelectorAll('.app-legend-depth-contours')).filter(el => el.getClientRects().length).length,
            accepted: !!document.querySelector('li.app-legend-depth-contours [data-stamp="depth-contours"]'),
            reason: document.querySelector('li.app-legend-depth-contours [data-reason="depth-contours"]')?.textContent?.trim() || null};
        });
        Object.assign(row, seen);
      } catch (error) { pageErrors.push(String(error)); }
      finally { await ctx.close(); }
      row.reads = requests.slice();
      const read = new Set(row.reads.filter(r => r.status === 200).map(r => r.path));
      const fetchedDocs = Object.entries(p.docs).filter(([path]) => read.has(path)).map(([, doc]) => doc);
      row.inView = fetchedDocs.length ? visibleLinesInView(fetchedDocs, p.camera.center, p.camera.zoom) : null;
      row.othersInView = fetchedDocs.length ? visibleOthersInView(fetchedDocs, p.camera.center, p.camera.zoom) : null;
      row.pairInView = visibleLinesInView(Object.values(p.docs), p.camera.center, p.camera.zoom);
      const verdict = classify({region: p.id, terrainOnly: p.terrainOnly, listed: p.listed, reads: row.reads, expected: p.expected,
        accepted: row.accepted === true, reason: row.reason ?? null, drawn: row.drawn ?? undefined, inView: row.inView,
        othersInView: row.othersInView});
      if (row.appliedView !== view) verdict.problems.push('camera query changed');
      if (!row.reads.some(r => r.path === pointer(p.id) && r.status === 200)) verdict.problems.push('no own-region relief pointer read');
      if (pageErrors.length) verdict.problems.push(...pageErrors.map(e => `page: ${e}`));
      Object.assign(row, verdict, {ok: verdict.ok && !verdict.problems.length});
      rows.push(row);
      console.log(`${row.ok ? 'ok  ' : 'HOLD'} ${p.id} ${view} ${row.result} accepted=${row.accepted} drawn=${row.drawn} inView=${row.inView} othersInView=${row.othersInView} pairInView=${row.pairInView} ${row.problems.join('; ')}`);
    }
  } catch (error) { errors.push(String(error)); }
  finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise(ok => server.close(ok));
    await writeFile(output, JSON.stringify(evidence, null, 2) + '\n', {flag: 'wx'});
  }
  const pass = rows.length === REGIONS.length && rows.every(r => r.ok) && !errors.length && !serverErrors.length;
  const counts = Object.entries(rows.reduce((c, r) => ({...c, [r.result]: (c[r.result] ?? 0) + 1}), {})).map(([k, v]) => `${k} ${v}`).join(', ');
  console.log(`${pass ? 'PASS' : 'HOLD'} ${m.build} ${rows.length}/${REGIONS.length} regions (${counts}); ${output}`);
  return pass;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await run(...process.argv.slice(2)) ? 0 : 2;
}
