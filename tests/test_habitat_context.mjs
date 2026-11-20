import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import test from 'node:test';
import {FILES, themes} from '../scripts/check_contrast.mjs';
import {decodeHabitatContext, habitatContextLayers, registryEntry, themePaint} from '../web/map/habitat-context.ts';
import {readPalette} from '../web/map/palette.ts';

// Use the installed renderer's own style validator and filter evaluator, not
// a hand-written mock of the filter syntax.
const require = createRequire(import.meta.resolve('maplibre-gl'));
const {featureFilter, validateStyleMin} = require('@maplibre/maplibre-gl-style-spec');
const swatches = {rock: 'habRock', mixed: 'habMixed', sediment: 'habSoft', kelp: 'habKelp', unknown: 'mapBoundary'};
const classes = Object.keys(swatches);
const evidence = ['measured', 'predicted', 'historical'];
const date = '2016-09-03 to 2016-09-25';
const ring = [[-121, 35], [-120, 35], [-120, 36], [-121, 36], [-121, 35]];
const hole = [[-120.8, 35.2], [-120.8, 35.8], [-120.2, 35.8], [-120.2, 35.2], [-120.8, 35.2]];
const polygon = {type: 'Polygon', coordinates: [ring, hole]};
const feature = (kind, evidenceClass, extra = {}, geometry = polygon, suffix = '') => {
  const id = `fixture-${kind}-${evidenceClass}${suffix}`;
  return {type: 'Feature', id, geometry, properties: {
    id, habitat_kind: kind, evidence_class: evidenceClass, source_id: 'fixture-source',
    source_class: evidenceClass === 'historical' ? ['Canopy'] : kind === 'rock' && evidenceClass === 'predicted' ? 'hard' : 'synthetic-code',
    source_date: evidenceClass === 'historical' ? date : evidenceClass === 'measured' ? '20000612-20000718' : null,
    fishing_target: false, fishing_export: false, depth_qualified: false, ...extra,
  }};
};
const document = features => ({type: 'FeatureCollection', schema_version: 1, layer: 'habitat', region_id: 'fixture-coast',
  disclaimer: 'NOT FOR NAVIGATION', sources: [{id: 'fixture-source', name: 'Synthetic Source Name'}], features});
const matrix = () => classes.flatMap(kind => evidence.map(ev => feature(kind, ev)));

// Consumer seam: reading native codes or conflating kinds/evidence would turn
// predicted hard into reef, sediment into sand, or historical canopy into today's layer.
test('HAB-1 context preserves every class and evidence, without rank or export', () => {
  const inputs = matrix();
  const {collection, refused} = decodeHabitatContext(document(inputs));
  assert.deepEqual(refused, []);
  assert.equal(collection.features.length, inputs.length);
  for (const [i, input] of inputs.entries()) {
    const {habitat_kind, evidence_class, source_id, source_date} = input.properties;
    assert.deepEqual(collection.features[i], {type: 'Feature', id: input.id, geometry: polygon, properties: {
      class: habitat_kind, evidence: evidence_class, source_id, ...(source_date === null ? {} : {date: source_date}),
      nonexport: true, fishing_target: false, fishing_export: false, depth_qualified: false,
    }});
  }
  assert.equal(registryEntry.legend.find(row => row.swatch === 'habSoft')?.label, 'Sediment');
  assert.doesNotMatch(JSON.stringify(registryEntry), /\bsand\b|\breef\b|\bcurrent\b|synthetic source name|fixture-source/i);
});

// Bad producer fields must be refused by index rather than normalized, allowed
// to grant access, or used to erase the valid rows in the same file.
test('malformed feature shapes, dates and safety fields are refused with specific reasons', () => {
  const cases = [
    [feature('sand', 'measured'), /habitat_kind/],
    [feature('rock', 'Measured'), /evidence_class/],
    [feature('rock', 'measured', {source_id: 'unlisted'}), /source_id/],
    [feature('rock', 'measured', {source_class: 1}), /source_class/],
    [feature('rock', 'measured', {id: 'mismatch'}), /ids/],
    [feature('kelp', 'historical', {source_date: null}), /source_date/],
    [feature('kelp', 'historical', {source_date: '2016-02-30'}), /source_date/],
    [feature('kelp', 'historical', {source_date: '2016-12-01 to 2016-01-01'}), /source_date/],
    [feature('rock', 'measured', {fishing_target: true}), /nonexportable/],
    [feature('rock', 'measured', {fishing_export: 'false'}), /nonexportable/],
    [feature('rock', 'measured', {depth_qualified: true}), /non-depth-qualified/],
    [feature('rock', 'measured', {nonexport: false}), /nonexportable/],
    [feature('rock', 'measured', {military_access: 'unknown'}), /military/],
    [feature('rock', 'measured', {closure_hold: 'false'}), /closure/],
    [{...feature('rock', 'measured'), properties: null}, /properties/],
    ...[
      null, {type: 'Point', coordinates: ring[0]}, {type: 'Polygon', coordinates: [ring.slice(0, -1)]},
      {type: 'Polygon', coordinates: [Array(4).fill(ring[0])]}, {type: 'MultiPolygon', coordinates: [[]]},
      {type: 'Polygon', coordinates: [ring, [[-200, 35], ...hole.slice(1, -1), [-200, 35]]]},
      {type: 'Polygon', coordinates: [ring.map(([lon, lat]) => [String(lon), lat])]},
      {type: 'Polygon', coordinates: new Array(1)},
    ].map(bad => [feature('rock', 'measured', {}, bad), /polygon/]),
  ];
  const valid = feature('sediment', 'measured', {}, {type: 'MultiPolygon', coordinates: [polygon.coordinates]});
  const result = decodeHabitatContext(document([...cases.map(([input]) => input), valid]));
  assert.deepEqual(result.collection.features.map(f => f.geometry), [valid.geometry]);
  assert.equal(result.refused.length, cases.length);
  for (const [i, [, reason]] of cases.entries()) {
    assert.equal(result.refused[i].index, i);
    assert.match(result.refused[i].reason, reason);
  }
});

