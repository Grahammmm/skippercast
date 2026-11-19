// THEME-ROUTE: the remaining palette-dependent overlays follow a live theme switch in place.
// Every test names the contract it protects and the believable bug that makes it fail (CI-ARTICLE-1).
// The paint oracle (tests/theme-paint-oracle.mjs) is the shared judge for layer paints; no network, no browser.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {signal} from '@preact/signals';
import {createCurrents} from '../web/map/currents.ts';
import {activityOverlay} from '../web/map/fleet.ts';
import {nearshoreThemePaint, ringHitLayer, ringLayer} from '../web/map/nearshore.ts';
import {readPalette} from '../web/map/palette.ts';
import {planningRouteOverlay} from '../web/map/planning-route.ts';
import {sstOverlay} from '../web/map/preview/sst.ts';
import {reachOverlay} from '../web/map/reach.ts';
import {shoreCollections, shoreOverlay} from '../web/map/shore.ts';
import {stationOverlay} from '../web/map/stations.ts';
import {swellOverlay} from '../web/map/swell.ts';
import {appView, current, hour, presentation} from '../web/state.ts';
import {assertThemePaintOracle} from './theme-paint-oracle.mjs';

// Tokens read as `<theme>:<name>`, so each theme has distinct values and a literal colour stands out.
const palette = theme => readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `${theme}:${name}`);
const palettes = {dark: palette('dark'), light: palette('light')};
const empty = {type: 'FeatureCollection', features: []};

const overlays = {
  stations: p => stationOverlay(p),
  reach: p => reachOverlay(p, empty),
  'planning-route': p => planningRouteOverlay(p, empty),
  shore: p => shoreOverlay(p, shoreCollections([])),
  'fleet-activity': p => activityOverlay(p, {heat: empty, tracks: empty, events: empty}),
  'preview-sst': p => sstOverlay({data_time: '2026-11-18T00:00:00Z', max_age_hours: 48, colours: [], cells: empty, breaks: empty}, p),
};

for (const [name, build] of Object.entries(overlays)) {
  test(`${name}: themePaint restores exactly a fresh build's paints, dark -> light -> dark`, () => {
    // Contract: an overlay installed in one theme equals a fresh build after a live switch (MB-21 engine applies the INSTALLED overlay's themePaint).
    // Bug: a palette-dependent paint the provider forgets (stale colour), or one that names a layer/property the builder never made.
    const report = assertThemePaintOracle({build, provider: build(palettes.dark), palettes});
    assert.ok(report.steps.every(s => s.mismatches.length === 0));
    assert.equal(report.addImage, 0, 'no image is registered: these overlays draw no pattern');
  });

  test(`${name}: layer order, layer and source IDs, layout, filters and data are identical in both themes`, () => {
    // Contract: no layer swap on a switch (same IDs, same draw order, same data). Bug: a builder that varies structure by theme, so an in-place paint edit cannot reach it.
    const dark = build(palettes.dark), light = build(palettes.light);
    const structure = o => ({sources: o.sources, layers: o.layers.map(({paint, ...rest}) => rest)});
    assert.deepEqual(structure(dark), structure(light));
    assert.ok(dark.layers.length > 0);
    assert.equal(typeof dark.themePaint, 'function');
    assert.equal(dark.themePatterns, undefined, 'no image to refresh');
  });

  test(`${name}: every theme-dependent colour comes from the palette, none is a literal`, () => {
    // Contract: colours via palette tokens only. Bug: a hex/rgb literal left in a paint, which a switch would leave unchanged.
    const leaves = value => Array.isArray(value) ? value.flatMap(leaves) : typeof value === 'string' ? [value] : [];
    for (const layer of build(palettes.dark).layers) {
      for (const [property, value] of Object.entries(layer.paint ?? {})) {
        if (!property.endsWith('-color')) continue;
        const colours = leaves(value).filter(v => /^(#|rgb|hsl)/i.test(v));
        assert.deepEqual(colours, [], `${layer.id}.${property}`);
      }
    }
  });
}

test('fleet-activity: themePaint reads no feature data, so a switch cannot touch vessel records', () => {
  // Contract: privacy unchanged, admin-only fleet layers keep their data in the sources only. Bug: a themePaint that re-reads or re-publishes the collections.
  const marker = {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'Point', coordinates: [0, 0]}, properties: {key: 'v1'}}]};
  const overlay = activityOverlay(palettes.dark, {heat: empty, tracks: empty, events: marker});
  const edits = overlay.themePaint(palettes.light);
  assert.doesNotMatch(JSON.stringify(edits), /"v1"|coordinates/);
  assert.ok(edits.every(e => typeof e.layer === 'string' && typeof e.property === 'string'));
});

