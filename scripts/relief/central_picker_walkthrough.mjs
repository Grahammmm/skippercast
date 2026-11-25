#!/usr/bin/env node
// C31 (PLAN-SKIPPERCAST): walk the six Central Coast regions through the app's OWN region picker (the port sheet's
// "Browse California regions and coverage" -> region list -> Open), not through history injection. LOCAL loopback,
// synthetic pointers (envelope 'a'*64): NOT hosted evidence, NOT an R8 verdict, no change to the shared Chart.
// Usage: central_picker_walkthrough.mjs REPO BASEMAP_PMTILES NEW_OUT_DIR SPEC.json
//   SPEC = six rows {region, release (release.json path), lon, lat, contours (dir with the published pair, or null)}.
// Per theme: open the first region by URL, pick each next region in the picker, then real Back through them. On arrival
// (and after every Back) it records the region the Chart shows, contour availability and the credit line, judges them
// against the spec, and stops forward travel at the FIRST broken navigation, keeping that shot and the reason.
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';

export const CENTRAL_REGIONS = [
  'cambria-san-simeon', 'big-sur-coast', 'south-big-sur-san-simeon', 'monterey-point-sur', 'point-arguello-conception', 'santa-cruz-monterey-bay',
];

/** Canonical contour availability of each Central region (the walkthrough's own claim, not the spec's): the two
 * Monterey-side regions publish terrain shading only; the other four publish a depth-contour pair. */
export const CENTRAL_AVAILABILITY = Object.freeze({
  'cambria-san-simeon': 'contours', 'big-sur-coast': 'contours', 'south-big-sur-san-simeon': 'contours', 'point-arguello-conception': 'contours',
  'monterey-point-sur': 'terrain-only', 'santa-cruz-monterey-bay': 'terrain-only',
});

/** The published contour pair: exactly these two files, nothing else, in a contour region's contours directory. */
export const CONTOUR_PAIR = Object.freeze(['depth-contours-overview.geojson', 'depth-contours.geojson']);

/** Expected contour availability of a spec row, taken from the canonical table; the row's own value cannot change it. */
export const expectedFor = row => {
  const contours = CENTRAL_AVAILABILITY[row?.region];
  if (!contours) throw new Error(`not a Central region: ${row?.region}`);
  return {region: row.region, contours};
};

/** Validate a spec: exactly the six Central regions, each once, in any order, each `contours` matching the canonical
 * availability (a directory string for a contour region, null for a terrain-only one; missing is refused). */
export function checkSpec(spec) {
  if (!Array.isArray(spec) || spec.length !== CENTRAL_REGIONS.length) throw new Error('spec must hold exactly the six Central regions');
  const seen = spec.map(r => r?.region);
  if (new Set(seen).size !== seen.length || !CENTRAL_REGIONS.every(r => seen.includes(r))) throw new Error('spec must name each Central region once');
  for (const r of spec) {
    if (typeof r.release !== 'string' || !Number.isFinite(r.lat) || !Number.isFinite(r.lon)) throw new Error(`incomplete spec row: ${r.region}`);
    if (CENTRAL_AVAILABILITY[r.region] === 'contours') {
      if (typeof r.contours !== 'string' || !r.contours) throw new Error(`${r.region} publishes contours: spec needs its contour directory`);
    } else if (r.contours !== null) throw new Error(`${r.region} is terrain-only: spec contours must be null`);
  }
  return spec;
}

/** Bind a contour directory to the published pair: exactly the two pair files, each a non-empty GeoJSON
 * FeatureCollection. `files` is [{name, bytes}] as read from the directory. Returns Map name -> bytes. */
