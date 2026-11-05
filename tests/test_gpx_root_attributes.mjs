import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';

// Synthetic, in-memory GPX only; any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const NS = 'http://www.topografix.com/GPX/1/1';
const root = (attrs, tag = 'gpx') => `<?xml version="1.0" encoding="UTF-8"?>\n<${tag}${attrs}><wpt lat="35" lon="-120"><name>One</name></wpt></${tag}>`;
const problemsOf = (xml) => { const c = checkGpx(xml, {waypoints: 1}); return c.ok ? [] : c.problems; };
const refused = (attrs, label = attrs) => assert.ok(problemsOf(root(attrs)).includes('Expected GPX 1.1 root'), label);
const accepted = (attrs, label = attrs) => assert.deepEqual(problemsOf(root(attrs)), [], label);

test('root_requires_genuine_version_and_namespace', () => {
  accepted(` version="1.1" xmlns="${NS}"`);
  refused(` xmlns="${NS}"`, 'missing version');
  refused(' version="1.1"', 'missing xmlns');
  refused(` version="" xmlns="${NS}"`, 'empty version');
  refused(' version="1.1" xmlns=""', 'empty xmlns');
  refused(` version="1.0" xmlns="${NS}"`, 'wrong version');
  refused(' version="1.1" xmlns="urn:wrong"', 'wrong namespace');
  refused('', 'no attributes');
});

test('root_decoy_names_and_values_never_supply_identity', () => {
  refused(` data-version="1.1" data-xmlns="${NS}"`, 'data- prefix');
  refused(` x:version="1.1" x:xmlns="${NS}"`, 'prefixed names');
  refused(` VERSION="1.1" XMLNS="${NS}"`, 'case lookalikes');
  refused(` version-x="1.1" xmlns-x="${NS}"`, 'suffix lookalikes');
  refused(` note='version="1.1" xmlns="${NS}"'`, 'single-quoted decoy value');
  refused(` note="version='1.1' xmlns='${NS}'"`, 'double-quoted decoy value');
  refused(` data-version="1.1" xmlns="${NS}"`, 'decoy version beside genuine xmlns');
  refused(` version="1.1" note='xmlns="${NS}"'`, 'decoy xmlns beside genuine version');
  // Decoys beside wrong genuine values do not rescue them.
  refused(` version="1.0" xmlns="urn:wrong" note='version="1.1" xmlns="${NS}"'`, 'wrong genuine values plus decoys');
});

test('root_refuses_duplicate_identity_tokens_even_when_identical', () => {
  refused(` version="1.1" version="1.1" xmlns="${NS}"`, 'identical duplicate version');
  refused(` version="1.1" version="1.0" xmlns="${NS}"`, 'unequal duplicate version');
  refused(` version="1.0" version="1.1" xmlns="${NS}"`, 'unequal duplicate version reversed');
  refused(` version="1.1" xmlns="${NS}" xmlns="${NS}"`, 'identical duplicate xmlns');
  refused(` version="1.1" xmlns="urn:wrong" xmlns="${NS}"`, 'unequal duplicate xmlns');
  refused(` xmlns="${NS}" version="1.1" xmlns="urn:wrong"`, 'unequal duplicate xmlns, other order');
});

test('root_refuses_malformed_or_missing_root', () => {
  refused(` version="1.1" xmlns="${NS}" broken`, 'unconsumed bare token');
  refused(` version="1.1" xmlns="${NS}" a="unterminated`, 'unterminated value');
  refused(` version=1.1 xmlns="${NS}"`, 'unquoted version');
  refused(` version="1.1"xmlns="${NS}"`, 'no whitespace between tokens');
  assert.ok(problemsOf(root(` version="1.1" xmlns="${NS}"`, 'GPX')).includes('Expected GPX 1.1 root'), 'case-sensitive root name');
  assert.ok(problemsOf(root(` version="1.1" xmlns="${NS}"`, 'kml')).includes('Expected GPX 1.1 root'), 'wrong root name');
  assert.equal(checkGpx('', {waypoints: 0}).ok, false);
  assert.ok(problemsOf('<?xml version="1.0"?>\n').length > 0);
});

test('root_accepts_reordered_quoted_and_spaced_attributes', () => {
  accepted(` xmlns="${NS}" version="1.1"`);
  accepted(` version='1.1' xmlns='${NS}'`);
  accepted(` version="1.1"\t\n xmlns = "${NS}"`);
  accepted(` creator="t" note='a "quoted" b' version="1.1" data-version="9" xmlns="${NS}" x:extra="1"`);
});

test('root_check_keeps_screen_and_input_behaviour', () => {
  const xml = root(` version="1.1" xmlns="${NS}"`), copy = String(xml);
  assert.equal(checkGpx(xml, {waypoints: 1}).ok, true, 'no-screen structural mode');
  assert.equal(xml, copy);
  const none = checkGpx(xml, {waypoints: 1}, null);
  assert.ok(!none.ok && none.problems.includes('Protected areas not checked'), 'null screen refuses');
  const inside = checkGpx(xml, {waypoints: 1}, {ready: () => true, pointAllowed: () => false, geometryAllowed: () => true});
  assert.ok(!inside.ok, 'refused point refuses');
  const clear = checkGpx(xml, {waypoints: 1}, {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true});
  assert.equal(clear.ok, true, 'clear screen accepts');
});
