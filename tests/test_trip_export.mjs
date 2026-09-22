import test from 'node:test';
import assert from 'node:assert/strict';
import {buildExport, DEFAULT_LAYERS, draftKey, offlineNotes, readDraft} from '../dist/trip-export.js';
import {geometryTrack} from '../dist/gpx.js';
import {geometryIntersects, pointInGeometry} from '../dist/geo-screen.js';

const NOW = new Date('2026-09-22T18:00:00.000Z');
const CHECKED = '2026-09-22T17:00:00.000Z';
const REGION = {
  id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles',
  mpa: {bounds: [-10, -10, 10, 10]}, regulations_url: 'https://example.org/rules',
};
const ring = (x, y, width = 1) => [[x, y], [x + width, y], [x + width, y + width], [x, y + width], [x, y]];
const polygon = (x, y, width = 1) => ({type: 'Polygon', coordinates: [ring(x, y, width)]});
const exclusion = (name, geometry) => ({
  type: 'Feature', properties: {NAME: name, FULLNAME: `${name} protected area`, CCR: 'Source reference'}, geometry,
});

function atlasFixture() {
  const target = (id, longitude) => ({
    id, name: `Waypoint ${id}`, label: `Reef ${id}`, latitude: 0, longitude,
    habitat_grade: 'A', habitat_score: 80, center_depth_ft: 100,
    neighborhood_depth_ft: [90, 110], terrain_interpretation: 'Mapped raised structure',
    evidence_status: 'Fish presence unverified.', ais_status: 'AIS unverified.',
    survey_year: 2008, source_url: 'https://example.org/survey', special_note: 'Measure a test drift.',
    area_ids: ['shared-reef'], drift_id: id === 'a' ? 'alignment-a' : null,
  });
  return {
    source_validation_date: '2026-09-20', targets: [target('a', 0), target('b', 4)],
    areas: [{
      id: 'shared-reef', target_ids: ['a', 'b'], extent_note: 'Partial mapped habitat',
      geometry: {type: 'MultiPolygon', coordinates: [
        [ring(-1, -1, 2), ring(-0.8, -0.8, 0.2)],
        [ring(3, -1, 2)],
      ]},
    }],
    drifts: [{
      id: 'alignment-a', target_id: 'a', basis: 'Surveyed terrain axis',
      geometry: {type: 'LineString', coordinates: [[-1, 0], [0, 0], [1, 0]]},
    }],
  };
}

function screenFixture(features = []) {
  let fresh = true;
  return {
    expire() { fresh = false; },
    ready: () => fresh,
    pointAllowed: t => fresh && !features.some(f => pointInGeometry([t.longitude, t.latitude], f.geometry)),
    geometryAllowed: geometry => fresh && !features.some(f => geometryIntersects(geometry, f.geometry)),
    exportExclusions: () => fresh ? {checked_at: CHECKED, features} : null,
  };
}

const request = (overrides = {}) => ({
  atlas: atlasFixture(), screen: screenFixture(), ids: ['a'], region: REGION, now: NOW, ...overrides,
});
const segmentsIn = xml => [...xml.matchAll(/<trkseg>([\s\S]*?)<\/trkseg>/g)].map(([, segment]) =>
  [...segment.matchAll(/<trkpt lat="([^"]+)" lon="([^"]+)"\/>/g)].map(([, lat, lon]) => [Number(lon), Number(lat)]));

test('day-plan defaults export only deduplicated waypoints with the requested provenance', () => {
  const result = buildExport(request({ids: ['a', 'a', 'b']}));
  assert.deepEqual(result.features.selected.map(t => t.id), ['a', 'b']);
  assert.equal((result.gpx.match(/<wpt /g) || []).length, 2);
  assert.doesNotMatch(result.gpx, /<trk>|<rte>/);
  assert.equal(result.counts.waypoints, 2);
  assert.equal(result.counts.tracks, 0);
  assert.equal(result.region_id, REGION.id);
  assert.equal(result.created_at, NOW.toISOString());
  assert.equal(result.boundary_checked_at, CHECKED);
});

