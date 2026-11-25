#!/usr/bin/env node
// C42: real browser history on a frozen Central build, with no hosted requests.
import {createHash} from 'node:crypto';
import {readFile, realpath, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {resolve, extname, sep} from 'node:path';
import {pathToFileURL} from 'node:url';

const contour = 'cambria-san-simeon', terrain = 'monterey-point-sur';
const pointer = region => `/catalog/relief/${region}.json`;
const contourPath = /^\/regions\/([^/]+)\/depth-contours(?:-overview)?\.geojson$/;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const mime = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css', '.json':'application/json','.geojson':'application/json','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};

export function clientAsset(path, build) {
  if (!/^[0-9a-f]{10}$/.test(build)) throw Error('invalid fingerprint');
  if (path === '/map') return `client/app.${build}.html`;
  if (path === '/sources') return `client/sources.${build}.html`;
  return /^\/(?:[A-Za-z0-9_.-]+\/)*[A-Za-z0-9_.-]+$/.test(path) && !path.split('/').some(s => s === '.' || s === '..') ? `client${path}` : null;
}

export function problems(expected, seen) {
  const out = [];
  if (seen.urlRegion !== expected || seen.shownRegion !== expected) out.push('wrong region in URL or Chart');
  if (!seen.shading) out.push('relief shading not shown');
  const isContour = expected === contour;
  if (seen.contourRows !== (isContour ? 1 : 0) || (isContour ? !seen.diagnostic || seen.drawn <= 0 : seen.drawn !== 0 || seen.contourCredit)) out.push(isContour ? 'expected contour absent from Chart' : 'stale contour on terrain-only Chart');
  if (isContour && !seen.requests.some(x => contourPath.exec(x.path)?.[1] === expected && x.status === 200)) out.push('no own-region contour read');
  const own = seen.requests.filter(x => x.path === pointer(expected) && x.status === 200);
  if (!own.length) out.push('no fresh own-region pointer read');
  if (seen.requests.some(x => (x.path.startsWith('/catalog/relief/') && x.path !== pointer(expected)) || (contourPath.test(x.path) && (expected !== contour || contourPath.exec(x.path)[1] !== expected)))) out.push('unexpected region resource requested');
  return out;
}

