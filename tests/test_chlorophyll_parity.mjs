import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import test from 'node:test';
import {FILES, themes} from '../scripts/check_contrast.mjs';
import {CHLOROPHYLL_SCALE, chlorophyllOverlay, chlorophyllStatus} from '../web/map/chlorophyll.ts';
import {regionalChlorophyll} from '../web/map/habitat-feed.ts';
import {layerEntry} from '../web/map/layers.ts';
import {NEARSHORE_STYLE} from '../web/map/nearshore-style.gen.ts';
import {readPalette} from '../web/map/palette.ts';

// Use the same expression evaluator as the locked MapLibre package, without starting a map.
const require = createRequire(import.meta.url);
const {Color, createPropertyExpression, latest} = createRequire(require.resolve('maplibre-gl/package.json'))('@maplibre/maplibre-gl-style-spec');

// scripts/build_chlorophyll_layer.py:48–49,54–69,152–157 (LogNorm, turbo table, alpha).
const STUDY = {ends: [0.05, 15], ramp: 'turbo', stopCount: 33, endpointColors: ['#30123b', '#7a0403'], peakAlpha: 0.85};
const BASE = {
  scale: [0.01, 0.1, 1, 10, 100],
  logStops: [-2, -1, 0, 1, 2],
  tokens: ['depth-0', 'blue', 'mint', 'amber', 'coral'],
  kitZoomPairs: [[8, 0.75], [11, 0.55], [13, 0.35], [15, 0.20]],
  mapLibreZoomPairs: [[7, 0.75], [10, 0.55], [12, 0.35], [14, 0.20]],
  colors: {
    dark: ['#7fd9c8', '#73bfff', '#69e0bc', '#eabd76', '#ff9c86'],
    light: ['#7fd9c8', '#0b5ea8', '#087354', '#8a5a00', '#b8402a'],
  },
};
const DEVIATES_FROM_STUDY = {
  logEndDelta: [-0.699, 0.824], // production minus study, in decades
  stopCountDelta: -28,
  usesStudyRamp: false,
  matchesStudyEndpoints: {dark: [false, false], light: [false, false]},
  peakAlphaDelta: -0.10,
};

const SAMPLE = '2026-10-20T12:00:00.000Z';
const NOW = new Date('2026-10-21T12:00:00Z');
const OBSERVATION = {product: 'Synthetic OCI', sampleAt: SAMPLE, maxAgeMs: 345600000, resolution: [0.25, 0.25], cells: [{lat: 35, lon: -121.25, value: 0.001}]};
const paint = (palette, observation = OBSERVATION) => chlorophyllOverlay(observation, palette).layers[0].paint;
const endsOf = array => [array[0], array.at(-1)];
const colorsOf = expression => expression.slice(3).filter((_, i) => i % 2 === 1);

function themePalettes() {
  const css = readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8');
  const numeric = Object.fromEntries([...css.matchAll(/--([a-z0-9-]+):\s*(\d*\.?\d+)\s*;/g)].map(([, key, value]) => [key, value]));
  return Object.fromEntries(Object.entries(themes(css, FILES['web/tokens.css'])).map(([theme, colors]) =>
    [theme, readPalette(name => colors[name] ?? numeric[name] ?? '')]));
}

// Guard against unreviewed changes to the range, ramp or zoom fade, including a partial switch to the study.
test('chlorophyll-4-parity: production paint and its known deviation from the study', () => {
  const pinnedPaint = paint(readPalette(name => name));
  const ramp = pinnedPaint['fill-color'];
  assert.deepEqual(CHLOROPHYLL_SCALE, BASE.scale);
  assert.deepEqual(ramp, ['interpolate', ['linear'], ['log10', ['get', 'value']],
    ...BASE.logStops.flatMap((position, i) => [position, BASE.tokens[i]])]);
  assert.deepEqual(NEARSHORE_STYLE.overlays.field_opacity_by_zoom, BASE.kitZoomPairs);
  const opacity = pinnedPaint['fill-opacity'];
  assert.deepEqual(opacity, ['interpolate', ['linear'], ['zoom'], ...BASE.mapLibreZoomPairs.flat()]);

  const colors = Object.fromEntries(Object.entries(themePalettes()).map(([theme, palette]) =>
    [theme, colorsOf(paint(palette)['fill-color'])]));
  assert.deepEqual(colors, BASE.colors);
  const tokens = colorsOf(ramp);
  assert.deepEqual({
    logEndDelta: endsOf(CHLOROPHYLL_SCALE).map((value, i) => +Math.log10(value / STUDY.ends[i]).toFixed(3)),
    stopCountDelta: tokens.length - STUDY.stopCount,
    usesStudyRamp: tokens.every(token => token.split('-').includes(STUDY.ramp)),
    matchesStudyEndpoints: Object.fromEntries(Object.entries(colors).map(([theme, values]) =>
      [theme, endsOf(values).map((value, i) => value === STUDY.endpointColors[i])])),
    peakAlphaDelta: +(Math.max(...colorsOf(opacity)) - STUDY.peakAlpha).toFixed(2),
  }, DEVIATES_FROM_STUDY);
});

