import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';

// Synthetic, in-memory GPX only; any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const wrap = (body) => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;
const wpt = (attrs, name = 'One') => wrap(`<wpt${attrs}><name>${name}</name></wpt>`);
const trk = (attrs) => wrap(`<trk><name>T</name><trkseg><trkpt${attrs}/></trkseg></trk>`);
const problemsOf = (xml, n = 1) => { const c = checkGpx(xml, {waypoints: n}); return c.ok ? [] : c.problems; };
// A synthetic screen that refuses latitude 35 or longitude -121 and records every point it is asked about.
function screenSeen() {
  const seen = [];
  return {seen, ready: () => true, pointAllowed: (p) => { seen.push(p); return p.latitude !== 35 && p.longitude !== -121; }, geometryAllowed: () => true};
}

test('coordinate_attributes_require_exact_unqualified_names', () => {
  for (const tag of ['wpt', 'trkpt']) {
    const make = (attrs) => tag === 'wpt' ? wpt(attrs) : trk(attrs);
    const n = tag === 'wpt' ? 1 : 0;
    for (const decoy of ['data-lat', 'x:lat', 'LAT', 'Lat']) {
      assert.ok(problemsOf(make(` ${decoy}="35" lon="-120"`), n).includes(`Invalid ${tag} lat`), `${tag} ${decoy}`);
    }
    for (const decoy of ['data-lon', 'x:lon', 'LON']) {
      assert.ok(problemsOf(make(` lat="35" ${decoy}="-120"`), n).includes(`Invalid ${tag} lon`), `${tag} ${decoy}`);
    }
    // Coordinate-looking text inside another attribute's value never counts.
    assert.ok(problemsOf(make(` note='lat="35" lon="-120"'`), n).includes(`Invalid ${tag} lat`));
    assert.ok(problemsOf(make(` note='lat="35" lon="-120"'`), n).includes(`Invalid ${tag} lon`));
    assert.ok(problemsOf(make(` note="x lat='35'" lat="" lon="-120"`), n).includes(`Invalid ${tag} lat`));
    // Unknown well-formed attributes plus genuine coordinates stay accepted.
    assert.equal(checkGpx(make(` data-lat="-35" extra="a lat='9'" lat="35" x:lon="1" lon="-120"`), {waypoints: n}).ok, true, tag);
  }
});

test('coordinate_attributes_reject_duplicates_and_malformed_tokens', () => {
  for (const tag of ['wpt', 'trkpt']) {
    const make = (attrs) => tag === 'wpt' ? wpt(attrs) : trk(attrs);
    const n = tag === 'wpt' ? 1 : 0;
    for (const attrs of [' lat="35" lat="35" lon="-120"', ' lat="35" lat="91" lon="-120"', ' lat="91" lat="35" lon="-120"']) {
      assert.ok(problemsOf(make(attrs), n).includes(`Invalid ${tag} lat`), attrs);
    }
    for (const attrs of [' lat="35" lon="-120" lon="-120"', ' lon="-120" lat="35" lon="1"']) {
      assert.ok(problemsOf(make(attrs), n).includes(`Invalid ${tag} lon`), attrs);
    }
    for (const attrs of [' lat=35 lon="-120"', ' lat="35 lon="-120"', ' lat="35"lon="-120"', ' lat lon="-120"', ' lat="35" lon="-120" "']) {
      const p = problemsOf(make(attrs), n);
      assert.ok(p.includes(`Malformed ${tag} attributes`), `${attrs} ${p}`);
      assert.equal(checkGpx(make(attrs), {waypoints: n}).ok, false);
    }
    // Missing and blank keep the existing wording.
    assert.ok(problemsOf(make(' lon="-120"'), n).includes(`Invalid ${tag} lat`));
    assert.ok(problemsOf(make(' lat="35"'), n).includes(`Invalid ${tag} lon`));
    assert.ok(problemsOf(make(' lat="  " lon="-120"'), n).includes(`Invalid ${tag} lat`));
    // Single or double quotes, attribute order and extra whitespace are all fine.
    for (const attrs of [" lat='35' lon='-120'", ' lon="-120"   lat = "35"', '\n lat="35"\t lon="-120" ']) {
      assert.equal(checkGpx(make(attrs), {waypoints: n}).ok, true, attrs);
    }
  }
});

