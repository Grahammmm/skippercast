import test from 'node:test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {buildExport, DEFAULT_LAYERS, draftKey, offlineNotes, readDraft,exportTargets,exportEvidenceLabel,exportPresetTargets} from '../dist/trip-export.js';
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
  allowResearch:true, atlas: atlasFixture(), screen: screenFixture(), ids: ['a'], region: REGION, now: NOW, ...overrides,
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
  // SC-LAUNCH-1: the reef area is screened whole even for a waypoints-only export.
  assert.throws(() => buildExport(request({atlas, screen})), /whole-boundary/);
  for (const layer of ['outlines', 'alignments']) {
    assert.throws(() => buildExport(request({atlas, screen, layers: {...DEFAULT_LAYERS, [layer]: true}})), /whole-boundary|outline or alignment intersects/);
  }
});

test('missing linked data blocks the layer that would use it, and a waypoint whose reef area cannot be screened', () => {
  const atlas = atlasFixture();
  atlas.drifts = [];
  assert.equal(buildExport(request({atlas})).counts.waypoints, 1);
  assert.throws(() => buildExport(request({atlas, layers: {...DEFAULT_LAYERS, alignments: true}})), /missing linked geometry/);
  atlas.areas = [];
  // SC-LAUNCH-1: without its reef area the whole reef cannot be screened, so the waypoint fails closed.
  assert.throws(() => buildExport(request({atlas})), /whole-boundary/);
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
  assert.match(html, /stays unchanged offline/);
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


test('research references require boolean opt-in; selected legacy drafts remain reviewable', () => {
  const atlas=atlasFixture();
  for(const consent of [undefined,false,'true',1])assert.throws(()=>buildExport(request({atlas,allowResearch:consent})),/explicit opt-in/);
  const draft=readDraft(JSON.stringify({ids:['a'],allowResearch:true}),atlas,'2026-09-22');
  assert.deepEqual(draft.ids,['a']);
  assert.equal(draft.allowResearch,undefined); // Consent never silently restores from saved data.
  assert.equal(buildExport(request({atlas,allowResearch:true})).counts.waypoints,1);
  assert.deepEqual(exportTargets(atlas.targets),[]);
  assert.match(exportEvidenceLabel(atlas.targets[0]),/Research coordinate.*not chart-depth qualified/);
});

test('measured scope preserves canonical publication and whole-reef screening gates', () => {
  const atlas=atlasFixture();atlas.targets[0].canonical_habitat=true;
  atlas.publication={status:'ready',expires_at:'2026-09-23T18:00:00Z'};
  assert.deepEqual(exportTargets(atlas.targets).map(t=>t.id),['a']);
  assert.deepEqual(exportTargets(atlas.targets,true).map(t=>t.id),['a','b']);
  assert.equal(buildExport(request({atlas,allowResearch:false})).counts.waypoints,1);
  atlas.publication.expires_at='2026-09-21T18:00:00Z';
  assert.throws(()=>buildExport(request({atlas,allowResearch:true})),/expired/);
  atlas.publication.expires_at='2026-09-23T18:00:00Z';
  assert.throws(()=>buildExport(request({atlas,allowResearch:true,screen:{...screenFixture(),geometryAllowed:()=>false}})),/whole-boundary/);
});


test('map and region presets include loaded measured reefs independently of legacy visible research',()=>{
 const targets=atlasFixture().targets;const measured={...targets[0],id:'canonical',canonical_habitat:true};
 const input={targets:[...targets,measured],visible:targets,contains:t=>t.id==='canonical'};
 assert.deepEqual(exportPresetTargets({...input,scope:'map'}).map(t=>t.id),['canonical']);
 assert.deepEqual(exportPresetTargets({...input,scope:'region'}).map(t=>t.id),['canonical']);
 assert.throws(()=>exportPresetTargets({...input,scope:'filtered'}),/explicit opt-in/);
 assert.deepEqual(exportPresetTargets({...input,scope:'filtered',allowResearch:true}).map(t=>t.id),['a','b']);
 assert.deepEqual(exportPresetTargets({...input,scope:'none'}),[]);
});

test('MLLW research waypoints retain explicit research class in GPX as well as notes',()=>{
 const atlas=atlasFixture();atlas.targets[0].vertical_datum='MLLW';
 const result=buildExport(request({atlas,allowResearch:true}));
 assert.match(result.gpx,/Research coordinate.*not chart-depth qualified/);
 assert.match(offlineNotes(result,REGION,{name:'test',date:'2026-09-22'}),/Research coordinate.*not chart-depth qualified/);
});

// U4: opt-in published depth-contour tracks (docs/chartplotter-export.md).
const {loadContourFile} = await import('../web/planner.ts');
const MORRO = JSON.parse(fs.readFileSync(new URL('../dist/regions/morro-bay/depth-contours.geojson', import.meta.url), 'utf8'));
const MORRO_REGION = {...REGION, id: 'morro-bay', name: 'Morro Bay'};
const contourRequest = overrides => request({
  region: MORRO_REGION, bounds: [-121.2, 35.1, -120.7, 35.6], layers: {...DEFAULT_LAYERS, outlines: true, alignments: true, exclusions: true},
  screen: screenFixture([exclusion('Morro', polygon(-121, 35.3, 0.1))]), ...overrides,
});
const count = (xml, re) => (xml.match(re) || []).length;
const indexFeatures = MORRO.features.filter(f => f.properties.kind === 'contour' && f.properties.index === true);

test('contour tracks are opt-in GPX tracks with provenance; off stays byte-identical', () => {
  const off = buildExport(contourRequest());
  assert.equal(off.gpx, buildExport(contourRequest({contours: undefined})).gpx);
  assert.equal(offlineNotes(off, MORRO_REGION, {name: 'n', date: '2026-09-22'}), offlineNotes(buildExport(contourRequest({contours: undefined})), MORRO_REGION, {name: 'n', date: '2026-09-22'}));
  assert.ok(!('contours' in off.counts) && !('contours' in off));
  const on = buildExport(contourRequest({contours: {collection: MORRO}}));
  assert.equal(indexFeatures.length, 6);
  assert.equal(on.counts.contours, 6);
  assert.equal(count(on.gpx, /<trk>/g), count(off.gpx, /<trk>/g) + 6);
  assert.equal(count(on.gpx, /<trk>/g), count(on.gpx, /<\/trk>/g));
  assert.equal(count(on.gpx, /<trkseg>/g), count(on.gpx, /<\/trkseg>/g));
  assert.ok(on.gpx.startsWith('<?xml version="1.0"') && on.gpx.includes('<gpx version="1.1"'));
  assert.doesNotMatch(on.gpx, /<rte/);
  const points = indexFeatures.reduce((n, f) => n + f.geometry.coordinates.flat().length, 0);
  assert.equal(on.counts.trackPoints, off.counts.trackPoints + points);
  assert.equal(on.counts.tracks, off.counts.tracks + 6);
  const descs = [...on.gpx.matchAll(/<name>\d+ ft contour · [^<]*<\/name><desc>([^<]*)<\/desc>/g)].map(m => m[1]);
  assert.equal(descs.length, 6);
  const names = MORRO.provenance.sources.map(s => s.name);
  for (const d of descs) assert.ok(names.some(n => d.startsWith(n)) && /Surveyed 2008\..*unverified source datum.*NOT FOR NAVIGATION\.$/.test(d), d);
  assert.doesNotMatch(descs.join(''), /Bound surveys not drawn/);
  const held = structuredClone(MORRO);
  held.provenance.sources_omitted = [{source_id: 'noaa-bag', review_status: 'candidate'}, {source_id: 'ok', review_status: 'approved'}];
  const withOmitted = buildExport(contourRequest({contours: {collection: held}}));
  assert.equal(count(withOmitted.gpx, /Bound surveys not drawn: noaa-bag \(candidate\) NOT FOR NAVIGATION/g), 6);
  const notes = offlineNotes(withOmitted, MORRO_REGION, {name: 'n', date: '2026-09-22'});
  assert.match(notes, /<h2>Depth contour tracks<\/h2>[\s\S]*noaa-bag \(candidate\)[\s\S]*not for navigation/);
});

test('no published contour file means no tracks and no error', async () => {
  const off = buildExport(contourRequest());
  const none = buildExport(contourRequest({contours: {collection: null}}));
  assert.equal(none.gpx, off.gpx);
  assert.equal(none.counts.contours, 0);
  assert.deepEqual(none.contours, []);
  const reply = (status, body) => async () => ({status, ok: status >= 200 && status < 300, json: async () => body});
  const page = () => 'https://skippercast.test/app/';
  assert.deepEqual(await loadContourFile('santa-cruz-monterey-bay', '2026-09-22', reply(404), page), {collection: null});
  assert.match((await loadContourFile('morro-bay', '2026-09-22', reply(500), page)).refused, /did not load/);
  assert.match((await loadContourFile('morro-bay', '2027-09-27', reply(200, MORRO), page)).refused, /withheld/);
  const urls = [];
  const drawn = await loadContourFile('morro-bay', '2026-09-22', async url => (urls.push(url), reply(200, MORRO)()), page);
  assert.deepEqual(urls, ['https://skippercast.test/app/regions/morro-bay/depth-contours.geojson']);
  assert.deepEqual(drawn, {collection: MORRO});
});

test('held or incomplete contour provenance is refused for the whole export', () => {
  const change = edit => { const c = structuredClone(MORRO); edit(c); return c; };
  const cases = [
    change(c => { c.publicationHeld = true; }),
    change(c => { c.features[3].properties.publicationHeld = false; }),
    change(c => { delete c.provenance.sources_omitted; }),
    change(c => { delete c.provenance; }),
    change(c => { c.provenance.sources[0].vertical_datum = ''; }),
    change(c => { c.provenance.region_id = 'cambria-san-simeon'; }),
  ];
  for (const collection of cases) assert.throws(() => buildExport(contourRequest({contours: {collection}})), /Depth contours cannot be exported/);
  assert.throws(() => buildExport(contourRequest({contours: {collection: MORRO}, now: new Date('2027-09-27T00:00:00Z')})), /Depth contours cannot be exported/);
});

function feetV2Fixture() {
  const identity = {survey_date: '2024', vertical_datum: 'MLLW'};
  const sources = [
    {...identity, source_id: 'native', name: 'Native survey', native_cell_m: 2},
    {...identity, source_id: 'coarse', name: 'Coarse survey', native_cell_m: 16},
  ];
  const index_depths_ft = [60, 150, 300];
  const run = (source_id, depth_ft, minzoom, lat, zoom = {}) => ({
    type: 'Feature', properties: {...identity, source_id, kind: 'contour', depth_ft,
      index: index_depths_ft.includes(depth_ft), estimated: true, minzoom, ...zoom},
    geometry: {type: 'LineString', coordinates: [[-121, lat], [-120.9, lat]]},
  });
  return {
    type: 'FeatureCollection',
    provenance: {region_id: MORRO_REGION.id, units: 'ft', set: 'ft-v2', shelf_limit_ft: 300, index_depths_ft,
      intervals: [
        {minzoom: 8, depths_ft: [60, 120, 180, 240, 300]},
        {minzoom: 11, depths_ft: [30, 90, 150, 210, 270]},
        {minzoom: 13, depths_ft: [10, 20, 40, 50, 70, 80, 100]},
        {minzoom: 15, depths_ft: [5, 15, 25], native_max_cell_m: 2},
      ], sources, review_expires: '2027-09-22',
      sources_omitted: [{source_id: 'held-grid', review_status: 'candidate'}, {source_id: 'approved-grid', review_status: 'approved'}]},
    features: [
      ...index_depths_ft.flatMap(depth => [
        run('native', depth, depth === 150 ? 11 : 8, 35.2, {maxzoom: 14}),
        run('coarse', depth, depth === 150 ? 11 : 8, 35.4),
        run('native', depth, 14, 35.3),
      ]),
      run('native', 5, 15, 35.21), run('coarse', 10, 13, 35.21),
      run('coarse', 30, 11, 35.21), run('coarse', 90, 11, 35.21),
    ],
  };
}

test('loadContourFile to GPX exports only the finest ft-v2 index tracks with source notes', async () => {
  const fixture = feetV2Fixture();
  const contours = await loadContourFile(MORRO_REGION.id, '2026-09-22',
    async () => new Response(JSON.stringify(fixture)), () => 'https://skippercast.test/app/');
  assert.ok(contours.collection, contours.refused);
  const result = buildExport(contourRequest({contours}));
  const tracks = [...result.gpx.matchAll(/<trk><name>(\d+ ft contour · [^<]+)<\/name><desc>([^<]*)<\/desc>(.*?)<\/trk>/g)];
  assert.equal(result.counts.contours, 6);
  const expected = [60, 150, 300].flatMap(depth => ['coarse', 'native'].map(source => `${depth} ft contour · ${source}`));
  assert.deepEqual(tracks.map(([, name]) => name).sort(), expected.sort());
  const notes = offlineNotes(result, MORRO_REGION, {name: 'test', date: '2026-09-22'});
  assert.match(notes, /<h2>Depth contour tracks<\/h2>.*Bound surveys not drawn: held-grid \(candidate\).*not for navigation/);
  assert.doesNotMatch(notes, /approved-grid/);
  for (const [, name, desc, segments] of tracks) {
    const native = name.endsWith('native'), lat = native ? 35.3 : 35.4;
    assert.deepEqual(segmentsIn(segments), [[[-121, lat], [-120.9, lat]]]);
    const source = native ? 'Native survey' : 'Coarse survey';
    assert.match(desc, /Surveyed 2024\..*MLLW.*estimated.*not a sounding or chart depth\. Lines stop where the reviewed survey grid stops\./);
    assert.ok(desc.startsWith(`${source}.`));
    assert.match(desc, /Bound surveys not drawn: held-grid \(candidate\) NOT FOR NAVIGATION\.$/);
    assert.ok(notes.includes(`<li>${name} · ${source}. Surveyed 2024; datum: MLLW.</li>`));
  }
  const onlySuperseded = buildExport(contourRequest({contours, bounds: [-121.1, 35.19, -120.8, 35.205]}));
  assert.equal(onlySuperseded.counts.contours, 0, 'coarse lines are not a fallback when native lines miss the bounds');
});

test('ft-v2 export refuses ambiguous runs and invalid metadata even outside the requested coverage', () => {
  const wrongSource = /Depth contours cannot be exported: a contour does not match its listed source\./;
  const wrongSet = /Depth contours cannot be exported: wrong region, units or interval\./;
  const wrongDepth = /Depth contours cannot be exported: a contour depth is not a multiple of 30 ft\./;
  for (const [label, edit, reason] of [
    ['duplicate finest run', c => c.features.push(c.features[2]), wrongSource],
    ['missing native run', c => c.features.splice(2, 1), wrongSource],
    ['non-native partner', c => { c.features[2].properties.minzoom = 8; }, wrongSource],
    ['mismatched survey date on bounded run', c => { c.features[0].properties.survey_date = '2023'; }, wrongSource],
    ['unlisted source', c => { c.features[2].properties.source_id = 'unknown'; }, wrongSource],
    ['incorrect datum', c => { c.features[2].properties.vertical_datum = 'NAVD88'; }, wrongSource],
    ['missing source field', c => { delete c.provenance.sources[0].name; }, /Depth contours cannot be exported: sources incomplete\./],
    ['missing omitted surveys', c => { delete c.provenance.sources_omitted; }, /Depth contours cannot be exported: omitted surveys not listed\./],
    ['expired review', c => { c.provenance.review_expires = '2026-09-21'; }, /Depth contours cannot be exported: source review expired or undated\./],
    ['wrong region', c => { c.provenance.region_id = 'different-region'; }, wrongSet],
    ['wrong units', c => { c.provenance.units = 'm'; }, wrongSet],
    ['interval_ft present', c => { c.provenance.interval_ft = 30; }, wrongSet],
    ['unknown set with otherwise v1 interval', c => Object.assign(c.provenance, {set: 'ft-v3', interval_ft: 30}), wrongSet],
    ['wrong shelf limit', c => { c.provenance.shelf_limit_ft = 600; }, wrongSet],
    ['wrong index depths', c => { c.provenance.index_depths_ft = [150, 60, 300]; }, wrongSet],
    ['flagged depth outside index set', c => { c.features[2].properties.depth_ft = 90; }, wrongDepth],
    ['index depth not flagged', c => { c.features[0].properties.index = false; }, wrongDepth],
  ]) {
    const collection = feetV2Fixture();
    edit(collection);
    assert.throws(() => buildExport(contourRequest({bounds: [0, 0, 1, 1], contours: {collection}})), reason, label);
  }
});

test('both contour sets refuse either hold key even when false or on a non-index line', () => {
  for (const fixture of [MORRO, feetV2Fixture()]) {
    for (const marker of ['publication_held', 'publicationHeld']) {
      const collection = structuredClone(fixture);
      const minor = collection.features.find(f => f.properties.kind === 'contour' && !f.properties.index);
      for (const record of [collection, collection.provenance, minor, minor.properties]) {
        record[marker] = false;
        assert.throws(() => buildExport(contourRequest({contours: {collection}})), /Depth contours cannot be exported: held or research material\./);
        delete record[marker];
      }
    }
  }
});

const SHA = 'a'.repeat(64);
const planWith = priorities => JSON.stringify({ids: ['a', 'ranked-only', 'a'], name: 'Keep me', date: '2028-02-29', avoidScope: 'region', rankedPlan: {sha256: SHA, species: 'reef', priorities}});

test('draft_null_priority_discards_whole_ranking, nonrecord entries too; independent fields survive', () => {
  const good = {id: 'ranked-only', rank: 1};
  for (const priorities of [[null], [good, null], [null, good], [good, {id: 'b', rank: 2}, null], [true], [7], ['x'], [[]], [{}], [{id: 'b'}], [{rank: 2}]]) {
    const draft = readDraft(planWith(priorities), atlasFixture(), '2026-09-22');
    assert.equal(draft.rankedPlan, null, JSON.stringify(priorities));
    assert.deepEqual(draft.ids, ['a'], 'ranked-only ids are dropped, atlas ids kept once');
    assert.equal(draft.name, 'Keep me');
    assert.equal(draft.date, '2028-02-29');
    assert.equal(draft.avoidScope, 'region');
  }
});

test('draft_valid_ranking_compatibility: valid and empty rankings are kept', () => {
  const kept = readDraft(planWith([{id: 'ranked-only', rank: 1}, {id: 'b', rank: 50}]), atlasFixture(), '2026-09-22');
  assert.equal(kept.rankedPlan.priorities.length, 2);
  assert.deepEqual(kept.ids, ['a', 'ranked-only']);
  assert.deepEqual(readDraft(planWith([]), atlasFixture(), '2026-09-22').rankedPlan.priorities, []);
  assert.equal(readDraft(planWith([{id: 'b', rank: 1}, {id: 'b', rank: 2}]), atlasFixture(), '2026-09-22').rankedPlan, null);
  assert.equal(readDraft(planWith([{id: 'b', rank: 1}, {id: 'c', rank: 1}]), atlasFixture(), '2026-09-22').rankedPlan, null);
  assert.equal(readDraft(planWith([{id: 'b', rank: 51}]), atlasFixture(), '2026-09-22').rankedPlan, null);
});
