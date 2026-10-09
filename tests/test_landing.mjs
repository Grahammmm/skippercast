// Landing (FE-07, docs/plans/front-end/dev-plan.md): the readout model over
// the live conditions feed and the CO-OPS water level (source, age and stale
// judged at a fixed clock), the feed path, the committed shoreline module
// against its generator, and the components rendered to strings: the hero
// copy, every tile with a source and an age, the fleet line only when given,
// and the layer dots as links into /map?layers=. FE-25: the night map's frame,
// source choice, style and credit, and that it loads only by dynamic import.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {FRAME, projector, shorelineModule, simplify} from '../scripts/build_landing_shoreline.mjs';
import {DEFAULT_PLACE, ageText, buoyReadings, compass, feedPath, feedState, fromHarbor, loadReadout, tideReading, tideURL} from '../web/landing/readings.ts';
import {RAIL_IDS} from '../web/profile.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const NOW = Date.parse('2026-10-07T20:00:00Z');
const ago = min => new Date(NOW - min * 60000).toISOString();
const source = (name, station, units, rows, extra = {}) => ({name, status: 'ok', max_age_hours: 2, data: {station, units, observations: rows}, ...extra});
/** A synthetic conditions feed: wind 20 min old, swell 34 min, water 200 min (stale). */
export const FEED = {
  schema_version: 1, region_id: 'morro-bay', generated_at: ago(12),
  sources: {
    offshore: source('Cape San Martin offshore', '46028', {WDIR: 'degT', WSPD: 'm/s', GST: 'm/s'}, [{time: ago(80), WDIR: 300, WSPD: 3, GST: 4}, {time: ago(20), WDIR: 320, WSPD: 7, GST: 9}]),
    'diablo-spectrum': source('Diablo Canyon swell and wind waves', '46215', {SwH: 'm', SwP: 'sec', SwD: '-'}, [{time: ago(34), SwH: 0.7, SwP: 10.5, SwD: 'WNW'}]),
    diablo: source('Diablo Canyon', '46215', {WTMP: 'degC', WVHT: 'm'}, [{time: ago(200), WTMP: 14.5, WVHT: 1}]),
  },
};
const coops = minutes => minutes.map(([min, v]) => ({t: new Date(NOW - min * 60000).toISOString().slice(0, 16).replace('T', ' '), v, s: '0.01', f: '0,0,0,0', q: 'p'}));
const TIDE = {metadata: {id: '9412110', name: 'Port San Luis'}, data: coops([[114, '2.10'], [60, '2.52'], [6, '3.04']])};

