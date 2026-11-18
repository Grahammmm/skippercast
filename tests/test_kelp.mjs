// MB-17a: the kelp layer module. Every test names the contract it protects and the believable bug
// that makes it fail (CI-ARTICLE-1). No network: the pointer is a fixture handed in directly or
// through an injected resolver.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {
  KELP_DOTS_IMAGE, KELP_HISTORICAL_2016, KELP_OUTLINE, KELP_SOURCE_LAYER, kelpLayers, loadKelp, resolveKelp, themePaint, themePatterns,
} from '../web/map/kelp.ts';
import {readPalette} from '../web/map/palette.ts';

const SHA = 'a'.repeat(64);
const pointer = (products, extra = {}) => ({schema: 'sc-kelp-pointer/1', status: 'reviewed', private: false, sha256: SHA, bytes: 1234,
  url: 'https://tiles.example.test/relief/kelp/' + SHA + '.pmtiles', products, ...extra});
const planet = year => ({sensor: 'Planet 3 m', season: 'september', year});
const landsat = (year, season, quarter) => ({sensor: 'Landsat 30 m', season, year, ...(quarter ? {quarter} : {})});
const at = iso => new Date(iso + 'T12:00:00Z');
const ready = (p, now) => { const r = resolveKelp(p, now); assert.equal(r.status, 'ready', JSON.stringify(r)); return r.layer; };
// Words the map must never draw: a live claim, a "current" claim, or a source name (G 11-18).
const FORBIDDEN = /\blive\b|\bcurrent|planet|landsat|cdfw|kelpwatch|zenodo|\bedi\b|sbc|lter/i;

test('labels: a Planet year and a Landsat quarter each read "Kelp canopy seen <season> <year> (<m>)"', () => {
  // Contract: the fixed label wording and resolution suffix. Bug: dropping the suffix, lower-casing
  // September, or taking the season from the wrong quarter.
  assert.equal(ready(pointer([planet(2024)]), at('2024-12-01')).label, 'Kelp canopy seen September 2024 (3 m)');
  assert.equal(ready(pointer([landsat(2026, 'summer')]), at('2026-11-18')).label, 'Kelp canopy seen summer 2026 (30 m)');
  for (const [q, season] of [[1, 'winter'], [2, 'spring'], [3, 'summer'], [4, 'fall']]) {
    assert.equal(ready(pointer([landsat(2026, season, q)]), at(`2026-${String(q * 3).padStart(2, '0')}-15`)).label, `Kelp canopy seen ${season} 2026 (30 m)`);
  }
});

test('products: a season that disagrees with its quarter, or a Planet quarter other than September, is refused', () => {
  // Contract: the label's season must be the pass's own season. Bug: trusting `season` over `quarter` and mislabelling a view.
  for (const bad of [landsat(2026, 'summer', 1), landsat(2026, 'september'), landsat(2026, 'winter', 5), {...planet(2024), season: 'summer'},
    {...planet(2024), quarter: 2}, {sensor: 'Sentinel', season: 'summer', year: 2026}, landsat(2026.5, 'summer'), landsat('2026', 'summer')]) {
    assert.deepEqual(resolveKelp(pointer([bad]), at('2026-11-18')).reason, 'products', JSON.stringify(bad));
  }
});

test('newest view wins; a Planet September wins a tie with a Landsat quarter; the two are not blended', () => {
  // Contract: KELP-ACCESS §4 "which layer wins". Bug: labelling the first or oldest product, or letting Landsat hide a same-quarter Planet map.
  const both = [planet(2024), landsat(2024, 'summer'), landsat(2024, 'fall'), landsat(2025, 'spring')];
  assert.equal(ready(pointer(both), at('2025-08-01')).label, 'Kelp canopy seen spring 2025 (30 m)');
  assert.equal(ready(pointer([landsat(2024, 'summer'), planet(2024)]), at('2024-11-01')).label, 'Kelp canopy seen September 2024 (3 m)');
});

test('staleness: beyond two quarters the label shows its date and is tagged out of date', () => {
  // Contract: KELP-ACCESS §6 boundary. Bug: an off-by-one at the boundary, or a stale view that keeps the fresh wording.
  const p = pointer([landsat(2026, 'spring')]);
  const edge = ready(p, at('2026-12-31')); // Q2 -> Q4: two quarters, still fresh
  assert.equal(edge.stale, false);
  assert.equal(edge.tag, null);
  assert.equal(edge.label, 'Kelp canopy seen spring 2026 (30 m)');
  const stale = ready(p, at('2027-01-01')); // Q1 2027: three quarters
  assert.equal(stale.stale, true);
  assert.equal(stale.tag, 'out of date');
  assert.equal(stale.observedThrough, '2026-06-30');
  assert.equal(stale.label, 'Kelp canopy seen spring 2026 (30 m) — not updated since 2026-06-30');
});

