import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {CSP, CONNECT_ORIGINS, IMAGE_ORIGINS, SECURITY_HEADERS, secure, headersFile} from '../server/security-headers.ts';
import {cloudSource, mapSourceHosts, naipSource} from '../packages/coast/src/map-sources.ts';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/sources.html': '/sources.0123456789.html'};
globalThis.BUILD_ID = 'test';
const {default: worker} = await import('../server/index.ts');

const directives = Object.fromEntries(CSP.split(';').map(d => d.trim().split(/\s+/)).map(([name, ...values]) => [name, values]));

function assertSecured(response, label) {
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(response.headers.get(name), value, `${label}: ${name}`);
}

test('the policy is enumerated: no scheme wildcards, no inline script, no framing', () => {
  assert.deepEqual(directives['script-src'], ["'self'"]);
  assert.deepEqual(directives['frame-ancestors'], ["'none'"]);
  assert.deepEqual(directives['object-src'], ["'none'"]);
  assert.deepEqual(directives['style-src-elem'], ["'self'"], 'no <style> elements are injected');
  for (const [name, values] of Object.entries(directives)) {
    assert.ok(!values.includes('https:') && !values.includes('*') && !values.includes('http:'), `${name} has a wildcard`);
    if (name !== 'style-src' && name !== 'style-src-attr') assert.ok(!values.includes("'unsafe-inline'"), `${name} allows inline`);
    assert.ok(!values.includes("'unsafe-eval'"), `${name} allows eval`);
  }
  assert.deepEqual(directives['connect-src'], ["'self'", ...CONNECT_ORIGINS]);
  for (const origin of IMAGE_ORIGINS) assert.ok(directives['img-src'].includes(origin));
  assert.match(SECURITY_HEADERS['Strict-Transport-Security'], /max-age=63072000; includeSubDomains; preload/);
  assert.match(SECURITY_HEADERS['Permissions-Policy'], /geolocation=\(self\)/);
});

// FE-22: the v2 cloud loop requests nowCOAST WMS tiles through MapLibre, which loads raster
// tiles with fetch (web/map/engine.ts keeps refreshExpiredTiles on), so its one host joins
// connect-src only; no <img> loads it and img-src stays as it was.
test('the GOES cloud frames\' host is allowed for MapLibre\'s tile fetches, and nothing wider', () => {
  const at = '2026-10-02T02:53:00.000Z';
  const frame = cloudSource({id: 'goes-longwave', kind: 'observation', observedAt: at, fetchedAt: at, availableTimes: [at], layer: 'goes_longwave_imagery',
    url: 'https://nowcoast.noaa.gov/', attribution: 'NOAA / NESDIS · GOES', license: 'public-domain-us-gov', limitations: 'Observed frames only.'}, new Date(at));
  const origin = new URL(frame.tiles[0]).origin;
  assert.equal(origin, 'https://nowcoast.noaa.gov');
  assert.ok(mapSourceHosts.includes(origin), 'the fixed publisher host packages/coast names');
  assert.ok(directives['connect-src'].includes(origin));
  assert.ok(!directives['img-src'].includes(origin), 'img-src is not widened');
  assert.equal(CONNECT_ORIGINS.filter(o => o.includes('nowcoast')).length, 1);
});

// FE-23: the aerial base's NAIP tiles load the same way (web/map/aerial.ts draws naipSource()), so its
// one USGS host joins connect-src only; every fixed publisher host packages/coast names is now allowed.
test('the NAIP aerial base\'s host is allowed for MapLibre\'s tile fetches, and nothing wider', () => {
  const origins = [...new Set(naipSource().tiles.map(t => new URL(t.replace('{bbox-epsg-3857}', '0,0,1,1')).origin))];
  assert.deepEqual(origins, ['https://imagery.nationalmap.gov']);
  assert.ok(mapSourceHosts.includes(origins[0]), 'the fixed publisher host packages/coast names');
  assert.ok(directives['connect-src'].includes(origins[0]));
  assert.ok(!directives['img-src'].includes(origins[0]), 'img-src is not widened');
  assert.equal(CONNECT_ORIGINS.filter(o => o.includes('nationalmap')).length, 1);
  for (const host of mapSourceHosts) assert.ok(directives['connect-src'].includes(host), host);
});

