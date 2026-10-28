import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {planTiles, tileURL, tileKey, packRequests, relativeTime, formatBytes, bannerText, installHint, isIOS, stampedHeaders,
  SHARED_FILES, TILE_CAP, ENC_ORIGIN, planBasemap} from '../dist/offline-core.js';

const read = p => readFileSync(new URL(p, import.meta.url), 'utf8');
const morro = JSON.parse(read('../dist/regions/morro-bay/region.json'));

test('Morro Bay pack coverage: swell forecast, chart tiles and basemap; no prefetched SST or current tiles', () => {
  const origin = 'https://skippercast.test';
  const urls = packRequests({origin, region: morro, shared: SHARED_FILES});
  assert.ok(urls.includes(`${origin}/api/forecast?region=morro-bay`), 'swell is in the saved forecast bundle, still subject to its age gate');
  assert.ok(urls.includes(morro.habitat_feed), 'the manifest is listed, not its referenced ocean tiles');
  assert.equal(urls.some(u => /habitat-tiles\//.test(u)), false, 'neither SST nor current tiles are prefetched');
  assert.equal(urls.some(u => /\/api\/coast\//.test(u)), false, 'Morro Bay ocean readings use the separate Coastal readings save');
  assert.ok(planTiles(morro.bounds).tiles.length > 0, 'chart tiles are planned');
  assert.ok(planBasemap(morro.bounds).tiles.length > 0, 'basemap ranges are planned');
  const pack = read('../dist/offline-pack.js'), trip = read('../web/trip.ts');
  assert.match(pack, /store\(tileURL\(t, layers\), tileKey\(/, 'the chart plan is saved');
  assert.match(trip, /new PMTiles\(rangeRecorder\(/, 'the basemap reader saves ranges');
  assert.match(trip, /reader\.getZxy\(t\.z, t\.x, t\.y/, 'every planned basemap tile is requested');
  assert.doesNotMatch(trip, /habitat-tiles|habitat-dynamics/, 'v2 extras do not add ocean tiles');
  assert.match(pack, /at >= sessionStart/, 'recently viewed data can be copied, not a guarantee of ocean coverage');
});

test('save-for-offline UI reminds users to check before leaving coverage without a full-coverage promise', () => {
  const ui = read('../web/app/Trip.tsx');
  assert.match(ui, /<p>Check the saved pack before leaving coverage\.<\/p>/);
  assert.match(ui, /Water temp and current tiles are not prefetched/);
  assert.doesNotMatch(ui, /full functionality|\d+ miles/i);
});

test('Morro Bay chart tiles at zoom 8-12 fit under the cap, and every tile is inside the grid', () => {
  const plan = planTiles(morro.bounds);
  assert.equal(plan.minZoom, 8);
  assert.equal(plan.maxZoom, 12);
  assert.ok(plan.tiles.length > 0 && plan.tiles.length <= TILE_CAP, String(plan.tiles.length));
  for (const {z, x, y} of plan.tiles) {
    const n = 2 ** (z - 1);
    assert.ok(x >= 0 && x < n && y >= 0 && y < n);
  }
  // Every zoom level is complete: the level's tiles cover the bounds' corners.
  const z12 = plan.tiles.filter(t => t.z === 12);
  const xs = z12.map(t => t.x), ys = z12.map(t => t.y);
  assert.equal(z12.length, (Math.max(...xs) - Math.min(...xs) + 1) * (Math.max(...ys) - Math.min(...ys) + 1));
});

test('the tile cap drops whole deeper zoom levels and says where it stopped', () => {
  const socal = JSON.parse(read('../dist/regions/southern-california/region.json'));
  const small = planTiles(morro.bounds, {cap: 20});
  assert.ok(small.tiles.length <= 20);
  assert.ok(small.maxZoom < 12 && small.maxZoom >= 8);
  assert.ok(small.tiles.every(t => t.z <= small.maxZoom));
  const big = planTiles(socal.bounds);
  assert.ok(big.tiles.length <= TILE_CAP);
  assert.equal(planTiles(morro.bounds, {cap: 1}).maxZoom, null);
  assert.throws(() => planTiles([1, 2, 1, 2]), /bounds/);
});

test('tile URLs are NOAA ENC GetMap requests only; cache keys never point at OpenStreetMap', () => {
  const url = new URL(tileURL({z: 12, x: 330, y: 800}, '0,1,2,6'));
  assert.equal(url.origin, ENC_ORIGIN);
  assert.equal(url.searchParams.get('request'), 'GetMap');
  assert.equal(url.searchParams.get('crs'), 'EPSG:3857');
  assert.equal(url.searchParams.get('width'), '512');
  const [minX, minY, maxX, maxY] = url.searchParams.get('bbox').split(',').map(Number);
  assert.ok(Math.abs((maxX - minX) - (maxY - minY)) < 1e-6);
  assert.match(tileKey('0,1,2,6', 12, 330, 800), /^https:\/\/gis\.charttools\.noaa\.gov\/__skippercast-tile\/0,1,2,6\/512\/12\/330\/800$/);
  const source = read('../dist/offline-core.js') + read('../dist/offline-pack.js');
  assert.doesNotMatch(source.replace(/\/\/.*$/gm, ''), /openstreetmap\.org/);
});

test('a pack lists the region config, its assets, rules, protected areas, feeds and forecast bundles', () => {
  const origin = 'https://skippercast.test';
  const urls = packRequests({origin, region: morro, config: 'regions/morro-bay/region.json', shared: SHARED_FILES,
    extra: ['https://api.weather.gov/alerts/active?zone=PZZ670', '/api/om/v1/marine?x=1']});
  const has = u => assert.ok(urls.includes(new URL(u, origin + '/').href), u);
  for (const u of ['regions/index.json', 'regions/morro-bay/region.json', 'regions/morro-bay/manifest.json', 'regions/morro-bay/coverage.json',
    morro.assets.regulations, morro.assets.protected_areas, morro.assets.atlas, morro.assets.search_plans, 'data/coasts.json',
    '/api/forecast?region=morro-bay', '/api/intelligence?region=morro-bay', 'https://api.weather.gov/alerts/active?zone=PZZ670', '/api/om/v1/marine?x=1',
    '/api/daily?region=morro-bay&part=regulations', '/api/daily?region=morro-bay&part=mpa-boundaries', '/api/daily?region=morro-bay&part=additional-closures'])
    has(u);
  // Every asset the region's published manifest names is saved.
  const manifest = JSON.parse(read('../dist/regions/morro-bay/manifest.json'));
  for (const asset of Object.values(manifest.assets)) has(asset.path);
  assert.equal(new Set(urls).size, urls.length);
  assert.throws(() => packRequests({origin, region: null}), /Region/);
});

test('saved-time wording is relative and never hides an invalid time', () => {
  const now = Date.parse('2026-09-29T12:00:00Z');
  assert.equal(relativeTime('2026-09-29T11:59:50Z', now), 'just now');
  assert.equal(relativeTime('2026-09-29T11:56:00Z', now), '4 min ago');
  assert.equal(relativeTime('2026-09-29T09:00:00Z', now), '3 h ago');
  assert.equal(relativeTime('2026-09-26T12:00:00Z', now), '3 days ago');
  assert.equal(relativeTime('1970-01-01T00:00:00.000Z', now), null);
  assert.equal(relativeTime('nope', now), null);
  assert.equal(formatBytes(340_000), '340 KB');
  assert.equal(formatBytes(12_345_678), '12.3 MB');
  assert.equal(stampedHeaders({'Content-Type': 'application/json'}, new Date(now)).get('X-SC-Saved-At'), '2026-09-29T12:00:00.000Z');
});

test('the banner appears offline and whenever saved data is on screen', () => {
  const now = Date.parse('2026-09-29T12:00:00Z');
  assert.equal(bannerText({online: false, savedAt: '2026-09-29T10:00:00Z', now}), 'Offline — showing data saved 2 h ago');
  assert.equal(bannerText({online: false, savedAt: null, now}), 'Offline — only saved data is available');
  assert.equal(bannerText({online: true, savedAt: '2026-09-29T11:00:00Z', now}), 'Connection problem — showing data saved 1 h ago');
  assert.equal(bannerText({online: true, savedAt: null, now}), null);
});

test('install help: browser prompt when offered, Share hint on iOS Safari, nothing when installed or dismissed', () => {
  const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
  const ipad = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15';
  const android = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36';
  assert.ok(isIOS(iphone) && isIOS(ipad, 5) && !isIOS(ipad, 0) && !isIOS(android));
  assert.equal(installHint({standalone: false, promptAvailable: true, userAgent: android}), 'prompt');
  assert.equal(installHint({standalone: false, promptAvailable: false, userAgent: android}), null);
  assert.equal(installHint({standalone: false, promptAvailable: false, userAgent: iphone}), 'ios');
  assert.equal(installHint({standalone: true, promptAvailable: false, userAgent: iphone}), null);
  assert.equal(installHint({standalone: false, promptAvailable: false, userAgent: iphone, dismissed: {ios: '2026-09-01'}}), null);
  assert.equal(installHint({standalone: false, promptAvailable: true, userAgent: android, dismissed: {prompt: '2026-09-01'}}), null);
});

// FE-61: v1's offline.js registered the worker on every visit; v2 registers it once something is saved (FE-51).
test('the app registers the stable, classic /sw.js, as the alerts do', () => {
  const trip = read('../web/trip.ts');
  assert.match(trip, /navigator\.serviceWorker\.register\('\/sw\.js'\)/);
  assert.doesNotMatch(trip, /register\('\/sw\.js',/, 'the worker is classic; web/alerts.ts registers it the same way');
  assert.match(read('../web/alerts.ts'), /register\('\/sw\.js'\)/);
  assert.doesNotMatch(read('../web/alerts.ts'), /register\('\/sw\.js',/);
});

test('saving a pack never re-stamps data the service worker answered from an older save', () => {
  const pack = read('../dist/offline-pack.js');
  assert.match(pack, /response\.headers\.has\('X-SC-Offline'\)/);
  // A pack that could not fetch its region config is discarded, keeping the older pack.
  assert.match(pack, /missing\.includes\(configURL\)/);
  assert.match(pack, /await caches\.delete\(name\);\s*throw error;/);
});
