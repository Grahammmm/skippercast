// SC1722-05: a mistyped or old page link gets web/404.html (still HTTP 404, no-store), while API, data,
// script and tile misses, HEAD probes (web/fleet.ts boatDirectory) and every known page stay as they were.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const PAGE = readFileSync(new URL('../web/404.html', import.meta.url), 'utf8');
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/sources.html': '/sources.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
globalThis.NOT_FOUND_HTML = PAGE; // what scripts/build-worker.mjs compiles in; the built bundle is checked below
const {default: deployed} = await import('../server/index.ts');
const {acceptsHtml, isPagePath} = await import('../server/routes/assets.ts');
const {boatDirectory} = await import('../web/fleet.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com', HTML = {Accept: 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8'};
const calls = [];
// Static assets: known pages answer 299 with their path; anything else is the platform's empty 404.
const upstream404 = () => new Response(null, {status: 404, headers: {'Content-Length': '0', 'Content-Encoding': 'gzip', ETag: '"old"', 'Cache-Control': 'public, max-age=31536000, immutable'}});
const ASSETS = {fetch: async request => { const {pathname} = new URL(request.url); calls.push([pathname, request.method]); return /^\/(landing|app|sources)\.0123456789$/.test(pathname) ? new Response(pathname, {status: 299}) : upstream404(); }};
const call = (path, {method = 'GET', headers = {}, env = {}, target = worker} = {}) => target.fetch(new Request(ORIGIN + path, {method, headers, body: ['GET', 'HEAD'].includes(method) ? undefined : '{}'}), {ASSETS, ...env});

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; }, async batch(queries) { const out = []; for (const q of queries) out.push(await q.run()); return out; }};
  return {sql, adapter};
}

async function assertBranded(response, label) {
  assert.equal(response.status, 404, label);
  assert.equal(response.headers.get('Content-Type'), 'text/html; charset=utf-8', label);
  assert.equal(response.headers.get('Cache-Control'), 'no-store', label);
  assert.equal(response.headers.get('Vary'), 'Accept', label);
  for (const leaked of ['Content-Length', 'Content-Encoding', 'ETag']) assert.equal(response.headers.get(leaked) === ({'Content-Length': '0', 'Content-Encoding': 'gzip', ETag: '"old"'})[leaked], false, `${label}: upstream ${leaked} not carried onto the page`);
  assert.ok((await response.text()) === PAGE, `${label}: the authored page, byte for byte`);
}
async function assertNotPage(response, label) {
  assert.equal(response.status, 404, label);
  assert.equal(response.headers.get('Vary') === 'Accept' && response.headers.get('Content-Type') === 'text/html; charset=utf-8', false, label);
  assert.ok((await response.text()) !== PAGE, `${label}: not the page`);
}
async function assertUntouched(response, label) {
  assert.equal(response.status, 404, label);
  assert.equal(response.headers.get('Content-Type'), null, label);
  assert.equal(response.headers.get('ETag'), '"old"', `${label}: the assets' own answer`);
  assert.equal((await response.text()).length, 0, label);
}