test('buoy readings: units converted, newest row, direction, source with age, stale past the source limit', () => {
  const [wind, swell, water] = buoyReadings(FEED, {}, NOW);
  assert.deepEqual([wind.reading, wind.unit, wind.detail, wind.source, wind.stale], ['14', 'kt', 'NW · gusts 17', 'NDBC 46028 · 20 min', false]);
  assert.deepEqual([swell.reading, swell.unit, swell.detail, swell.source, swell.stale], ['2.3', 'ft', '11 s · WNW', 'NDBC 46215 · 34 min', false]);
  assert.deepEqual([water.reading, water.unit, water.source, water.stale], ['58', '°F', 'NDBC 46215 · 3 h', true]);
  assert.equal(wind.basis, 'Observed wind at the Cape San Martin offshore buoy, out at sea: not a harbor or launch reading. Averaged over 8 minutes, with the peak gust; stale after 2 h.');
  // With the region's positions the basis says how far from the harbor each buoy is.
  const region = JSON.parse(readFileSync(join(ROOT, 'regions/morro-bay/region.json'), 'utf8'));
  const placed = buoyReadings(FEED, region, NOW);
  assert.match(placed[0].basis, /^Observed wind at the Cape San Martin offshore buoy, about 56 nm WNW of Morro Bay harbor, out at sea: not a harbor or launch reading\./);
  assert.match(placed[2].basis, /at the Diablo Canyon buoy, about 10 nm S of Morro Bay harbor;/);
  assert.equal(fromHarbor({harbor: region.harbor}, '46028'), null, 'no buoy position, no distance');
  // A source without its own age limit shows its age and is never called stale for age alone.
  const unlimited = structuredClone(FEED);
  delete unlimited.sources.diablo.max_age_hours;
  const water0 = buoyReadings(unlimited, {}, NOW)[2];
  assert.deepEqual([water0.source, water0.stale], ['NDBC 46215 · 3 h', false]);
  assert.match(water0.basis, /the feed gives no age limit, so only the age is shown\.$/);
  assert.doesNotMatch(water0.basis, /stale after/);
  // A failed fetch at the source turns a fresh-looking row stale; a feed with another schema reads as missing.
  const failed = structuredClone(FEED);
  failed.sources.offshore.status = 'error';
  assert.equal(buoyReadings(failed, {}, NOW)[0].stale, true);
  const none = buoyReadings({schema_version: 2}, {stations: {offshore_buoy: '46028', nearshore_buoy: '46215'}}, NOW);
  assert.deepEqual(none.map(r => [r.reading, r.source, r.stale]), [['No reading', 'NDBC 46028 · unavailable', true], ['No reading', 'NDBC 46215 · unavailable', true], ['No reading', 'NDBC 46215 · unavailable', true]]);
  // A unit the model does not know is never converted as if it were.
  const knots = structuredClone(FEED);
  knots.sources.offshore.data.units.WSPD = 'kt';
  assert.equal(buoyReadings(knots, {}, NOW)[0].reading, 'No reading');
  // A sample from the future (clock skew past five minutes) is stale.
  const future = structuredClone(FEED);
  future.sources.offshore.data.observations = [{time: new Date(NOW + 10 * 60000).toISOString(), WDIR: 1, WSPD: 1, GST: 1}];
  assert.equal(buoyReadings(future, {}, NOW)[0].stale, true);
});

test('tide: latest water level, trend over two hours, NOAA station and age; stale after an hour; missing data says so', () => {
  const tide = tideReading(TIDE, '9412110', 'Port San Luis', NOW);
  assert.deepEqual([tide.reading, tide.unit, tide.detail, tide.source, tide.stale], ['3.0', 'ft', 'rising', 'NOAA 9412110 · 6 min', false]);
  assert.match(tide.basis, /Port San Luis, in feet above mean lower low water, every 6 minutes; stale after 1 h\.$/);
  assert.match(tideReading(TIDE, '9412110', 'Port San Luis', NOW, 'Reference water level; not a Morro Bay bar-current prediction.').basis,
    /stale after 1 h\. Reference water level; not a Morro Bay bar-current prediction\.$/, 'the region\'s tide note reaches the basis');
  assert.equal(tideReading(TIDE, '9412110', 'Port San Luis', NOW + 2 * 3600000).stale, true);
  assert.equal(tideReading({data: coops([[90, '3.0'], [6, '2.4']])}, '9412110', 'x', NOW).detail, 'falling');
  assert.equal(tideReading({data: coops([[6, '2.4']])}, '9412110', 'x', NOW).detail, undefined, 'one point gives no trend');
  const missing = tideReading({error: {message: 'No data was found.'}}, '9412110', 'x', NOW);
  assert.deepEqual([missing.reading, missing.source, missing.stale], ['No reading', 'NOAA 9412110 · unavailable', true]);
  assert.match(tideURL('9412110'), /^https:\/\/api\.tidesandcurrents\.noaa\.gov\/api\/prod\/datagetter\?product=water_level&application=SkipperCast&station=9412110&range=2&/);
});