test('no label, note or reason ever says "live" or "current", or names a source, fresh or stale', () => {
  // Contract: G 11-18 (no source names on the map) and the wording rule. Bug: a stale layer described as current, or a sensor name leaking into the label.
  const clocks = ['2024-10-01', '2025-03-01', '2026-11-18', '2027-06-01', '2029-01-01'];
  const seen = [];
  for (const products of [[planet(2024)], [landsat(2024, 'summer')], [planet(2024), landsat(2026, 'summer')]]) {
    for (const day of clocks) {
      const r = resolveKelp(pointer(products), at(day));
      if (r.status === 'ready') seen.push(r.layer.label, r.layer.tag ?? '', r.layer.offReason ?? '');
      else seen.push(r.note);
    }
  }
  seen.push(resolveKelp(null, at('2026-11-18')).note, KELP_HISTORICAL_2016.label);
  assert.ok(seen.some(s => s.startsWith('Kelp canopy seen')));
  for (const s of seen) assert.doesNotMatch(s, FORBIDDEN, s);
});

test('default visibility: a stale Planet-only September, or anything over four quarters old, starts off with a reason', () => {
  // Contract: KELP-ACCESS §6 + MB-17a. Bug: a three-year-old Planet map on by default, or a Landsat quarter hidden too early.
  const fresh = ready(pointer([planet(2026)]), at('2026-11-18'));
  assert.equal(fresh.defaultOn, true);
  assert.equal(fresh.offReason, null);
  assert.equal(ready(pointer([planet(2025)]), at('2026-03-01')).defaultOn, true); // two quarters: not yet stale
  const old = ready(pointer([planet(2025)]), at('2026-04-01')); // three quarters
  assert.equal(old.defaultOn, false);
  assert.match(old.offReason, /^Off by default: /);
  const landsatStale = ready(pointer([landsat(2026, 'spring')]), at('2027-01-01')); // stale but Landsat: still on, with its date
  assert.equal(landsatStale.stale, true);
  assert.equal(landsatStale.defaultOn, true);
  const landsatOld = ready(pointer([landsat(2026, 'spring')]), at('2027-07-01')); // five quarters
  assert.equal(landsatOld.defaultOn, false);
  assert.match(landsatOld.offReason, /four quarters/);
});

test('refusals: a private, unreviewed, unidentified or malformed pointer is unavailable, never drawn', () => {
  // Contract: same refusal style as relief-data.ts (private must be exactly false, status exactly reviewed, identity complete).
  // Bug: treating an absent `private` or `status` as acceptable, or accepting a pointer with no bytes/hash.
  const now = at('2026-11-18');
  const good = [landsat(2026, 'summer')];
  const cases = [
    ['private', pointer(good, {private: true})], ['private', pointer(good, {private: undefined})], ['private', pointer(good, {private: 'false'})],
    ['unreviewed', pointer(good, {status: 'draft'})], ['unreviewed', pointer(good, {status: undefined})],
    ['schema', pointer(good, {schema: 'sc-kelp-pointer/2'})], ['schema', 'kelp'],
    ['identity', pointer(good, {sha256: undefined})], ['identity', pointer(good, {sha256: 'A'.repeat(64)})], ['identity', pointer(good, {sha256: 'a'.repeat(63)})],
    ['identity', pointer(good, {bytes: undefined})], ['identity', pointer(good, {bytes: 0})], ['identity', pointer(good, {bytes: '1234'})], ['identity', pointer(good, {bytes: 1.5})],
    ['identity', pointer(good, {url: 'http://tiles.example.test/k.pmtiles'})], ['identity', pointer(good, {url: 'https://u:p@tiles.example.test/k.pmtiles'})], ['identity', pointer(good, {url: undefined})],
    ['products', pointer([])], ['products', pointer(undefined)], ['products', pointer([planet(2030)])],
  ];
  for (const [reason, p] of cases) {
    const r = resolveKelp(p, now);
    assert.equal(r.status, 'unavailable', JSON.stringify(p));
    assert.equal(r.reason, reason, JSON.stringify(p));
    assert.equal(r.layer, undefined);
  }
  assert.equal(resolveKelp(pointer(good), new Date('nope')).reason, 'clock');
});

