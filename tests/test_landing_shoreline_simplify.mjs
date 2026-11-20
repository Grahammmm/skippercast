// RF2000-9: simplify measures distance to the finite replacement segment, so a
// valid line that doubles back keeps an excursion beyond the segment endpoints.
import assert from 'node:assert/strict';
import test from 'node:test';
import {simplify} from '../scripts/build_landing_shoreline.mjs';

const same = (a, b, message) => assert.ok(JSON.stringify(a) === JSON.stringify(b), `${message}: ${JSON.stringify(a)}`);

test('backtracking_beyond_segment_endpoint_is_preserved', () => {
  const past = [[0, 0], [10, 0], [1, 0]];
  same(simplify(past, 0.5), past, 'overshoot past end');
  const reverse = [[1, 0], [10, 0], [0, 0]];
  same(simplify(reverse, 0.5), reverse, 'reverse direction');
  const before = [[5, 0], [-4, 0], [6, 0]];
  same(simplify(before, 0.5), before, 'overshoot before start');
});

test('segment_projection_inside_endpoints_keeps_normal_simplification', () => {
  same(simplify([[0, 0], [0.5, 0], [1, 0]], 0.5), [[0, 0], [1, 0]], 'straight drops');
  const bend = [[0, 0], [0.5, 2], [1, 0]];
  same(simplify(bend, 0.5), bend, 'bend kept');
  same(simplify([[0, 0], [1, 0.1], [2, 0], [3, 5]], 0.5), [[0, 0], [2, 0], [3, 5]], 'existing vector');
});

test('coincident_endpoints_and_short_inputs', () => {
  const loop = [[0, 0], [3, 4], [0, 0]];
  same(simplify(loop, 0.5), loop, 'out-of-tolerance excursion kept');
  same(simplify([[0, 0], [0.1, 0], [0, 0]], 0.5), [[0, 0], [0, 0]], 'small excursion dropped');
  same(simplify([], 0.5), [], 'empty');
  same(simplify([[1, 2]], 0.5), [[1, 2]], 'singleton');
  same(simplify([[1, 2], [3, 4]], 0.5), [[1, 2], [3, 4]], 'pair');
});

test('tolerance_boundary_and_nonmutation', () => {
  same(simplify([[0, 0], [1, 0.5], [2, 0]], 0.5), [[0, 0], [2, 0]], 'exactly at tolerance drops');
  const beyond = [[0, 0], [1, 0.51], [2, 0]];
  same(simplify(beyond, 0.5), beyond, 'just beyond stays');
  // Perpendicular distance to the supporting line is 0.2 (< 0.5) but the point is 1.0+ from the segment.
  const exterior = [[0, 0], [3, 0.2], [1, 0]];
  same(simplify(exterior, 0.5), exterior, 'exterior point kept');
  const input = [[0, 0], [10, 0], [1, 0]], copy = JSON.parse(JSON.stringify(input));
  const out = simplify(input, 0.5);
  same(input, copy, 'input unchanged');
  assert.ok(out[0] === input[0] && out[1] === input[1] && out[2] === input[2], 'original references and order');
});
