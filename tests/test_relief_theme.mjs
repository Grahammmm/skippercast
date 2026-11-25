import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {attachBottomRelief} from '../web/map/bottom-relief.ts';
import {chartMark} from '../web/map/chart.ts';
import {contoursOverlay} from '../web/map/depth-contours.ts';
import {PALETTE_TOKENS, readPalette} from '../web/map/palette.ts';
import {assertThemePaintOracle} from './theme-paint-oracle.mjs';

const palettes = Object.fromEntries(['dark', 'light'].map((theme, i) => [theme,
  readPalette(name => name.endsWith('width') || name.endsWith('opacity') ? String(1 - i * 0.2) : `${theme}:${name}`),
]));
const themeOf = p => p === palettes.light ? 'light' : 'dark';
const region = 'fixture', id = 'fixture-survey', sha = 'a'.repeat(64);
const pointer = {region, private: false, sha256: sha, release_sha256: sha, envelope_sha256: sha, digest_root_sha256: sha,
  bytes: 1024, minzoom: 10, maxzoom: 10, bounds: [-121, 35, -120, 36],
  sources: [{id, rights_class: 'public', rights: {public_display: 'allowed'}, attribution: 'Fixture',
    label: 'estimated', vertical_datum: 'fixture', survey_dates: ['2025-01-01']}],
  detail_summary: {mask: 'transparent-nodata', depth_bands: [{source_id: id, resolution_m: 10, min_depth_m: 0, max_depth_m: 90}]},
  native_support_by_zoom: {10: {tiles: 1, limit_m: 91.44, sources: []}}};
const surveyDetail = {type: 'FeatureCollection', region, navigation: 'NOT FOR NAVIGATION', features: [{
  type: 'Feature', properties: {tier: 'none', sources: []},
  geometry: {type: 'Polygon', coordinates: [[[-121, 35], [-120, 35], [-120, 36], [-121, 35]]]},
}]};

// The overlay submitted by the real attachment owns these providers. A stale
// light flag or incomplete projection leaves raster/coast/survey paint behind;
// a themed pattern ID makes the oracle detect a missing or re-added image.
test('attached relief and survey paint match fresh builds; hatch updates under one ID', async t => {
  const dataset = {theme: 'dark'}, canvas = {
    scale() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    getImageData(_x, _y, width, height) { return {width, height, ink: this.strokeStyle, widthPx: this.lineWidth}; },
  };
  const tokens = new Map(Object.entries(PALETTE_TOKENS).map(([key, token]) => [`--${token}`, key]));
  const globals = {
    document: {documentElement: {dataset}, createElement: tag => tag === 'canvas' ? {getContext: () => canvas} : {append() {}, setAttribute() {}}},
    getComputedStyle: () => ({getPropertyValue: name => palettes[dataset.theme][tokens.get(name)]}),
    MutationObserver: class { observe() { assert.fail('Relief must not subscribe to DOM theme changes'); } },
  };
  const old = Object.fromEntries(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, globals);
  t.after(() => { for (const [key, desc] of Object.entries(old)) { if (desc) Object.defineProperty(globalThis, key, desc); else delete globalThis[key]; } });
  const field = signal(true);
  let overlay;
  const installed = new Promise((ready, unavailable) => {
    const handle = attachBottomRelief({region, surveyDetail, ready, unavailable, page: 'https://fixture.test/map',
      engine: {setOverlay: (_, next) => { overlay = next; }, setVisible() {}}, library: {addProtocol() {}},
      seafloorOn: () => true, fieldOn: () => field.value, fetchFn: async () => Response.json(pointer)});
    t.after(() => handle.destroy());
  });
  await installed;
  const dark = overlay;
  dataset.theme = 'light';
  field.value = false;
  field.value = true;
  const light = overlay;
  const ids = o => o.layers.map(l => l.id);
  assert.deepEqual(ids(light), ids(dark));
  assert.deepEqual(light.sources, dark.sources);
  assert.equal(dark.layers[0].paint['raster-brightness-max'], 0.75);
  assert.equal(light.layers[0].paint['raster-brightness-min'], 0.30);
  const report = assertThemePaintOracle({palettes, build: p => p === palettes.light ? light : dark, provider: {
    themePaint(p) { dataset.theme = themeOf(p); return dark.themePaint(p); },
    themePatterns(p) { dataset.theme = themeOf(p); return dark.themePatterns(p); },
  }});
  const [darkHatch] = dark.themePatterns(palettes.dark);
  dataset.theme = 'light';
  const [lightHatch] = dark.themePatterns(palettes.light);
  assert.deepEqual(report.addedIds, [darkHatch.id]);
  assert.deepEqual([lightHatch.id, darkHatch.pixelRatio, lightHatch.pixelRatio], [darkHatch.id, 2, 2]);
  assert.deepEqual([darkHatch.image.widthPx, lightHatch.image.widthPx], [1.2, 1.4]);
  assert.equal(lightHatch.image.ink, palettes.light.mapNosurvey);
});

