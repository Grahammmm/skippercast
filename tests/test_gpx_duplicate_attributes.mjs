import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';

// Synthetic, in-memory GPX only; any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const DUP = 'Duplicate XML attribute';
const NS = 'xmlns="http://www.topografix.com/GPX/1/1"';
const wrap = (body, root = `version="1.1" creator="t" ${NS}`) => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx ${root}>${body}</gpx>`;
const wpt = (inner = '<name>One</name>', attrs = '', root) => wrap(`<wpt lat="35" lon="-120"${attrs}>${inner}</wpt>`, root);
const trk = (attrs = '', seg = '') => wrap(`<trk><name>T</name><trkseg><trkpt lat="35" lon="-120"${attrs}/>${seg}</trkseg></trk>`);
const problemsOf = (xml, n = 1, screen) => { const c = checkGpx(xml, {waypoints: n}, screen); return c.ok ? [] : c.problems; };
const generic = (xml, n = 1) => problemsOf(xml, n).filter(p => p === DUP);

test('duplicate_unhandled_attributes_are_refused', () => {
  const cases = [
    [wpt('<name>One</name>', '', `version="1.1" creator="a" creator="b" ${NS}`), 1],
    [wpt('<name>One</name>', ' extra="a" extra="b"'), 1],
    [wpt('<name extra="a" extra="b">One</name>'), 1],
    [wpt('<name>One</name><desc extra="a" extra="a">d</desc>'), 1],
    [wpt('<name>One</name><cmt extra="a" extra="b">d</cmt>'), 1],
    [wpt('<name>One</name>', " extra='a' extra=\"b\""), 1],
    [wpt('<name>One</name>', " extra='a' extra='a'"), 1],
    [wpt('<name>One</name>', ' extra="b" other="x" extra="a"'), 1],
    [wpt('<name>One</name>', '', `version="1.1" ${NS} xmlns:a="u" xmlns:a="v"`), 1],
    [wrap('<trk extra="a" extra="b"><name>T</name></trk>'), 0],
    [trk(' extra="a" extra="b"'), 0],
    [wrap('<trk><name>T</name><trkseg><trkpt lat="35" lon="-120"/><trkpt lat="35" lon="-120" extra="a" extra="b"/></trkseg></trk>'), 0],
    [wpt('<name>One</name><extensions/>', ' extra="a" extra="b"'), 1],
  ];
  cases.forEach(([xml, n], i) => {
    const c = checkGpx(xml, {waypoints: n});
    assert.equal(c.ok, false, `case ${i}`);
    assert.equal(c.problems.filter(p => p === DUP).length, 1, `case ${i}: ${c.problems}`);
  });
  // Self-closing element with a duplicate.
  assert.deepEqual(problemsOf(wrap('<wpt lat="35" lon="-120" extra="a" extra="b"/>'), 1).includes(DUP), true);
  // Multiple duplicated names still give one generic diagnostic.
  assert.deepEqual(generic(wpt('<name>One</name>', ' a="1" a="2" b="1" b="2"')), [DUP]);
});

test('duplicate_detection_is_token_and_element_scoped', () => {
  const ok = [
    wpt('<name>One</name><desc extra="a">x</desc>', ' extra="a"'),
    wpt('<name>One</name>', ' extra="a" other="b"'),
    wpt('<name>One</name>', ' note=\'extra="b"\' extra="a"'),
    wpt('<name>One</name>', ' extra="a" Extra="b"'),
    wpt('<name>One</name>', ' x:extra="a" y:extra="b"'),
  ];
  ok.forEach((xml, i) => assert.equal(checkGpx(xml, {waypoints: 1}).ok, true, `ok ${i}`));
});

test('existing_duplicate_coordinate_and_identity_diagnostics_stay_exact', () => {
  for (const axis of ['lat', 'lon']) {
    const wptXml = wrap(`<wpt lat="35" lon="-120" ${axis}="1"><name>One</name></wpt>`);
    assert.deepEqual(problemsOf(wptXml), [`Invalid wpt ${axis}`]);
    const trkXml = wrap(`<trk><name>T</name><trkseg><trkpt lat="35" lon="-120" ${axis}="1"/></trkseg></trk>`);
    assert.deepEqual(problemsOf(trkXml, 0), [`Invalid trkpt ${axis}`]);
  }
  for (const attr of ['version="1.1"', NS]) {
    assert.deepEqual(problemsOf(wpt('<name>One</name>', '', `version="1.1" ${NS} ${attr}`)), ['Expected GPX 1.1 root']);
  }
  // Mixed: a new duplicate plus a coordinate error reports both categories.
  const mixed = wrap('<wpt lat="35" lat="36" lon="-120" extra="a" extra="b"><name>One</name></wpt>');
  assert.deepEqual([...problemsOf(mixed)].sort(), [DUP, "Invalid wpt lat"]);
});

test('attribute_refusal_preserves_other_validation', () => {
  assert.equal(checkGpx(wpt('<name>One</name>', ' note="a&#x41;&amp;b"'), {waypoints: 1}).ok, true);
  const bad = problemsOf(wpt('<name>One</name>', ' extra="a&bogus;" extra="b"'));
  assert.ok(bad.includes('Malformed XML entity reference') && bad.includes(DUP), String(bad));
  // Screen verdicts are still collected for a duplicate-attribute file.
  const xml = wpt('<name>One</name>', ' extra="a" extra="b"');
  const screen = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true};
  const c = checkGpx(xml, {waypoints: 1}, screen);
  assert.equal(c.ok, false);
  assert.equal(c.screen.length, 1);
  assert.equal(c.screen[0].screened, true);
  const clear = checkGpx(wpt(), {waypoints: 1}, screen);
  assert.equal(clear.ok, true);
  // Input is a primitive string and is unchanged.
  const before = xml;
  checkGpx(xml, {waypoints: 1});
  assert.equal(xml, before);
});