test('screen_uses_the_validated_actual_coordinate_pair', () => {
  // A decoy before or after the real attribute must not change the screened pair.
  for (const attrs of [' data-lat="-35" lat="35" lon="-120"', ' lat="35" data-lat="-35" lon="-120"']) {
    const s = screenSeen(), c = checkGpx(wpt(attrs), {waypoints: 1}, s);
    assert.deepEqual(s.seen, [{longitude: -120, latitude: 35}], attrs);
    assert.equal(c.ok, false);
    assert.ok(c.problems.some(p => p.startsWith('Inside or near')), JSON.stringify(c));
  }
  for (const attrs of [' data-lon="120" lat="10" lon="-121"', ' lat="10" lon="-121" data-lon="120"']) {
    const s = screenSeen(), c = checkGpx(wpt(attrs), {waypoints: 1}, s);
    assert.deepEqual(s.seen, [{longitude: -121, latitude: 10}], attrs);
    assert.equal(c.ok, false);
  }
  // A genuinely clear pair with decoys still passes, and the verdict is for that pair.
  const s = screenSeen(), c = checkGpx(wpt(' data-lat="35" lat="34" lon="-120"'), {waypoints: 1}, s);
  assert.equal(c.ok, true);
  assert.deepEqual(s.seen, [{longitude: -120, latitude: 34}]);
  assert.deepEqual(c.screen.map(v => v.screened), [true]);
});

test('coordinate_attribute_contract_preserves_edges', () => {
  for (const [lat, lon] of [['90', '180'], ['-90', '-180'], ['0', '0']]) {
    assert.equal(checkGpx(wpt(` lat="${lat}" lon="${lon}"`), {waypoints: 1}).ok, true, `${lat},${lon}`);
  }
  for (const bad of ['', 'NaN', 'Infinity', '-Infinity', '90.0001', '-91', 'abc']) {
    assert.ok(problemsOf(wpt(` lat="${bad}" lon="0"`)).includes('Invalid wpt lat'), `lat ${bad}`);
  }
  for (const bad of ['', 'NaN', 'Infinity', '180.5', '-181']) {
    assert.ok(problemsOf(wpt(` lat="0" lon="${bad}"`)).includes('Invalid wpt lon'), `lon ${bad}`);
  }
  // Without a screen only the structure is checked; one verdict per waypoint, unscreened.
  const plain = checkGpx(wpt(' lat="35" lon="-120"'), {waypoints: 1});
  assert.deepEqual(plain.screen.map(v => v.screened), [false]);
  assert.equal(plain.ok, true);
  // A null (not loaded) screen refuses.
  const nulled = checkGpx(wpt(' lat="35" lon="-120"'), {waypoints: 1}, null);
  assert.equal(nulled.ok, false);
  assert.ok(nulled.problems.includes('Protected areas not checked'));
  // An invalid or malformed waypoint is never screened clear and never returns ok.
  for (const attrs of [' lat="35" lat="35" lon="-120"', ' data-lat="35" lon="-120"', ' lat=35 lon="-120"']) {
    const s = screenSeen(), c = checkGpx(wpt(attrs), {waypoints: 1}, s);
    assert.equal(c.ok, false, attrs);
    assert.deepEqual(s.seen, [], attrs);
    assert.deepEqual(c.screen.map(v => v.screened), [false], attrs);
  }
  // One verdict per opening waypoint; a bad one does not borrow its neighbour's coordinates.
  const two = wrap('<wpt data-lat="35" lat="34" lon="-120"><name>A</name></wpt><wpt lon="-120"><name>B</name></wpt>');
  const s2 = screenSeen(), c2 = checkGpx(two, {waypoints: 2}, s2);
  assert.equal(c2.ok, false);
  assert.equal(c2.screen.length, 2);
  assert.deepEqual(s2.seen, [{longitude: -120, latitude: 34}]);
  // Track points are structurally checked only: they add no waypoint verdicts and are not screened.
  const s3 = screenSeen(), c3 = checkGpx(wrap('<wpt lat="34" lon="-120"><name>A</name></wpt><trk><name>T</name><trkseg><trkpt lat="35" lon="-120"/></trkseg></trk>'), {waypoints: 1}, s3);
  assert.equal(c3.ok, true);
  assert.equal(c3.screen.length, 1);
  assert.deepEqual(s3.seen, [{longitude: -120, latitude: 34}]);
});

// A screen that clears every pair and records what it was asked about.
function clearScreen() {
  const seen = [];
  return {seen, ready: () => true, pointAllowed: (p) => { seen.push(p); return true; }, geometryAllowed: () => true};
}
const NONDECIMAL = ['0x23', '0X23', '0b100011', '0B100011', '0o43', '0O43', '35e0', '3.5E1', '1e-7', '-1E-7', '3.5e+1', '35E-0', '+35e0'];
const both = (tag, lat, lon) => { const attrs = ` lat=\"${lat}\" lon=\"${lon}\"`; return tag === 'wpt' ? wpt(attrs) : trk(attrs); };

