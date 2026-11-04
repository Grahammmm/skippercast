// RF1330-1: a shoreline line with an impossible latitude/longitude is rejected whole before Spear measures
// swim distance (it used to pass through the queried point and claim zero yards); valid siblings survive.
import assert from 'node:assert/strict';
import test from 'node:test';
import {publishedChartFiles} from '../web/chart-files.ts';
import {linesOf, loadShoreLines, resetShoreLines, shoreLines, yardsFromShore} from '../web/shore-distance.ts';

const PAGE = 'https://example.test/';
const line = coordinates => ({type: 'Feature', geometry: {type: 'LineString', coordinates}});
const multi = coordinates => ({type: 'Feature', geometry: {type: 'MultiLineString', coordinates}});
const fc = (...features) => ({type: 'FeatureCollection', features});
const deepFreeze = v => { if (v && typeof v === 'object') { Object.values(v).forEach(deepFreeze); Object.freeze(v); } return v; };
const same = (a, b, msg) => assert.ok(JSON.stringify(a) === JSON.stringify(b), msg);

const GOOD = [[-120.8, 35.3], [-120.79, 35.31]];

test('shore_rejects_out_of_range_vertex_without_bridging', () => {
  const bad = [
    [[-120.8, 35.3], [-120.8, 135.3]], // the reproduced probe
    [[-120.8, 35.3], [-120.8, -90.0001]],
    [[-120.8, 35.3], [-120.8, 90.0001]],
    [[-180.0001, 35.3], [-120.8, 35.3]],
    [[-120.8, 35.3], [180.0001, 35.3]],
    [[-120.8, 35.3], [-120.8, 135.3], [-120.79, 35.31]], // invalid middle vertex: no bridge to a shorter line
    [[-120.8, 35.3], [-120.79, 35.31], [NaN, 35.3]],
    [[-120.8, 35.3], [Infinity, 35.3]],
    [[-120.8, 35.3], ['-120.8', 35.3]], // no coercion
  ];
  for (const coordinates of bad) assert.deepEqual(linesOf(fc(line(coordinates))), [], JSON.stringify(coordinates));
  // No axis swap or wrap: a swapped but in-range pair is simply a (different) valid position, an out-of-range one is dropped.
  assert.deepEqual(linesOf(fc(line([[35.3, -120.8], [35.3, -120.79]]))), []);
  // The old defect: zero yards at the queried point from the impossible segment.
  assert.equal(yardsFromShore({latitude: 35.3, longitude: -120.8}, linesOf(fc(line(bad[0])))), null);
});

test('shore_keeps_valid_siblings_and_boundaries', () => {
  const edge = [[-180, -90], [180, 90]];
  const extra = [[-120.8, 35.3, 12, 'z'], [-120.8, 35.3, 99], [0, 0], [-0.5, -0.5]];
  const input = deepFreeze(fc(
    line([[-120.8, 35.3], [-120.8, 135.3]]),
    line(GOOD),
    multi([[[-120.8, 35.3], [-120.8, 95]], edge, [[-121, 36]], [[-121, 36], [-121.1, 36.1]], [[-121, 36], [200, 36]]]),
    line(extra),
    multi([[[-1, -1], [-2, -2]], [[-1, 91], [-2, -2]]]),
    {type: 'Feature', geometry: {type: 'Point', coordinates: [-120.8, 35.3]}},
    null,
  ));
  const before = JSON.stringify(input);
  same(linesOf(input), [GOOD, edge, [[-121, 36], [-121.1, 36.1]], extra, [[-1, -1], [-2, -2]]], 'exact ordered survivors');
  assert.equal(JSON.stringify(input), before, 'input untouched');
  assert.equal(linesOf(input)[3], input.features[3].geometry.coordinates, 'extra dimensions and duplicates kept, not copied');
});

test('shore_bounds_all_invalid_is_unknown', async () => {
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('no network'); };
  resetShoreLines();
  publishedChartFiles.value = {region: 'r', files: ['shoreline-overview.geojson']};
  try {
    let calls = 0;
    const f = async () => { calls++; return new Response(JSON.stringify(fc(line([[-120.8, 35.3], [-120.8, 135.3]]), line([[-181, 35], [-120, 35]])))); };
    await loadShoreLines('r', PAGE, f);
    assert.equal(shoreLines.value.region, 'r');
    assert.equal(shoreLines.value.lines, null);
    await loadShoreLines('r', PAGE, f);
    assert.equal(calls, 1, 'terminal invalid file is remembered, not asked again');
    assert.equal(shoreLines.value.lines, null);
  } finally {
    globalThis.fetch = realFetch;
    publishedChartFiles.value = null;
    resetShoreLines();
  }
});

test('shore_bounds_mixed_load_uses_only_valid_distance', async () => {
  const p = {latitude: 35.3, longitude: -120.8};
  const validOnly = [[[-120.79, 35.3], [-120.79, 35.31]]];
  const body = fc(line([[-120.8, 35.3], [-120.8, 135.3]]), line(validOnly[0]));
  resetShoreLines();
  try {
    await loadShoreLines('r', PAGE, async () => new Response(JSON.stringify(body)));
    same(shoreLines.value.lines, validOnly, 'only the valid sibling loads');
    const yards = yardsFromShore(p, shoreLines.value.lines);
    assert.ok(yards > 500, `a real distance, not zero: ${yards}`);
    assert.equal(yards, yardsFromShore(p, validOnly));
  } finally {
    resetShoreLines();
  }
});