export function checkContourPair(region, files) {
  const names = files.map(f => f.name).sort();
  if (names.length !== CONTOUR_PAIR.length || !CONTOUR_PAIR.every((n, i) => names[i] === n)) {
    throw new Error(`${region}: contour directory must hold exactly ${CONTOUR_PAIR.join(' and ')}, found ${names.join(', ') || 'nothing'}`);
  }
  for (const f of files) {
    let doc;
    try { doc = JSON.parse(f.bytes); } catch { throw new Error(`${region}: ${f.name} is not JSON`); }
    if (doc?.type !== 'FeatureCollection' || !Array.isArray(doc.features) || !doc.features.length) throw new Error(`${region}: ${f.name} is not a non-empty FeatureCollection`);
  }
  return new Map(files.map(f => [f.name, f.bytes]));
}

/** The walk: open row 0 by URL, pick rows 1..n in the picker, then Back n times landing on rows n-1..0. */
export function planWalk(spec) {
  const rows = checkSpec(spec);
  const steps = [{kind: 'open', region: rows[0].region}];
  for (const row of rows.slice(1)) steps.push({kind: 'pick', region: row.region});
  for (let i = rows.length - 2; i >= 0; i--) steps.push({kind: 'back', region: rows[i].region});
  return steps;
}

/** Judge one arrival against what the spec says that region must show. */
export function judgeArrival(expected, seen) {
  const problems = [], notes = [];
  if (seen.urlRegion !== expected.region) problems.push(`address names ${seen.urlRegion}, not ${expected.region}`);
  if (seen.shownRegion !== expected.region) problems.push(`Chart shows ${seen.shownRegion}, not ${expected.region}`);
  // Request invariants hold whatever is drawn: a contour region asks for its published file, a terrain-only one never does.
  if (expected.contours === 'contours') {
    if (!seen.creditLines.length) problems.push('no contour credit line');
    if (!(seen.contourFilesRequested > 0)) problems.push('published contours not requested');
    if (!(seen.contoursDrawn > 0) && seen.contourFilesRequested > 0 && seen.creditLines.length) {
      // Loaded and credited but outside the arrival camera is a finding about the view, not a missing release.
      notes.push(`published contours loaded and credited but none in view at the arrival camera (${seen.camera ?? 'no camera in address'}${seen.drawnReadable === false ? '; drawn count not readable' : ''})`);
    } else if (!(seen.contoursDrawn > 0)) problems.push('published contours not drawn');
  } else {
    if (seen.contourFilesRequested !== 0) problems.push(`terrain-only region requested ${seen.contourFilesRequested} contour files`);
    if (seen.contoursDrawn > 0) problems.push(`terrain-only region draws ${seen.contoursDrawn} contour features`);
    if (seen.contourRows > 0) problems.push('terrain-only region shows a contour legend row');
    if (seen.creditLines.length) problems.push('terrain-only region shows a contour credit line');
  }
  if (seen.pageErrors?.length) problems.push(`page errors: ${seen.pageErrors.length}`);
  return {ok: problems.length === 0, problems, notes};
}

/** Who picks whom: the picker's own coverage snapshot decides which regions can be opened at all. */
export function pickerReach(snapshotRows, spec) {
  const byId = new Map(snapshotRows.map(([id, name, lifecycle]) => [id, {name, lifecycle}]));
  return checkSpec(spec).map(r => {
    const row = byId.get(r.region);
    return {region: r.region, listed: !!row, name: row?.name ?? null, lifecycle: row?.lifecycle ?? null,
      openable: !!row && (row.lifecycle === 'active' || row.lifecycle === 'preview')};
  });
}

