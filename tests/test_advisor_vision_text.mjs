// RF1100-3: every text the vision validator returns (server/advisor/vision/validate.ts str())
// has no control, zero-width, bidi-override/isolate or BOM character and is cut at a whole
// code point, so a cut never leaves half an emoji. Plain text comes out as before.
import test from 'node:test';
import assert from 'node:assert/strict';

const {parseFishId, parseCountBoard} = await import('../server/advisor/vision/validate.ts');

const META = {provider: 'claude', model: 'm', ms: 5};
const ALLOWED = new Set(['lingcod', 'vermilion_rockfish']);
const fish = (...candidates) => parseFishId({candidates}, ALLOWED, META);
const board = input => parseCountBoard(input, META);
const LONE_HIGH = /[\uD800-\uDBFF]$/;
// What main's str() returned, for plain-text parity.
const mainStr = (v, max) => { const s = v.replace(/\s+/g, ' ').trim(); return s ? s.slice(0, max) : null; };

test('a bidi override inside a fish label is removed', () => {
  assert.equal(fish({species_key: 'lingcod', label: 'Ling\u202Ecod', confidence: 0.9}).candidates[0].label, 'Lingcod');
  assert.equal(fish({label: '\u2066Ling\u2069\uFEFFcod\u200D', confidence: 0.9}).candidates[0].label, 'Lingcod');
});

test('a label of only hidden characters falls back to the key, and with no key the candidate is dropped', () => {
  const kept = fish({species_key: 'lingcod', label: '\u200B', confidence: 0.9});
  assert.deepEqual(kept.candidates.map(c => [c.species_key, c.label]), [['lingcod', 'lingcod']]);
  const dropped = fish({label: '\u200B\u202E\u0000', confidence: 0.9});
  assert.equal(dropped.candidates.length, 0);
  assert.equal(dropped.needs_better_photo, true);
  assert.equal(dropped.reason, 'no_fish');
});

test('count-board labels and notes lose control characters; whitespace controls still collapse', () => {
  const r = board({boat_name: 'New\u0000 Horizon\u202E', lines: [{label: 'Vermilion\u0007', count: 12}, {label: '\u0001\u007F', count: 3}],
    notes: 'Limits\u0000 of rock\u0085fish\nand two\tlings', trip_type: '\u200B'});
  assert.deepEqual(r.lines.map(l => [l.label, l.count]), [['Vermilion', 12]], 'a hidden-only line is dropped');
  assert.equal(r.notes, 'Limits of rockfish and two lings');
  assert.equal(r.boat_name, 'New Horizon');
  assert.equal(r.trip_type, null, 'empty after removal is null');
});

test('a cut never leaves a lone surrogate and keeps an emoji that fits', () => {
  const straddle = 'a'.repeat(59) + '\u{1F41F}\u{1F41F}';
  assert.ok(LONE_HIGH.test(straddle.slice(0, 60)), 'the old UTF-16 cut would split the emoji');
  const label = fish({label: straddle, confidence: 0.5}).candidates[0].label;
  assert.ok(!LONE_HIGH.test(label));
  assert.equal(label, 'a'.repeat(59) + '\u{1F41F}', '59 letters + fish is 60 code points: kept whole');
  assert.equal(board({lines: [{label: 'b'.repeat(60) + '\u{1F41F}', count: 1}]}).lines[0].label, 'b'.repeat(60));
  const fishes = board({notes: '\u{1F41F}'.repeat(301)}).notes;
  assert.equal(Array.from(fishes).length, 300);
  assert.ok(!LONE_HIGH.test(fishes));
  assert.ok(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(fishes));
});

test('plain text is unchanged from main', () => {
  assert.equal(fish({label: 'Café  rockfish\t', confidence: 0.5}).candidates[0].label, 'Café rockfish');
  const notes = Array.from({length: 40}, (_, i) => `word${i}`).join(' ').padEnd(320, 'z');
  assert.equal(board({notes}).notes, mainStr(notes, 300));
  assert.equal(board({notes}).notes.length, 300);
  for (const v of ['Vermilion rockfish', 'Señorita 🐟 x2', '  Bocaccio\n']) assert.equal(board({boat_name: v}).boat_name, mainStr(v, 80));
});

test('cues of only hidden characters are dropped and at most three are kept', () => {
  const [c] = fish({species_key: 'lingcod', label: 'Lingcod', confidence: 0.9,
    cues: ['\u200B\u200C', 'big mouth\u202E', '\u0000', 'mottled', 'teeth', 'fourth']}).candidates;
  assert.deepEqual(c.cues, ['big mouth', 'mottled', 'teeth']);
});