test('the page is small, static and links back to /map and /', () => {
  assert.ok(Buffer.byteLength(PAGE) < 6 * 1024);
  assert.match(PAGE, /<html lang="en">/); assert.match(PAGE, /name="robots" content="noindex"/); assert.match(PAGE, /SkipperCast/);
  assert.match(PAGE, /<a href="\/map"[^>]*>Open the map<\/a>/); assert.match(PAGE, /<a href="\/"[^>]*>Home<\/a>/);
  assert.doesNotMatch(PAGE, /<script|<form|<style|https?:\/\//i);
});

test('unknown_page_get_is_branded_but_still_404', async () => {
  for (const path of ['/nope', '/old/link', '/old/link.html', '/old.release.html', '/old.release.v2.html', '/old/link/', '/nope?x=1&y=<b>', '/apiary', '/Nope']) await assertBranded(await call(path, {headers: HTML}), path);
  const page = await (await call('/nope?q=zzzmarker', {headers: HTML})).text();
  assert.ok(!page.includes('zzzmarker') && !page.includes('/nope'), 'nothing from the request is reflected');
});

test('accept_is_explicit_and_positive', async () => {
  for (const accept of ['text/html', 'TEXT/HTML', 'application/json, text/html;q=0.5', 'text/html ; q=1', 'text/html;q=0.001', 'text/html;level=1;q=0.8']) {
    assert.equal(acceptsHtml(accept), true, accept); await assertBranded(await call('/nope', {headers: {Accept: accept}}), accept);
  }
  for (const accept of [null, '', '*/*', 'text/*', 'application/json', 'application/xhtml+xml', 'text/html;q=0', 'text/html;q=0.0', 'text/html;q=abc', 'text/html;q=-1', 'text/html;q=2', 'text/html;q=1.5', 'text/htmlx', 'xtext/html', 'text/html;q=0, */*', 'text/html;q=0, text/html']) {
    assert.equal(acceptsHtml(accept), false, String(accept)); await assertUntouched(await call('/nope', {headers: accept === null ? {} : {Accept: accept}}), String(accept));
  }
});

test('resource_misses_never_get_html', async () => {
  const roots = ['/api', '/feeds', '/coast-data', '/data', '/regions', '/tiles', '/basemap', '/assets', '/vendor', '/downloads', '/icons', '/.well-known'];
  for (const path of ['/missing.js', '/x/app.css', '/data.json', '/x.geojson', '/a.pmtiles', '/logo.png', '/font.woff2', '/x.zip', '/page.HTML', '/page.html.js', '/old.release.js', '/old.release.html.map', '/old.release.HTML', '/sw.map']) await assertUntouched(await call(path, {headers: HTML}), path);
  // Reserved namespaces: through the assets handler's own check (the app answers /api and /feeds itself earlier).
  for (const root of roots) for (const path of [root, `${root}/`, `${root}/x`, `${root}/x/y.html`, `${root}/x/`]) assert.equal(isPagePath(path), false, path);
  for (const path of ['/data/nope', '/tiles/1/2/3', '/regions/x/region.json', '/assets/x', '/downloads/y', '/vendor/z', '/basemap/b', '/icons/i', '/coast-data/c', '/.well-known/w']) await assertNotPage(await call(path, {headers: HTML}), path);
  for (const path of ['/apiary', '/dataset', '/tilesx', '/assetsx/y']) assert.equal(isPagePath(path), true, path);
  for (const path of ['/a%2eb', '/a%2Fb', '/a%5cb', '/x%2e%2e/y', '/a%00']) { assert.equal(isPagePath(path), false, path); await assertUntouched(await call(path, {headers: HTML}), path); }
  assert.equal(isPagePath('/'), true); assert.equal(isPagePath('/a.b/c'), true, 'a dot in an earlier segment is a page path'); assert.equal(isPagePath('/a.b/c.js'), false);
  assert.equal(isPagePath('/old.release.html'), true, 'a multi-dot .html name is a page path'); assert.equal(isPagePath('/old.release.html.js'), false);
});

test('head_and_other_methods_do_not_synthesize', async () => {
  for (const headers of [{}, HTML]) for (const path of ['/nope', '/ports/morro-bay']) {
    const r = await call(path, {method: 'HEAD', headers});
    assert.equal(r.ok, false, path); assert.equal(r.status, 404, path); assert.equal(r.headers.get('Content-Type') === 'text/html; charset=utf-8' && r.headers.get('Vary') === 'Accept', false, path); assert.equal((await r.text()).length, 0, path);
  }
  for (const method of ['POST', 'PUT', 'OPTIONS', 'DELETE']) {
    const r = await call('/nope', {method, headers: HTML});
    assert.equal(r.headers.get('Content-Type') === 'text/html; charset=utf-8' && r.headers.get('Vary') === 'Accept', false, method);
  }
});

test('public_off_gate_still_hides_directory', async () => {
  const PORTS = [{id: 'morro-bay', name: 'Morro Bay', region: 'morro-bay', status: 'active'}];
  for (const env of [{}, {PUBLIC_PAGES_ENABLED: 'false'}, {PUBLIC_PAGES_ENABLED: 'tru'}]) {
    calls.length = 0;
    const head = await call('/ports/morro-bay', {method: 'HEAD', headers: HTML, env});
    assert.equal(head.ok, false); assert.equal(head.status, 404); assert.equal(calls.length, 0, 'the gate answers before the assets');
    const seen = [];
    const fetcher = async (url, init) => { seen.push([url, init]); return call(url, {method: init.method, headers: HTML, env}); };
    assert.ok((await boatDirectory('morro-bay', null, fetcher, async () => PORTS)).length === 0, 'no boat-list link while the pages are off');
    assert.equal(seen.length, 1); assert.equal(seen[0][0], '/ports/morro-bay'); assert.equal(seen[0][1].method, 'HEAD'); assert.equal(seen[0][1].credentials, 'omit'); assert.equal(seen[0][1].cache, 'no-store');
    const get = await call('/ports/morro-bay', {headers: HTML, env});
    assert.equal(get.status, 404); assert.match(get.headers.get('Content-Type'), /json/, 'the existing JSON 404'); assert.equal((await get.json()).error, 'Not found');
  }
});

test('api_errors_are_not_rewritten', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    for (const path of ['/api/nope', '/api/trips/']) {
      const r = await call(path, {headers: {...HTML, 'x-test-owner': 'alice'}, env});
      assert.equal(r.status, 404, path); assert.match(r.headers.get('Content-Type'), /json/, path); const body = await r.json(); assert.equal(body.error, 'Not found'); assert.equal(typeof body.request_id, 'string');
    }
    const auth = await call('/api/auth/nope', {headers: HTML, env});
    assert.equal(auth.status, 404); assert.match(auth.headers.get('Content-Type'), /json/); assert.equal((await auth.json()).error, 'Not found');
    assert.equal((await call('/api/nope', {headers: HTML})).status, 401, 'anonymous private API keeps its 401');
    for (const path of ['/feeds/nope/x.json', '/feeds/']) { const r = await call(path, {headers: HTML}); assert.equal(r.status, 404, path); assert.equal((await r.clone().text()).includes('<h1'), false, path); }
  } finally { sql.close(); }
});