test('sst preview: the break lines follow the theme; the cell colours stay the file\'s own', () => {
  // Contract: the SST ramp is data (carried by the file), only the break halo and under-stroke are palette roles. Bug: re-colouring the ramp on a switch.
  const edits = overlays['preview-sst'](palettes.dark).themePaint(palettes.light);
  const colours = Object.fromEntries(edits.filter(e => e.property === 'line-color').map(e => [e.layer, e.value]));
  assert.deepEqual(colours, {'preview-sst-break-halo': 'light:text', 'preview-sst-break-line': 'light:bg-deep'});
  assert.deepEqual(edits.find(e => e.layer === 'preview-sst-cells' && e.property === 'fill-color').value, ['get', 'colour']);
});

test('nearshore rings: nearshoreThemePaint equals a fresh ring build in both themes', () => {
  // Contract: the rings mount inside Swell's overlay, whose themePaint spreads this in. Bug: ring colours left stale (blue ring on the other theme's water).
  assertThemePaintOracle({build: p => ({layers: [ringHitLayer(p), ringLayer(p)]}), provider: {themePaint: nearshoreThemePaint}, palettes});
});

test('swell overlay mounts the rings\' themePaint: the overlay the engine installs restyles its rings in place', () => {
  // Contract: the overlay swell.ts hands to engine.setOverlay (not just the nearshore helper) carries the ring paints, which the engine applies on a theme switch.
  // Bug: the helper exists but swellOverlay never sets themePaint, so visible rings keep the previous theme's blue stroke.
  const ringIds = [ringHitLayer(palettes.dark), ringLayer(palettes.dark)].map(l => l.id);
  for (const field of [false, true]) {
    const build = p => { const o = swellOverlay(p, {field, rings: true}); return {layers: o.layers.filter(l => ringIds.includes(l.id))}; };
    assert.equal(typeof swellOverlay(palettes.dark, {field, rings: true}).themePaint, 'function', `field=${field}`);
    const report = assertThemePaintOracle({build, provider: swellOverlay(palettes.dark, {field, rings: true}), palettes});
    assert.ok(report.steps.every(s => s.mismatches.length === 0), `field=${field}`);
  }
});

test('theme-invariant inventory: aerial, clouds and the preview chlorophyll, currents and seafloor layers use no palette', () => {
  // Contract: these five draw rasters/images with fixed values, so they need no themePaint. Bug: one of them gaining a palette colour later
  // without a themePaint, which would then keep the paint it was built with after a switch.
  for (const file of ['aerial', 'clouds', 'preview/chlorophyll', 'preview/currents', 'preview/seafloor']) {
    const source = readFileSync(new URL(`../web/map/${file}.ts`, import.meta.url), 'utf8');
    assert.doesNotMatch(source, /palette|themePaint|themePatterns/i, file);
  }
});

