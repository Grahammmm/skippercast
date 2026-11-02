// RF0420-6: the landing shoreline generator refuses provenance text that
// would break out of the `//` comment of web/landing/shoreline-path.ts and a
// drawn feature that is not a line of finite coordinates, naming the field
// or the feature index; non-drawn features stay unchecked and the committed
// catalog still yields the committed module byte for byte.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {shorelineModule} from '../scripts/build_landing_shoreline.mjs';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const PROVENANCE = {source: 'NOAA NGS CUSP', license: 'public-domain', attribution: 'NOAA NGS CUSP'};
const line = (coordinates = [[-121.5, 35.2], [-121.4, 35.3]]) => ({
  type: 'Feature', properties: {ATTRIBUTE: 'Natural.Mean High Water', SRC_DATE: '20200101'},
  geometry: {type: 'LineString', coordinates},
});
const marsh = geometry => ({type: 'Feature', properties: {ATTRIBUTE: 'Natural.Apparent-Marsh', SRC_DATE: '20200101'}, geometry});
const doc = (features, provenance = {}) => ({features, provenance: {...PROVENANCE, ...provenance}});
const refuses = (geojson, message) => assert.throws(() => shorelineModule(geojson), e => e instanceof Error && e.message === message, message);

test('a line break or control character in provenance text is refused naming the field', () => {
  refuses(doc([line()], {source: 'NOAA\nexport const X = 1'}), 'shoreline provenance source has a line break or control character');
  refuses(doc([line()], {license: 'public\rdomain'}), 'shoreline provenance license has a line break or control character');
  refuses(doc([line()], {license: 'public\u2028domain'}), 'shoreline provenance license has a line break or control character');
  refuses(doc([line()], {license: 'public\u2029domain'}), 'shoreline provenance license has a line break or control character');
  refuses(doc([line()], {source: 'NOAA\u0000'}), 'shoreline provenance source has a line break or control character');
  refuses(doc([line()], {source: 'NOAA\u0085'}), 'shoreline provenance source has a line break or control character');
  refuses(doc([line()], {attribution: 'NOAA\u007f'}), 'shoreline provenance attribution has a line break or control character');
  refuses(doc([line()], {source: 42}), 'shoreline provenance source has a line break or control character');
  refuses({features: [line()]}, 'shoreline provenance source has a line break or control character');
});

test('provenance text over 300 characters is refused; 300 is accepted', () => {
  refuses(doc([line()], {license: 'x'.repeat(301)}), 'shoreline provenance license has a line break or control character');
  assert.match(shorelineModule(doc([line()], {license: 'x'.repeat(300)})), new RegExp(`\\(${'x'.repeat(300)}\\)`));
});

test('a drawn feature without line geometry is refused by index', () => {
  refuses(doc([line(), marsh(null), {...line(), geometry: null}]), 'shoreline feature 2: geometry is not a line');
  refuses(doc([line(), line(), {...line(), geometry: {type: 'Polygon', coordinates: [[[-121.5, 35.2], [-121.4, 35.3], [-121.5, 35.3], [-121.5, 35.2]]]}}]),
    'shoreline feature 2: geometry is not a line');
  refuses(doc([{...line(), geometry: {type: 'LineString', coordinates: 'x'}}]), 'shoreline feature 0: geometry is not a line');
  refuses(doc([{...line(), geometry: {type: 'MultiLineString', coordinates: [[[-121.5, 35.2], [-121.4, 35.3]], 7]}}]), 'shoreline feature 0: geometry is not a line');
});

test('a drawn feature with a non-finite coordinate is refused by index without the value', () => {
  for (const bad of [[NaN, 35], ['-121', 35], [-121], [-121, Infinity], null]) {
    const message = 'shoreline feature 1: coordinate is not a finite number';
    refuses(doc([line(), line([[-121.5, 35.2], bad])]), message);
  }
  refuses(doc([{...line(), geometry: {type: 'MultiLineString', coordinates: [[[-121.5, 35.2], [-121.4, 35.3]], [[-121.5, NaN]]]}}]),
    'shoreline feature 0: coordinate is not a finite number');
});

test('a non-drawn feature is skipped unchecked', () => {
  const text = shorelineModule(doc([marsh(null), marsh({type: 'Polygon', coordinates: [[[NaN, 35]]]}), line()]));
  assert.match(text, /d: 'M[\d.]+ [\d.]+l/);
  assert.doesNotMatch(text, /NaN/);
});

test('every check runs before any text: a bad later feature refuses even after good ones', () => {
  refuses(doc([line(), line(), line(), line([[-121.5, 35.2], [NaN, 35]])]), 'shoreline feature 3: coordinate is not a finite number');
});

test('the committed catalog still yields the committed module byte for byte', () => {
  const geojson = JSON.parse(readFileSync(`${ROOT}catalog/shoreline/morro-bay.geojson`, 'utf8'));
  const committed = readFileSync(`${ROOT}web/landing/shoreline-path.ts`, 'utf8');
  const text = shorelineModule(geojson);
  assert.ok(text === committed, 'run node scripts/build_landing_shoreline.mjs');
});