async function run(root, bundlePath, basemapPath, basemapSha, output) {
  if (!output || !/^[0-9a-f]{64}$/.test(basemapSha)) throw Error('usage: central_built_navigation.mjs C35_OUT C27_BUNDLE BASEMAP BASEMAP_SHA RECEIPT');
  root = await realpath(root);
  const manifestBytes = await readFile(resolve(root, 'manifest.json'));
  const bundleBytes = await readFile(bundlePath);
  const m = JSON.parse(manifestBytes), bundle = JSON.parse(bundleBytes);
  if (m.schema !== 'sc-central-stage-tree/1' || m.sources_shell !== clientAsset('/sources', m.build)) throw Error('wrong fixture schema or shell identity');
  const assets = async key => {
    const file = resolve(root, key);
    if (!file.startsWith(root + sep) || file !== await realpath(file)) throw Error(`unexpected client file: ${key}`);
    const body = await readFile(file);
    if (body.length !== m.files[key].bytes || hash(body) !== m.files[key].sha256) throw Error(`changed client bytes: ${key}`);
    return body;
  };
  const feeds = new Map();
  for (const id of [terrain, contour]) {
    const row = bundle.regions[id];
    if (row?.region !== id || m.files[m.served[pointer(id)]]?.sha256 !== row.served[pointer(id)]?.sha256) throw Error(`C35/C27 pointer mismatch: ${id}`);
    for (const [path, pin] of Object.entries(row.served)) {
      if (!path.startsWith(`/feeds/tiles/relief/${id}/`) || !['relief archive','digest tree'].includes(pin.role)) continue;
      const body = await readFile(pin.file);
      if (hash(body) !== pin.sha256) throw Error(`changed feed bytes: ${path}`);
      feeds.set(path, body);
    }
    if (!feeds.get(`/feeds/tiles/relief/${id}/${row.archive_sha256}.pmtiles`)) throw Error(`missing feed archive: ${id}`);
  }
  const base = await readFile(basemapPath);
  if (hash(base) !== basemapSha) throw Error('changed basemap');
  feeds.set('/feeds/tiles/basemap/c42.pmtiles', base);
  feeds.set('/feeds/tiles/basemap/manifest.json', Buffer.from(JSON.stringify({key:'tiles/basemap/c42.pmtiles'})));

  const requests = [], serverErrors = [];
  const server = createServer(async (req, res) => {
    const path = new URL(req.url, 'http://127.0.0.1').pathname;
    try {
      const file = clientAsset(path, m.build);
      let body = feeds.get(path) ?? (file && Object.hasOwn(m.files, file) ? await assets(file) : null);
      const headers = {'Content-Type': mime[extname(file ?? path)] ?? 'application/octet-stream', 'Cache-Control':'no-store'};
      let status = body ? 200 : 404;
      if (body && req.headers.range && path.endsWith('.pmtiles')) {
        const match = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range);
        const start = Number(match?.[1]), end = Math.min(Number(match?.[2]), body.length - 1);
        if (!match || start > end || end - start >= 16 * 1024 * 1024) { res.writeHead(416).end(); return; }
        headers['Content-Range'] = `bytes ${start}-${end}/${body.length}`;
        body = body.subarray(start, end + 1); status = 206;
      }
      if (path === '/map' || path === '/sources' || path.startsWith('/catalog/relief/') || contourPath.test(path) || /\/regions\/[^/]+\/region\.json$/.test(path)) {
        requests.push({path, status, sha256: body ? hash(body) : null});
      }
      res.writeHead(status, headers).end(req.method === 'HEAD' ? undefined : body);
    } catch (error) { serverErrors.push(String(error)); res.writeHead(500).end(); }
  });
  await new Promise((ok, fail) => server.once('error', fail).listen(0, '127.0.0.1', ok));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const steps = [], errors = [];
  const evidence = {scope:'C42 local; unmodified build shell; Worker route subset; no SW, hosted QA or approval', build:m.build, manifestSha:hash(manifestBytes), bundleSha:hash(bundleBytes), basemapSha, steps, errors, serverErrors};
  let browser;
  try {
    const {chromium} = await import('@playwright/test');
    browser = await chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
    const ctx = await browser.newContext({viewport:{width:390,height:844}, deviceScaleFactor:1, isMobile:true, hasTouch:true, serviceWorkers:'block'});
    await ctx.route('**/*', r => new URL(r.request().url()).origin === origin ? r.continue() : r.abort());
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    async function observe(name, region, action) {
      const mark = requests.length;
      await action();
      await page.waitForURL(u => u.searchParams.get('region') === region, {timeout:15000});
      await page.locator(`.app-location[data-region="${region}"]`).waitFor({timeout:15000});
      const keep = page.getByRole('button',{name:'Keep Boat for now',exact:true});
      if (await keep.isVisible()) await keep.click();
      const layers = page.getByRole('button',{name:'Layers',exact:true}).first();
      await layers.click();
      await page.locator('li.app-legend-relief:visible').waitFor({timeout:22000}).catch(() => {});
      const listedContours = JSON.parse((await assets(`client/regions/${region}/region.json`)).toString()).chart_files.filter(file => file.startsWith('depth-contours'));
      if (listedContours.length) await page.locator('[data-contours-drawn]:not([data-contours-drawn="0"])').waitFor({state:'attached',timeout:5000}).catch(() => {});
      const seen = await page.evaluate(() => ({
        urlRegion:new URL(location.href).searchParams.get('region'),
        diagnostic:!!document.querySelector('[data-contours-drawn]'),
        shownRegion:document.querySelector('.app-location')?.dataset.region,
        shading:!!document.querySelector('li.app-legend-relief')?.getClientRects().length,
        drawn:Math.max(0,...Array.from(document.querySelectorAll('[data-contours-drawn]'), el => Number(el.dataset.contoursDrawn) || 0)),
        contourRows:Array.from(document.querySelectorAll('.app-legend-depth-contours')).filter(el => el.getClientRects().length).length,
        contourCredit:document.querySelector('[data-stamp="depth-contours"]')?.textContent ?? null,
        navigation:performance.getEntriesByType('navigation')[0]?.type,
        href:location.pathname + location.search,
      }));
      await layers.click();
      seen.requests = requests.slice(mark);
      const failures = problems(region, seen);
      if (['back','forward'].includes(name) && seen.navigation !== 'back_forward') failures.push('not a browser history restoration');
      steps.push({name, region, listedContours, ...seen, problems:failures});
    }
    await observe('open', terrain, () => page.goto(`${origin}/map?region=${terrain}&presentation=chart&diagnostics=1`));
    await observe('pick', contour, async () => {
      const sheet = page.locator('section.ui-sheet').first();
      for (let i = 0; i < 3 && await sheet.getAttribute('data-detent') !== 'full'; i++) {
        await sheet.locator('button.ui-sheet-handle').click();
        await page.waitForTimeout(500);
      }
      await page.locator('button.app-port').first().click();
      await page.locator('summary',{hasText:'Browse California regions and coverage'}).click();
      await page.locator('section.region-picker select').selectOption(contour);
      await page.locator('section.region-picker').getByRole('button',{name:/^Open/}).click();
    });
    await observe('back', terrain, () => page.goBack({timeout:15000}));
    await observe('forward', contour, () => page.goForward({timeout:15000}));
    const sources = await ctx.newPage();
    const response = await sources.goto(`${origin}/sources`);
    const credits = await sources.evaluate(ids => Object.fromEntries(ids.map(id => {
      const heading = document.getElementById(`region-${id}`);
      const labels = [];
      for (let el = heading?.nextElementSibling; el && el.tagName !== 'H4'; el = el.nextElementSibling) {
        if (el.tagName === 'H5') labels.push(el.textContent.trim());
      }
      return [id,{shading:labels.includes('Depth shading'),contours:labels.includes('Depth contours')}];
    })), [terrain, contour]);
    evidence.sources = {sha256:hash(await response.body()), credits};
    if (evidence.sources.sha256 !== m.files[m.sources_shell].sha256 || !credits[terrain].shading || credits[terrain].contours || !credits[contour].shading || !credits[contour].contours) errors.push('wrong served /sources identity or credits');
    // Direct asset control, after the timed walk so it cannot be mistaken for an app fetch.
    evidence.contourRoutes = [];
    for (const id of [terrain, contour]) {
      for (const name of ['depth-contours-overview.geojson','depth-contours.geojson']) {
        const path = `/regions/${id}/${name}`, pin = m.files[clientAsset(path, m.build)];
        const read = await ctx.request.get(origin + path, {maxRedirects:0});
        const status = read.status(), sha256 = read.ok() ? hash(await read.body()) : null;
        evidence.contourRoutes.push({path,status,sha256});
        if (id === contour ? status !== 200 || sha256 !== pin?.sha256 : status !== 404 || pin) errors.push(`wrong contour asset scope: ${path}`);
      }
    }
  } catch (error) { errors.push(String(error)); }
  finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise(ok => server.close(ok));
    await writeFile(output, JSON.stringify(evidence,null,2)+'\n',{flag:'wx'});
  }
  const pass = steps.length === 4 && !steps.some(step => step.problems.length) && !errors.length && !serverErrors.length;
  console.log(`${pass ? 'PASS' : 'HOLD'} ${m.build} ${steps.length}/4 browser observations; ${output}`);
  return pass;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await run(...process.argv.slice(2)) ? 0 : 2;
}
