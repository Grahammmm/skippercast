// SkipperCast's offline inputs for scripts/showcase.py (the `setup` named in docs/showcase/pages-*.json).
//
// The same kind of synthetic answers the browser tests use (e2e/fixtures.ts, e2e/v2-brief.spec.ts,
// e2e/v2-landing.spec.ts), all timed from the one fixed clock, so both columns of the gallery see identical
// inputs and no live forecast, feed, buoy, tide, coastal bridge, boundary or imagery service is ever reached.
// Regional files (MPA polygons) are read from the revision being captured (`root`). Values are invented:
// never a forecast, observation or production feed.
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {forecastFixture} from '../e2e/forecast-fixture.ts';

/** A 1×1 transparent PNG: what the stubbed NAIP imagery service answers with (as e2e/fixtures.ts). */
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const MPA_SERVICE = 'https://services2.arcgis.com/Uq9r85Potqm3MfRV/arcgis/rest/services/biosds582_fpu/FeatureServer/0/query';
const BASEMAP = 'tiles/basemap/ca-coast-fixture.pmtiles';
const HOUR = 3_600_000, DAY = 24 * HOUR;

function regionalData(root) {
  const read = path => { try { return JSON.parse(readFileSync(resolve(root, path), 'utf8')); } catch { return null; } };
  const directory = read('dist/regions/index.json') || {regions: []};
  return id => {
    const entry = directory.regions.find(row => row.id === (id || directory.default_region));
    const region = entry && read(`dist/${entry.config}`);
    const mpas = region?.assets?.protected_areas && read(`dist/${region.assets.protected_areas}`);
    if (!region || !mpas) return null;
    return {region, mpas, closures: region.assets.closures ? read(`dist/${region.assets.closures}`) : null};
  };
}

/** The region's daily feed (as e2e/v2-brief.spec.ts): a buoy, the day's tides, a quiet advisory check and yesterday's trips. */
function dailyFeed(region, now) {
  const iso = ms => new Date(now + ms).toISOString(), checked = iso(-10 * 60_000), yesterday = iso(-DAY).slice(0, 10);
  return {schema_version: 1, generated_at: checked, region_id: region, landing_names: ['Morro Bay', 'Avila'], sources: {
    'buoy-46011': {id: 'buoy-46011', name: 'NOAA NDBC 46011 observations', kind: 'observation', url: 'https://www.ndbc.noaa.gov/station_page.php?station=46011',
      checked_at: checked, max_age_hours: 6, status: 'ok', data: {station: '46011', observations: [{time: iso(-HOUR), WSPD: 4, GST: 6, WVHT: 1.2, DPD: 11, MWD: 295, WTMP: 14.5}]}},
    tides: {id: 'tides', name: 'NOAA CO-OPS 9412110 predictions', kind: 'prediction', url: 'https://tidesandcurrents.noaa.gov/stationhome.html?id=9412110',
      checked_at: checked, max_age_hours: 36, status: 'ok',
      data: {station: '9412110', datum: 'MLLW', predictions: [{time: iso(-4 * HOUR), height_ft: 0.9, type: 'L'}, {time: iso(2 * HOUR), height_ft: 4.1, type: 'H'}, {time: iso(8 * HOUR), height_ft: 0.6, type: 'L'}]}},
    'nws-alerts': {id: 'nws-alerts', name: 'NWS marine alerts', kind: 'advisory', url: 'https://api.weather.gov/alerts/active?zone=PZZ670', checked_at: checked, status: 'ok', data: {alerts: []}},
  }, reports: [{date: yesterday, boat: 'Fixture Gull', port: 'Morro Bay'}, {date: yesterday, boat: 'Fixture Tern', port: 'Avila Beach'}]};
}

