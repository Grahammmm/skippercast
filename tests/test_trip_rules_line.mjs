// SC2037-15: mount the actual sheet with a synthetic signed-in API and rule registry.
import assert from 'node:assert/strict';
import {readFile, mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setImmediate} from 'node:timers/promises';
import {pathToFileURL} from 'node:url';
import test, {after} from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const fixture = JSON.parse(await readFile(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const region = {...fixture.region, species: ['reef', 'salmon']};
const NOW = Date.parse('2026-10-12T18:00:00Z'), HOUR = 3600000;
const COPY = 'regions/morro-bay/regulations-startup.json';
const DAILY = '/api/daily?region=morro-bay&part=regulations';
const NOTICE = 'Rules could not be loaded. Check the official rules before each trip.';
const CHECK = /Check the official rules before this trip/;
const LEGAL = 'Not legal advice; check the official page.';
const trip = (id, date, targets, extra) => ({id, date, targets, region: region.id, point: region.forecast_points[0].id,
  species: 'lingcod', start_hour: 7, end_hour: 13, wind_limit: 15, gust_limit: 20, sea_limit: 4, enabled: 1, ...extra});
function registry(age = 0, status = 'reviewed') {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(NOW - 72 * HOUR).toISOString();
  d.rules_review_status = status;
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok',
      content_sha256: s.approved_content_sha256, data_retrieved_at: new Date(NOW - age * HOUR).toISOString()};
  }
  for (const id of ['lingcod', 'rockfish', 'salmon']) d.species[id].windows = [{start: '2026-10-10', end: '2026-10-13'}];
  return d;
}

const dir = await mkdtemp(join(tmpdir(), 'trip-rules-')), out = join(dir, 'sheet.mjs');
after(() => rm(dir, {recursive: true, force: true}));
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
  export {TripAlerts} from './web/app/TripAlerts.tsx';
  export {regsData, resetRegs} from './web/regs.ts';
  export {render, h} from 'preact'; export {act} from 'preact/test-utils';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const {TripAlerts, render, h, act, regsData, resetRegs} = await import(pathToFileURL(out).href);

// Small DOM for Preact mounting (including effects and link attributes), as in test_regs_retry.mjs.
class Node {
  constructor(type, name, data = '') { Object.assign(this, {nodeType: type, localName: name, data, childNodes: [], parentNode: null, style: {}, attrs: {}}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null; }
  get textContent() { return this.nodeType === 3 ? this.data : this.childNodes.map(c => c.textContent).join(''); }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.remove(); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {} removeEventListener() {}
}
const all = (node, pred) => [...(pred(node) ? [node] : []), ...node.childNodes.flatMap(c => all(c, pred))];
const rows = root => all(root, n => n.localName === 'p' && n.attrs['data-status']);
const matches = (root, copy) => root.textContent.split(copy).length - 1;
async function until(ready) {
  for (let i = 0; i < 30 && !ready(); i++) await act(() => setImmediate());
  assert.ok(ready(), 'sheet reached expected state');
}
async function sheet(t, trips, copy) {
  t.mock.timers.enable({apis: ['Date'], now: NOW});
  regsData.value = null; resetRegs();
  const root = new Node(1, 'div'), urls = [];
  const original = globalThis.document;
  globalThis.document = {createElement: n => new Node(1, n), createElementNS: (_, n) => new Node(1, n), createTextNode: s => new Node(3, '#text', s)};
  t.after(async () => { await act(() => render(null, root)); if (original) globalThis.document = original; else delete globalThis.document; });
  t.mock.method(globalThis, 'fetch', async url => {
    urls.push(url);
    switch (url) {
      case '/api/session': return Response.json({signedIn: true});
      case 'regions/morro-bay/region.json': return Response.json(region);
      case '/api/trips': return Response.json({trips, events: []});
      case '/api/comfort': return Response.json({feedback: []});
      case COPY: return copy;
      default: return new Response(null, {status: 404});
    }
  });
  const draw = target => act(() => render(h(TripAlerts, {regionId: region.id, target}), root));
  await draw(null);
  return {root, urls, draw};
}

test('three upcoming trips share one registry read, and each date drives its own season reading', async t => {
  const {root, urls, draw} = await sheet(t, [trip('reef', '2026-10-13', ['reef', 'lingcod']),
    trip('closed', '2026-10-14'), trip('unknown', '2026-10-15', ['no-profile']), trip('past', '2026-10-11')], Response.json(registry()));
  await until(() => rows(root).length === 4);
  const [lingcod, rockfish, closed, unknown] = rows(root);
  assert.match(lingcod.textContent, /Lingcod · Open .*Verified Oct 12.*Checked today/);
  assert.match(rockfish.textContent, /Rockfish \/ rock cod · Open /);
  const links = all(lingcod, n => n.localName === 'a');
  assert.equal(links.length, 1);
  assert.equal(links[0].attrs.href, fixture.regulations.sources['rules-central'].url);
  assert.match(closed.textContent, /Lingcod · Closed Closed on Wed 14 Oct/);
  assert.doesNotMatch(closed.textContent, /\bOpen\b/);
  assert.match(unknown.textContent, CHECK);
  assert.equal(unknown.attrs['data-status'], 'unknown');
  assert.equal(matches(root, LEGAL), 1);
  assert.equal(rows(all(root, n => n.localName === 'article')[0]).length, 0, 'past trip stays unchanged');
  await draw('reef');
  assert.equal(urls.filter(url => url === COPY).length, 1);
  assert.equal(urls.filter(url => url === DAILY).length, 1);
});

for (const [name, age, status, other] of [['Stale', 50], ['Overdue', 30], ['Unreviewed', 0, 'draft'], ['Another region’s', 0, 'reviewed', 'different']]) {
  test(`${name} rules never label a trip open`, async t => {
    const {root} = await sheet(t, [trip('a', '2026-10-13', ['lingcod'], other ? {region: other} : {})], Response.json(registry(age, status)));
    await until(() => rows(root).length === 1);
    const [reading] = rows(root);
    assert.match(reading.textContent, CHECK);
    assert.equal(reading.attrs['data-status'], 'unknown');
    assert.doesNotMatch(reading.textContent, /· Open\b|Verified/);
    assert.equal(all(reading, n => n.localName === 'a').length, 1);
  });
}

test('pending rules are quiet; a failed load says so once for the sheet, not per trip', async t => {
  const pending = Promise.withResolvers();
  const {root, urls, draw} = await sheet(t, [trip('a', '2026-10-13', ['reef']), trip('b', '2026-10-14')], pending.promise);
  await until(() => urls.includes(COPY));
  assert.match(root.textContent, /Add to calendar/);
  assert.equal(matches(root, NOTICE), 0);
  assert.equal(rows(root).length, 0);
  pending.resolve(new Response(null, {status: 503}));
  await until(() => matches(root, NOTICE) > 0);
  assert.equal(matches(root, NOTICE), 1);
  assert.ok(root.textContent.indexOf(NOTICE) < root.textContent.indexOf('Add to calendar'));
  assert.equal(rows(root).length, 0);
  await draw('salmon');
  assert.equal(urls.filter(url => url === COPY).length, 1, 'a failed read is not retried on sheet rerender');
});
