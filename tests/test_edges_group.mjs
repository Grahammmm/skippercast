import assert from 'node:assert/strict';
import test from 'node:test';
import {EDGE_LAYERS, edgesGroup, toggleEdge, toggleEdgesGroup} from '../web/map/edges-group.ts';

const [fronts, colour, eddies] = ['sst-fronts', 'chl-edges', 'eddies'];
const unrelated = 'swell';
const subsets = [[], [fronts], [colour], [eddies], [fronts, colour],
  [fronts, eddies], [colour, eddies], [fronts, colour, eddies]];

test('C1: edge IDs and rail order are fixed', () => {
  assert.deepEqual(EDGE_LAYERS, [fronts, colour, eddies]);
});

// Rows are indexed by how many edges are on and available. Crossing both power
// sets catches counting stale/unrelated IDs, or using the input order for members.
const states = [['none'], ['off', 'on'], ['off', 'mixed', 'on'], ['off', 'mixed', 'mixed', 'on']];
for (const offered of subsets) {
  test(`C1: full state table for available edges ${offered.join(', ') || '(none)'}`, () => {
    for (const selected of subsets) {
      const on = new Set([unrelated, ...[...selected].reverse()]);
      const available = new Set([unrelated, ...[...offered].reverse()]);
      const active = offered.filter(id => selected.includes(id));
      assert.deepEqual(edgesGroup(on, available), {
        state: states[offered.length][active.length],
        members: [fronts, colour, eddies].map(id => ({
          id, on: active.includes(id), available: offered.includes(id),
        })),
      }, `selected edges: ${selected.join(', ') || '(none)'}`);
      assert.deepEqual(on, new Set([unrelated, ...selected]));
      assert.deepEqual(available, new Set([unrelated, ...offered]));
    }
  });
}

for (const [name, selected, offered, expected] of [
  ['on clears even unavailable edges', [fronts, colour, eddies], [colour], []],
  ['off adds only available edges', [eddies], [fronts], [eddies, fronts]],
  ['mixed fills missing available edges without clearing stale IDs', [colour, eddies], [fronts, colour], [colour, eddies, fronts]],
  ['none keeps even stale IDs in a fresh set', [fronts, eddies], [], [fronts, eddies]],
]) {
  test(`C2: ${name}`, () => {
    const on = new Set([unrelated, ...selected]);
    const available = new Set([unrelated, ...offered]);
    const next = toggleEdgesGroup(on, available);
    assert.deepEqual(next, new Set([unrelated, ...expected]));
    assert.notStrictEqual(next, on);
    assert.deepEqual(on, new Set([unrelated, ...selected]));
    assert.deepEqual(available, new Set([unrelated, ...offered]));
  });
}

for (const [name, id, expected] of [
  ['adds only the requested off edge', fronts, [unrelated, fronts, colour, eddies]],
  ['removes only the requested on edge', colour, [unrelated, eddies]],
  ['leaves an unavailable on edge intact', eddies, [unrelated, colour, eddies]],
  ['leaves a non-edge intact even when available', unrelated, [unrelated, colour, eddies]],
]) {
  test(`C3: ${name}`, () => {
    const on = new Set([unrelated, colour, eddies]);
    const available = new Set([unrelated, fronts, colour]);
    const next = toggleEdge(on, available, id);
    assert.deepEqual(next, new Set(expected));
    assert.notStrictEqual(next, on);
    assert.deepEqual(on, new Set([unrelated, colour, eddies]));
    assert.deepEqual(available, new Set([unrelated, fronts, colour]));
  });
}