test('the feed clock, ages, compass points and the feed path', () => {
  assert.deepEqual(feedState(FEED, NOW), {age: '12 min', stale: false});
  assert.deepEqual(feedState(FEED, NOW + 2 * 3600000), {age: '2 h', stale: true});
  assert.deepEqual(feedState(null, NOW), {age: null, stale: true});
  assert.deepEqual([ageText(59 * 60000), ageText(3 * 3600000), ageText(50 * 3600000), ageText(-5)], ['59 min', '3 h', '2 d', '0 min']);
  assert.deepEqual([compass(0), compass(320), compass(283), compass(359), compass(-90)], ['N', 'NW', 'WNW', 'N', 'W']);
  const region = JSON.parse(readFileSync(join(ROOT, 'regions/morro-bay/region.json'), 'utf8'));
  assert.equal(feedPath(region.conditions_feed), '/feeds/conditions/regions/morro-bay/latest.json');
  assert.equal(feedPath(undefined, 'x'), '/feeds/conditions/regions/x/latest.json');
});

test('loadReadout reads the region, the feed and the tide; a failure becomes an unavailable tile', async () => {
  const region = JSON.parse(readFileSync(join(ROOT, 'regions/morro-bay/region.json'), 'utf8'));
  const asked = [];
  const reply = body => ({ok: body !== null, status: body === null ? 404 : 200, json: async () => body});
  const fetchFn = async url => {
    asked.push(url);
    if (url === 'regions/morro-bay/region.json') return reply(region);
    if (url.startsWith('/feeds/')) return reply(FEED);
    return reply(null);
  };
  const readout = await loadReadout(fetchFn, 'morro-bay', () => NOW);
  assert.deepEqual(asked, ['regions/morro-bay/region.json', '/feeds/conditions/regions/morro-bay/latest.json', tideURL('9412110')]);
  assert.deepEqual(readout.readings.map(r => r.id), ['wind', 'swell', 'water', 'tide']);
  assert.deepEqual(readout.readings.map(r => r.source), ['NDBC 46028 · 20 min', 'NDBC 46215 · 34 min', 'NDBC 46215 · 3 h', 'NOAA 9412110 · unavailable']);
  assert.match(readout.readings[0].basis, /about 56 nm WNW of Morro Bay harbor, out at sea: not a harbor or launch reading/);
  assert.ok(readout.readings[3].basis.endsWith(region.stations.tide_note), 'the tide tile carries the region\'s tide note');
  assert.equal(readout.place, region.name, 'the readout names the region it reads (#422)');
  assert.equal(DEFAULT_PLACE, region.name, 'the name shown while region.json loads is the region\'s own');
  const offline = await loadReadout(async () => { throw Error('offline'); }, 'morro-bay', () => NOW);
  assert.ok(offline.readings.every(r => r.stale && /unavailable$/.test(r.source)));
  assert.equal(offline.place, DEFAULT_PLACE);
  assert.deepEqual(offline.feed, {age: null, stale: true});
});

test('the landing reads the stored profile under the store\'s key', async () => {
  const {STORAGE_KEYS} = await load();
  const main = readFileSync(join(ROOT, 'web/landing/main.tsx'), 'utf8');
  assert.equal(main.match(/PROFILE_KEY = '([^']+)'/)?.[1], STORAGE_KEYS.profile);
});

test('the shoreline module is generated from the region\'s CUSP import, framed on the region, with its attribution', () => {
  const geojson = JSON.parse(readFileSync(join(ROOT, 'catalog/shoreline/morro-bay.geojson'), 'utf8'));
  assert.equal(readFileSync(join(ROOT, 'web/landing/shoreline-path.ts'), 'utf8'), shorelineModule(geojson), 'run node scripts/build_landing_shoreline.mjs');
  assert.equal(geojson.provenance.license, 'public-domain');
  assert.match(geojson.provenance.source, /^NOAA National Geodetic Survey, Continually Updated Shoreline Product \(CUSP\)$/);
  assert.ok(geojson.features.every(f => /^\d{8}$/.test(f.properties.SRC_DATE)), 'a source date on every feature');
  const {height, project} = projector();
  assert.deepEqual(project([FRAME[0], FRAME[3]]), [0, 0]);
  const [x, y] = project([FRAME[2], FRAME[1]]);
  assert.ok(Math.abs(x - 1000) < 1e-9 && Math.abs(y - height) <= 0.5, 'the frame spans the viewBox');
  const harbor = project([-120.868, 35.3667]);
  assert.ok(harbor[0] > 700 && harbor[0] < 1000 && harbor[1] > 0 && harbor[1] < height, 'Morro Bay sits on the right, inside the frame');
  assert.deepEqual(simplify([[0, 0], [1, 0.1], [2, 0], [3, 5]], 0.5), [[0, 0], [2, 0], [3, 5]]);
});