// The wire format has no land flag: a masked land retrieval can be null or omitted.
// Exercise explicit null (land), an omitted grid position (missing), and an explicit numeric zero separately.
test('chlorophyll gaps produce no geometry at the feed-to-overlay boundary', async () => {
  const id = 'chlorophyll-observation', region = 'test-coast';
  const base = `https://example.test/feeds/conditions/regions/${region}/`;
  const time = Date.parse(SAMPLE) / 1000;
  const fields = ['latitude', 'longitude', 'chlorophyll_mg_m3'];
  const bounds = [-121.5, 34.75, -119.75, 35.25];
  const resolution_degrees = OBSERVATION.resolution;
  const cells = [[35, -121.25, 0.001], [35, -121, 0], /* missing at -120.75 */ [35, -120.5, null], [35, -120.25, 500], [35, -120, 100]];
  const bytes = Buffer.from(JSON.stringify({schema_version: 1, region_id: region, layer_id: id, fields, bounds, resolution_degrees, frames: [{time, cells}]}));
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  const path = `habitat-tiles/${id}--243-70-${sha256.slice(0, 16)}.json`;
  const layer = {id, kind: 'observation', fields, resolution_degrees, frames: [{time, valid_cells: 2}],
    sample_at: SAMPLE, status: 'ok', max_age_hours: 96, native_stride: 1, tiles: [{path, bounds, sha256, bytes: bytes.length}]};
  const manifest = {schema_version: 1, region_id: region, layers: {[id]: layer}, sources: {[id]: {name: OBSERVATION.product}}};
  const fetchFn = async url => url === base + 'habitat-dynamics.json' ? Response.json(manifest)
    : url === base + path ? new Response(bytes) : new Response('', {status: 404});
  const feed = await regionalChlorophyll(region, {fetchFn, now: NOW, page: 'https://example.test/map'});
  assert.equal(feed.state, 'ready', 'the populated controls must survive the feed checks');
  const {features} = chlorophyllOverlay(feed.observation, readPalette(name => name)).sources.chlorophyll.data;
  assert.deepEqual(features.map(f => f.properties.value), [0.001, 100], 'wire values of zero and 500 are rejected');
  for (const [gap, lon] of [['zero', -121], ['missing', -120.75], ['land', -120.5]]) {
    assert.ok(features.every(f => {
      const longitudes = f.geometry.coordinates[0].map(([x]) => x);
      return lon < Math.min(...longitudes) || lon > Math.max(...longitudes);
    }), `${gap} position must not be painted`);
  }
});

// Range comparisons at the paint boundary, not a claim that 500 passes the feed's physical-value guard.
test('chlorophyll paint clamps out-of-range values to the labelled end stops', () => {
  const legend = endsOf(layerEntry('chlorophyll').legend);
  assert.deepEqual(legend, [{label: '≤0.01 mg/m³', swatch: 'depth0'}, {label: '100 mg/m³', swatch: 'coral'}]);
  const [min, max] = endsOf(CHLOROPHYLL_SCALE);
  assert.ok(0.001 < min && 500 > max);
  for (const [theme, palette] of Object.entries(themePalettes())) {
    const expression = createPropertyExpression(paint(palette)['fill-color'], 'fill-color', latest.paint_fill['fill-color']);
    assert.equal(expression.result, 'success', expression.result === 'error' ? expression.value.map(e => e.message).join('; ') : undefined);
    for (const [value, {swatch}] of [[0.001, legend[0]], [500, legend[1]]]) {
      const color = expression.value.evaluateWithoutErrorHandling({zoom: 7}, {properties: {value}});
      assert.deepEqual(color, Color.parse(palette[swatch]), `${theme}: ${value} mg/m³`);
    }
  }
});

// Captured with these fixtures on main 2aaa85a6. Compare JSON bytes, not just the note or parsed fields.
test('chlorophyll status preserves fresh age, stale withholding and feed-error bytes', () => {
  const ready = {state: 'ready', observation: OBSERVATION};
  const basis = 'NOAA NPP/NOAA-20 merged OCI surface chlorophyll proxy on its native 0.0375° grid, labelled with its sample date and withheld at the manifest age limit; cloud gaps stay empty. Not bait or fish.';
  const cases = [
    ['fresh', ready, NOW,
      '{"drawn":{"product":"Synthetic OCI","sampleAt":"2026-10-20T12:00:00.000Z","maxAgeMs":345600000,"resolution":[0.25,0.25],"cells":[{"lat":35,"lon":-121.25,"value":0.001}]},' +
      '"note":"sample 2026-10-20T12:00:00.000Z · 24.0 h old","copy":{"note":[{"id":"map.status.chlorophyll.sample","vars":{"sample":"2026-10-20T12:00:00.000Z","age":{"num":24,"digits":1}}}]},' +
      '"basis":"Synthetic OCI, native 0.25° × 0.25° grid; sample 2026-10-20T12:00:00.000Z (24.0 h old). Withheld at 96 h. Surface chlorophyll proxy, not bait or fish. Cloud gaps stay empty; no interpolation."}'],
    ['stale at 96 h', ready, new Date('2026-10-24T12:00:00Z'),
      `{"drawn":null,"basis":"${basis}","note":"withheld · last sample 2026-10-20T12:00:00.000Z","copy":{"note":[{"id":"map.status.chlorophyll.withheld","vars":{"sample":"2026-10-20T12:00:00.000Z"}}]}}`],
    ['feed error', {state: 'error'}, NOW,
      `{"drawn":null,"basis":"${basis}","note":"unavailable: feed checks failed","copy":{"note":[{"id":"map.status.chlorophyll.feedFailed"}]}}`],
  ];
  for (const [label, feed, now, expected] of cases) assert.equal(JSON.stringify(chlorophyllStatus(true, feed, now)), expected, label);
});