// ----- Currents: a canvas, not a map layer. Colours are read from the palette when drawn (no theme observer of its own); the map's idle after a switch redraws them. -----
const NOW = new Date('2026-10-07T12:20:00Z'), WEST = -121.0, NORTH = 35.5, STEP = 0.04, N = 8, PX = 100, SIZE = (N - 1) * PX;
const gridCells = () => {
  const out = [];
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    const uMs = 0.3, vMs = 0.1;
    out.push({lat: +(NORTH - j * STEP).toFixed(6), lon: +(WEST + i * STEP).toFixed(6), uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * 1.943844492, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  return out;
};
const wcofs = {
  id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: '2026-10-07T11:50:00Z',
  issuedAt: '2026-10-07T03:00:00Z', sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
  attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.',
  frames: ['09', '12', '15'].map(h => ({validAt: `2026-10-07T${h}:00:00Z`, cells: gridCells()})),
};
const ocean = {schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-07T11:55:00Z', currents: [wcofs], cloud: null, sources: []};

function currentsHarness({reduced = false} = {}) {
  const canvases = [], requests = [], listeners = {}, fetches = [], loads = [];
  const context = () => {
    const ctx = {strokes: [], fills: [], setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {}, fill() {}, setLineDash() {},
      getImageData: (_x, _y, w, h) => ({data: new Uint8ClampedArray(w * h * 4)})};
    Object.defineProperty(ctx, 'strokeStyle', {set(v) { ctx.strokes.push(v); }});
    Object.defineProperty(ctx, 'fillStyle', {set(v) { ctx.fills.push(v); }});
    return ctx;
  };
  const doc = {hidden: false, addEventListener() {}, removeEventListener() {},
    createElement: () => { const ctx = context(); return {width: 0, height: 0, dataset: {}, setAttribute() {}, remove() {}, getContext: () => ctx, ctx}; }};
  const view = {container: () => ({append: c => canvases.push(c)}), size: () => ({width: SIZE, height: SIZE}),
    project: (lon, lat) => ({x: (lon - WEST) / STEP * PX, y: (NORTH - lat) / STEP * PX}), unproject: (x, y) => ({lon: WEST + x / PX * STEP, lat: NORTH - y / PX * STEP}),
    busy: () => false, land: () => [], on: (type, fn) => { (listeners[type] ??= []).push(fn); return () => {}; }};
  let theme = 'dark';
  const data = {coastOcean: signal({data: ocean}), coastStatus: signal({ocean: 'ready', report: 'idle', history: 'idle'}), setPlace: () => loads.push('setPlace'), load: async () => { loads.push('load'); }};
  const currents = createCurrents({view, palette: () => palettes[theme], data, doc, motion: {matches: reduced, addEventListener() {}, removeEventListener() {}},
    frames: {request: fn => { requests.push(fn); return requests.length; }, cancel() {}}, now: () => NOW, zone: () => 'America/Los_Angeles',
    fetchFn: async () => { fetches.push(1); throw new Error('no network'); }});
  // A theme switch changes the palette; MapLibre then repaints and the map goes idle, which redraws the canvases.
  return {currents, canvases, requests, fetches, loads, switchTo(next) { theme = next; for (const fn of listeners.idle ?? []) fn(); }};
}

for (const reduced of [false, true]) {
  test(`currents (${reduced ? 'reduced motion, still' : 'animated'}): colours are read when drawn, so the redraw after a switch uses the new palette with no request`, t => {
    // Contract: "Currents particle colours read the palette at draw time" and a switch causes no feed read or data load.
    // Bug: the flow colours captured once when the overlay is created, so a switch leaves the old theme's particles.
    presentation.value = 'chart'; appView.value = 'coast'; hour.value = '2026-10-07T12:00Z'; current.value = 'wcofs';
    const h = currentsHarness({reduced});
    t.after(() => { h.currents.destroy(); current.value = 'off'; hour.value = null; });
    const [base, dash] = h.canvases, loads = h.loads.length;
    assert.equal(h.canvases.length, 2);
    assert.ok(Number(dash.dataset.paths) > 0);
    assert.ok(base.ctx.fills.every(c => c === 'dark:flow') && base.ctx.strokes.every(c => c === 'dark:flow'), 'built dark');
    for (const next of ['light', 'dark', 'light']) h.switchTo(next);
    assert.equal(base.ctx.strokes.at(-1), 'light:flow');
    assert.equal(base.ctx.fills.at(-1), 'light:flow');
    if (reduced) assert.equal(dash.ctx.strokes.at(-1), 'light:flow', 'the still dashes too');
    else { h.requests.shift()(1000); assert.ok(dash.ctx.strokes.at(-1).startsWith('light:'), 'the next animation frame draws in the new theme'); }
    assert.equal(h.loads.length, loads, 'no data load or place change');
    assert.equal(h.fetches.length, 0, 'no feed request');
  });
}