// A different layer/version or projected data must not be treated as an empty,
// valid seafloor result; downstream can distinguish refusal from no coverage.
test('HAB-1 envelope errors are distinct from a valid empty collection', () => {
  for (const extra of [{type: 'Feature'}, {schema_version: '1'}, {layer: 'other'}, {crs: {}}, {features: null},
    {sources: [{id: 'dup'}, {id: 'dup'}]}]) {
    const result = decodeHabitatContext({...document([]), ...extra});
    assert.equal(result.collection, null);
    assert.equal(result.refused[0].index, null);
    assert.ok(result.refused[0].reason);
  }
  assert.deepEqual(decodeHabitatContext(document([])), {collection: {type: 'FeatureCollection', features: []}, refused: []});
});

const css = readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8');
const numbers = Object.fromEntries([...css.matchAll(/--([a-z0-9-]+):\s*(\d*\.?\d+)\s*;/g)].map(m => [m[1], m[2]]));
const palettes = Object.entries(themes(css, FILES['web/tokens.css'])).map(([theme, tokens]) => [theme,
  readPalette(name => tokens[name] ?? numbers[name] ?? '')]);
const matches = (layer, f) => featureFilter(layer.filter, layer.id).filter({zoom: 10}, f);

// A hold may survive in a preview/extended row. Both draw paths must exclude
// it even if the rest of the feature is valid, without clearing its metadata.
test('military and closure holds survive decoding and suppress fill and outline', () => {
  const flags = [{military_access: 'unverified'}, {military_hold: true}, {closure_hold: true},
    {military_access: 'verified', military_hold: false, closure_hold: false, nonexport: true}];
  const {collection, refused} = decodeHabitatContext(document(flags.map((flag, i) => feature('kelp', 'historical', flag, polygon, i))));
  assert.deepEqual(refused, []);
  const layers = habitatContextLayers(palettes[0][1]);
  assert.equal(collection.features.length, flags.length);
  for (const [i, f] of collection.features.entries()) {
    for (const [key, value] of Object.entries(flags[i])) assert.equal(f.properties[key], value);
    assert.equal(f.properties.nonexport, true);
    assert.deepEqual(layers.filter(layer => matches(layer, f)).map(layer => layer.type), i === 3 ? ['fill', 'line'] : []);
  }
});

// Independent palette/renderer checks catch theme paint targeting the wrong IDs,
// class filters collapsing different bottom types, and evidence paints that look alike.
test('Chart-only zoom gate, token colours and evidence styling agree in both themes', () => {
  assert.equal(registryEntry.id, 'habitat-context');
  assert.deepEqual(registryEntry.presentations, ['chart']);
  assert.equal(registryEntry.control, 'seafloor');
  assert.equal(registryEntry.gate, 'zoom ≥ 10');
  const [source] = registryEntry.sources;
  const data = decodeHabitatContext(document(matrix())).collection;
  assert.deepEqual(palettes.map(([theme]) => theme).sort(), ['dark', 'light']);
  const layerSets = [];
  for (const [theme, palette] of palettes) {
    const layers = habitatContextLayers(palette);
    layerSets.push(layers);
    assert.deepEqual(validateStyleMin({version: 8, sources: {[source]: {type: 'geojson', data}}, layers}), [], theme);
    assert.equal(new Set(layers.map(layer => layer.id)).size, 2 * data.features.length);
    assert.ok(layers.every(layer => layer.source === source && layer.minzoom === 9));
    const colors = [];
    for (const kind of classes) {
      const [measured, predicted, historical] = data.features.filter(f => f.properties.class === kind)
        .map(f => layers.filter(layer => matches(layer, f)));
      for (const [fill, line, ...extra] of [measured, predicted, historical]) {
        assert.deepEqual(extra, []);
        assert.equal(fill.type, 'fill');
        assert.equal(line.type, 'line');
        for (const [layer, property] of [[fill, 'fill-color'], [line, 'line-color']]) {
          assert.equal(layer.paint[property], palette[swatches[kind]]);
          colors.push({layer: layer.id, property, value: palette[swatches[kind]]});
        }
      }
      assert.ok(predicted[0].paint['fill-opacity'] < measured[0].paint['fill-opacity']);
      assert.ok(predicted[1].paint['line-opacity'] < measured[1].paint['line-opacity']);
      assert.equal(measured[1].paint['line-dasharray'], undefined);
      assert.ok(historical[1].paint['line-dasharray']?.length >= 2);
    }
    const byLayer = (a, b) => a.layer.localeCompare(b.layer);
    assert.deepEqual([...themePaint(palette)].sort(byLayer), colors.sort(byLayer));
  }
  assert.notDeepEqual(layerSets[0].map(layer => layer.paint), layerSets[1].map(layer => layer.paint));
});