// v1 and ft-v2 use different paint expressions and label sets. The provider
// must retain the mounted generation, not widen a palette-only change into a
// reconfiguration or leave either label ink/halo expression in the old theme.
test('both contour generations restyle to fresh paint in both directions', () => {
  for (const set of [undefined, 'ft-v2']) {
    const data = {type: 'FeatureCollection', features: [], set};
    const build = p => contoursOverlay(p, data);
    assertThemePaintOracle({palettes, build, provider: build(palettes.dark)});
  }
});

// Contract: survey detail is opt-in, and "off" means off. The transparent hit layer stays mounted after the toggle,
// so a tap on open water must not open a survey reading while detail is off, and switching off must close a survey
// reading that is already open (and take the survey line back off a coastline card). Bug caught: a tap after
// on -> off still opens "Survey detail" because show() never checked the toggle.
test('survey hit layer answers only while detail is on, and switching off closes its reading', async t => {
  const dataset = {theme: 'dark'}, canvas = {
    scale() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
    getImageData(_x, _y, width, height) { return {width, height, ink: this.strokeStyle, widthPx: this.lineWidth}; },
  };
  const tokens = new Map(Object.entries(PALETTE_TOKENS).map(([key, token]) => [`--${token}`, key]));
  const globals = {
    document: {documentElement: {dataset}, createElement: tag => tag === 'canvas' ? {getContext: () => canvas} : {append() {}, setAttribute() {}}},
    getComputedStyle: () => ({getPropertyValue: name => palettes[dataset.theme][tokens.get(name)]}),
    MutationObserver: class { observe() {} },
  };
  const old = Object.fromEntries(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  Object.assign(globalThis, globals);
  t.after(() => { chartMark.value = null; for (const [key, desc] of Object.entries(old)) { if (desc) Object.defineProperty(globalThis, key, desc); else delete globalThis[key]; } });
  let overlay, view;
  const installed = new Promise((ready, unavailable) => {
    const handle = attachBottomRelief({region, surveyDetail, ready, unavailable, page: 'https://fixture.test/map',
      surveyView: next => { view = next; },
      engine: {setOverlay: (_, next) => { overlay = next; }, setVisible() {}, renderedValues: () => [], view: {on: () => () => {}}},
      library: {addProtocol() {}}, seafloorOn: () => false, fieldOn: () => false, fetchFn: async () => Response.json(pointer)});
    t.after(() => handle.destroy());
  });
  await installed;
  const tap = () => overlay.inspect.show({tier: 'none'});
  const surveyOpen = () => chartMark.peek()?.id.endsWith('-survey');

  tap();
  assert.equal(chartMark.peek(), null, 'detail never switched on: no survey reading');
  view.toggle();
  tap();
  assert.ok(surveyOpen(), 'detail on: open water opens the survey reading');
  view.toggle();
  assert.equal(chartMark.peek(), null, 'switching off closes the open survey reading');
  tap();
  assert.equal(chartMark.peek(), null, 'detail off again: the still-mounted hit layer must stay silent');

  const coast = {id: 'coastline:fixture', name: 'Shore', kind: 'coast', reading: 'Shoreline', source: '', basis: ''};
  chartMark.value = coast;
  view.toggle();
  tap();
  assert.notEqual(chartMark.peek(), coast, 'detail on: the coastline card gains the survey line');
  assert.match(chartMark.peek().reading, /^Shoreline · /);
  view.toggle();
  assert.equal(chartMark.peek(), coast, 'switching off restores the plain coastline card');
});
