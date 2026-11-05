import test from 'node:test';
import assert from 'node:assert/strict';
import {readGpxWaypoints, MAX_GPX_BYTES, MAX_GPX_POINTS} from '../web/gpx-waypoints.ts';

// Synthetic, in-memory GPX only (no customer files); any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const NS10 = 'http://www.topografix.com/GPX/1/0', NS11 = 'http://www.topografix.com/GPX/1/1';
const gpx11 = (body, attrs = '') => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="t" xmlns="${NS11}"${attrs}>${body}</gpx>`;
const wpt = (lat, lon, inner = '') => `<wpt lat="${lat}" lon="${lon}">${inner}</wpt>`;
const ok = xml => { const r = readGpxWaypoints(xml); assert.equal(r.ok, true, JSON.stringify(r)); return r; };
const code = xml => { const r = readGpxWaypoints(xml); assert.equal(r.ok, false, 'expected a fatal error'); return r.error.code; };
const same = (a, b, msg) => assert.ok(JSON.stringify(a) === JSON.stringify(b), `${msg}: ${JSON.stringify(a)}`);

test('gpx_waypoints_vendor_styles', () => {
  const garmin = `<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<gpx xmlns="${NS11}" xmlns:gpxx="http://www.garmin.com/xmlschemas/GpxExtensions/v3" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.1" creator="Garmin">
<metadata><name>Marks</name><desc>not a waypoint note</desc></metadata>
<wpt lat="34.4012" lon="-119.7123"><ele>5</ele><time>2026-01-02T03:04:05Z</time><name>Rock Pile</name><sym>Fishing Hot Spot Facility</sym>
<extensions><gpxx:WaypointExtension><gpxx:DisplayMode>SymbolAndName</gpxx:DisplayMode></gpxx:WaypointExtension></extensions></wpt>
<wpt lat="34.5" lon="-120.25"><name>Kelp &amp; Reef</name><desc>Sea bass &lt;late&gt;</desc><cmt>ignored comment</cmt></wpt></gpx>`;
  same(ok(garmin).waypoints, [{name: 'Rock Pile', lat: 34.4012, lon: -119.7123, note: null}, {name: 'Kelp & Reef', lat: 34.5, lon: -120.25, note: 'Sea bass <late>'}], 'garmin');
  assert.deepEqual(ok(garmin).rejected, []);

  const lowrance = `<?xml version='1.0'?><gpx version='1.0' creator='Lowrance' xmlns='${NS10}'><wpt lat='33.1' lon='-117.5'><name>Wreck 1</name><cmt>from cmt</cmt></wpt>
<wpt lat='33.2' lon='-117.6'><name>Wreck 2</name></wpt><rte><name>R</name><rtept lat='33.3' lon='-117.7'><name>Leg</name></rtept></rte></gpx>`;
  const l = ok(lowrance);
  same(l.waypoints, [{name: 'Wreck 1', lat: 33.1, lon: -117.5, note: 'from cmt'}, {name: 'Wreck 2', lat: 33.2, lon: -117.6, note: null}], 'lowrance');
  same(l.rejected, [{index: 3, element: 'rtept', name: 'Leg', reason: 'route-point-not-imported'}], 'route point listed, not imported');

  const navionics = `<gpx:gpx xmlns:gpx="${NS11}" version="1.1" creator="Navionics"><gpx:wpt lat="32.9" lon="-117.3"><gpx:name>Drop off</gpx:name><gpx:desc><![CDATA[1 <fathom> & more]]></gpx:desc></gpx:wpt>
