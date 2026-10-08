// Chart basemap style (FE-72, docs/plans/front-end/design.md § 4, § 5): every
// colour comes from web/map/palette.ts, labels start at zoom 9, the attribution
// is exact, the self-hosted glyphs exist, and the filters match the Protomaps
// schema in a synthetic PMTiles fixture. Offline: no tile or glyph is fetched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import vm from 'node:vm';
import {PALETTE_TOKENS, coastPalette, readPalette} from '../web/map/palette.ts';
import {BASEMAP_ATTRIBUTION, BASEMAP_SOURCE, LABEL_FONT, LABEL_MIN_ZOOM, basemapStyle} from '../web/map/style.ts';
import {FILES, themes} from '../scripts/check_contrast.mjs';
import {lintFile} from '../scripts/check_tokens.mjs';
import {decodeTile} from '../dist/seafloor-data.js';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url));
const OPTIONS = {archive: 'https://example.test/tiles/basemap/ca-coast.pmtiles', assets: 'https://example.test/basemap/'};
const VARIANTS = ['day', 'night'];
// A sentinel per token: no real colour can collide with these, so a style colour
// that is not one of them was written somewhere other than the palette.
const sentinel = readPalette(name => `token(${name})`);
const SENTINELS = new Set(Object.values(sentinel));
const styles = Object.fromEntries(VARIANTS.map(variant => [variant, basemapStyle(sentinel, {...OPTIONS, variant})]));
const symbols = style => style.layers.filter(layer => layer.type === 'symbol');

test('the palette reads every token from web/tokens.css in both themes', () => {
  const css = read('web/tokens.css').toString();
  for (const [theme, tokens] of Object.entries(themes(css, FILES['web/tokens.css']))) {
    const palette = readPalette(name => tokens[name] ?? '');
    for (const [key, token] of Object.entries(PALETTE_TOKENS)) assert.equal(palette[key], tokens[token], `${theme} --${token}`);
  }
});

test('a missing token fails loudly instead of drawing an uncoloured map', () => {
  assert.throws(() => readPalette(name => (name === 'bg-deep' ? '' : 'token')), /missing --bg-deep/);
});

test('every style colour comes from the palette (both variants)', () => {
  for (const [variant, style] of Object.entries(styles)) {
    let colours = 0;
    for (const layer of style.layers) {
      for (const [property, value] of Object.entries({...layer.paint, ...layer.layout})) {
        if (!property.endsWith('-color')) continue;
        colours++;
        assert.ok(SENTINELS.has(value), `${variant} ${layer.id} ${property} = ${JSON.stringify(value)}`);
      }
    }
    assert.ok(colours >= 6, `${variant} has ${colours} colours`);
    const json = JSON.stringify(style);
    assert.doesNotMatch(json, /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?)\(/i, `${variant} carries a colour literal`);
  }
  for (const value of Object.values(coastPalette(sentinel))) assert.ok(SENTINELS.has(value), `coast palette ${value}`);
});

test('the style modules pass the token lint', () => {
  for (const file of ['web/map/style.ts', 'web/map/palette.ts']) assert.deepEqual(lintFile(file, read(file).toString()), [], file);
});

test('no labels below zoom 9; the night variant keeps only town labels', () => {
  for (const [variant, style] of Object.entries(styles)) {
    assert.ok(symbols(style).length, variant);
    for (const layer of symbols(style)) assert.ok(layer.minzoom >= LABEL_MIN_ZOOM, `${variant} ${layer.id} starts at ${layer.minzoom}`);
  }
  assert.equal(LABEL_MIN_ZOOM, 9);
  assert.deepEqual(symbols(styles.night).map(layer => layer.id), ['labels-places']);
  assert.ok(styles.night.layers.length < styles.day.layers.length);
});

