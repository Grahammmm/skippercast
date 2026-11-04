import test from 'node:test';
import assert from 'node:assert/strict';
import {featuresGPX} from '../dist/gpx.js';
import {checkGpx} from '../web/gpx-check.ts';

const user = (name, id) => ({name, id, latitude: 0, longitude: 0, user_waypoint: true, category: 'other'});
const atlasPoint = (name, id) => ({name, id, latitude: 0, longitude: 0, neighborhood_depth_ft: [100, 200]});
function output(points, options = {}) {
  const xml = featuresGPX({}, {selected: points, waypoints: points, areas: [], drifts: []}, 'Day', options);
  assert.deepEqual(checkGpx(xml, {waypoints: points.length}), {ok: true,
    screen: Array(points.length).fill({inside: false, name: null, distanceM: null, screened: false})});
  return xml;
}
const names = xml => [...xml.matchAll(/<wpt[^>]*><name>(.*?)<\/name>/g)].map(m => m[1]);

for (const [label, dirty] of [
  ['trailing whitespace', 'Reef '], ['C0 control', 'Reef\u0001'],
  ['U+FFFE', 'Reef\uFFFE'], ['U+FFFF', 'Reef\uFFFF'],
  ['lone high surrogate', 'Re\uD800ef'], ['lone low surrogate', 'Re\uDC00ef'],
]) {
  test(`${label} is removed before case-insensitive uniqueness`, () => {
    assert.deepEqual(names(output([user('Reef', 'u1'), user(dirty, 'u2'), user('reef (2)', 'u3')])),
      ['Reef', 'Reef (2)', 'reef (2) (2)']);
    assert.deepEqual(names(output([user(dirty, 'u1')])), ['Reef']);
  });
}
test('blank, absent and forbidden-only atlas names use unique Waypoint defaults', () => {
  const points = ['   ', '   ', '', null, undefined, '\u0001\uFFFE\uFFFF\uD800'];
  assert.deepEqual(names(output(points.map((n, i) => atlasPoint(n, `a${i}`)))),
    ['Waypoint', 'Waypoint (2)', 'Waypoint (3)', 'Waypoint (4)', 'Waypoint (5)', 'Waypoint (6)']);
});
test('valid surrogate pairs and XML escaping survive cleaning and deduplication', () => {
  assert.deepEqual(names(output([user('  Reef 😀 & <rock>  ', 'u1'), user('Reef 😀 & <rock>', 'u2')])),
    ['Reef 😀 &amp; &lt;rock&gt;', 'Reef 😀 &amp; &lt;rock&gt; (2)']);
});
test('ranked plotter names collide with cleaned user names while cmt ids stay unchanged', () => {
  const ranked = {...atlasPoint('Atlas name', 'atlas:id'), trip_rank: 1, trip_species: 'reef'};
  for (const points of [[ranked, user(' 01 Reef 100-200ft\u0001 ', 'user:id')],
    [user(' 01 Reef 100-200ft\u0001 ', 'user:id'), ranked]]) {
    const xml = output(points);
    assert.deepEqual(names(xml), ['01 Reef 100-200ft', '01 Reef 100-200ft (2)']);
    assert.deepEqual([...xml.matchAll(/<cmt>(.*?)<\/cmt>/g)].map(m => m[1]), points.map(p => p.id));
  }
});
test('XML cleaning also applies to track names and other exported text without trimming it', () => {
  const xml = output([user('Reef', ' id\uFFFF ')], {exclusions: [{properties: {NAME: 'Closure\uFFFF', FULLNAME: 'Full\uFFFE\uD800😀'},
    geometry: {type: 'LineString', coordinates: [[0, 0], [1, 1]]}}]});
  assert.match(xml, /<name>AVOID Closure<\/name>/);
  assert.match(xml, /<cmt> id <\/cmt>/);
  assert.match(xml, /Full😀/);
  assert.doesNotMatch(xml, /[\uFFFE\uFFFF\uD800]/u);
});
test('clean-name synthetic export is byte-identical to main before this change', () => {
  const xml = output([user('Reef & rock', 'u1'), user('Launch 😀', 'u2')]);
  const golden = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<gpx version=\"1.1\" creator=\"SkipperCast\" xmlns=\"http://www.topografix.com/GPX/1/1\"><metadata><name>Day</name><desc>WGS84 coordinates. Habitat research; tracks show outlines and structure alignments, not navigation routes. Check current rules and charted hazards.</desc></metadata><wpt lat=\"0\" lon=\"0\"><name>Reef &amp; rock</name><cmt>u1</cmt><desc>User waypoint. User-supplied label; not verified habitat, depth or navigation guidance. Check current regulations, closures, conditions and official charts.</desc><type>other</type></wpt><wpt lat=\"0\" lon=\"0\"><name>Launch 😀</name><cmt>u2</cmt><desc>User waypoint. User-supplied label; not verified habitat, depth or navigation guidance. Check current regulations, closures, conditions and official charts.</desc><type>other</type></wpt></gpx>\n";
  assert.equal(xml, golden);
});
