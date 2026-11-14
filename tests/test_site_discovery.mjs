// Search and link-preview metadata: the landing's canonical, share card and
// structured data (docs/web-app.md#search-and-link-previews), canonicals, and the
// static robots.txt and sitemap.xml. FE-61 dropped v1's share card with
// dist/index.html; these checks keep it from going missing again.
import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync, readFileSync, statSync, writeFileSync} from 'node:fs';
import {isDeepStrictEqual} from 'node:util';

const dist = new URL('../dist/', import.meta.url);
const read = name => readFileSync(new URL(name, dist), 'utf8');
const ORIGIN = 'https://skippercast.com';
const head = html => html.split('</head>')[0];
const meta = (html, attr, key) => [...head(html).matchAll(new RegExp(`<meta ${attr}="${key}" content="([^"]*)"`, 'g'))].map(m => m[1]);
const SNAPSHOT = new URL('./fixtures/search-surface.json', import.meta.url);
const canonical = html => [...head(html).matchAll(/<link rel="canonical" href="([^"]+)"/g)].map(m => m[1]);

test('the landing names one canonical home, a share card and the site name', () => {
  const html = read('landing.html');
  assert.deepEqual(canonical(html), [`${ORIGIN}/`]);
  const title = head(html).match(/<title>([^<]+)<\/title>/)[1];
  const [description] = meta(html, 'name', 'description');
  assert.match(title, /^SkipperCast · /);
  assert.match(title + description, /fishing/i, 'the words people search for are in the title or description');
  assert.ok(description.length <= 170, `description ${description.length} characters`);
  assert.deepEqual(meta(html, 'property', 'og:url'), [`${ORIGIN}/`]);
  assert.deepEqual(meta(html, 'property', 'og:title'), [title]);
  assert.deepEqual(meta(html, 'property', 'og:description'), [description]);
  assert.deepEqual(meta(html, 'name', 'twitter:card'), ['summary_large_image']);
  assert.ok(!meta(html, 'name', 'robots').length, 'the landing is indexable');
  // The card's image: absolute, served from dist, under Signal's 1 MiB preview limit, size as declared.
  const [image] = meta(html, 'property', 'og:image');
  assert.deepEqual(meta(html, 'name', 'twitter:image'), [image]);
  assert.ok(image.startsWith(`${ORIGIN}/`), image);
  const file = new URL(image.slice(ORIGIN.length + 1), dist);
  assert.ok(existsSync(file) && statSync(file).size < 1_048_576, image);
  assert.deepEqual([meta(html, 'property', 'og:image:width'), meta(html, 'property', 'og:image:height')], [['1736'], ['906']]);
  // WebSite (Google's site-name signal) and Organization, matching the advisor pages' Organization.
  const ld = JSON.parse(head(html).match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/)[1]);
  const byType = Object.fromEntries(ld.map(item => [item['@type'], item]));
  assert.deepEqual(byType.WebSite, {'@context': 'https://schema.org', '@type': 'WebSite', name: 'SkipperCast', url: `${ORIGIN}/`});
  assert.equal(byType.Organization.url, `${ORIGIN}/`);
  assert.ok(existsSync(new URL(byType.Organization.logo.slice(ORIGIN.length + 1), dist)), byType.Organization.logo);
});

test('the pages served at two paths each name one canonical; the map and private pages stay noindex', () => {
  // Without an area the app redirects to the saved home or the landing (web/app/main.tsx), so it stays out of search and the sitemap.
  const app = read('app.html');
  assert.deepEqual(meta(app, 'name', 'robots'), ['noindex']);
  assert.deepEqual(canonical(app), []);
  assert.equal(meta(app, 'name', 'description').length, 1);
  assert.deepEqual(canonical(read('sources.html')), [`${ORIGIN}/sources`]);
  for (const page of ['admin.html', 'chat.html', 'my-data.html', 'upload.html']) assert.deepEqual(meta(read(page), 'name', 'robots'), ['noindex'], `${page} stays out of search`);
});

test('the .html legal and research pages name one self-referencing canonical', () => {
  for (const page of ['licenses.html', 'species-research.html'])
    assert.deepEqual(canonical(read(page)), [`${ORIGIN}/${page}`], page);
});