<gpx:rte><gpx:rtept lat="32.8" lon="-117.2"/><gpx:rtept lat="32.7" lon="-117.1"><gpx:name>B</gpx:name></gpx:rtept></gpx:rte></gpx:gpx>`;
  const n = ok(navionics);
  same(n.waypoints, [{name: 'Drop off', lat: 32.9, lon: -117.3, note: '1 <fathom> & more'}], 'navionics');
  same(n.rejected.map(r => [r.index, r.element, r.name, r.reason]), [[2, 'rtept', '', 'route-point-not-imported'], [3, 'rtept', 'B', 'route-point-not-imported']], 'every rtept listed');
});

test('gpx_waypoints_namespace_and_placement', () => {
  const r = ok(gpx11(`<foo:wpt xmlns:foo="urn:x" lat="1" lon="2"/><foo:rtept xmlns:foo="urn:x"/><foo:trkpt xmlns:foo="urn:x"/>` +
    `<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>` +
    `<rte><wpt lat="3" lon="3"><name>Nested</name></wpt></rte>` +
    `<wpt lat="4" lon="4"/><wpt lat="4" lon="4"><name>Same</name></wpt><wpt lat="4" lon="4"><name>Same</name></wpt>`));
  assert.equal(r.ignoredTrackPoints, 2, 'only GPX-namespace track points are counted');
  same(r.rejected, [{index: 1, element: 'wpt', name: 'Nested', reason: 'invalid-placement'}], 'nested wpt is refused, lookalike extensions are not candidates');
  same(r.waypoints.map(w => w.name), ['', 'Same', 'Same'], 'blank name stays blank; duplicates are kept');
  // An element in a shadowed or removed namespace is not GPX.
  const shadow = ok(gpx11(`<wpt xmlns="urn:other" lat="1" lon="1"/><wpt lat="2" lon="2" xmlns="${NS11}"/>`));
  assert.equal(shadow.waypoints.length, 1);
  same(ok(gpx11('')), {ok: true, waypoints: [], rejected: [], ignoredTrackPoints: 0}, 'empty gpx succeeds');
  // Attribute-name decoys: only whole unqualified lat/lon count.
  const decoy = ok(gpx11(`<wpt foo:lat="9" xmlns:foo="urn:x" lat="5" lon="6" data="lat='1' lon='2'"/><wpt xlat="1" lon="2"/>`));
  same(decoy.waypoints, [{name: '', lat: 5, lon: 6, note: null}], 'decoys');
  same(decoy.rejected.map(x => x.reason), ['invalid-latitude'], 'xlat is not lat');
  assert.equal(code(gpx11(`<wpt lat="1" lat="2" lon="3"/>`)), 'invalid-xml', 'duplicate attribute is fatal');
  // An empty prefix suffix is malformed, never a default-namespace declaration.
  assert.equal(code(gpx11(`<wpt xmlns:="${NS11}" lat="1" lon="2"/>`)), 'invalid-xml', 'xmlns: with no prefix is fatal');
  assert.equal(code(gpx11(`<wpt xmlns:="urn:other" lat="1" lon="2"/>`)), 'invalid-xml');
  // XML name characters: U+00D7 and U+00F7 are not name characters; U+00C0 and an astral letter are.
  assert.equal(code(gpx11(`<wpt lat="1" lon="2" \u00d7a="1"/>`)), 'invalid-xml', 'U+00D7 cannot start an attribute name');
  assert.equal(code(gpx11(`<wpt lat="1" lon="2" a\u00f7="1"/>`)), 'invalid-xml', 'U+00F7 is not a name character');
  assert.equal(code(gpx11(`<\u00d7x lat="1" lon="2"/>`)), 'invalid-xml', 'U+00D7 cannot start an element name');
  assert.equal(code(gpx11(`<wpt xmlns:\u00d7p="urn:x" lat="1" lon="2"/>`)), 'invalid-xml', 'U+00D7 cannot start a prefix');
  assert.equal(code(gpx11(`<wpt lat="1" lon="2" a\u2000="1"/>`)), 'invalid-xml', 'U+2000 is not a name character');
  assert.equal(ok(gpx11(`<wpt lat="1" lon="2" \u00c0\u00b7x="1" \u{10000}="2"/>`)).waypoints.length, 1, 'legal non-ASCII names still read');
});

test('gpx_waypoints_text_and_limits', () => {
  const r = ok(gpx11(
    wpt(1, 2, '<name>  A&amp;B &lt;&gt; &quot;&apos; &#65;&#x42; &amp;#0;  </name><desc>  </desc><cmt>fallback</cmt>') +
    wpt(1, 2, '<name><![CDATA[<b>&amp;</b>]]><!-- DOCTYPE --></name><desc>d</desc><cmt>c</cmt>') +
    wpt(1, 2, '<name>DOCTYPE &amp;lt;!ENTITY</name>')));
  same(r.waypoints.map(w => [w.name, w.note]), [['A&B <> "\' AB &#0;', 'fallback'], ['<b>&amp;</b>', 'd'], ['DOCTYPE &lt;!ENTITY', null]], 'decoding is single-pass');
  // 80 UTF-16 units: an emoji straddling the cut is dropped whole; one that fits is kept.
  const split = 'a'.repeat(79) + '😀', fits = 'b'.repeat(78) + '😀' + 'zzz';
  const t = ok(gpx11(wpt(1, 2, `<name>${split}</name>`) + wpt(1, 2, `<name>${fits}</name>`) + wpt(1, 2, `<name>${'c'.repeat(200)}</name>`)));
  assert.equal(t.waypoints[0].name, 'a'.repeat(79));
  assert.equal(t.waypoints[1].name, 'b'.repeat(78) + '😀');
  assert.equal(t.waypoints[2].name.length, 80);
  // Note: 1,000 code points, not units.
  const emojis = '😀'.repeat(1001), note = ok(gpx11(wpt(1, 2, `<desc>${emojis}</desc>`))).waypoints[0].note;
  assert.equal([...note].length, 1000);
  assert.equal(ok(gpx11(wpt(1, 2, `<cmt>${'x'.repeat(1000)}</cmt>`))).waypoints[0].note.length, 1000);
  // Scalar fields: child markup, repeats (any of the three) and a bad desc never fall back to cmt.
  const bad = ok(gpx11(wpt(1, 2, '<name>a<b/>c</name>') + wpt(1, 2, '<name>x</name><name>y</name>') + wpt(1, 2, '<desc>d<i>x</i></desc><cmt>c</cmt>') + wpt(1, 2, '<cmt>1</cmt><cmt>2</cmt>')));
  same(bad.rejected.map(x => x.reason), Array(4).fill('invalid-waypoint-text'), 'markup and repeats');
  same(bad.rejected.map(x => x.name), ['', '', '', ''], 'unreadable names are blank');
  assert.equal(bad.waypoints.length, 0);
  // Extension fields never override GPX ones.
  same(ok(gpx11(wpt(1, 2, '<name>Real</name><extensions><name>Fake</name><desc>no</desc></extensions>'))).waypoints, [{name: 'Real', lat: 1, lon: 2, note: null}], 'extensions');
  // Inclusive boundaries are parsed; the spots route (exclusive) is the downstream save's concern.
  same(ok(gpx11(wpt(90, 180) + wpt(-90, -180) + wpt('+1.', '.5') + wpt('-0', '0'))).waypoints.map(w => [w.lat, w.lon]), [[90, 180], [-90, -180], [1, 0.5], [0, 0]], 'bounds');
});

test('gpx_waypoints_bad_coordinates_are_listed', () => {
  const cases = [['91', '0', 'invalid-latitude'], ['-90.0001', '0', 'invalid-latitude'], ['0', '180.5', 'invalid-longitude'], ['0', '-181', 'invalid-longitude'],
    ['abc', '0', 'invalid-latitude'], ['', '0', 'invalid-latitude'], ['  ', '0', 'invalid-latitude'], ['NaN', '0', 'invalid-latitude'], ['Infinity', '0', 'invalid-latitude'],
    ['1e1', '0', 'invalid-latitude'], ['0x10', '0', 'invalid-latitude'], ['0', '1,5', 'invalid-longitude'], ['999', '999', 'invalid-latitude']];
  const body = cases.map(([a, b], i) => wpt(a, b, `<name>P${i}</name>`)).join('') + wpt(10, 20, '<name>Good</name>') + '<wpt lon="1"><name>NoLat</name></wpt><wpt lat="1"><name>NoLon</name></wpt>';
  const r = ok(gpx11(body));
  same(r.waypoints.map(w => w.name), ['Good'], 'only the good one is read');
  same(r.rejected.map(x => [x.index, x.name, x.reason]), [...cases.map(([, , why], i) => [i + 1, `P${i}`, why]), [15, 'NoLat', 'invalid-latitude'], [16, 'NoLon', 'invalid-longitude']], 'every refusal is listed with index, name and reason');
  // Precedence: placement before coordinates, coordinates before text.
  const p = ok(gpx11(`<rte><wpt lat="99" lon="0"/></rte>` + wpt(0, 0, '<name>a</name><name>b</name>') + wpt(99, 0, '<name>a</name><name>b</name>')));
  same(p.rejected.map(x => x.reason), ['invalid-placement', 'invalid-waypoint-text', 'invalid-latitude'], 'precedence');
  // Entity-decoded coordinates are read once: &#x31; is "1".
  same(ok(gpx11('<wpt lat="&#x31;0" lon="&#52;"/>')).waypoints, [{name: '', lat: 10, lon: 4, note: null}], 'references in attributes');
});

test('gpx_waypoints_forbids_entities_and_declarations', () => {
  const expansion = `<?xml version="1.0"?>\n<!DOCTYPE gpx [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>\n` +
    `<gpx version="1.1" xmlns="${NS11}"><wpt lat="1" lon="2"><name>&c;</name></wpt></gpx>`;
  assert.equal(code(expansion), 'forbidden-declaration', 'entity expansion attempt never expands');
  assert.equal(code(`<!DOCTYPE gpx SYSTEM "http://example.invalid/x.dtd">` + gpx11('')), 'forbidden-declaration');
  assert.equal(code(gpx11(wpt(1, 2) + '<!ENTITY x "y">')), 'forbidden-declaration');
  assert.equal(code(gpx11(wpt(1, 2, '<extensions><![INCLUDE[x]]></extensions>'))), 'forbidden-declaration');
  for (const ref of ['&xxe;', '&custom;', '&amp', '&;', '&#;', '&#x;', '&#xZ;', '&#1;', '&#0;', '&#xFFFE;', '&#xD800;', '&#x110000;', '&#99999999999;', '&#x0000000000000110000;', '&AMP;', '& ']) {
    assert.equal(code(gpx11(`<wpt lat="1" lon="2"><name>${ref}</name></wpt>`)), 'invalid-xml', `text ${ref}`);
    assert.equal(code(gpx11(`<wpt lat="1" lon="2" x="${ref}"/>`)), 'invalid-xml', `attribute ${ref}`);
    assert.equal(code(gpx11(`<extensions><junk>${ref}</junk></extensions>`)), 'invalid-xml', `ignored element ${ref}`);
  }
  same(ok(gpx11(wpt(1, 2, '<name>&#x41;&#0000065;&#x10FFFF;</name>'))).waypoints[0].name, 'AA\u{10FFFF}', 'legal references with leading zeroes');
  for (const [label, bad] of [['NUL', '\u0000'], ['BEL', '\u0007'], ['FFFE', '\ufffe'], ['lone high', '\ud800'], ['lone low', '\udc00'], ['reversed pair', '\udc00\ud800']]) {
    assert.equal(code(gpx11(`<wpt lat="1" lon="2"><name>a${bad}</name></wpt>`)), 'invalid-xml', label);
    assert.equal(code(gpx11(`<extensions x="${bad}"/>`)), 'invalid-xml', `${label} in ignored attribute`);
    assert.equal(code(gpx11(`<!-- ${bad} -->`)), 'invalid-xml', `${label} in comment`);
  }
});

test('gpx_waypoints_requires_complete_document', () => {
  const good = gpx11(wpt(1, 2, '<name>One</name>') + wpt(3, 4, '<name>Two</name>'));
  assert.equal(ok(good).waypoints.length, 2);
  // Truncation anywhere is fatal, never a prefix of the waypoints.
  for (const cut of [good.indexOf('</gpx>'), good.indexOf('</gpx>') + 3, good.indexOf('lon="4"') + 4, good.indexOf('<name>Two') + 3, good.indexOf('Two'), good.indexOf('<wpt lat="3"') + 1, 40, 5]) {
    assert.equal(code(good.slice(0, cut)), 'invalid-xml', `truncated at ${cut}`);
  }
  for (const [label, xml] of [
    ['truncated comment', gpx11(wpt(1, 2)).replace('</gpx>', '<!-- x')],
    ['truncated CDATA', gpx11(wpt(1, 2, '<name><![CDATA[x</name>'))],
    ['balanced prefix then corruption', gpx11(wpt(1, 2, '<name>ok</name>') + '<broken') ],
    ['mismatched close', gpx11('<wpt lat="1" lon="2"></name></wpt>')],
    ['stray close', good + '</gpx>'],
    ['second root', good + good],
    ['text after root', good + 'x'],
    ['text before root', 'x' + good],
    ['empty input', ''],
    ['comments only', '<!-- x -->'],
    ['raw ]]>', gpx11(wpt(1, 2, '<name>a]]>b</name>'))],
    ['double hyphen in comment', gpx11('<!-- a -- b -->')],
    ['comment ending in hyphen', gpx11('<!-- a --->')],
    ['raw < in attribute', gpx11('<wpt lat="1" lon="2" x="a<b"/>')],
    ['unquoted attribute', gpx11('<wpt lat=1 lon="2"/>')],
    ['missing space between attributes', gpx11('<wpt lat="1"lon="2"/>')],
    ['duplicate namespace-expanded attribute', gpx11('<wpt xmlns:a="urn:x" xmlns:b="urn:x" a:k="1" b:k="2" lat="1" lon="2"/>')],
    ['undeclared element prefix', gpx11('<zz:wpt lat="1" lon="2"/>')],
    ['undeclared attribute prefix', gpx11('<wpt zz:k="1" lat="1" lon="2"/>')],
    ['empty prefix namespace', gpx11('<wpt xmlns:a="" lat="1" lon="2"/>')],
    ['xml namespace on another prefix', gpx11(wpt(5, 6) + '<wpt xmlns:a="http://www.w3.org/XML/1998/namespace" lat="1" lon="2"/>')],
    ['xml namespace as default', gpx11(wpt(5, 6) + '<wpt xmlns="http://www.w3.org/XML/1998/namespace" lat="1" lon="2"/>')],
    ['xmlns namespace on a prefix', gpx11(wpt(5, 6) + '<wpt xmlns:a="http://www.w3.org/2000/xmlns/" lat="1" lon="2"/>')],
    ['xmlns namespace as default', gpx11(wpt(5, 6) + '<wpt xmlns="http://www.w3.org/2000/xmlns/" lat="1" lon="2"/>')],
    ['xmlns namespace on prefix xml', gpx11(wpt(5, 6) + '<wpt xmlns:xml="http://www.w3.org/2000/xmlns/" lat="1" lon="2"/>')],
    ['xml prefix bound elsewhere', gpx11(wpt(5, 6) + '<wpt xmlns:xml="urn:x" lat="1" lon="2"/>')],
    ['non-initial PI', gpx11('<?pi x?>')],
    ['PI before root', `<?xml-stylesheet href="x"?>` + gpx11('')],
    ['whitespace before declaration', ' ' + good],
    ['CDATA outside root', '<![CDATA[x]]>' + good],
    ['unclosed root', `<gpx version="1.1" xmlns="${NS11}">`],
    ['junk in ignored extension', gpx11('<extensions><a><b></a></extensions>')],
  ]) assert.equal(code(xml), 'invalid-xml', label);
  for (const [label, xml] of [
    ['version 1.2', good.replace('version="1.1"', 'version="1.2"')],
    ['version missing', good.replace(' version="1.1"', '')],
    ['namespace/version mismatch', good.replace('version="1.1"', 'version="1.0"')],
    ['wrong namespace', good.replace(NS11, 'urn:other')],
    ['no namespace', good.replace(` xmlns="${NS11}"`, '')],
    ['namespace removed', good.replace(`xmlns="${NS11}"`, 'xmlns=""')],
    ['wrong root name', good.replaceAll('gpx>', 'GPX>').replace('<gpx ', '<GPX ')],
    ['prefixed version only', good.replace('version="1.1"', 'a:version="1.1" xmlns:a="urn:x"')],
    ['non-UTF-8 declaration', good.replace('UTF-8', 'ISO-8859-1')],
    ['XML 1.1 declaration', good.replace('version="1.0"', 'version="1.1"')],
  ]) assert.equal(code(xml), 'unsupported-gpx', label);
  // Legal oddities still read: BOM, other-cased utf-8, comments around root, `>` inside a quoted attribute, scoped prefix declared late.
  const odd = `\ufeff<?xml version="1.0" encoding="utf-8"?><!-- c -->\n<g:gpx xmlns:g="${NS11}" version="1.1"><g:wpt lat="1" lon="2" note="a>b"><g:name>X</g:name></g:wpt></g:gpx>\n<!-- end -->\n`;
  same(ok(odd).waypoints, [{name: 'X', lat: 1, lon: 2, note: null}], 'legal variants');
  // Legal reserved-name uses: explicit xmlns:xml with its own URI, and a namespace reset.
  assert.equal(ok(gpx11('<wpt xmlns:xml="http://www.w3.org/XML/1998/namespace" lat="1" lon="2"/>')).waypoints.length, 1, 'explicit xmlns:xml');
  assert.equal(ok(gpx11('<foo xmlns=""><bar xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="1" lon="2"/></bar></foo>')).waypoints.length, 0, 'namespace reset');
});

test('gpx_waypoints_caps_are_utf8_and_all_candidates', () => {
  assert.equal(MAX_GPX_BYTES, 1_048_576);
  assert.equal(MAX_GPX_POINTS, 1_000);
  const base = gpx11(wpt(1, 2, '<name>a</name>') + '<!---->');
  const pad = n => gpx11(wpt(1, 2, '<name>a</name>') + `<!--${'x'.repeat(n)}-->`);
  const overhead = Buffer.byteLength(pad(0));
  const exact = pad(MAX_GPX_BYTES - overhead);
  assert.equal(Buffer.byteLength(exact), MAX_GPX_BYTES);
  assert.equal(ok(exact).waypoints.length, 1, 'exactly at the byte cap is accepted');
  assert.equal(code(pad(MAX_GPX_BYTES - overhead + 1)), 'file-too-large', 'one byte over');
  // Fewer UTF-16 units than the cap, more UTF-8 bytes.
  const wide = gpx11(`<!--${'€'.repeat(Math.ceil(MAX_GPX_BYTES / 3))}-->`);
  assert.ok(wide.length < MAX_GPX_BYTES && Buffer.byteLength(wide) > MAX_GPX_BYTES);
  assert.equal(code(wide), 'file-too-large');
  assert.equal(code('x'.repeat(MAX_GPX_BYTES + 1)), 'file-too-large');
  assert.ok(base.length < 400);
  // Candidates: wpt and rtept together, accepted or refused.
  const many = n => gpx11(Array.from({length: n}, (_, i) => i % 3 === 0 ? '<rtept lat="1" lon="1"/>' : i % 3 === 1 ? '<wpt lat="999" lon="1"/>' : wpt(1, 1)).join(''));
  const at = ok(many(MAX_GPX_POINTS));
  assert.equal(at.waypoints.length + at.rejected.length, MAX_GPX_POINTS);
  same(at.rejected.map(x => x.index).slice(0, 4), [1, 2, 4, 5], 'refusals are in source order');
  assert.equal(code(many(MAX_GPX_POINTS + 1)), 'too-many-points', 'the 1,001st fails the whole file');
  assert.equal(code(gpx11(wpt(1, 1).repeat(5) + '<rtept lat="1" lon="1"/>'.repeat(MAX_GPX_POINTS - 4)) ), 'too-many-points', 'rtept consume the cap');
  assert.equal(code(many(MAX_GPX_POINTS + 1) .replace('</gpx>', '<broken')), 'too-many-points', 'late overflow gives no prefix');
  // Nesting depth 64 is allowed, 65 is not (self-closing leaves count).
  const nest = depth => `<gpx version="1.1" xmlns="${NS11}">` + '<e>'.repeat(depth - 2) + '<leaf/>' + '</e>'.repeat(depth - 2) + '</gpx>';
  assert.equal(ok(nest(64)).waypoints.length, 0);
  assert.equal(code(nest(65)), 'xml-depth-exceeded');
});

test('gpx_waypoints_is_browser_independent_and_private', async () => {
  const saved = Object.fromEntries(['DOMParser', 'document', 'localStorage', 'XMLHttpRequest', 'EventSource'].map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
  const traps = [];
  const spied = {};
  for (const k of ['log', 'warn', 'error', 'info', 'debug']) { spied[k] = console[k]; console[k] = () => traps.push(`console.${k}`); }
  try {
    for (const k of Object.keys(saved)) Object.defineProperty(globalThis, k, {configurable: true, get() { traps.push(k); throw new Error(`${k} must not be touched`); }});
    globalThis.fetch = () => { traps.push('fetch'); throw new Error('fetch must not be called'); };
    const r = readGpxWaypoints(gpx11(wpt(1, 2, '<name>Private</name><desc>secret note</desc>')));
    assert.equal(r.ok, true);
    assert.equal(readGpxWaypoints(`<!DOCTYPE x>`).ok, false);
    assert.deepEqual(traps, [], 'no DOM, storage, network or logging');
  } finally {
    for (const [k, d] of Object.entries(saved)) { if (d) Object.defineProperty(globalThis, k, d); else delete globalThis[k]; }
    Object.assign(console, spied);
  }
  // Fatal messages are fixed text and never echo the file.
  const err = readGpxWaypoints(gpx11('<wpt lat="1" lon="2"><name>SECRET-MARK&nope;</name></wpt>'));
  assert.ok(!JSON.stringify(err).includes('SECRET-MARK'));
  // The reader bundles for the browser with no server or Node dependency.
  const {build} = await import('esbuild');
  const out = await build({entryPoints: [new URL('../web/gpx-waypoints.ts', import.meta.url).pathname], bundle: true, write: false, platform: 'browser', format: 'esm', logLevel: 'silent'});
  assert.equal(out.outputFiles.length, 1);
  assert.doesNotMatch(out.outputFiles[0].text, /\brequire\(|node:|process\.|DOMParser/);
});