let components;
async function load() {
  if (components) return components;
  const out = join(await mkdtemp(join(tmpdir(), 'landing-')), 'landing.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LandingHead, LandingApp, NAV} from './web/landing/Landing.tsx';
      export {Shoreline, ShorelineCredit} from './web/landing/Shoreline.tsx';
      export {SHORELINE} from './web/landing/shoreline-path.ts';
      export {Readout} from './web/landing/Readout.tsx';
      export {LayerDots, layerURL, DOT_LABELS} from './web/landing/LayerDots.tsx';
      export {RAIL_ENTRIES} from './web/app/rail.ts';
      export {STORAGE_KEYS} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  components = await import(pathToFileURL(out).href);
  return components;
}

test('the landing page holds the hero and footer statically; its parts render the nav, pills, port question and readout; no map engine', async () => {
  const {LandingHead, LandingApp, Shoreline, ShorelineCredit, SHORELINE, NAV, render, h} = await load();
  const page = readFileSync(join(ROOT, 'dist/landing.html'), 'utf8');
  assert.match(page, /<h1 class="landing-title">Know the water before you leave the dock\.<\/h1>/);
  assert.match(page, /<p class="landing-lede">Wind, swell, water temperature and tide from fixed Central Coast buoys and a tide gauge, each with its station and age, beside the seafloor and currents on one map\.<\/p>/);
  assert.doesNotMatch(page, /your launch/, 'the readings are fixed stations, not the visitor\'s launch');
  assert.equal((page.match(/<footer/g) || []).length, 1);
  assert.match(page, /<p>Forecasts, observations and habitat carry separate clocks; check the rules before you fish\.<\/p>/);
  assert.doesNotMatch(page, /CUSP|surveyed/, 'the credit comes from the generated module, not the page');
  assert.equal(render(h(ShorelineCredit, {})), `<p class="landing-credit">Shoreline: ${SHORELINE.attribution}, surveyed ${SHORELINE.sourceYears[0]}–${SHORELINE.sourceYears.at(-1)}.</p>`);
  for (const id of ['landing-night', 'landing-shore', 'landing-head', 'landing-app', 'landing-dots', 'landing-credit']) assert.match(page, new RegExp(`<div id="${id}" class="landing-host">`));
  assert.ok(page.indexOf('id="landing-night"') < page.indexOf('id="landing-shore"'), 'the shoreline paints over the night map until it has drawn');
  assert.deepEqual([...page.matchAll(/<script\b[^>]*>/g)].map(m => m[0]), ['<script type="module" src="../web/landing/main.tsx">'], 'one module, no inline script');
  const head = render(h(LandingHead, {href: 'https://s.test/?ui=v2'}));
  assert.match(head, /href="\/\?ui=v2">SkipperCast</);
  assert.match(head, /href="\/map\?region=morro-bay&amp;view=fleet&amp;ui=v2">Fleet</);
  assert.match(head, /href="\/report">Reports</);
  assert.match(head, /href="\/sources">How it’s built</); // served by shellFor (#475, tests/test_worker_routes.mjs)
  assert.match(head, /href="\/\?ui=v1#account">Sign in</);
  assert.equal(NAV.length, 3);
  const app = render(h(LandingApp, {href: 'https://s.test/?ui=v2', navigate: () => {}, load: false}));
  assert.deepEqual([...app.matchAll(/data-profile="([a-z]+)"[^>]*>.*?<\/svg>([A-Za-z]+)<\/button>/g)].map(m => [m[1], m[2]]), [['boat', 'Boat'], ['shore', 'Shore'], ['spear', 'Spear']]);
  assert.doesNotMatch(app, /aria-pressed="true"/, 'no pill pressed without a stored profile');
  assert.match(app, /Where are you launching\?/);
  assert.ok(app.indexOf('landing-readout') < app.indexOf('landing-pills'), 'the readings come before any choice (D4)');
  assert.match(app, /aria-busy="true"/, 'the readout waits for its readings');
  assert.match(app, /href="\/map\?region=morro-bay&amp;view=conditions&amp;ui=v2">Hour by hour on the map</);
  const pressed = render(h(LandingApp, {href: 'https://s.test/', initialProfile: 'shore', navigate: () => {}, load: false}));
  assert.match(pressed, /aria-pressed="true"[^>]*data-profile="shore"|data-profile="shore"[^>]*aria-pressed="true"/);
  assert.match(render(h(Shoreline, {})), /<svg class="landing-shore" viewBox="0 0 1000 \d+" preserveAspectRatio="xMaxYMid slice" aria-hidden="true"/);
  for (const file of ['Landing', 'Readout', 'LayerDots', 'ProfilePills', 'Shoreline', 'main'])
    assert.doesNotMatch(readFileSync(join(ROOT, `web/landing/${file}.tsx`), 'utf8'), /from '(?:[^']*maplibre[^']*|three|[^']*packages\/coast[^']*|\.\.\/state\.ts|\.\.\/app\/[^']*)'/, `${file}.tsx loads no map engine and none of the app's store`);
});

test('every readout tile shows a source and an age, a stale one says stale, and the fleet line shows only when given', async () => {
  const {Readout, render, h} = await load();
  const readout = {readings: [...buoyReadings(FEED, {}, NOW), tideReading(TIDE, '9412110', 'Port San Luis', NOW)], feed: feedState(FEED, NOW)};
  const html = render(h(Readout, {data: readout}));
  const tiles = [...html.matchAll(/<li data-reading="([a-z]+)">(.*?)<\/li>/gs)];
  assert.deepEqual(tiles.map(m => m[1]), ['wind', 'swell', 'water', 'tide']);
  for (const [, id, tile] of tiles) {
    assert.match(tile, /<span class="ui-mono">(NDBC|NOAA) \d+ · \d+ (min|h)<\/span>/, `${id} shows source and age`);
    assert.match(tile, /<details class="ui-popover"/, `${id} has its basis in a disclosure`);
  }
  assert.deepEqual(tiles.filter(m => /data-state="stale"/.test(m[2])).map(m => m[1]), ['water']);
  assert.match(tiles[2][2], /<span class="ui-tile-stale ui-eyebrow">stale<\/span>/);
  assert.match(html, /<p class="landing-fresh ui-eyebrow" data-state="ok">Buoy feed updated 12 min ago<\/p>/);
  assert.match(html, /aria-labelledby="landing-readout-title"[^>]*><h2 id="landing-readout-title" class="landing-readout-title ui-eyebrow">Latest readings · Morro Bay &amp; Avila area<\/h2>/, 'the strip names the place, not the visitor\'s launch (#422)');
  assert.match(render(h(Readout, {data: {...readout, place: 'Cambria'}})), />Latest readings · Cambria area</);
  assert.doesNotMatch(html, /landing-more/, 'no link without an address');
  assert.match(render(h(Readout, {data: readout, conditions: '/map?region=morro-bay&view=conditions'})), /<a class="landing-more" href="\/map\?region=morro-bay&amp;view=conditions">Hour by hour on the map<\/a>/);
  assert.doesNotMatch(html, /data-fleet/);
  assert.match(render(h(Readout, {data: readout, fleet: 'Fleet line text'})), /<p class="landing-fleet" data-fleet="true">Fleet line text<\/p>/);
  const late = render(h(Readout, {data: {...readout, feed: {age: '3 h', stale: true}}}));
  assert.match(late, /data-state="stale">Buoy feed stale, updated 3 h ago</);
});

test('layer dots link each rail entry into the app with that layer, keeping the ui switch', async () => {
  const {LayerDots, layerURL, DOT_LABELS, RAIL_ENTRIES, render, h} = await load();
  assert.deepEqual(DOT_LABELS, Object.fromEntries(RAIL_ENTRIES.map(e => [e.id, e.label])), 'the dots carry the rail labels');
  const html = render(h(LayerDots, {href: 'https://s.test/?ui=v2&utm=x', region: 'morro-bay'}));
  assert.deepEqual([...html.matchAll(/data-layer="([a-z-]+)"/g)].map(m => m[1]), [...RAIL_IDS]);
  assert.match(html, /href="https:\/\/s\.test\/map\?region=morro-bay&amp;layers=seafloor&amp;ui=v2" data-layer="seafloor">.*?<span class="landing-dot-name">Seafloor<\/span>/s);
  assert.equal(layerURL('https://s.test/#x', 'morro-bay', 'swell'), 'https://s.test/map?region=morro-bay&layers=swell');
});

let night;
/** NightMap.tsx and what it shares with the app, bundled for Node; MapLibre and the terrain renderer stay out (both load by dynamic import only). */
async function loadNight() {
  if (night) return night;
  const out = join(await mkdtemp(join(tmpdir(), 'night-')), 'night.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {NIGHT_SOURCES, NightCredit, nightCamera, nightCoastline, nightRegion, nightSource, nightState, nightStyle} from './web/landing/NightMap.tsx';
      export {currentsState} from './web/map/currents.ts';
      export {readPalette} from './web/map/palette.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    external: ['*/maplibre.js', '*/terrain.js'],
  });
  night = await import(pathToFileURL(out).href);
  return night;
}

test('the night map frames the region with the harbor right of centre, over the hero\'s open water (FE-25)', async () => {
  const {nightCamera, nightRegion} = await loadNight();
  const region = JSON.parse(readFileSync(join(ROOT, 'regions/morro-bay/region.json'), 'utf8'));
  const asked = [];
  const info = await nightRegion('morro-bay', async url => { asked.push(url); return {ok: true, json: async () => region}; }, 'https://s.test/?ui=v2');
  assert.deepEqual(asked, ['https://s.test/regions/morro-bay/region.json']);
  assert.deepEqual([info.bounds, info.center, info.harbor, info.timezone], [region.bounds, region.map.center, {latitude: region.harbor.latitude, longitude: region.harbor.longitude}, 'America/Los_Angeles']);
  assert.deepEqual(info.localAreas.map(a => a.id), region.map.local_areas.map(a => a.id));
  assert.equal(await nightRegion('morro-bay', async () => ({ok: true, json: async () => ({...region, bounds: [1, 2]})}), 'https://s.test/'), null);
  assert.equal(await nightRegion('morro-bay', async () => ({ok: false, json: async () => region}), 'https://s.test/'), null);
  const [, south, , north] = info.bounds;
  const merc = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  for (const [width, height, at] of [[1440, 900, 0.72], [1024, 768, 0.72], [390, 844, 0.62]]) {
    const c = nightCamera(info, width, height), world = 256 * 2 ** c.zoom;
    assert.ok(Math.abs((width / 2 + (info.harbor.longitude - c.longitude) / 360 * world) / width - at) < 1e-9, `harbor ${at * 100}% across at ${width} px`);
    assert.ok(Math.abs((merc(north) - merc(south)) / (2 * Math.PI) * world / height - 1) < 0.01, `the bounds fill ${height} px top to bottom`);
    assert.equal(c.latitude, (south + north) / 2);
  }
});

test('the night map draws the first listed source with a fresh frame, the night style with the landing glow, and credits both once drawn', async () => {
  const {NIGHT_SOURCES, NightCredit, currentsState, nightSource, nightState, nightStyle, readPalette, render, h} = await loadNight();
  const now = new Date('2026-10-07T12:20:00Z'), cells = [{lat: 35.3, lon: -121, uMs: 0.2, vMs: 0.1, speedKnots: 0.43, towardDeg: 63}];
  const field = (id, kind, extra) => ({id, kind, label: id, fetchedAt: '2026-10-07T12:00:00Z', nativeResolutionKm: kind === 'forecast' ? 4 : 6, sampleStride: 1, surfaceOnly: true, ...extra});
  const forecast = field('wcofs', 'forecast', {issuedAt: '2026-10-07T03:00:00Z', frames: [{validAt: '2026-10-07T12:00:00Z', cells}]});
  const radar = field('hfr-6', 'observation', {frames: [{validAt: '2026-10-07T11:00:00Z', cells}]});
  const staleForecast = {...forecast, issuedAt: '2026-10-05T03:00:00Z'};
  assert.deepEqual(NIGHT_SOURCES, ['wcofs', 'hfr-6', 'hfr-1']);
  assert.equal(nightSource([radar, forecast], now), 'wcofs', 'the forecast first while it is fresh');
  assert.equal(nightSource([radar, staleForecast], now), 'hfr-6', 'observed radar when the forecast cycle is too old');
  assert.equal(nightSource([staleForecast], now), 'wcofs', 'none fresh: the forecast, which then draws nothing and says why');
  assert.equal(nightSource(undefined, now), 'wcofs');

  const palette = readPalette(name => `token(${name})`);
  const style = nightStyle(palette, 'https://s.test/feeds/tiles/basemap/a.pmtiles', 'https://s.test/?ui=v2', 'morro-bay');
  assert.equal(style.name, 'SkipperCast basemap (night)');
  assert.equal(style.glyphs, 'https://s.test/basemap/glyphs/{fontstack}/{range}.pbf');
  assert.equal(style.sources.coastline.data, 'https://s.test/regions/morro-bay/shoreline.geojson');
  assert.deepEqual(style.layers.slice(-2).map(l => [l.id, l.paint['line-color'], l.paint['line-opacity']]), [['coastline-glow', 'token(depth-0)', 0.45], ['coastline', 'token(flow)', 0.9]], 'the coastline last, in the SVG\'s glow');
  const colours = style.layers.flatMap(l => Object.entries(l.paint ?? {}).filter(([k]) => k.endsWith('-color')).map(([, v]) => v));
  assert.ok(colours.length > 5 && colours.every(v => /^token\([a-z0-9-]+\)$/.test(v)), 'every colour is a token');

  try {
    nightState.value = 'loading';
    assert.equal(render(h(NightCredit, {})), '', 'no credit before the map draws');
    nightState.value = 'ready';
    assert.equal(render(h(NightCredit, {})), '<p class="landing-credit" data-credit="basemap">Basemap: © OpenStreetMap contributors, © Protomaps.</p>');
    currentsState.value = {drawn: {}, note: '', reason: '', basis: 'NOAA WCOFS surface forecast, about 4 km, issued 3 h ago; arrows follow the toward-bearing and their motion is illustrative.'};
    assert.match(render(h(NightCredit, {})), /<p class="landing-credit" data-credit="currents">Currents: NOAA WCOFS surface forecast, about 4 km, issued 3 h ago; arrows follow the toward-bearing and their motion is illustrative\.<\/p>$/);
    nightState.value = 'failed';
    assert.equal(render(h(NightCredit, {})), '', 'a failed map credits nothing');
  } finally { nightState.value = 'loading'; }
});

test('MapLibre and the night map load only by dynamic import, after first paint (FE-25, design § 13)', () => {
  const main = readFileSync(join(ROOT, 'web/landing/main.tsx'), 'utf8'), map = readFileSync(join(ROOT, 'web/landing/NightMap.tsx'), 'utf8');
  assert.match(main, /import\('\.\/NightMap\.tsx'\)/);
  assert.doesNotMatch(main, /from '\.\/NightMap/, 'main.tsx never imports the night map statically');
  assert.match(main, /afterFirstPaint\(nightMap\)/);
  assert.match(main, /if \(!webgl2\(\)\) return;/, 'no WebGL2: MapLibre is never fetched and the shoreline stays');
  assert.match(map, /import\('\.\.\/map\/maplibre\.js'\)/);
  assert.doesNotMatch(map.replace(/^import type [^;]+;$/gm, ''), /from '[^']*(?:maplibre|pmtiles|three|coast3d|embed)[^']*'/, 'MapLibre types only; no renderer');
});
