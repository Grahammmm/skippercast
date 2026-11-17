// RF1951-10: automatic chart scales keep negative-only samples inside the row, larger values drawn higher.
import assert from 'node:assert/strict';
import test from 'node:test';
import {chart} from '../packages/coast/src/charts/series.ts';

const START = '2026-01-01T00:00:00Z', END = '2026-01-01T02:00:00Z', MID = '2026-01-01T01:00:00Z';
const render = (values, extra = {}) => chart([{label: 'T', unit: 'u', color: '#fff', points: [{at: START, value: values[0]}, {at: MID, value: values[1]}], ...extra}],
  START, END, START, 'UTC', {});
const ys = svg => [...svg.match(/<path d="([^"]*)"/)[1].matchAll(/[ML][\d.]+,(-?[\d.]+)/g)].map(m => Number(m[1]));
const inRow = y => Number.isFinite(y) && y >= 16 && y <= 77;

test('negative_only_scale_contains_points', () => {
  for (const values of [[-10, -9], [-2, -1]]) {
    const [a, b] = ys(render(values));
    assert.ok(inRow(a) && inRow(b), `${values} -> ${a},${b}`);
    assert.ok(b < a, 'larger value is drawn higher');
  }
});

test('negative_constant_scale_is_nondegenerate', () => {
  const [a, b] = ys(render([-10, -10]));
  assert.ok(inRow(a) && a === b);
});

test('nonnegative_and_explicit_controls_are_unchanged', () => {
  assert.match(render([1, 2]), /M69\.00,50\.48 L438\.50,23\.96/);
  assert.ok(ys(render([0, 0])).every(inRow));
  assert.ok(ys(render([-3, 5])).every(inRow));
  const [a, b] = ys(render([-11, -9], {min: -12, max: -8}));
  assert.ok(Math.abs(a - 61.75) < 0.01 && Math.abs(b - 31.25) < 0.01, `explicit bounds: ${a},${b}`);
});
