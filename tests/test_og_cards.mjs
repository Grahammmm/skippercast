import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8');
const region = JSON.parse(read('../regions/morro-bay/region.json'));
const ports = JSON.parse(read('../catalog/home-ports.json')).ports;
globalThis.REGIONS = {[region.id]: region, 'fixture-alias': region};
globalThis.DEPLOYMENT = {allowed_origins: []};
globalThis.SHELLS = {'/app.html': '/app.hash.html', '/landing.html': '/landing.hash.html'};
const {ogFor} = await import('../server/og.ts');
const {serveAsset} = await import('../server/routes/assets.ts');
const app = read('../dist/app.html'), landing = read('../dist/landing.html');
const query = s => new URLSearchParams(s);
const expected = {
  title: 'Morro Bay & Avila fishing conditions · SkipperCast',
  description: 'Wind, swell, tide and water temperature for Morro Bay & Avila on one map.',
};
const noTime = value => assert.doesNotMatch(value, /\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b|\b(today|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b/i);

test('known region uses config names, first region wins, transient keys never enter previews', () => {
  for (const suffix of ['', '&region=unknown', '&day=2026-11-04&hour=13:00&spot=secret&forecast=storm']) {
    const og = ogFor(query(`region=morro-bay${suffix}`));
    assert.deepEqual(og, expected);
    Object.values(og).forEach(noTime);
  }
});

const rejectedIds = ['', 'unknown', '__proto__', 'constructor', '<script>', 'morro-bay">', '../../secret', '..', 'morro-bay/..'];
test('unknown, hostile, empty and prototype region ids never become metadata', () => {
  for (const id of rejectedIds) {
    assert.equal(ogFor(query(`region=${encodeURIComponent(id)}`)), null, id);
  }
  assert.equal(ogFor(query('')), null);
  assert.equal(ogFor(query('region=unknown&region=morro-bay')), null);
});

test('port names come only from the directory, belong to the region, and must be unambiguous', () => {
  const port = ports.find(p => p.region === region.id);
  assert.ok(port);
  const og = ogFor(query(`region=${region.id}&port=${port.id}`));
  assert.deepEqual(og, {...expected, title: `${port.name}, ${expected.title}`});
  Object.values(og).forEach(noTime);
  for (const suffix of ['port=junk', 'port=%3Cscript%3E', 'port=__proto__', 'port=constructor', 'port=monterey', `port=${port.id}&port=${port.id}`, `port=junk&port=${port.id}`]) {
    assert.deepEqual(ogFor(query(`region=${region.id}&${suffix}`)), expected, suffix);
  }
});

const tags = html => [...html.matchAll(/<meta\b[^>]*>/g)].map(([tag]) =>
  Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, k, v]) => [k, v])));
const meta = (html, key) => {
  const found = tags(html).filter(t => t.property === key || t.name === key);
  assert.equal(found.length, 1, key);
  return found[0].content;
};
test('static app preview tags are unique, mirror landing image, and keep noindex', () => {
  assert.equal(meta(app, 'og:type'), 'website');
  assert.equal(meta(app, 'og:site_name'), 'SkipperCast');
  assert.equal(meta(app, 'og:title'), app.match(/<title>(.*?)<\/title>/)[1]);
  assert.equal(meta(app, 'og:description'), meta(app, 'description'));
  assert.equal(meta(app, 'twitter:card'), 'summary_large_image');
  assert.equal(meta(app, 'robots'), 'noindex');
  for (const key of ['og:image', 'og:image:width', 'og:image:height', 'og:image:alt']) assert.equal(meta(app, key), meta(landing, key));
  tags(app).filter(t => t.property?.startsWith('og:') || t.name === 'twitter:card').forEach(t => noTime(t.content));
});

const calls = [];
class Rewriter {
  handlers = [];
  on(selector, handler) { this.handlers.push([selector, handler]); return this; }
  async transform(response) {
    let html = await response.text();
    for (const [selector, handler] of this.handlers) {
      calls.push(selector);
      if (selector === 'head') {
        html = html.replace('</head>', end => {
          let insert = '';
          handler.element({append(value, options) {
            assert.equal(options?.html, true);
            insert += value;
          }});
          return insert + end;
        });
        continue;
      }
      const property = selector.match(/^meta\[property="([^"]+)"\]$/)[1];
      html = html.replace(new RegExp(`<meta property="${property}" content="[^"]*" \\/>`), tag => {
        let result = tag;
        handler.element({setAttribute(name, value) {
          assert.equal(name, 'content');
          result = tag.replace(/content="[^"]*"/, `content="${value.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"`);
        }});
        return result;
      });
    }
    return new Response(html, response);
  }
}
const fetchShell = async path => {
  const raw = new Request(`https://skippercast.com${path}`);
  return serveAsset({req: {raw}, var: {path: new URL(raw.url).pathname}, env: {ASSETS: {fetch: async () =>
    new Response(app, {status: 200, headers: {'Content-Type': 'text/html', 'X-Fixture': 'kept', 'Cache-Control': 'public'}})}}});
};
test('rewriter changes only the OG contents and adds one /map preload, retaining status, headers and other bytes', async () => {
  globalThis.HTMLRewriter = Rewriter;
  try {
    // The alias fixture catches hrefs built from the query key instead of the config id.
    for (const path of ['/map?region=morro-bay', '/map?region=fixture-alias', '/?region=morro-bay', '/app.html?region=morro-bay']) {
      calls.length = 0;
      const response = await fetchShell(path), html = await response.text();
      const escaped = value => value.replaceAll('&', '&amp;');
      let wanted = app.replace(`property="og:title" content="${meta(app, 'og:title')}"`, `property="og:title" content="${escaped(expected.title)}"`)
        .replace(`property="og:description" content="${meta(app, 'og:description')}"`, `property="og:description" content="${escaped(expected.description)}"`);
      const selectors = ['meta[property="og:title"]', 'meta[property="og:description"]'];
      if (path.startsWith('/map?')) {
        wanted = wanted.replace('</head>', '<link rel="preload" as="fetch" crossorigin="anonymous" href="/regions/morro-bay/region.json"></head>');
        selectors.push('head');
      }
      assert.equal(html, wanted, path);
      assert.deepEqual(calls, selectors, path);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('Cache-Control'), 'no-store');
      assert.equal(response.headers.get('Content-Type'), 'text/html');
      assert.equal(response.headers.get('X-Fixture'), 'kept');
    }
    // A first-value-only check could rewrite the shell for an ambiguous shared link.
    const untouched = ['/map', '/map?view=coast', ...rejectedIds.map(id => `/map?region=${encodeURIComponent(id)}`),
      '/map?region=unknown&region=morro-bay', '/map?region=morro-bay&region=unknown', '/map?region=morro-bay&region=morro-bay',
      '/?region=unknown&region=morro-bay', '/landing.html?region=morro-bay', '/sources?region=morro-bay',
      '/status?region=morro-bay', '/about.html?region=morro-bay', '/'];
    for (const path of untouched) {
      calls.length = 0;
      const response = await fetchShell(path);
      assert.equal(await response.text(), app, path);
      assert.equal(response.headers.get('Cache-Control'), path.startsWith('/about.html') ? 'public' : 'no-store');
      assert.equal(calls.length, 0, path);
    }
  } finally { delete globalThis.HTMLRewriter; }
});

test('without HTMLRewriter the app body is byte-identical', async () => {
  assert.equal(typeof globalThis.HTMLRewriter, 'undefined');
  const response = await fetchShell('/map?region=morro-bay');
  assert.equal(await response.text(), app);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
});