test('known_and_non404_responses_are_identical', async () => {
  for (const [path, body] of [['/', '/landing.0123456789'], ['/?region=morro-bay', '/app.0123456789'], ['/map', '/app.0123456789'], ['/sources', '/sources.0123456789']]) {
    const r = await call(path, {headers: HTML}); assert.equal(r.status, 299, path); assert.equal(await r.text(), body, path); assert.equal(r.headers.get('Cache-Control'), 'no-store', path);
  }
  const redirect = await call('/coast', {headers: HTML}); assert.equal(redirect.status, 302);
  assert.equal((await call('/sources/', {headers: HTML})).status, 301);
  // A mapped page whose asset is missing is a build fault, not an unknown link: it is not replaced.
  const saved = globalThis.SHELLS['/sources.html']; globalThis.SHELLS['/sources.html'] = '/gone.0123456789.html';
  try { assert.equal((await call('/sources', {headers: HTML})).headers.get('Vary') === 'Accept', false); } finally { globalThis.SHELLS['/sources.html'] = saved; }
  // Unmapped answers other than 404 pass through untouched; a thrown fetch and a missing binding behave as before.
  for (const status of [200, 204, 206, 301, 401, 403, 500]) {
    const kept = {fetch: async () => new Response(status === 204 ? null : 'asset', {status, headers: {'X-Kept': 'yes', ETag: '"e"'}})};
    const r = await worker.fetch(new Request(ORIGIN + '/nope', {headers: HTML}), {ASSETS: kept});
    assert.equal(r.status, status); assert.equal(r.headers.get('X-Kept'), 'yes'); assert.equal(r.headers.get('ETag'), '"e"'); if (status !== 204) assert.equal(await r.text(), 'asset');
  }
  const failing = {fetch: async () => { throw Error('assets down'); }};
  let thrown = null;
  try { const r = await worker.fetch(new Request(ORIGIN + '/nope', {headers: HTML}), {ASSETS: failing}); thrown = r.status >= 500 ? 'error response' : null; } catch (e) { thrown = String(e.message); }
  assert.ok(thrown !== null, 'a failing assets binding still fails: it is not turned into the page');
  const none = await worker.fetch(new Request(ORIGIN + '/nope', {headers: HTML}), {});
  assert.equal(none.status, 404); assert.equal(await none.text(), 'Not found');
  // Without the compiled page (a source-only run) the assets' own 404 stays.
  const page = globalThis.NOT_FOUND_HTML; delete globalThis.NOT_FOUND_HTML;
  try { await assertUntouched(await call('/nope', {headers: HTML}), 'no compiled page'); } finally { globalThis.NOT_FOUND_HTML = page; }
});

test('real_build_embeds_authored_page', async t => {
  const build = readFileSync(new URL('../scripts/build-worker.mjs', import.meta.url), 'utf8');
  assert.match(build, /readFile\('web\/404\.html'/); assert.match(build, /NOT_FOUND_HTML:JSON\.stringify\(notFoundHtml\)/);
  const bundle = new URL('../dist/server/index.js', import.meta.url);
  if (!existsSync(bundle)) return t.skip('dist/server/index.js not built here (node scripts/build-worker.mjs); the builder runs it');
  // The bundle carries its own compiled constants (esbuild define), so it needs none of this file's globals.
  const {default: built} = await import(bundle.href);
  const headers = {Accept: 'text/html'};
  const miss = await built.fetch(new Request(ORIGIN + '/nope', {headers}), {ASSETS});
  assert.equal(miss.status, 404); assert.equal(miss.headers.get('Cache-Control'), 'no-store');
  assert.ok((await miss.text()) === PAGE, 'the built Worker serves the bytes of web/404.html');
  for (const path of ['/missing.js', '/tiles/1/2/3', '/data/x']) await assertUntouched(await built.fetch(new Request(ORIGIN + path, {headers}), {ASSETS}), path);
  assert.equal((await built.fetch(new Request(ORIGIN + '/nope', {method: 'HEAD', headers}), {ASSETS})).headers.get('Vary') === 'Accept', false);
  assert.equal((await built.fetch(new Request(ORIGIN + '/api/auth/nope', {headers}), {ASSETS})).status, 404);
});