/** The conditions feed behind the landing readings (as e2e/v2-landing.spec.ts). */
function conditionsFeed(region, now) {
  const ago = min => new Date(now - min * 60_000).toISOString();
  const buoy = (name, station, units, row) => ({name, status: 'ok', max_age_hours: 2, data: {station, units, observations: [row]}});
  return {schema_version: 1, region_id: region, generated_at: ago(12), sources: {
    offshore: buoy('Cape San Martin offshore', '46028', {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, {time: ago(20), WDIR: 320, WSPD: 7, GST: 9}),
    'diablo-spectrum': buoy('Diablo Canyon swell and wind waves', '46215', {SwH: 'm', SwP: 'sec', SwD: '-'}, {time: ago(34), SwH: 0.7, SwP: 10.5, SwD: 'WNW'}),
    diablo: buoy('Diablo Canyon', '46215', {WTMP: 'degC'}, {time: ago(40), WTMP: 14.5}),
  }};
}

/** A NOAA WCOFS surface-current packet on a 0.04° grid off Morro Bay, three-hourly frames around now (as e2e/v2-landing.spec.ts). */
function oceanPacket(now) {
  const three = 3 * HOUR, first = Math.floor(now / three) * three - three, iso = ms => new Date(ms).toISOString(), cells = [];
  for (let j = 0; j < 9; j++) for (let i = 0; i < 17; i++) {
    const lon = +(-121.24 + i * 0.04).toFixed(6), lat = +(35.16 + j * 0.04).toFixed(6), uMs = 0.15 + i * 0.03, vMs = 0.12 - j * 0.02;
    cells.push({lat, lon, uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * 1.943844492, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  const wcofs = {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: iso(now - 600_000),
    issuedAt: iso(now - three), sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
    attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.', frames: [0, 1, 2, 3].map(k => ({validAt: iso(first + k * three), cells}))};
  return {schemaVersion: 1, countyId: 'slo', generatedAt: iso(now - 300_000), currents: [wcofs], cloud: null, sources: []};
}

export default async function setup(context, {root, now: nowDate, here}) {
  const packet = regionalData(root);
  const now = nowDate.getTime(), stamp = nowDate.toISOString();
  const tiny = readFileSync(resolve(here, 'tests/fixtures/basemap/tiny.pmtiles'));
  const offline = route => route.fulfill({status: 503, json: {error: 'Offline showcase'}});
  await context.route('https://imagery.nationalmap.gov/**', route => route.fulfill({body: PIXEL, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}}));
  await context.route(url => url.origin + url.pathname === MPA_SERVICE, async route => {
    const data = packet(new URL(route.request().frame().url()).searchParams.get('region'));
    if (data) await route.fulfill({json: data.mpas}); else await route.abort('blockedbyclient');
  });
  const coops = min => ({t: new Date(now - min * 60_000).toISOString().slice(0, 16).replace('T', ' '), v: min > 60 ? '2.10' : '3.04'});
  await context.route('https://api.tidesandcurrents.noaa.gov/**', route => route.fulfill({json: {metadata: {id: '9412110', name: 'Port San Luis'}, data: [coops(114), coops(6)]}}));
  // Everything the local Worker would fetch upstream gets a synthetic answer or "offline": live data would make the columns differ.
  await context.route('**/feeds/**', route => route.fulfill({status: 404, json: {error: 'No feed in the showcase (offline)'}}));
  await context.route('**/feeds/data/regions/*/latest.json', route => route.fulfill({json: dailyFeed(new URL(route.request().url()).pathname.split('/').at(-2), now)}));
  await context.route('**/feeds/conditions/regions/*/latest.json', route => route.fulfill({json: conditionsFeed(new URL(route.request().url()).pathname.split('/').at(-2), now)}));
  await context.route('**/feeds/tiles/basemap/manifest.json', route => route.fulfill({json: {schema_version: 1, key: BASEMAP}}));
  await context.route(`**/feeds/${BASEMAP}`, route => {
    const range = /bytes=(\d+)-(\d+)/.exec(route.request().headers().range ?? '');
    if (!range) return route.fulfill({body: tiny, headers: {'Accept-Ranges': 'bytes'}});
    const start = Number(range[1]), end = Math.min(Number(range[2]), tiny.length - 1);
    return route.fulfill({status: 206, body: tiny.subarray(start, end + 1),
      headers: {'Content-Range': `bytes ${start}-${end}/${tiny.length}`, 'Accept-Ranges': 'bytes', 'Content-Type': 'application/octet-stream'}});
  });
  await context.route(/\/(?:api\/coast|coast-data)\//, offline);
  await context.route('**/api/coast/ocean', route => route.fulfill({json: oceanPacket(now)}));
  await context.route('**/api/forecast?*', offline);
  await context.route('**/api/om/**', route => route.fulfill({json: forecastFixture(new URL(route.request().url()), now)}));
  await context.route('**/api/daily?*', async route => {
    const url = new URL(route.request().url());
    const part = url.searchParams.get('part');
    const data = packet(url.searchParams.get('region'));
    if ((part !== 'mpa-boundaries' && part !== 'additional-closures') || !data) return offline(route);
    const source = part === 'mpa-boundaries' ? {geojson: data.mpas} : data.closures ? {sha256: data.closures.source_sha256} : null;
    await route.fulfill({json: {schema_version: 1, region_id: data.region.id, part, generated_at: stamp, catch_probability: null, bite_score: null,
      sources: source ? {[part]: {status: 'ok', data_retrieved_at: stamp, data: source}} : {}}});
  });
  if (process.env.SHOWCASE_LOG_REQUESTS) context.on('request', request => console.log(`  request ${request.method()} ${request.url().slice(0, 160)}`));
}
