import assert from 'node:assert/strict';
import test from 'node:test';
import {feedAgeMinutes, watchdog} from '../server/watchdog.ts';

const NOW = Date.parse('2026-11-16T12:00:00Z');
const iso = ms => new Date(NOW + ms).toISOString();
const run = feed => watchdog({}, NOW, Promise.resolve(feed));
const quiet = async fn => { const w = console.warn; console.warn = () => {}; try { return await fn(); } finally { console.warn = w; } };

test('watchdog_future_clock_is_unknown_not_fresh', async () => {
  const feed = {completed_at: '2027-11-16T12:00:00Z'};
  assert.equal(feedAgeMinutes(feed, NOW), Infinity);
  const r = await quiet(() => run(feed));
  assert.equal(r.age_minutes, null);
  assert.equal(r.action, 'no-token');
});

test('watchdog_future_tolerance_boundary', async () => {
  const edge = {completed_at: iso(3600000)};
  assert.equal(feedAgeMinutes(edge, NOW), -60);
  assert.equal((await run(edge)).action, 'none');
  const over = {completed_at: iso(3600001)};
  assert.equal(feedAgeMinutes(over, NOW), Infinity);
  assert.equal((await quiet(() => run(over))).action, 'no-token');
});

test('watchdog_timestamp_precedence_survives', () => {
  assert.equal(feedAgeMinutes({completed_at: iso(7200000), generated_at: iso(0)}, NOW), Infinity);
  assert.equal(feedAgeMinutes({generated_at: iso(0)}, NOW), 0);
  assert.equal(feedAgeMinutes({generated_at: '2027-11-16T12:00:00Z'}, NOW), Infinity);
});

test('watchdog_healthy_clock_controls', async () => {
  for (const [ms, age] of [[0, 0], [-1200000, 20], [-2700000, 45]]) {
    const feed = {completed_at: iso(ms)};
    assert.equal(feedAgeMinutes(feed, NOW), age);
    assert.equal((await run(feed)).action, 'none');
  }
  assert.equal((await quiet(() => run({completed_at: iso(-2700001)}))).action, 'no-token');
  for (const feed of [{}, {completed_at: 'bad'}]) {
    const r = await quiet(() => run(feed));
    assert.equal(r.age_minutes, null);
    assert.equal(r.action, 'no-token');
  }
});