test('included geometry is deduplicated without joining polygon holes, islands or alignment tracks', () => {
  const atlas = atlasFixture();
  const result = buildExport(request({atlas, ids: ['a', 'b', 'a'], layers: {...DEFAULT_LAYERS, outlines: true, alignments: true}}));
  assert.deepEqual(result.counts, {waypoints: 2, outlines: 1, alignments: 1, exclusions: 0, tracks: 2, trackPoints: 18, largestTrack: 15});
  assert.deepEqual(segmentsIn(result.gpx), [...atlas.areas[0].geometry.coordinates.flat(), atlas.drifts[0].geometry.coordinates]);
  assert.doesNotMatch(result.gpx, /<rte>|<rtept /);
});

test('an expired boundary screen blocks a new export even after a successful preview', () => {
  const screen = screenFixture();
  const input = request({screen});
  assert.equal(buildExport(input).counts.waypoints, 1);
  screen.expire();
  assert.throws(() => buildExport(input), /Protected-area checks/);
  assert.throws(() => buildExport(request({screen: null})), /Protected-area checks/);
});

test('unknown, protected and invalid-coordinate selections fail even for an outline-only plan', () => {
  assert.throws(() => buildExport(request({ids: ['missing']})), /Unknown target/);
  assert.throws(() => buildExport(request({screen: screenFixture([exclusion('MPA', polygon(-0.2, -0.2, 0.4))]), layers: {...DEFAULT_LAYERS, waypoints: false, outlines: true}})), /selected spot fails/);
  for (const coordinate of [NaN, Infinity, 91]) {
    const atlas = atlasFixture();
    atlas.targets[0].latitude = coordinate;
    assert.throws(() => buildExport(request({atlas})), /selected spot fails/);
  }
});

test('full linked geometry is screened even when reverse target references are missing', () => {
  const atlas = atlasFixture();
  atlas.areas[0].target_ids = [];
  const screen = screenFixture([exclusion('MPA', polygon(0.4, -0.1, 0.2))]);
  assert.equal(buildExport(request({atlas, screen})).counts.waypoints, 1);
  for (const layer of ['outlines', 'alignments']) {
    assert.throws(() => buildExport(request({atlas, screen, layers: {...DEFAULT_LAYERS, [layer]: true}})), /outline or alignment intersects/);
  }
});

test('missing linked data blocks only the layer that would use it', () => {
  const atlas = atlasFixture();
  atlas.areas = [];
  atlas.drifts = [];
  assert.equal(buildExport(request({atlas})).counts.waypoints, 1);
  for (const layer of ['outlines', 'alignments']) {
    assert.throws(() => buildExport(request({atlas, layers: {...DEFAULT_LAYERS, [layer]: true}})), /missing linked geometry/);
  }
});

test('a region without qualified targets can export intersecting AVOID outlines in full', () => {
  const included = exclusion('Near', polygon(-2, -2, 4));
  const outside = exclusion('Far', polygon(7, 7, 1));
  const result = buildExport(request({
    atlas: {targets: [], areas: [], drifts: []}, ids: [],
    screen: screenFixture([included, outside]), bounds: [1, 1, 1.5, 1.5],
    layers: {...DEFAULT_LAYERS, waypoints: false, exclusions: true},
  }));
  assert.equal(result.counts.waypoints, 0);
  assert.equal(result.counts.exclusions, 1);
  assert.match(result.gpx, /<name>AVOID Near<\/name>/);
  assert.doesNotMatch(result.gpx, /AVOID Far/);
  assert.deepEqual(segmentsIn(result.gpx), included.geometry.coordinates);
  const regionResult = buildExport(request({
    atlas: {targets: [], areas: [], drifts: []}, ids: [], screen: screenFixture([included, outside]),
    layers: {...DEFAULT_LAYERS, waypoints: false, exclusions: true},
  }));
  assert.equal(regionResult.counts.exclusions, 2);
});

test('empty exports and requested AVOID outlines without a current snapshot are rejected', () => {
  assert.throws(() => buildExport(request({ids: []})), /Select at least one/);
  assert.throws(() => buildExport(request({layers: {waypoints: false, outlines: false, alignments: false, exclusions: false}})), /Select at least one/);
  const screen = screenFixture();
  screen.exportExclusions = () => null;
  assert.throws(() => buildExport(request({screen, layers: {...DEFAULT_LAYERS, exclusions: true}})), /outlines are unavailable/);
});

test('malformed requested exclusion geometry cannot silently disappear during extent filtering', () => {
  const features = [exclusion('Valid', polygon(-2, -2, 4)), exclusion('Broken', {type: 'Polygon', coordinates: []})];
  assert.throws(() => buildExport(request({
    atlas: {targets: [], areas: [], drifts: []}, ids: [], screen: screenFixture(features),
    layers: {...DEFAULT_LAYERS, waypoints: false, exclusions: true},
  })), /geometry|polygon|boundary|outline/i);
});