async function main() {
  const [{mkdir, open, readdir, readFile, realpath, writeFile}, {basename, dirname, join, resolve}, {createServer}, {chromium}, {build}] = await Promise.all([
    import('node:fs/promises'), import('node:path'), import('node:http'), import('@playwright/test'), import('esbuild')]);
  const [repo, basemap, output, specPath] = process.argv.slice(2);
  if (!repo || !basemap || !output || !specPath) throw new Error('usage: central_picker_walkthrough.mjs REPO BASEMAP OUT SPEC.json');
  const sha = data => createHash('sha256').update(data).digest('hex');
  const spec = checkSpec(JSON.parse(await readFile(specPath, 'utf8')));
  const coverage = JSON.parse(await readFile(join(repo, 'catalog/app/region-coverage.json'), 'utf8'));
  const reach = pickerReach(coverage.regions, spec);
  const index = 'layers/public/relief.digests/', archive = 'layers/public/tiles/relief.pmtiles';

  const regions = new Map();
  for (const row of spec) {
    const raw = await readFile(row.release), release = JSON.parse(raw), root = resolve(dirname(row.release), '../..');
    const layers = new Map(release.layers.map(r => [r.path, r]));
    if (release.schema !== 'sc-relief-release/1' || release.private !== false || release.region !== row.region ||
        !release.sources?.length || !release.sources.every(s => s.rights_class === 'public' && s.rights?.public_display === 'allowed') ||
        layers.size !== release.layers.length || layers.get(`${index}root.json`)?.sha256 !== release.digest_root_sha256) {
      throw new Error('expected the byte-pinned public relief package for ' + row.region);
    }
    const pinnedPath = async key => { const p = join(root, key); if (!layers.has(key) || await realpath(p) !== p) throw new Error(`unbound release layer: ${key}`); return p; };
    const pinnedBytes = async key => { const b = await readFile(await pinnedPath(key)); if (b.length !== layers.get(key).bytes || sha(b) !== layers.get(key).sha256) throw new Error(`hash mismatch: ${key}`); return b; };
    const archiveRef = layers.get(archive), fd = await open(await pinnedPath(archive), 'r');
    const pointer = {...release, sha256: archiveRef.sha256, bytes: archiveRef.bytes, release_sha256: sha(raw), envelope_sha256: 'a'.repeat(64), status: 'reviewed'};
    const object = `/feeds/tiles/relief/${release.region}/${archiveRef.sha256}`;
    let pair = null;
    if (row.contours) {
      const dir = resolve(row.contours);
      if (await realpath(dir) !== dir) throw new Error(`unbound contour directory: ${row.region}`);
      const entries = await readdir(dir, {withFileTypes: true});
      if (entries.some(e => !e.isFile())) throw new Error(`${row.region}: contour directory holds more than regular files`);
      pair = checkContourPair(row.region, await Promise.all(entries.map(async e => ({name: e.name, bytes: await readFile(join(dir, e.name))}))));
    }
    regions.set(row.region, {...row, pair, pointer, object, digestBase: `${object}.digests/${release.digest_root_sha256}/`, pinnedBytes, fd,
      size: archiveRef.bytes, digestRoot: await pinnedBytes(`${index}root.json`), indexPrefix: index});
  }

  const server = createServer((req, res) => { res.writeHead(406).end(); });
  await new Promise((ok, fail) => server.once('error', fail).listen(0, '127.0.0.1', ok));
  const origin = `http://127.0.0.1:${server.address().port}`;
  server.unref();

  const template = await readFile(join(repo, 'dist/app.html'), 'utf8');
  const html = template.replace(/<link rel="stylesheet" href="\.\.\/web\/[^"]+"\s*\/>/g, '');
  if (html === template || !html.includes('../web/app/boot.ts')) throw new Error('unexpected app.html entry');
  const entry = html.replace('</head>', '<link rel="stylesheet" href="/stdin.css"></head>').replace('../web/app/boot.ts', '/stdin.js');
  const [chart, worker] = await Promise.all([
    build({absWorkingDir: repo, write: false, bundle: true, format: 'esm', outdir: 'qa', loader: {'.woff2': 'file'},
      stdin: {resolveDir: repo, contents: `
        import './web/tokens.css';
        import './web/ui/ui.css';
        import './web/app/app.css';
        import './web/landing/port-input.css';
        import './web/region-picker.css';
        import './web/app/account.css';
        import './web/app/trip.css';
        import './web/app/helm.css';
        import './web/app/boot.ts';
        import {reliefDrawn} from './web/app/MapStage.tsx';
        window.qaDrawn = () => reliefDrawn.value;
      `}, plugins: [{name: 'local-chart-worker', setup(b) {
        b.onResolve({filter: /maplibre-gl-worker\.mjs\?worker&url$/}, () => ({path: 'worker', namespace: 'qa'}));
        b.onLoad({filter: /^worker$/, namespace: 'qa'}, () => ({contents: 'export default "/worker.js";'}));
        // The picker's stylesheet is already bundled above; its ?url import only needs a stable string.
        b.onResolve({filter: /region-picker\.css\?url$/}, () => ({path: 'picker-css', namespace: 'qa'}));
        b.onLoad({filter: /^picker-css$/, namespace: 'qa'}, () => ({contents: 'export default "/region-picker.css";'}));
      }}]}),
    build({absWorkingDir: repo, entryPoints: [join(repo, 'node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs')], write: false, bundle: true, format: 'esm'}),
  ]);
  const assets = new Map(chart.outputFiles.map(f => [`/${basename(f.path)}`, Buffer.from(f.contents)]));
  assets.set('/worker.js', Buffer.from(worker.outputFiles[0].contents));
  const folder = resolve(output);
  await mkdir(folder);
  await mkdir(join(folder, 'shots'));

  async function rangeResponse(r, fd, size) {
    const range = /^bytes=(\d+)-(\d+)$/.exec(r.request().headers().range || '');
    if (!range) throw new Error('archive read without a bounded Range');
    const start = Number(range[1]), end = Math.min(Number(range[2]), size - 1);
    if (start > end || end - start >= 16 * 1024 * 1024) throw new Error('invalid archive Range');
    const body = Buffer.alloc(end - start + 1);
    if ((await fd.read(body, 0, body.length, start)).bytesRead !== body.length) throw new Error('short archive Range');
    return r.fulfill({status: 206, body, headers: {'content-range': `bytes ${start}-${end}/${size}`}});
  }
  const mime = p => p.endsWith('.css') ? 'text/css' : p.endsWith('.js') ? 'text/javascript' : p.endsWith('.svg') ? 'image/svg+xml'
    : p.endsWith('.png') ? 'image/png' : p.endsWith('.woff2') ? 'font/woff2' : p.endsWith('.html') ? 'text/html' : 'application/json';
  const baseFile = await open(basemap, 'r'), baseSize = (await baseFile.stat()).size;
  const requested = {contours: [], pointers: []};

  async function route(ctx, theme, errors) {
    await ctx.route('**/*', async r => {
      const {origin: host, pathname: path} = new URL(r.request().url());
      try {
        if (host !== origin) return await r.abort();
        if (path === '/map') return await r.fulfill({contentType: 'text/html', body: entry.replace('<html lang="en">', `<html lang="en" data-theme="${theme}">`)});
        if (path === '/feeds/tiles/basemap/manifest.json') return await r.fulfill({json: {key: 'tiles/basemap/offline.pmtiles'}});
        if (path === '/feeds/tiles/basemap/offline.pmtiles') return await rangeResponse(r, baseFile, baseSize);
        if (assets.has(path)) return await r.fulfill({body: assets.get(path), contentType: mime(path)});
        for (const [id, g] of regions) {
          if (path === `/catalog/relief/${id}.json`) { requested.pointers.push(id); return await r.fulfill({json: g.pointer}); }
          if (path === `${g.object}.pmtiles`) return await rangeResponse(r, g.fd, g.size);
          if (path === `${g.digestBase}root.json`) return await r.fulfill({body: g.digestRoot});
          if (path.startsWith(g.digestBase)) {
            const chunk = path.slice(g.digestBase.length);
            if (/^\d+\/\d+_\d+\.json$/.test(chunk)) return await r.fulfill({body: await g.pinnedBytes(g.indexPrefix + chunk)});
          }
          if (path === `/regions/${id}/region.json` && g.pair) {
            const doc = JSON.parse(await readFile(join(repo, 'dist', path), 'utf8'));
            doc.chart_files = [...new Set([...(doc.chart_files ?? []), 'depth-contours-overview.geojson', 'depth-contours.geojson'])].sort();
            return await r.fulfill({json: doc});
          }
          const contour = new RegExp('^/regions/' + id + '/(depth-contours(?:-overview)?\\.geojson)$').exec(path);
          if (contour) {
            requested.contours.push(`${id}/${contour[1]}`);
            if (g.pair) return await r.fulfill({body: g.pair.get(contour[1]), contentType: 'application/json'});
            return await r.fulfill({status: 404, body: ''});   // a terrain-only region publishes none
          }
        }
        const glyph = /^(?:\/basemap)?\/glyphs\/v\/[0-9a-f]+\/(dm-sans-medium\/\d+-\d+\.pbf)$/.exec(path);
        if (glyph) return await r.fulfill({body: await readFile(join(repo, 'dist/basemap/glyphs', glyph[1]))});
        if (/^\/[a-z0-9][a-z0-9./_-]*$/i.test(path) && !path.includes('..')) {
          const body = await readFile(join(repo, 'dist', path)).catch(err => { if (err.code !== 'ENOENT' && err.code !== 'EISDIR') throw err; });
          if (body) return await r.fulfill({body, contentType: mime(path)});
        }
        return await r.fulfill({status: 404, body: ''});
      } catch (error) { errors.push(`${path}: ${error.message}`); await r.abort(); }
    });
  }

  // PICKER_OPEN_CAMERA=default opens the first region without a camera, as the picker's own Open button does.
  const url = row => `/map?region=${row.region}${process.env.PICKER_OPEN_CAMERA === 'default' ? '' : `&view=${row.lat},${row.lon},11`}&presentation=chart&diagnostics=1`;
  const byRegion = new Map(spec.map(r => [r.region, r]));

  async function settle(page) {
    const first = page.getByRole('button', {name: 'Keep Boat for now', exact: true});
    if (await first.isVisible().catch(() => false)) await first.click();
    await page.waitForFunction(() => window.qaDrawn?.(), null, {timeout: 25000});
    await page.waitForTimeout(2500);
  }

  async function observe(page, name, errors, expected) {
    const shot = join(folder, `shots/${name}.png`);
    const bytes = await page.screenshot({path: shot, animations: 'disabled'});
    const layersBtn = page.getByRole('button', {name: 'Layers', exact: true}).first();
    await layersBtn.click();
    await page.locator('li.app-legend-relief:visible').waitFor({state: 'visible', timeout: 10000});
    const seen = await page.evaluate(() => ({
      urlRegion: new URL(location.href).searchParams.get('region'),
      drawnReadable: document.querySelector('[data-contours-drawn]') !== null,
      href: location.pathname + location.search,
      camera: new URL(location.href).searchParams.getAll('view').find(v => v.includes(',')) ?? null,
      shownRegion: document.querySelector('.app-location[data-region]')?.dataset.region ?? null,
      shownName: document.querySelector('.app-location')?.textContent?.replace(/\s+/g, ' ').trim() ?? null,
      contoursDrawn: Math.max(0, ...[...document.querySelectorAll('[data-contours-drawn]')].map(e => Number(e.dataset.contoursDrawn) || 0)),
      contourRows: [...document.querySelectorAll('.app-legend-depth-contours')].filter(e => e.offsetParent).length,
      creditLines: [...document.querySelectorAll('.app-legend-note[data-stamp]')].filter(e => e.offsetParent).map(e => e.innerText.replace(/\s+/g, ' ').slice(0, 160)),
    }));
    await layersBtn.click();
    seen.pageErrors = [...errors];
    seen.href = seen.href ?? null;
    seen.contourFilesRequested = requested.contours.slice(mark).filter(f => f.startsWith(expected.region + '/')).length;
    seen.camera = seen.camera ?? null;
    return {name, shot: `shots/${name}.png`, sha256: sha(bytes), expected, seen, verdict: judgeArrival(expected, seen)};
  }

  // The picker, as a person uses it: port button -> browse regions -> choose in the list -> Open.
  async function pickInApp(page, region) {
    // On a phone the port button sits at the foot of the bottom sheet, so a person first pulls the sheet up.
    const sheet = page.locator('section.ui-sheet').first();
    for (let i = 0; i < 3 && await sheet.getAttribute('data-detent') !== 'full'; i++) {
      await sheet.locator('button.ui-sheet-handle').click();
      await page.waitForTimeout(600);
    }
    const port = page.locator('button.app-port').first();
    await port.scrollIntoViewIfNeeded({timeout: 10000});
    await port.click({timeout: 10000});
    const browse = page.locator('summary', {hasText: 'Browse California regions and coverage'});
    await browse.waitFor({state: 'visible', timeout: 10000});
    await browse.click();
    const select = page.locator('section.region-picker select');
    await select.waitFor({state: 'visible', timeout: 10000});
    const options = await select.locator('option').evaluateAll(list => list.map(o => o.value));
    if (!options.includes(region)) return {ok: false, reason: `the picker list does not offer ${region}`, options};
    await select.selectOption(region);
    const open = page.locator('section.region-picker').getByRole('button', {name: /^Open/});
    if (await open.isDisabled()) return {ok: false, reason: `the picker's Open button is disabled for ${region}`, options};
    await Promise.all([page.waitForURL(new RegExp(`region=${region}(&|$)`), {timeout: 20000}), open.click()]);
    return {ok: true, options};
  }

  let mark = 0;
  const results = [];
  const browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist']});
  try {
    for (const theme of ['light', 'dark']) {
      const ctx = await browser.newContext({viewport: {width: 390, height: 844}, deviceScaleFactor: 1, colorScheme: theme, hasTouch: true, isMobile: true, serviceWorkers: 'block'});
      const errors = [], steps = [];
      let broken = null;
      try {
        await route(ctx, theme, errors);
        const page = await ctx.newPage();
        page.on('pageerror', e => errors.push(e.message));
        let n = 0;
        for (const step of planWalk(spec)) {
          if (broken) break;
          n++;
          mark = requested.contours.length;
          const name = `${theme}-${String(n).padStart(2, '0')}-${step.kind}-${step.region}`;
          const expected = expectedFor(byRegion.get(step.region));
          try {
            if (step.kind === 'open') await page.goto(origin + url(byRegion.get(step.region)), {timeout: 30000});
            else if (step.kind === 'pick') {
              const picked = await pickInApp(page, step.region);
              if (!picked.ok) { broken = {step: name, why: picked.reason, options: picked.options}; steps.push({name, kind: step.kind, region: step.region, broken}); await page.screenshot({path: join(folder, `shots/${name}-BROKEN.png`)}); break; }
            } else { await page.goBack({timeout: 20000}); await page.waitForURL(new RegExp(`region=${step.region}(&|$)`), {timeout: 20000}); }
            await settle(page);
            const seen = await observe(page, name, errors, expected);
            steps.push({kind: step.kind, region: step.region, ...seen});
            if (!seen.verdict.ok) broken = {step: name, why: seen.verdict.problems.join('; ')};
          } catch (error) {
            broken = {step: name, why: String(error.message).split('\n')[0]};
            steps.push({name, kind: step.kind, region: step.region, broken});
            await page.screenshot({path: join(folder, `shots/${name}-BROKEN.png`)}).catch(() => {});
          }
        }
      } finally { await ctx.close(); }
      results.push({theme, broken, steps, pageErrors: errors});
    }
  } finally { await browser.close(); }
  await writeFile(join(folder, 'walkthrough.json'), JSON.stringify({
    scope: 'LOCAL loopback walkthrough of the app\'s own region picker (C31); synthetic pointers; not hosted evidence, not a release decision',
    regions: spec.map(r => ({region: r.region, release: r.release, contours: r.contours,
      contourPair: regions.get(r.region).pair && Object.fromEntries([...regions.get(r.region).pair].map(([n, b]) => [n, sha(b)]))})), pickerReach: reach, requested, results}, null, 2) + '\n', {flag: 'wx'});
  for (const r of regions.values()) await r.fd.close();
  await baseFile.close();
  console.log('DONE ' + join(folder, 'walkthrough.json'));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
