import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';
import {featuresGPX} from '../dist/gpx.js';

// Synthetic, in-memory GPX only; any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const MALFORMED = 'Malformed XML entity reference', FORBIDDEN = 'XML-forbidden character reference';
const wrap = (body, creator = 't') => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="${creator}" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;
const wpt = (name = 'One', extra = '', attrs = '') => wrap(`<wpt lat="35" lon="-120"${attrs}><name>${name}</name>${extra}</wpt>`);
const problemsOf = (xml, n = 1, screen) => { const c = checkGpx(xml, {waypoints: n}, screen); return c.ok ? [] : c.problems; };
const clearScreen = () => ({ready: () => true, pointAllowed: () => true, geometryAllowed: () => true});

/** Every place a reference may sit, so one bad reference is rejected wherever it appears. */
const placements = ref => [
  ['wpt name', wpt(`a${ref}b`), 1],
  ['desc', wpt('One', `<desc>x ${ref} y</desc>`), 1],
  ['cmt', wpt('One', `<cmt>${ref}</cmt>`), 1],
  ['track name', wrap(`<trk><name>T${ref}</name><trkseg><trkpt lat="35" lon="-120"/></trkseg></trk>`), 0],
  ['creator attribute', wrap('', `c${ref}`), 0],
  ['extra quoted attribute', wpt('One', '', ` extra='${ref}'`), 1],
];

test('gpx_references_reject_unknown_and_unterminated', () => {
  for (const ref of ['&bogus;', '&AMP;', '&Amp;', 'x &', '&', '& rock', '&#;', '&#x;', '&#X41;', '&#+65;', '&#-65;', '&#x+41;', '&#65', '&#x41', '&amp', '&lt &gt;']) {
    for (const [where, xml, n] of placements(ref)) {
      const problems = problemsOf(xml, n);
      assert.ok(problems.includes(MALFORMED), `${ref} in ${where}: ${JSON.stringify(problems)}`);
    }
  }
  // Two bad references report one diagnostic.
  const twice = problemsOf(wpt('a &bogus; b &nope;', '<desc>& and &</desc>'));
  assert.equal(twice.filter(p => p === MALFORMED).length, 1);
  assert.equal(twice.length, 1);
  // A trailing ampersand at the very end of a value is still caught.
  assert.ok(problemsOf(wpt('end&')).includes(MALFORMED));
});

test('gpx_references_reject_forbidden_numeric_characters', () => {
  const bad = ['&#0;', '&#x0;', '&#1;', '&#x1;', '&#11;', '&#xB;', '&#12;', '&#31;', '&#x1F;', '&#xD800;', '&#55296;', '&#xDFFF;', '&#xFFFE;', '&#65535;', '&#xFFFF;', '&#1114112;', '&#x110000;', '&#8;',
    `&#${'9'.repeat(400)};`, `&#x${'F'.repeat(400)};`, `&#${'0'.repeat(300)}0;`, `&#x${'0'.repeat(300)}D800;`];
  for (const ref of bad) {
    for (const [where, xml, n] of placements(ref)) {
      let problems;
      assert.doesNotThrow(() => { problems = problemsOf(xml, n); }, `${ref} in ${where}`);
      assert.ok(problems.includes(FORBIDDEN), `${ref.slice(0, 20)} in ${where}: ${JSON.stringify(problems)}`);
      assert.ok(!problems.includes(MALFORMED), `${ref.slice(0, 20)} in ${where} is well formed but forbidden`);
    }
  }
});

test('gpx_references_preserve_valid_character_edges', () => {
  const good = ['&#9;', '&#x9;', '&#10;', '&#xA;', '&#13;', '&#xd;', '&#32;', '&#x20;', '&#xD7FF;', '&#55295;', '&#xE000;', '&#57344;', '&#xFFFD;', '&#65533;', '&#x10000;', '&#65536;', '&#x10FFFF;', '&#1114111;',
    '&#0000065;', '&#x0000041;', '&#xaBcD;', '&#xABCDE;', '&#x1F41F;', `&#${'0'.repeat(300)}65;`, '&amp;', '&lt;', '&gt;', '&quot;', '&apos;', '&amp;&lt;&gt;&quot;&apos;'];
  for (const ref of good) {
    for (const [where, xml, n] of placements(`x${ref}y`)) assert.deepEqual(problemsOf(xml, n), [], `${ref} in ${where}`);
  }
  // Whitespace references inside otherwise nonempty text, and a supplementary character written directly.
  assert.deepEqual(problemsOf(wpt('a&#9;b&#10;c&#13;d')), []);
  assert.deepEqual(problemsOf(wpt('Fish \u{1F41F} &#x1F41F;')), []);
});