test('export tracks reject incomplete polygons and unusable line coordinates', () => {
  for (const geometry of [
    {type: 'Polygon', coordinates: [[[0, 0], [1, 0]]]},
    {type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
    {type: 'MultiPolygon', coordinates: [[ring(0, 0)], [[[2, 2], [3, 2]]]]},
    {type: 'LineString', coordinates: [[0, 0], [NaN, 1]]},
    {type: 'LineString', coordinates: [[0, 0], [181, 1]]},
    {type: 'LineString', coordinates: [[0, 0], [1, 91]]},
  ]) assert.throws(() => geometryTrack('test', 'test', geometry), /Invalid export/);
});

test('restoring a draft prunes removed targets, deduplicates choices and preserves explicit coverage', () => {
  const raw = JSON.stringify({ids: ['b', 'gone', 'b', 'a'], name: 'x'.repeat(100), date: '2028-02-29', avoidScope: 'region', layers: {waypoints: false, outlines: true, alignments: 'true', exclusions: true, unknown: true}});
  const draft = readDraft(raw, atlasFixture(), '2026-09-22');
  assert.deepEqual(draft.ids, ['b', 'a']);
  assert.equal(draft.name.length, 80);
  assert.equal(draft.date, '2028-02-29');
  assert.equal(draft.avoidScope, 'region');
  assert.deepEqual(draft.layers, {waypoints: false, outlines: true, alignments: false, exclusions: true});
  assert.notEqual(draftKey('test-coast'), draftKey('another-coast'));
});

test('corrupt drafts and impossible calendar dates recover to usable defaults', () => {
  for (const raw of [null, '{broken', 'null', '17', '[]']) {
    const draft = readDraft(raw, atlasFixture(), '2026-09-22');
    assert.deepEqual(draft.ids, []);
    assert.equal(draft.name, 'My fishing day');
    assert.equal(draft.date, '2026-09-22');
    assert.equal(draft.avoidScope, 'map');
    assert.deepEqual(draft.layers, DEFAULT_LAYERS);
  }
  for (const date of ['2026-02-30', '2025-02-29', '2026-13-01', '2026-00-10', 'not-a-date']) {
    assert.equal(readDraft(JSON.stringify({date}), atlasFixture(), '2026-09-22').date, '2026-09-22');
  }
});

test('offline notes preserve plan/source provenance and safely render user and source text', () => {
  const atlas = atlasFixture();
  atlas.targets[0].label = '<script>alert("label")</script>';
  atlas.targets[0].special_note = 'A & B <test> "quoted"';
  atlas.targets[0].source_url = 'javascript:alert(1)';
  const region = {...REGION, regulations_url: 'data:text/html,<script>alert(1)</script>'};
  const result = buildExport(request({atlas, region}));
  const html = offlineNotes(result, region, {name: '<script>alert("plan")</script>', date: '2026-09-24'});
  assert.doesNotMatch(html, /<script|href="(?:javascript:|data:)/i);
  assert.match(html, /&lt;script&gt;alert\(&quot;plan&quot;\)&lt;\/script&gt;/);
  assert.match(html, /A &amp; B &lt;test&gt; &quot;quoted&quot;/);
  assert.match(html, /Planned date 2026-09-24/);
  assert.ok(html.includes(NOW.toISOString()));
  assert.ok(html.includes(CHECKED));
  assert.match(html, /does not update offline/);
  assert.match(html, /not a future clearance/);
  assert.match(html, /AIS unverified/);
});

test('GPX escapes text and strips XML-forbidden controls without creating routes', () => {
  const atlas = atlasFixture();
  atlas.targets[0].name = 'A & B <reef>\u0000\u000b';
  atlas.targets[0].special_note = 'Keep "this" \'note\'';
  const result = buildExport(request({atlas, title: 'Plan <one> & "two"'}));
  assert.match(result.gpx, /<name>A &amp; B &lt;reef&gt;<\/name>/);
  assert.match(result.gpx, /Plan &lt;one&gt; &amp; &quot;two&quot;/);
  assert.match(result.gpx, /Keep &quot;this&quot; &apos;note&apos;/);
  assert.doesNotMatch(result.gpx, /[\u0000-\u0008\u000b\u000c\u000e-\u001f]|<rte>/);
});
