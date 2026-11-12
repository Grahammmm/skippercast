// The day strip reveals the chosen chip by moving only its own scrollLeft (SC1722-19): never scrollIntoView, focus or another scroller.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const out = join(mkdtempSync(join(tmpdir(), 'dock-reveal-')), 'bundle.mjs');
await build({stdin: {resolveDir: process.cwd(), loader: 'ts', contents: `export {revealDockDay} from './web/app/TimeDock.tsx';`}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const {revealDockDay} = await import(pathToFileURL(out).href);

const rect = (left, width) => ({left, right: left + width, width, top: 0, bottom: 30, height: 30});
// A strip at x=100 with a 1 px border, 200 px of client width, 600 px of content; chips are drawn relative to the current scrollLeft.
function strip({scrollLeft = 0, left = 100, clientLeft = 1, clientWidth = 200, scrollWidth = 600} = {}) {
  const writes = [], trap = name => () => { throw new Error(`${name} must not be called`); };
  const el = {
    clientLeft, clientWidth, scrollWidth, scrollTop: 0, writes,
    getBoundingClientRect: () => rect(left, clientWidth + 2 * clientLeft),
    scrollIntoView: trap('scrollIntoView'), focus: trap('focus'), scrollTo: trap('scrollTo'), scrollBy: trap('scrollBy'),
  };
  let value = scrollLeft;
  Object.defineProperty(el, 'scrollLeft', {get: () => value, set: v => { writes.push(v); value = v; }});
  Object.defineProperty(el, 'scrollTop', {get: () => 0, set: () => { throw new Error('scrollTop must not be written'); }});
  return el;
}
// A chip whose content position is `at` (from the strip's content start): its box moves with the strip's scrollLeft.
const chip = (el, at, width = 80, base = 101) => ({getBoundingClientRect: () => rect(base + at - el.scrollLeft, width), scrollIntoView: () => { throw new Error('scrollIntoView must not be called'); }, focus: () => { throw new Error('focus must not be called'); }});

test('horizontal_reveal_left_right_visible_and_empty: a chip clipped on the right scrolls in by the least amount', () => {
  const s = strip();
  revealDockDay(s, chip(s, 300));       // spans 300..380 of 200 visible: needs 180
  assert.equal(s.scrollLeft, 180);
  assert.deepEqual(s.writes, [180]);
});

test('horizontal_reveal_left_right_visible_and_empty: a chip clipped on the left scrolls back by the least amount', () => {
  const s = strip({scrollLeft: 300});
  revealDockDay(s, chip(s, 250));       // visible window is 300..500, chip starts at 250
  assert.equal(s.scrollLeft, 250);
});

test('horizontal_reveal_left_right_visible_and_empty: a chip already fully visible causes no write', () => {
  const s = strip({scrollLeft: 100});
  revealDockDay(s, chip(s, 150));       // 150..230 inside 100..300
  revealDockDay(s, chip(s, 100));       // flush with the left edge
  revealDockDay(s, chip(s, 220));       // flush with the right edge
  assert.deepEqual(s.writes, []);
});

test('horizontal_reveal_left_right_visible_and_empty: fractional geometry inside half a pixel is not a scroll', () => {
  const s = strip({scrollLeft: 100});
  revealDockDay(s, chip(s, 220.4));     // 0.4 px past the right edge
  revealDockDay(s, chip(s, 99.6));      // 0.4 px before the left edge
  assert.deepEqual(s.writes, []);
});

test('horizontal_reveal_left_right_visible_and_empty: the result is clamped to the strip\'s own scroll range', () => {
  const near = strip({scrollLeft: 100, scrollWidth: 420});
  revealDockDay(near, chip(near, 395, 80));   // would want 275 (475 - 200), but the strip's range ends at 420 - 200 = 220
  assert.equal(near.scrollLeft, 220);
  const start = strip({scrollLeft: 10});
  revealDockDay(start, chip(start, -40));     // a chip left of the content start
  assert.equal(start.scrollLeft, 0);
});

test('horizontal_reveal_left_right_visible_and_empty: a chip wider than the strip is aligned to its left edge', () => {
  const s = strip();
  revealDockDay(s, chip(s, 50, 260));
  assert.equal(s.scrollLeft, 50);
});

test('horizontal_reveal_left_right_visible_and_empty: a missing strip or chip, or a zero-width strip, does nothing', () => {
  const s = strip();
  revealDockDay(null, chip(s, 300));
  revealDockDay(s, null);
  revealDockDay(null, null);
  const flat = strip({clientWidth: 0});
  revealDockDay(flat, chip(flat, 300));
  assert.deepEqual(s.writes, []);
  assert.deepEqual(flat.writes, []);
});

test('horizontal_reveal_left_right_visible_and_empty: only the strip\'s scrollLeft changes, with spies on every other scroll path', () => {
  const s = strip();
  for (const name of ['scrollTo', 'scroll', 'scrollBy']) globalThis[name] = () => { throw new Error(`window ${name} must not be called`); };
  revealDockDay(s, chip(s, 400));
  revealDockDay(s, chip(s, 0));
  assert.equal(s.scrollLeft, 0);
  for (const name of ['scrollTo', 'scroll', 'scrollBy']) delete globalThis[name];
});
