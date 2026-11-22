import {readFile, readdir} from 'node:fs/promises';
import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import type {AddressInfo} from 'node:net';
import type {BrowserContext, Page} from '@playwright/test';
import type {Map as Chart} from 'maplibre-gl';

export type Theme = 'dark' | 'light';

declare global {
  interface Window {
    d3Chart: Chart;
    d3DuplicateImages: string[];
  }
}

const client = new URL('../dist/client/', import.meta.url);
const archive = 'tiles/basemap/d3-fixture.pmtiles';
const empty = {type: 'FeatureCollection', features: []};
const types: Record<string, string> = {js: 'text/javascript', css: 'text/css', html: 'text/html', woff2: 'font/woff2', pbf: 'application/x-protobuf', svg: 'image/svg+xml'};

/** No Worker or proxy: only built code and static presentation assets can leave this server. */
export async function serveThemeApp() {
  const shell = (await readdir(client)).find(name => /^app\.[a-f0-9]+\.html$/.test(name));
  if (!shell) throw new Error('Run pnpm build first');
  const server = createServer(async (req, res) => {
    const path = new URL(req.url!, 'http://127.0.0.1').pathname;
    const file = path === '/map' ? shell : path.slice(1);
    try {
      if (path !== '/map' && !/^\/(?:assets|fonts|glyphs)\/[\w%./ -]+$/.test(path)) throw new Error('not a static asset');
      const url = new URL(file, client);
      if (!url.href.startsWith(client.href)) throw new Error('not a client path');
      const body = await readFile(url);
      res.writeHead(200, {'Content-Type': types[file.split('.').at(-1)!] ?? 'application/octet-stream'}).end(body);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  return {origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}`, close: () => server.close()};
}

export const FIRST = 'morro-bay';
export const NEXT = 'cambria-san-simeon';
const at = [-120.88, 35.38];
const line = {type: 'FeatureCollection', features: [{type: 'Feature', properties: {}, geometry: {type: 'LineString', coordinates: [[-120.89, 35.36], [-120.89, 35.40]]}}]};
const ring = [[-120.9, 35.37], [-120.88, 35.37], [-120.88, 35.39], [-120.9, 35.39], [-120.9, 35.37]];
const HOUR = 3600_000;
export const NOW = Date.parse('2030-05-10T18:15:00Z');
const OBSERVED = new Date(NOW - HOUR / 2).toISOString();
const hash = (bytes: Buffer | string) => createHash('sha256').update(bytes).digest('hex');
function ocean(region: string) {
  const grid = [-120.92, -120.90, -120.88, -120.86].flatMap((lon, x) => [35.34, 35.36, 35.38, 35.40].map((lat, y) => [lat, lon, x, y] as const));
  const defs = [
    ['sst-analysis', 'analysis', ['temperature_c', 'analysis_error_c', 'temperature_gradient_c_per_km', 'thermal_contrast_supported'], (x: number, y: number) => [12 + x + y, 0.1, 0.4, 1]],
    ['chlorophyll-observation', 'observation', ['chlorophyll_mg_m3'], (x: number) => [0.5 + x]],
    ['wcofs-surface-forecast', 'forecast', ['u_mps', 'v_mps'], (x: number) => [0.2 + x / 10, 0.3]],
  ] as const;
  const tiles = new Map<string, string>();
  const layers = Object.fromEntries(defs.map(([id, kind, values, sample]) => {
    const time = kind === 'forecast' ? Math.floor(NOW / HOUR) * 3600 : Date.parse(OBSERVED) / 1000;
    const fields = ['latitude', 'longitude', ...values], bounds = [-120.94, 35.32, -120.84, 35.42], resolution_degrees = [0.02, 0.02];
    const cells = grid.map(([lat, lon, x, y]) => [lat, lon, ...sample(x, y)]);
    const frames = [{time, valid_cells: cells.length}];
    const body = JSON.stringify({schema_version: 1, region_id: region, layer_id: id, bounds, fields, resolution_degrees, frames: [{time, cells}]});
    const sha256 = hash(body), path = `habitat-tiles/${id}-${sha256.slice(0, 16)}.json`;
    tiles.set(path, body);
    return [id, {id, kind, fields, resolution_degrees, status: 'ok', max_age_hours: 24, issued_at: OBSERVED, sample_at: OBSERVED, surface_only: true,
      frames, tiles: [{path, sha256, bytes: Buffer.byteLength(body), bounds}]}];
  }));
  const sources = Object.fromEntries(defs.map(([id]) => [id, {name: `Synthetic ${id}`, data_retrieved_at: OBSERVED}]));
  return {manifest: {schema_version: 1, region_id: region, layers, sources}, tiles};
}
function forecast(region: string | null) {
  const issued = Math.floor(NOW / HOUR) * 3600 - 6 * 3600;
  const time = Array.from({length: 24}, (_, n) => issued + n * 3600);
  const points = [-121.1, -120.9, -120.7].flatMap((lon, x) => [35.1, 35.3, 35.5].map((lat, y) => [`grid-${x}-${y}`, lat, lon]));
  const model = (variables: Record<string, [number, string]>) => ({meta: {last_run_initialisation_time: issued, data_end_time: time.at(-1)},
    data: points.map((_, i) => ({utc_offset_seconds: 0,
      hourly_units: {time: 'unixtime', ...Object.fromEntries(Object.entries(variables).map(([name, [, unit]]) => [name, unit]))},
      hourly: {time, ...Object.fromEntries(Object.entries(variables).map(([name, [value]]) => [name, time.map(() => value + i / 4)]))}}))});
  return {region_id: region, requested_points: points, retrieved: NOW - 600_000, models: {
    ncep_gfswave016: model({swell_wave_height: [4, 'ft'], swell_wave_period: [12, 's'], swell_wave_direction: [280, '°']}),
    gfs_global: model({wind_speed_10m: [10, 'kn'], wind_direction_10m: [280, '°'], wind_gusts_10m: [15, 'kn']}),
  }};
}
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const bounds = [-121, 35.2, -120.7, 35.6];
const genericRegion = (id: string) => ({schema_version: 1, id, name: `Synthetic ${id}`, status: 'active', timezone: 'America/Los_Angeles', jurisdiction_id: 'california-fixture',
  bounds, map: {center: [at[1], at[0]], zoom: 12, local_areas: id === FIRST ? [{id: 'estero-bay', bounds}] : []},
  stations: {tide: '9412110'},
  chart_files: ['shoreline.geojson', 'depth-contours.geojson', 'depth-contours-overview.geojson'],
  basemap: {default: 'night'}});

export async function bindThemeFixture(context: BrowserContext, origin: string, starting: Theme, stale = false) {
  const requests: string[] = [], seen: string[] = [];
  const oceans = new Map([FIRST, NEXT].map(id => [id, ocean(id)]));
  const tiles = await readFile(new URL('../tests/fixtures/basemap/tiny.pmtiles', import.meta.url));
  const seafloor = await readFile(new URL('../tests/fixtures/seafloor/chart.pmtiles', import.meta.url));
  const ledger = JSON.stringify({region: FIRST, reaches: [
    {id: `${FIRST}-fx1`, region: FIRST, status: 'habitat-screened'}, {id: `${FIRST}-fx2`, region: FIRST, status: 'habitat-held-for-screen'},
  ]});
  let regionHold: Promise<void> | undefined, release: (() => void) | undefined;
  let nearshore = false;
  await context.addInitScript(() => {
    // Do not let a delayed, unrelated page telemetry flush pollute the
    // all-request oracle; map-data requests remain fully observed.
    Object.defineProperty(navigator, 'doNotTrack', {value: '1'});
    localStorage.setItem('skippercast-first-run-v1', 'done');
    localStorage.setItem('skippercast-profile-v1', 'boat');
    sessionStorage.setItem('skippercast-flyover-v1', '1');
  });
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname;
    seen.push(path);
    // Count attempted I/O, including fixture hits, off-origin attempts and partial-content transport.
    if (req.headers().range || !/^(?:\/map$|\/(?:assets|fonts|glyphs)\/)/.test(path) || req.resourceType() === 'image') requests.push(path);
    if (url.origin !== origin) {
      if (req.resourceType() === 'image' || url.hostname === 'nowcoast.noaa.gov' || url.searchParams.get('request') === 'GetMap') {
        return route.fulfill({body: pixel, contentType: 'image/png', headers: {'Access-Control-Allow-Origin': '*'}});
      }
      return route.abort('blockedbyclient');
    }
    // Observe the instance created by the built app without substituting a map or an overlay.
    // Import the original wrapper under a distinct URL so this shim does not recursively intercept itself.
    if (/^\/assets\/maplibre\.[\da-f]+\.js$/.test(path) && !url.search) {
      const original = await readFile(new URL(path.slice(1), client), 'utf8');
      if (/export\{[^}]* as lib[,}]/.test(original)) {
        return route.fulfill({contentType: 'text/javascript', body: `
          import {lib} from ${JSON.stringify(`${path}?original`)};
          export * from ${JSON.stringify(`${path}?original`)};
          const proto = lib.Map.prototype;
          const addControl = proto.addControl, addImage = proto.addImage, setPaint = proto.setPaintProperty;
          window.d3DuplicateImages = [];
          proto.addControl = function (...args) {
            if (this.getContainer().classList.contains('app-chart')) window.d3Chart = this;
            return addControl.apply(this, args);
          };
          proto.addImage = function (id, ...args) {
            if (this.hasImage(id)) window.d3DuplicateImages.push(id);
            return addImage.call(this, id, ...args);
          };
          ${stale ? `proto.setPaintProperty = function (id, key, ...args) {
            if (id === this.getStyle().layers.find(layer => layer.type === 'background')?.id && key === 'background-color'
                && (document.documentElement.dataset.theme ?? 'dark') !== ${JSON.stringify(starting)}) return this;
            return setPaint.call(this, id, key, ...args);
          };` : ''}
        `});
      }
    }
    if (path === `/feeds/${archive}` || path === `/feeds/tiles/seafloor/seafloor-${FIRST}.pmtiles`) {
      const bytes = path === `/feeds/${archive}` ? tiles : seafloor;
      const range = /^bytes=(\d+)-(\d+)$/.exec(req.headers().range ?? '');
      if (!range) return route.fulfill({body: bytes});
      const start = Number(range[1]), end = Math.min(Number(range[2]), bytes.length - 1);
      return route.fulfill({status: 206, body: bytes.subarray(start, end + 1), headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`, 'Accept-Ranges': 'bytes'}});
    }
    if (path === '/feeds/tiles/basemap/manifest.json') return route.fulfill({json: {schema_version: 1, key: archive}});
    if (path === `/feeds/tiles/seafloor/manifest-${FIRST}.json`) return route.fulfill({json: {schema_version: 1, region: FIRST, status: 'ready',
      expires_at: new Date(NOW + 86_400_000).toISOString(), archive_sha256: createHash('sha256').update(seafloor).digest('hex'),
      ledger_sha256: createHash('sha256').update(ledger).digest('hex'), source_attribution: ['Fixture Survey Lab'],
      source_use_notice: 'Retain source-specific terms and credits.', planning_notice: 'Planning only. Not a navigation chart. Check current CDFW regulations.'}});
    if (path === `/feeds/tiles/seafloor/regions/${FIRST}/ledger.json`) return route.fulfill({body: ledger, contentType: 'application/json'});
    const region = /^\/regions\/([^/]+)\/region\.json$/.exec(path)?.[1];
    if (region) {
      if (region === NEXT) await regionHold;
      const data = genericRegion(region);
      if (!nearshore) data.map.local_areas = [];
      return route.fulfill({json: data});
    }
    if (path.endsWith('/shoreline.geojson') || path.endsWith('/shoreline-overview.geojson')) return route.fulfill({json: line});
    if (path === `/regions/${FIRST}/shore-habitat.geojson`) {
      const id = 'synthetic-shore-run', url = `${origin}/synthetic-shore-evidence`;
      return route.fulfill({json: {type: 'FeatureCollection', regionId: FIRST, features: [{type: 'Feature', id,
        geometry: {type: 'MultiLineString', coordinates: [line.features[0]!.geometry.coordinates]},
        properties: {id, region: FIRST, areaId: 'fixture', name: 'Synthetic shore run', shoreClass: 'Sandy', substrate: 'sand',
          sourceYear: 2029, sourceUrl: url, attribution: 'Synthetic fixture', accessUrl: url,
          reviewedAt: OBSERVED, reviewExpiresAt: '2030-06-01T00:00:00Z',
          access: [{id: 'synthetic-access', name: 'Synthetic access', coordinates: at, sourceUrl: url, checkedAt: OBSERVED}]}}]}});
    }
    const contourRegion = /^\/regions\/([^/]+)\/depth-contours(?:-overview)?\.geojson$/.exec(path)?.[1];
    if (contourRegion) {
      const source = {source_id: 'synthetic', name: 'Synthetic contour fixture', survey_date: '2030-01-01', vertical_datum: 'synthetic'};
      return route.fulfill({json: {...line, provenance: {region_id: contourRegion, units: 'ft', interval_ft: 30, review_expires: '2030-06-01', sources: [source], sources_omitted: []},
        features: [{...line.features[0], properties: {...source, kind: 'contour', depth_ft: 150}}, {...line.features[0], properties: {...source, kind: 'survey-edge'}}]}});
    }
    if (path === '/api/forecast') return route.fulfill({json: forecast(url.searchParams.get('region'))});
    if (path === '/api/coast/report') {
      const id = 'synthetic-nearshore', sourceUrl = `${origin}/synthetic-nearshore-evidence`;
      return route.fulfill({json: {schemaVersion: 1, countyId: 'slo', generatedAt: OBSERVED,
        forecasts: [], observations: [], tides: [], tideEvents: [], alerts: [], catches: [],
        visibility: {status: 'unknown', feet: null, observedAt: null, sourceUrl: null},
        sources: [{id, label: 'Synthetic nearshore model', url: sourceUrl, kind: 'forecast', outcome: 'ok', fetchedAt: OBSERVED}],
        nearshore: [{id, name: 'Synthetic model site', areaId: 'central', lon: at[0], lat: at[1], sourceId: id,
          issuedAt: OBSERVED, fetchedAt: OBSERVED, url: sourceUrl, kind: 'forecast', availability: 'available', freshness: 'current',
          temporalResolutionMinutes: 60, hours: [-1, 0, 1].map(offset => ({at: new Date((Math.floor(NOW / HOUR) + offset) * HOUR).toISOString(),
            waveFt: 4, periodS: 12, directionDeg: 280, qualityFlag: 0, secondaryFlag: 0}))}]}});
    }
    if (path === '/api/session') return route.fulfill({json: {enabled: true, signedIn: true, is_admin: true}});
    if (path === '/api/fleet/map/filters') return route.fulfill({json: {region: 'CA'}});
    const activity = /^\/api\/fleet\/map\/(events|tracks|heat)$/.exec(path)?.[1];
    if (activity) {
      const geometry = activity === 'events' ? {type: 'Point', coordinates: at} : activity === 'tracks' ? line.features[0]!.geometry : {type: 'Polygon', coordinates: [ring]};
      return route.fulfill({json: {type: 'FeatureCollection', features: [{type: 'Feature', geometry,
        properties: {id: 'theme-test', kind: 'drift-anchor', segment_kind: 'drift-anchor', dwell_min: 10, planning_only: false}}], meta: {next: null, trips: 1}}});
    }
    if (path === '/feeds/conditions/goes-times.json') return route.fulfill({json: {id: 'goes-longwave', kind: 'observation', layer: 'goes_longwave_imagery',
      observedAt: OBSERVED, fetchedAt: OBSERVED, attribution: 'Synthetic cloud frame', availableTimes: [OBSERVED]}});
    const fronts = /^\/feeds\/conditions\/regions\/([^/]+)\/sst-fronts\.json$/.exec(path)?.[1];
    if (fronts) return route.fulfill({json: {schema_version: 1, region_id: fronts, layer_id: 'sst-fronts', product: 'Synthetic SST', max_age_hours: 48,
      observed_at: OBSERVED, fronts: [{id: 'theme-front', observed_at: OBSERVED, strength_c_per_km: 0.8, uncertainty_c: 0.2, band_half_width_km: 1, geometry: line.features[0]!.geometry}]}});
    const oceanPath = /^\/feeds\/conditions\/regions\/([^/]+)\/(.+)$/.exec(path);
    const feed = oceanPath && oceans.get(oceanPath[1]!);
    if (feed) {
      const file = oceanPath![2]!;
      if (file === 'habitat-dynamics.json') return route.fulfill({json: feed.manifest});
      const body = feed.tiles.get(file);
      if (body) return route.fulfill({body, contentType: 'application/json'});
    }
    if (path.endsWith('.geojson')) return route.fulfill({json: empty});
    if (path === '/map' || /^\/(assets|fonts|glyphs)\//.test(path)) return route.continue();
    return route.fulfill({status: 404, json: {error: 'No synthetic fixture'}});
  });
  return {requests, seen, nearshore: (enabled: boolean) => { nearshore = enabled; },
    hold: () => { regionHold = new Promise<void>(resolve => { release = resolve; }); },
    release: () => { release?.(); regionHold = undefined; }};
}

export function snapshot(page: Page) {
  return page.evaluate(() => {
    const map = window.d3Chart, style = map.getStyle();
    const {lng, lat} = map.getCenter();
    return {theme: document.documentElement.dataset.theme ?? 'dark',
      camera: [lng, lat, map.getZoom(), map.getPitch(), map.getBearing(), map.getPadding()],
      layers: style.layers.map(({id, paint}) => ({id, paint: paint ?? {}})),
      images: map.listImages().sort(), duplicates: [...window.d3DuplicateImages],
      sources: Object.keys(style.sources).sort()};
  });
}