test('a missing pointer is "unavailable", not an empty layer, and the resolver is the only way in', async () => {
  // Contract: MB-17 "missing source -> layer unavailable, not empty". Bug: an absent file or a failed read resolving to a ready layer with no products,
  // or the module fetching on its own (fetch is made to throw here).
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => { throw new Error('kelp.ts must not fetch'); };
  try {
    const now = at('2026-11-18');
    for (const missing of [undefined, null]) {
      assert.deepEqual(resolveKelp(missing, now), {status: 'unavailable', reason: 'missing', note: 'Kelp canopy is unavailable.'});
      assert.equal((await loadKelp(() => missing, now)).reason, 'missing');
    }
    assert.equal((await loadKelp(async () => { throw new Error('404'); }, now)).reason, 'unreadable');
    const loaded = await loadKelp(async () => pointer([landsat(2026, 'summer')]), now);
    assert.equal(loaded.status, 'ready');
    assert.equal(loaded.layer.label, 'Kelp canopy seen summer 2026 (30 m)');
  } finally { globalThis.fetch = realFetch; }
});

test('CDFW 2016 kelp is labelled historical and starts off', () => {
  // Contract: MB-17 / KELP-ACCESS §6. Bug: the 2016 survey on by default, or labelled as recent canopy.
  assert.equal(KELP_HISTORICAL_2016.label, 'Kelp canopy 2016 (historical)');
  assert.equal(KELP_HISTORICAL_2016.defaultOn, false);
});

// Tokens read as `<theme>:<name>`, so each theme has its own distinct palette values.
const palette = theme => readPalette(name => /^map-.*-(?:opacity|width)$/.test(name) ? '1' : `${theme}:${name}`);

test('paints: both themes take every colour from the palette, and themePaint targets real paint properties', () => {
  // Contract: MAP-REPLAN-3 structural contract and "colours via palette tokens". Bug: a hard-coded colour that survives a theme switch,
  // or a themePaint edit naming a layer/property kelpLayers never created (restyle would skip it silently).
  const colours = {};
  for (const theme of ['dark', 'light']) {
    const p = palette(theme), layers = kelpLayers(p), edits = themePaint(p);
    assert.deepEqual(layers.map(l => l.id), ['kelp-dots', 'kelp-outline']);
    for (const l of layers) {
      assert.equal(l['source-layer'], KELP_SOURCE_LAYER);
      assert.ok(['fill', 'line'].includes(l.type));
    }
    const outline = layers.find(l => l.id === KELP_OUTLINE);
    assert.equal(outline.paint['line-color'], p.habKelp);
    assert.ok(edits.length > 0);
    for (const e of edits) {
      const layer = layers.find(l => l.id === e.layer);
      assert.ok(layer && e.property in layer.paint, `${e.layer}.${e.property}`);
      assert.equal(e.value, p.habKelp);
    }
    // Every string paint value is a pattern image id or a palette value; nothing else.
    for (const l of layers) for (const v of Object.values(l.paint)) {
      if (typeof v === 'string') assert.ok(v === KELP_DOTS_IMAGE || Object.values(p).includes(v), v);
    }
    colours[theme] = outline.paint['line-color'];
  }
  assert.notEqual(colours.dark, colours.light);
});

test('no colour literals in the module', () => {
  // Contract: scripts/check_tokens.mjs rejects them repo-wide; this keeps the failure beside the module. Bug: a pasted #hex / rgb() fallback.
  const source = readFileSync(new URL('../web/map/kelp.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|oklch|oklab|hwb|lab|lch)\(/);
});

test('dot pattern: drawn in the theme\'s kelp colour and replaced by id; with no canvas there is no pattern', () => {
  // Contract: themePatterns replaces the image in place, so a theme switch re-colours the dots. Bug: a fixed-colour dot image that
  // never changes with the theme, or a throw when canvas is unavailable.
  const old = globalThis.document;
  const fills = [];
  try {
    globalThis.document = {createElement: () => ({width: 0, height: 0, getContext: () => ({
      scale() {}, beginPath() {}, arc() {}, fill() { fills.push(this.fillStyle); },
      getImageData: (_x, _y, w, h) => ({width: w, height: h, data: new Uint8ClampedArray(w * h * 4)}),
    })})};
    const out = {};
    for (const theme of ['dark', 'light']) {
      const [pattern, ...rest] = themePatterns(palette(theme));
      assert.equal(rest.length, 0);
      assert.equal(pattern.id, KELP_DOTS_IMAGE);
      assert.equal(pattern.pixelRatio, 2);
      assert.equal(pattern.image.width, 20);
      out[theme] = fills.splice(0);
      assert.ok(out[theme].length > 0 && out[theme].every(c => c === palette(theme).habKelp));
    }
    assert.notDeepEqual(out.dark, out.light);
    globalThis.document = {createElement: () => ({getContext: () => null})};
    assert.deepEqual(themePatterns(palette('dark')), []);
  } finally { globalThis.document = old; }
});
