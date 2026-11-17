import test from 'node:test';
import assert from 'node:assert/strict';
import {checkGpx} from '../web/gpx-check.ts';

// Synthetic, in-memory GPX only; any network use fails the test.
const realFetch = globalThis.fetch;
test.beforeEach(() => { globalThis.fetch = () => { throw new Error('network is blocked in this test'); }; });
test.afterEach(() => { globalThis.fetch = realFetch; });

const LITERAL = 'XML-forbidden control character', REFERENCE = 'XML-forbidden character reference';
const wrap = (body, creator = 't') => `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="${creator}" xmlns="http://www.topografix.com/GPX/1/1">${body}</gpx>`;
const wpt = (name = 'One', extra = '', attrs = '') => wrap(`<wpt lat="35" lon="-120"${attrs}><name>${name}</name>${extra}</wpt>`);
const problemsOf = (xml, n = 1, screen) => { const c = checkGpx(xml, {waypoints: n}, screen); return c.ok ? [] : c.problems; };
const clearScreen = () => ({ready: () => true, pointAllowed: () => true, geometryAllowed: () => true});
const placements = text => [
  ['wpt name', wpt(`a${text}b`), 1],
  ['desc', wpt('One', `<desc>x ${text} y</desc>`), 1],
  ['cmt', wpt('One', `<cmt>${text}</cmt>`), 1],
  ['track name', wrap(`<trk><name>T${text}</name><trkseg><trkpt lat="35" lon="-120"/></trkseg></trk>`), 0],
  ['creator attribute', wrap('', `c${text}`), 0],
  ['extra quoted attribute', wpt('One', '', ` extra='${text}'`), 1],
  ['content start', wpt(`${text}x`), 1],
  ['content end', wpt(`x${text}`), 1],
];

test('raw_surrogate_halves_are_refused_everywhere', () => {
  for (const half of ['\ud800', '\udbff', '\udc00', '\udfff', '\ud800\ud800', '\udc00\udc00', '\udc00\ud800']) {
    for (const [where, xml, n] of placements(half)) {
      let c;
      assert.doesNotThrow(() => { c = checkGpx(xml, {waypoints: n}); }, where);
      assert.equal(c.ok, false, `${where} ${half.length} units`);
      assert.deepEqual(c.problems.filter(p => p === LITERAL), [LITERAL], where);
      assert.equal(c.problems.length, 1, `${where}: ${c.problems}`);
    }
  }
});

test('valid_pairs_and_adjacent_bmp_survive', () => {
  for (const ok of ['\u{10000}', '\u{1F41F}', '\u{10FFFF}', '\ud7ff', '\ue000', '\ud7ff\ue000', '\u{1F41F}\u{1F41F}\u{10000}', 'a\u{1F41F}b']) {
    for (const [where, xml, n] of placements(ok)) assert.deepEqual(problemsOf(xml, n), [], where);
  }
  for (const bad of ['\u{1F41F}\ud800', '\ud800\u{1F41F}', '\u{1F41F}\udc00', '\udc00\u{1F41F}', '\ud800\u{1F41F}\udc00']) {
    for (const [where, xml, n] of placements(bad)) assert.deepEqual(problemsOf(xml, n), [LITERAL], where);
  }
});

test('raw_character_guard_preserves_reference_contract', () => {
  assert.deepEqual(problemsOf(wpt('a&#xD800;b')), [REFERENCE]);
  assert.deepEqual(problemsOf(wpt('a&#56320;b')), [REFERENCE]);
  assert.deepEqual(problemsOf(wpt('a&amp;#xD800;b')), []);
  assert.deepEqual(problemsOf(wpt('a&#x1F41F;&#128031;b')), []);
});

test('raw_character_refusal_keeps_screen_contract', () => {
  const xml = wpt('a\ud800b');
  const copy = String(xml);
  const clear = checkGpx(xml, {waypoints: 1}, clearScreen());
  assert.equal(clear.ok, false);
  assert.deepEqual(clear.problems, [LITERAL]);
  assert.equal(clear.screen.length, 1);
  assert.equal(clear.screen[0].screened, true);
  assert.equal(xml, copy);
  for (const screen of [null, undefined]) {
    const c = checkGpx(xml, {waypoints: 1}, screen);
    assert.equal(c.ok, false);
    assert.ok(c.problems.includes(LITERAL));
  }
  // two invalid halves in one file: still one diagnostic
  assert.deepEqual(problemsOf(wpt('\ud800a\udc00')), [LITERAL]);
  // a clean export with an emoji name still passes with a clear screen
  const good = checkGpx(wpt('Fish \u{1F41F}'), {waypoints: 1}, clearScreen());
  assert.equal(good.ok, true);
});