test('javascript_radices_and_scientific_notation_are_not_gpx_decimals', () => {
  for (const tag of ['wpt', 'trkpt']) {
    const n = tag === 'wpt' ? 1 : 0;
    for (const bad of NONDECIMAL) {
      const onLat = problemsOf(both(tag, bad, '-120'), n), onLon = problemsOf(both(tag, '35', bad.startsWith('-') || bad.startsWith('+') ? bad : `-${bad}`), n);
      assert.ok(onLat.includes(`Invalid ${tag} lat`), `${tag} lat ${bad}: ${onLat}`);
      assert.ok(!onLat.includes(`Invalid ${tag} lon`), `${tag} lat ${bad} must not blame lon`);
      assert.ok(onLon.includes(`Invalid ${tag} lon`), `${tag} lon ${bad}: ${onLon}`);
      assert.ok(!onLon.includes(`Invalid ${tag} lat`), `${tag} lon ${bad} must not blame lat`);
    }
    // A valid neighbouring decimal point does not authorize them.
    assert.ok(problemsOf(both(tag, '35.5e0', '-120'), n).includes(`Invalid ${tag} lat`));
  }
});

test('ordinary_xml_decimal_spellings_are_preserved', () => {
  const spellings = [['+35', 35], ['035', 35], ['35.', 35], ['.5', 0.5], ['-.5', -0.5], ['-0', -0], ['0', 0], [' 34.5 ', 34.5], ['\t34.5\n', 34.5], ['0.0000001', 1e-7], ['-0.0000001', -1e-7]];
  for (const [text, expected] of spellings) {
    const s = clearScreen(), c = checkGpx(wpt(` lat=\"${text}\" lon=\"${text}\"`), {waypoints: 1}, s);
    assert.equal(c.ok, true, `wpt ${JSON.stringify(text)}: ${JSON.stringify(c)}`);
    assert.equal(s.seen.length, 1, text);
    assert.equal(s.seen[0].latitude, expected, `latitude ${text}`);
    assert.equal(s.seen[0].longitude, expected, `longitude ${text}`);
    assert.equal(checkGpx(trk(` lat=\"${text}\" lon=\"${text}\"`), {waypoints: 0}).ok, true, `trkpt ${JSON.stringify(text)}`);
  }
  // Tiny decimals are never rounded to zero.
  const s = clearScreen();
  checkGpx(wpt(' lat=\"0.0000001\" lon=\"-120\"'), {waypoints: 1}, s);
  assert.notEqual(s.seen[0].latitude, 0);
});

test('invalid_lexical_token_is_never_screened_clear', () => {
  const good = '<wpt lat=\"34\" lon=\"-120\"><name>Good</name></wpt>', bad = '<wpt lat=\"0x23\" lon=\"-120\"><name>Bad</name></wpt>';
  for (const [label, body] of [['bad first', bad + good], ['bad second', good + bad]]) {
    const s = clearScreen(), c = checkGpx(wrap(body), {waypoints: 2}, s);
    assert.equal(c.ok, false, label);
    assert.ok(c.problems.includes('Invalid wpt lat'), label);
    assert.equal(c.screen.length, 2, label);
    assert.equal(s.seen.length, 1, `${label}: only the valid sibling is screened`);
    assert.deepEqual(s.seen[0], {longitude: -120, latitude: 34}, label);
  }
  // Exponent in longitude: same refusal, no borrowing of the valid latitude.
  const s2 = clearScreen(), c2 = checkGpx(wpt(' lat=\"34\" lon=\"-1.2e2\"'), {waypoints: 1}, s2);
  assert.equal(c2.ok, false);
  assert.deepEqual(s2.seen, []);
  assert.deepEqual(c2.screen.map(v => v.screened), [false]);
});

test('track_only_lexical_refusal_is_structural', () => {
  for (const bad of ['0x23', '35e0', '0b11', '0o43']) {
    const s = clearScreen(), c = checkGpx(trk(` lat=\"${bad}\" lon=\"-120\"`), {waypoints: 0}, s);
    assert.equal(c.ok, false, bad);
    assert.ok(c.problems.includes('Invalid trkpt lat'), `${bad}: ${c.problems}`);
    assert.ok(!c.problems.includes('Waypoint count mismatch'), bad);
    assert.deepEqual(s.seen, [], bad);
    assert.equal(c.screen.length, 0, bad);
  }
});
