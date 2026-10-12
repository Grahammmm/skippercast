// Search and link-preview metadata: the landing's canonical, share card and
// structured data (docs/web-app.md#search-and-link-previews), the map's canonical, and the
// static robots.txt and sitemap.xml. FE-61 dropped v1's share card with
// dist/index.html; these checks keep it from going missing again.
import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync, readFileSync, statSync} from 'node:fs';

const dist = new URL('../dist/', import.meta.url);
const read = name => readFileSync(new URL(name, dist), 'utf8');
const ORIGIN = 'https://skippercast.com';
const head = html => html.split('</head>')[0];
const meta = (html, attr, key) => [...head(html).matchAll(new RegExp(`<meta ${attr}="${key}" content="([^"]*)"`, 'g'))].map(m => m[1]);
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

test('the map and the pages served at two paths each name one canonical', () => {
  const app = read('app.html');
  assert.deepEqual(canonical(app), [`${ORIGIN}/map`], '/ also serves the app for shared links');
  assert.ok(!meta(app, 'name', 'robots').length, 'the map is indexable');
  assert.equal(meta(app, 'name', 'description').length, 1);
  assert.deepEqual(canonical(read('sources.html')), [`${ORIGIN}/sources`]);
  assert.deepEqual(canonical(read('privacy.html')), [`${ORIGIN}/privacy`]);
  for (const page of ['admin.html', 'chat.html', 'my-data.html', 'upload.html']) assert.deepEqual(meta(read(page), 'name', 'robots'), ['noindex'], `${page} stays out of search`);
});

test('robots.txt allows crawling and names the sitemap; the sitemap lists only indexable public pages', () => {
  const robots = read('robots.txt').split('\n').filter(line => line && !line.startsWith('#'));
  assert.deepEqual(robots, ['User-agent: *', 'Allow: /', `Sitemap: ${ORIGIN}/sitemap.xml`]);
  const xml = read('sitemap.xml');
  assert.match(xml, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1]);
  assert.equal(new Set(locs).size, locs.length, 'no duplicates');
  assert.ok(locs.includes(`${ORIGIN}/`) && locs.includes(`${ORIGIN}/map`));
  // Every entry is a page in dist (by its served path) or a server-rendered public page, and none is noindex.
  const served = {'/': 'landing.html', '/map': 'app.html', '/sources': 'sources.html', '/privacy': 'privacy.html'};
  const serverPages = new Set(['/report']);
  for (const loc of locs) {
    assert.ok(loc.startsWith(`${ORIGIN}/`), loc);
    const path = loc.slice(ORIGIN.length);
    if (serverPages.has(path)) continue;
    const page = served[path] ?? path.slice(1);
    assert.ok(page.endsWith('.html') && existsSync(new URL(page, dist)), `${loc} is a page in dist`);
    assert.ok(!meta(read(page), 'name', 'robots').includes('noindex'), `${loc} is indexable`);
  }
});