test('robots.txt allows crawling and names the sitemap; the sitemap lists only indexable public pages', () => {
  const robots = read('robots.txt').split('\n').filter(line => line && !line.startsWith('#'));
  assert.deepEqual(robots, ['User-agent: *', 'Allow: /', `Sitemap: ${ORIGIN}/sitemap.xml`]);
  const xml = read('sitemap.xml');
  assert.match(xml, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
  assert.equal(new Set(locs).size, locs.length, 'no duplicates');
  assert.ok(locs.includes(`${ORIGIN}/`));
  assert.ok(!locs.includes(`${ORIGIN}/map`), 'the map redirects without an area');
  for (const path of ['/coverage', '/skill']) assert.equal(locs.filter(loc => loc === `${ORIGIN}${path}`).length, 1, `${path} is listed once`);
  for (const alias of ['/coverage.html', '/skill.html']) assert.ok(!locs.includes(`${ORIGIN}${alias}`), `${alias} is not listed; the page is served at its extensionless path`);
  // Every entry is a page in dist (by its served path) or a server-rendered public page, and none is noindex.
  const served = {'/': 'landing.html', '/sources': 'sources.html', '/status': 'status.html', '/coverage': 'coverage.html', '/skill': 'skill.html'};
  const serverPages = new Set(['/report', '/about', '/methodology']);
  for (const loc of locs) {
    assert.ok(loc.startsWith(`${ORIGIN}/`), loc);
    const path = loc.slice(ORIGIN.length);
    if (serverPages.has(path)) continue;
    const page = served[path] ?? path.slice(1);
    assert.ok(page.endsWith('.html') && existsSync(new URL(page, dist)), `${loc} is a page in dist`);
    assert.ok(!meta(read(page), 'name', 'robots').includes('noindex'), `${loc} is indexable`);
  }
});

test('coverage_and_skill_use_their_served_canonical_paths', () => {
  for (const [page, path] of [['coverage.html', '/coverage'], ['skill.html', '/skill']]) {
    const html = read(page);
    assert.deepEqual(canonical(html), [`${ORIGIN}${path}`], `${page} names its served path as its one canonical`);
    assert.ok(!meta(html, 'name', 'robots').some(value => /noindex/i.test(value)), `${page} is indexable`);
  }
});

test('discovery_keeps_private_and_alias_urls_out', () => {
  const locs = [...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
  for (const path of ['/map', '/admin.html', '/chat.html', '/my-data.html', '/upload.html', '/coverage.html', '/skill.html'])
    assert.ok(!locs.includes(`${ORIGIN}${path}`), `${path} stays out of the sitemap`);
});

// The search-facing surface in one committed snapshot (tests/fixtures/search-surface.json): robots.txt
// byte for byte, the sitemap's exact URL list, and the robots and canonical tags of a fixed page list.
// Any change to these files fails here until the snapshot changes in the same, reviewed PR.
// To accept a deliberate change: SEARCH_SURFACE_UPDATE=1 node --test tests/test_site_discovery.mjs
const SURFACE_PAGES = ['landing', 'sources', 'status', 'coverage', 'skill', 'licenses', 'species-research', 'app', 'admin', 'chat', 'my-data', 'upload'];
const SERVER_PAGES = ['/report', '/about', '/methodology'];

async function searchSurface() {
  const pages = {};
  for (const name of SURFACE_PAGES) {
    const html = read(`${name}.html`);
    pages[`${name}.html`] = {robots: meta(html, 'name', 'robots'), canonical: canonical(html)};
  }
  // The server pages are rendered by the worker from dist/coast-readable.html; no network is used.
  globalThis.REGIONS = {};
  globalThis.DEPLOYMENT = {allowed_origins: [ORIGIN]};
  const {serveCoastPage} = await import('../server/coast-pages.ts');
  const template = read('coast-readable.html');
  for (const path of SERVER_PAGES) {
    const response = await serveCoastPage(new Request(ORIGIN + path), {template, regions: {}, now: new Date('2026-10-07T12:00:00Z'), fetcher: async () => { throw new Error('offline'); }});
    const html = await response.text();
    pages[path] = {robots: meta(html, 'name', 'robots'), canonical: canonical(html), xRobotsTag: response.headers.get('X-Robots-Tag')};
  }
  return {
    robotsTxt: read('robots.txt').split('\n'),
    sitemap: [...read('sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]),
    pages,
  };
}

test('search_surface_matches_the_committed_snapshot', async () => {
  const actual = await searchSurface();
  if (process.env.SEARCH_SURFACE_UPDATE === '1') writeFileSync(SNAPSHOT, JSON.stringify(actual, null, 2) + '\n');
  const expected = JSON.parse(readFileSync(SNAPSHOT, 'utf8'));
  assert.ok(isDeepStrictEqual(actual.robotsTxt, expected.robotsTxt), `dist/robots.txt changed; update tests/fixtures/search-surface.json in the same PR:\n${JSON.stringify(actual.robotsTxt)}`);
  assert.ok(isDeepStrictEqual(actual.sitemap, expected.sitemap), `dist/sitemap.xml URL list changed; update tests/fixtures/search-surface.json in the same PR:\n${JSON.stringify(actual.sitemap)}`);
  assert.ok(isDeepStrictEqual(Object.keys(actual.pages), Object.keys(expected.pages)), 'the fixed page list changed');
  for (const page of Object.keys(expected.pages))
    assert.ok(isDeepStrictEqual(actual.pages[page], expected.pages[page]), `${page} robots or canonical tags changed; update tests/fixtures/search-surface.json in the same PR:\n${JSON.stringify(actual.pages[page])}`);
});