// Every https origin written as a string literal in the client must be either
// allowed by the CSP or known to be a plain link (never fetched or embedded).
const LINK_ONLY = new Set(['docs.raymarine.com', 'inavx.com', 'marinespecies.wildlife.ca.gov', 'support.garmin.com',
  'wildlife.ca.gov', 'www.fisheries.noaa.gov', 'www.lowrance.com', 'www.morrobayca.gov', 'www.ndbc.noaa.gov',
  'www.simrad-yachting.com', 'www8.garmin.com']);
test('every origin the client code names is allowed by the CSP or is a plain link', () => {
  const allowed = new Set([...CONNECT_ORIGINS, ...IMAGE_ORIGINS].map(o => new URL(o).host));
  const dist = new URL('../dist/', import.meta.url), unknown = new Set();
  for (const name of readdirSync(dist).filter(n => n.endsWith('.js'))) {
    const text = readFileSync(new URL(name, dist), 'utf8');
    for (const match of text.matchAll(/(?<!href=)["'`]https:\/\/([A-Za-z0-9.-]+)/g)) {
      if (!allowed.has(match[1]) && !LINK_ONLY.has(match[1])) unknown.add(`${match[1]} (${name})`);
    }
  }
  assert.deepEqual([...unknown], [], 'add new fetch/tile hosts to server/security-headers.ts, or to LINK_ONLY if only linked');
});

test('page shells, assets, APIs, feeds and errors all carry the security headers', async () => {
  const requested = [];
  // env.ASSETS responses have immutable headers on Workers; model that here.
  class Immutable extends Headers { set() { throw new TypeError('immutable'); } }
  const ASSETS = {fetch: async request => {
    const path = new URL(request.url).pathname;requested.push(path);
    const html = path.startsWith('/index.') || path.startsWith('/sources.');
    const response = new Response(html ? '<!doctype html><title>x</title>' : 'x', {headers: {'Content-Type': html ? 'text/html' : 'text/javascript'}});
    Object.defineProperty(response, 'headers', {value: new Immutable(response.headers)});
    return response;
  }};
  const env = {ASSETS};
  const shell = await worker.fetch(new Request('https://skippercast.com/'), env);
  assert.equal(shell.status, 200);assertSecured(shell, 'shell');
  assert.equal(shell.headers.get('Cache-Control'), 'no-store', 'shells stay uncached');
  assert.deepEqual(requested, ['/index.0123456789']);
  assertSecured(await worker.fetch(new Request('https://skippercast.com/sources.html'), env), 'sources shell');
  const asset = await worker.fetch(new Request('https://skippercast.com/app.0123456789.js'), env);
  assertSecured(asset, 'asset');assert.equal(asset.headers.get('Content-Type'), 'text/javascript');
  const api = await worker.fetch(new Request('https://skippercast.com/api/session'), {});
  assert.equal(api.status, 200);assertSecured(api, 'api');
  assertSecured(await worker.fetch(new Request('https://skippercast.com/api/nope'), {}), 'api 401/404');
  assertSecured(await worker.fetch(new Request('https://skippercast.com/feeds/../secret'), {}), 'feed 404');
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw Error('upstream down'); };
    const failed = await worker.fetch(new Request('https://skippercast.com/api/intelligence?region=morro-bay'), {});
    assert.equal(failed.status, 503);assertSecured(failed, 'error');
  } finally { globalThis.fetch = original; }
});

test('secure() copies immutable responses and keeps status, body and existing headers', async () => {
  const mutable = new Response('ok', {status: 201, headers: {'Cache-Control': 'no-store'}});
  assert.equal(secure(mutable), mutable);
  const frozen = Response.redirect('https://skippercast.com/', 302);
  const out = secure(frozen);
  assert.notEqual(out, frozen);assert.equal(out.status, 302);assert.equal(out.headers.get('Location'), 'https://skippercast.com/');
  assertSecured(out, 'redirect');
  assert.equal(await secure(new Response('body')).text(), 'body');
});

test('the generated _headers file applies the same headers to directly served assets', () => {
  const text = headersFile(), lines = text.split('\n');
  assert.equal(lines[1], '/*');
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.ok(lines.includes(`  ${name}: ${value}`), name);
});

test('pages carry no meta CSP that could drift from the header policy', () => {
  const dist = new URL('../dist/', import.meta.url);
  for (const name of readdirSync(dist).filter(n => n.endsWith('.html'))) {
    assert.doesNotMatch(readFileSync(new URL(name, dist), 'utf8'), /http-equiv=["']Content-Security-Policy/i, name);
  }
});