test('the attribution reads "© OpenStreetMap contributors, © Protomaps"', () => {
  assert.equal(BASEMAP_ATTRIBUTION, '© OpenStreetMap contributors, © Protomaps');
  for (const style of Object.values(styles)) {
    assert.deepEqual(Object.keys(style.sources), [BASEMAP_SOURCE]);
    assert.equal(style.sources[BASEMAP_SOURCE].attribution, BASEMAP_ATTRIBUTION);
    assert.equal(style.sources[BASEMAP_SOURCE].url, `pmtiles://${OPTIONS.archive}`);
  }
});

test('labels use the self-hosted DM Sans glyphs and the style needs no sprite', () => {
  for (const style of Object.values(styles)) {
    assert.equal(style.glyphs, `${OPTIONS.assets}glyphs/{fontstack}/{range}.pbf`);
    assert.equal(style.sprite, undefined);
    for (const layer of symbols(style)) {
      assert.deepEqual(layer.layout['text-font'], [LABEL_FONT]);
      assert.equal(layer.layout['icon-image'], undefined, layer.id);
    }
  }
  for (const range of ['0-255', '8192-8447']) {
    const path = `dist/basemap/glyphs/${LABEL_FONT}/${range}.pbf`;
    assert.ok(existsSync(new URL(`../${path}`, import.meta.url)), path);
    const head = read(path).subarray(0, 64).toString('latin1');
    assert.ok(head.includes(LABEL_FONT) && head.includes(range), `${path} names its font stack and range`);
  }
  assert.ok(existsSync(new URL(`../dist/basemap/glyphs/DM-SANS-OFL.txt`, import.meta.url)), 'the OFL travels with the glyphs');
});

// The filter operators the style uses, evaluated against a decoded MVT feature.
function evaluate(expr, feature) {
  if (!Array.isArray(expr)) return expr;
  const [op, ...args] = expr;
  if (op === 'all') return args.every(arg => evaluate(arg, feature));
  if (op === 'in') return evaluate(args[1], feature).includes(evaluate(args[0], feature));
  if (op === '==') return evaluate(args[0], feature) === evaluate(args[1], feature);
  if (op === 'literal') return args[0];
  if (op === 'get') return feature.properties[args[0]];
  if (op === 'has') return args[0] in feature.properties;
  if (op === 'geometry-type') return ['Unknown', 'Point', 'LineString', 'Polygon'][feature.type];
  throw new Error(`filter operator ${op} is not covered by this test`);
}

test('every basemap layer matches a feature of the synthetic Protomaps fixture', async () => {
  const sandbox = {TextDecoder, DecompressionStream, Response, Uint8Array, DataView, ArrayBuffer, Promise, console};
  vm.createContext(sandbox);
  vm.runInContext(read('dist/vendor/pmtiles-4.5.0/pmtiles.js').toString() + ';globalThis.pmtiles = pmtiles;', sandbox);
  const buf = read('tests/fixtures/basemap/tiny.pmtiles');
  const archive = new sandbox.pmtiles.PMTiles({getKey: () => 'tiny', getBytes: async (offset, length) => ({data: buf.buffer.slice(buf.byteOffset + offset, buf.byteOffset + offset + length)})});
  const header = await archive.getHeader();
  assert.equal(header.minZoom, 10);
  assert.ok(header.minLon < -120.8 && header.maxLon > -120.8 && header.minLat < 35.4 && header.maxLat > 35.4, 'Morro Bay tile');
  const metadata = await archive.getMetadata();
  const tile = decodeTile(new Uint8Array((await archive.getZxy(10, 168, 404)).data));
  for (const style of Object.values(styles)) {
    for (const layer of style.layers.filter(l => l.source === BASEMAP_SOURCE)) {
      const sourceLayer = layer['source-layer'];
      assert.ok(metadata.vector_layers.some(v => v.id === sourceLayer), `${sourceLayer} in vector_layers`);
      const features = tile[sourceLayer]?.features ?? [];
      assert.ok(features.some(f => !layer.filter || evaluate(layer.filter, f)), `${layer.id} matches no fixture feature`);
    }
  }
});
