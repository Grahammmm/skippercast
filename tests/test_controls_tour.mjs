import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {TOUR_STEPS, tourTransition} from '../web/tour.ts';

const out = join(await mkdtemp(join(tmpdir(), 'controls-tour-')), 'tour.mjs');
await build({
  stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {ControlsTour} from './web/app/ControlsTour.tsx';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out,
  jsx: 'automatic', jsxImportSource: 'preact', logLevel: 'silent',
});
const {ControlsTour, render, h} = await import(pathToFileURL(out).href);

test('tour starts on request, skips from every step and replays from the beginning', () => {
  assert.equal(tourTransition(null, 'next'), null);
  assert.equal(tourTransition(null, 'back'), null);
  for (let step = 0; step < TOUR_STEPS.length; step++) {
    assert.equal(tourTransition(step, 'close'), null);
    assert.equal(tourTransition(tourTransition(step, 'close'), 'replay'), 0);
    assert.equal(tourTransition(step, 'replay'), 0);
  }
});

test('forward/back stay within the tour; completion allows replay', () => {
  let step = tourTransition(null, 'replay');
  assert.equal(tourTransition(step, 'back'), 0);
  for (let expected = 1; expected < TOUR_STEPS.length; expected++) {
    step = tourTransition(step, 'next');
    assert.equal(step, expected);
    assert.equal(tourTransition(step, 'back'), expected - 1);
  }
  step = tourTransition(step, 'next');
  assert.equal(step, null);
  assert.equal(tourTransition(step, 'replay'), 0);
});

test('one copy source renders four short steps with skip, back and completion controls', () => {
  assert.deepEqual(TOUR_STEPS.map(s => s.title), ['Time dock', 'Layer list', 'Save for offline', 'Evidence-limit line']);
  for (const [step, content] of TOUR_STEPS.entries()) {
    const html = render(h(ControlsTour, {step, act() {}}));
    assert.ok(html.includes(content.title));
    assert.ok(html.includes(content.text));
    assert.match(html, /aria-live="polite" aria-atomic="true"/);
    assert.match(html, /Skip tour/);
    assert.match(html, /Back/);
    assert.ok(html.includes(step === 3 ? 'Finish' : 'Next'));
    assert.doesNotMatch(content.text, /catch|hotspot/i);
  }
});