test('gpx_reference_decode_is_single_pass', () => {
  // Escaped ampersands are plain text, never decoded a second time.
  assert.deepEqual(problemsOf(wpt('&amp;#0;', '<desc>&amp;bogus; &amp;#xD800; &amp;amp;</desc>')), []);
  assert.deepEqual(problemsOf(wpt('&lt;name&gt;')), []);
  assert.deepEqual(problemsOf(wpt('x', '', ' extra="&amp;#0; &amp;nope;"')), []);
  // A decoded numeric character still collides with the literal one; an escaped reference does not.
  const two = (a, b) => wrap(`<wpt lat="35" lon="-120"><name>${a}</name></wpt><wpt lat="36" lon="-120"><name>${b}</name></wpt>`);
  for (const [a, b] of [['A', '&#65;'], ['A', '&#x41;'], ['&#65;', '&#x61;'], ['a b', 'A&#32;B'], ['R&amp;D', 'r&#38;d'], ['R&amp;D', 'r&#x26;D'], ['&lt;x&gt;', '&#60;X&#62;']]) {
    assert.ok(problemsOf(two(a, b), 2).includes('Duplicate waypoint name'), `${a} vs ${b}`);
  }
  for (const [a, b] of [['&amp;#65;', 'A'], ['&amp;#65;', '&#65;'], ['&amp;lt;', '&lt;'], ['&amp;amp;', '&amp;']]) {
    assert.deepEqual(problemsOf(two(a, b), 2), [], `${a} vs ${b}`);
  }
  // A custom entity is never expanded, even when declared.
  const dtd = '<?xml version="1.0"?>\n<!DOCTYPE gpx [<!ENTITY boat "Reel">]>\n<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="35" lon="-120"><name>&boat;</name></wpt></gpx>';
  assert.ok(problemsOf(dtd).includes(MALFORMED));
});

test('gpx_reference_validation_preserves_screen_contract', () => {
  const bad = wpt('a &bogus;'), forbidden = wpt('a &#0;');
  for (const xml of [bad, forbidden]) {
    const withScreen = checkGpx(xml, {waypoints: 1}, clearScreen());
    assert.equal(withScreen.ok, false); assert.equal(withScreen.screen.length, 1);
    assert.equal(withScreen.screen[0].screened, true); assert.equal(withScreen.screen[0].inside, false);
    const without = checkGpx(xml, {waypoints: 1});
    assert.equal(without.ok, false); assert.equal(without.screen[0].screened, false);
  }
  assert.deepEqual(problemsOf(bad), [MALFORMED]);
  assert.deepEqual(problemsOf(forbidden), [FORBIDDEN]);
  // Valid references do not change the screen result.
  const ok = checkGpx(wpt('a &amp; b'), {waypoints: 1}, clearScreen());
  assert.equal(ok.ok, true); assert.equal(ok.screen[0].screened, true);
  // A null screen still refuses; inside and unchecked waypoints are still refused with valid references present.
  assert.deepEqual(problemsOf(wpt('a &amp; b'), 1, null), ['Protected areas not checked']);
  const refusing = {ready: () => true, pointAllowed: () => false, geometryAllowed: () => true};
  assert.ok(problemsOf(wpt('a &amp; b'), 1, refusing).some(p => p.startsWith('Inside or near')));
  // Both a reference problem and a screen refusal are reported together.
  const both = problemsOf(bad, 1, refusing);
  assert.ok(both.includes(MALFORMED) && both.some(p => p.startsWith('Inside or near')));
  // Reference tracks stay structural: valid AVOID and contour tracks pass even with a refusing screen; a bad reference in one fails.
  const track = (name, desc) => wrap(`<trk><name>${name}</name><desc>${desc}</desc><trkseg><trkpt lat="35" lon="-120"/></trkseg></trk>`);
  assert.deepEqual(problemsOf(track('AVOID: A &amp; B', 'outline &lt;ref&gt;'), 0, refusing), []);
  assert.deepEqual(problemsOf(track('Contour 30 ft', 'depth'), 0, refusing), []);
  assert.deepEqual(problemsOf(track('AVOID: A & B', 'outline'), 0, refusing), [MALFORMED]);
  assert.deepEqual(problemsOf(track('Contour', 'x &#1;'), 0), [FORBIDDEN]);
  // Existing coordinate diagnostics are unchanged by reference scanning.
  assert.deepEqual(problemsOf(wpt('One', '', ' lat="91"')), ['Invalid wpt lat']);
});

test('gpx_reference_validation_keeps_generated_export_bytes_valid', () => {
  const user = (name, id) => ({name, id, latitude: 35.1, longitude: -120.2, user_waypoint: true, category: 'other'});
  const points = [user('Tom & Jerry\'s "rock" <1>', 'u1'), user('Fish \u{1F41F}', 'u2'), user('A & B', 'u3')];
  const xml = featuresGPX({}, {selected: points, waypoints: points, areas: [], drifts: []}, 'Day & "night" <trip>');
  assert.match(xml, /&amp;/);
  const c = checkGpx(xml, {waypoints: 3});
  assert.equal(c.ok, true, JSON.stringify(c));
  assert.equal(checkGpx(xml, {waypoints: 3}, clearScreen()).ok, true);
  // The checker does not mutate or repair the bytes it reads.
  const before = xml.slice();
  checkGpx(xml, {waypoints: 3});
  assert.equal(xml, before);
});
