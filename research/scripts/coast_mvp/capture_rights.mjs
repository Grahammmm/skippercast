// Real-browser proof that C5 rights survive the C3 adapter (see README-viewer.md).
// Requires the local preview server from README-viewer.md; blocks every non-local request.
import {chromium} from '@playwright/test';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const origin = 'http://localhost:5179';
const out = process.env.C3_SCREENSHOTS;
if (!out) throw Error('Set C3_SCREENSHOTS to a task-owned output directory');
await mkdir(out, {recursive: true});
const inventory = JSON.parse(await readFile(new URL('fixtures/rights-adapter/inventory.json', import.meta.url), 'utf8'));
const used = inventory.sources.filter(s => s.contributed_cells > 0);
const unused = inventory.sources.filter(s => s.contributed_cells === 0).map(s => s.source_id);
const browser = await chromium.launch({headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
try {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.route('**/*', route => route.request().url().startsWith(origin) ? route.continue() : route.abort());
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => { if (/\.(png|mvt|json|html)$/.test(new URL(r.url()).pathname)) requests.push({url: r.url().slice(origin.length), status: r.status()}); });
  await page.goto(origin + '/research/scripts/coast_mvp/viewer-preview.html?manifest=rights-adapted');
  await page.waitForSelector('body[data-ready="true"]', {timeout: 60000}).catch(async error => {
    console.error({status: await page.locator('#status').innerText(), errors, requests}); throw error;
  });
  assert.equal(await page.locator('body').getAttribute('data-failed'), null);
  const chrome = page.locator('.coast-mvp-chrome');
  const banner = chrome.locator('strong[role="note"]');
  const bannerText = await banner.innerText();
  assert.match(bannerText, /Not for navigation/); assert.match(bannerText, /SYNTHETIC FIXTURE/);
  assert.match(bannerText, /Rights review required/); assert.match(bannerText, /For-profit permission unresolved \(needs_permission\)/);
  const rows = {};
  for (const s of used) {
    const row = chrome.locator(`p.coast-mvp-source[data-source-id="${s.source_id}"]`);
    assert.equal(await row.count(), 1, s.source_id);
    const t = await row.innerText();
    // Verbatim survival of every rights field the adapter must keep.
    for (const field of [s.name, s.rights.attribution, s.rights.license, s.sha256, String(s.contributed_cells)]) assert.ok(t.includes(field), `${s.source_id}: ${field}`);
    const hrefs = await row.locator('a').evaluateAll(as => as.map(a => a.href));
    assert.ok(hrefs.includes(s.source_url) && hrefs.includes(s.rights.terms_url), s.source_id + ' links');
    rows[s.source_id] = {status: await row.getAttribute('data-rights-status'), text: t, links: hrefs};
  }
  assert.equal(rows['c3fx-csumb-usgs-release'].status, 'needs_permission');
  assert.match(rows['c3fx-csumb-usgs-release'].text, /for-profit permission unresolved; publication held/);
  assert.equal(rows['c3fx-gebco-grid'].status, 'review_required'); assert.equal(rows['c3fx-noaa-cc0'].status, 'review_required');
  // Text nodes, not HTML: the angle-bracket credit renders literally and creates no element.
  assert.equal(await chrome.locator('credit').count(), 0);
  const chromeText = await chrome.innerText();
  for (const id of unused) assert.ok(!chromeText.includes(id), 'unused source shown: ' + id);
  const caveats = await chrome.locator('p.coast-mvp-caveat').allInnerTexts();
  for (const re of [/^needs_permission: CSUMB Seafloor Mapping Lab/, /^GEBCO:/, /endorsement by any source, GEBCO, the IHO or the IOC/, /^Not for navigation/, /^Rights status: review_required/]) {
    assert.ok(caveats.some(c => re.test(c)), 'caveat ' + re);
  }
  const rightsLink = chrome.locator('a.coast-mvp-rights-page');
  const rightsHref = await rightsLink.getAttribute('href');
  assert.equal(rightsHref, origin + '/research/scripts/coast_mvp/fixtures/viewer-demo/rights.html');
  const views = [{name: 'rights-panel', pitch: 45, bearing: -25, zoom: 15.5}];
  for (const v of views) {
    await page.evaluate(v => new Promise(resolve => { const m = window.preview.map; m.once('idle', () => resolve()); m.jumpTo(v); }), v);
    v.contourFeatures = await page.evaluate(() => window.preview.map.querySourceFeatures('mvp-contours', {sourceLayer: 'contours'}).length);
    assert.ok(v.contourFeatures > 0, 'adapted manifest still drives real contour MVT');
    await page.screenshot({path: out + '/rights-panel.png'});
  }
  // Collapsing the panel must not hide the unresolved-permission warning.
  await chrome.locator('summary').click();
  assert.equal(await chrome.locator('details').evaluate(d => d.open), false);
  assert.ok(await banner.isVisible()); assert.match(await banner.innerText(), /needs_permission/);
  await page.screenshot({path: out + '/rights-collapsed.png'});
  // Follow the link: the complete C5 page resolves locally and pins the same inventory bytes.
  const popupPromise = page.waitForEvent('popup');
  await chrome.locator('summary').click();
  await rightsLink.click();
  const rightsPage = await popupPromise;
  await rightsPage.waitForLoadState();
  const pageText = await rightsPage.locator('body').innerText();
  const manifest = await page.evaluate(() => fetch('./fixtures/viewer-demo/rights-adapted.json').then(r => r.json()));
  assert.ok(pageText.includes(manifest.rightsInventory.sha256), 'rights page pins the same inventory');
  assert.match(pageText, /needs_permission/); assert.match(pageText, /SYNTHETIC FIXTURE ONLY/);
  for (const s of used) assert.ok(pageText.includes(s.rights.attribution) && pageText.includes(s.sha256), 'rights page ' + s.source_id);
  await rightsPage.screenshot({path: out + '/rights-page.png', fullPage: true});
  assert.equal(errors.length, 0, errors.join('\n'));
  assert.ok(requests.some(r => r.url.endsWith('.png')) && requests.some(r => r.url.endsWith('.mvt')));
  assert.ok(requests.every(r => r.status === 200), JSON.stringify(requests));
  const receipt = {manifest: 'rights-adapted.json', inventorySha256: manifest.rightsInventory.sha256, banner: bannerText,
    rows: Object.fromEntries(Object.entries(rows).map(([k, v]) => [k, {status: v.status, links: v.links}])),
    unusedExcluded: unused, caveats, rightsPage: rightsHref.slice(origin.length), views, requests, errors};
  await writeFile(out + '/rights-acceptance.json', JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify(receipt, null, 2));
} finally { await browser.close(); }
