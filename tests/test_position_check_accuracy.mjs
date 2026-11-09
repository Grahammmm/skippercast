// RF0804-8: a wide reported position accuracy must not bypass closure proximity. geo-screen's screenPlace measures only closures whose box is
// within 20 km of the place; the position check promises "near" within 70 m plus the reported accuracy, so with a wide radius it measures the
// nearest held closure again without that shortcut. Synthetic held screens, the real shared geometry helpers and the real PositionView.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {PLANNING_MARGIN_M, distanceM, pointGeometry, screenPlace} from '../dist/geo-screen.js';
import {readingFor} from '../web/position-check.ts';

const root = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'position-accuracy-')), 'view.mjs');
await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export {PositionView} from './web/app/PositionView.tsx';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const view = await import(pathToFileURL(out).href);
const screenText = (fix, reading) => view.render(view.h(view.PositionView, {state: {phase: 'done', result: {located: {ok: true, fix}, reading}}, pack: 'saved', onCheck() {}, lang: 'en'}))
  .replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ');

const LAT = 35.005, LON = -120.25; // the estimated position
const mLat = 1 / 111320, mLon = 1 / (111320 * Math.cos(LAT * Math.PI / 180));
/** A 200 m square closure whose south-west corner is `east` / `north` metres from the estimated position. */
const square = (east, north) => { const w = LON + east * mLon, s = LAT + north * mLat, e = w + 200 * mLon, n = s + 200 * mLat; return {type: 'Polygon', coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}; };
const RESERVE = {type: 'Polygon', coordinates: [[[-120, 35], [-119.99, 35], [-119.99, 35.01], [-120, 35.01], [-120, 35]]]}; // the reproduced case: about 22.8 km east
const feature = (geometry, properties = {NAME: 'Synthetic reserve'}) => ({properties, geometry});
const held = (features, extra = {}) => ({current: true, missing: [], clock: 'ok', checked_at: '2026-11-09T15:00:00Z', features, ...extra});
const screenOf = (features, extra = {}, covers = () => true) => ({heldBoundaries: () => held(features, extra), coversGeometry: covers});
const fix = (accuracyM, p = {latitude: LAT, longitude: LON}) => ({latitude: p.latitude, longitude: p.longitude, accuracyM});
const measured = (p, geometry) => distanceM(pointGeometry(p.longitude, p.latitude), geometry);
const tenth = d => Math.round(d * 10) / 10;

test('wide_accuracy_reaches_a_closure_beyond_screen_shortcut', () => {
  const screen = screenOf([feature(RESERVE, {FULLNAME: 'Synthetic State Marine Reserve', NAME: 'Synthetic reserve'})]);
  const actual = measured(fix(25000), RESERVE);
  assert.ok(actual > 20000 && actual < 25000 + PLANNING_MARGIN_M, `the case is a closure past 20 km but inside the radius (${actual} m)`);
  const reading = readingFor(fix(25000), screen);
  assert.equal(reading.kind, 'checked');
  assert.equal(reading.where, 'near');
  assert.equal(reading.name, 'Synthetic State Marine Reserve');
  assert.equal(reading.distanceM, tenth(actual));
  assert.equal(reading.lowAccuracy, true);
  assert.equal(reading.fix.accuracyM, 25000);
  const text = screenText(fix(25000), reading);
  assert.match(text, /You are near Synthetic State Marine Reserve/);
  assert.ok(!/You are outside/.test(text), 'no outside headline');
  assert.match(text, /Nearest closure: 12\.\d nmi \(22\.\d km\) away/);
  assert.match(text, /Position accuracy: ±13\.\d nmi \(25\.0 km\)/);
  assert.match(text, /Low accuracy/);
  assert.match(text, /official/i);
});

test('wide_accuracy_recomputes_even_with_a_nonnull_shortcut_candidate', () => {
  const diagonal = feature(square(19000, 19000), {NAME: 'Diagonal'}); // boxes within 20 km on both axes: measured by screenPlace, but about 26.9 km away
  const beside = feature(square(21000, 0), {NAME: 'Beside'});          // 21 km due east: skipped by the shortcut, inside the radius
  const dDiagonal = measured(fix(25000), diagonal.geometry), dBeside = measured(fix(25000), beside.geometry);
  assert.ok(dBeside > 20000 && dBeside < 25000 + PLANNING_MARGIN_M && dDiagonal > 25000 + PLANNING_MARGIN_M, `${dBeside} inside, ${dDiagonal} outside the radius`);
  const premise = screenPlace({status: 'ready', boundaries: [{name: 'Diagonal', geometry: diagonal.geometry}, {name: 'Beside', geometry: beside.geometry}], coversGeometry: () => true}, fix(25000));
  assert.equal(premise.name, 'Diagonal', 'the shortcut alone returns a nonnull but farther candidate');
  for (const features of [[diagonal, beside], [beside, diagonal]]) {
    const reading = readingFor(fix(25000), screenOf(features));
    assert.equal(reading.where, 'near');
    assert.equal(reading.name, 'Beside');
    assert.equal(reading.distanceM, tenth(dBeside));
  }
  // Equal distances keep the first in held order.
  for (const [a, b] of [['First', 'Second'], ['Second', 'First']]) {
    const reading = readingFor(fix(25000), screenOf([feature(RESERVE, {NAME: a}), feature(RESERVE, {NAME: b})]));
    assert.equal(reading.name, a);
  }
  // No name on the closure reads as the unnamed headline.
  const unnamed = readingFor(fix(25000), screenOf([feature(RESERVE, {})]));
  assert.equal(unnamed.name, null);
  assert.match(screenText(fix(25000), unnamed), /You are near a closed area/);
});

test('wide_accuracy_keeps_inside_missing_layer_and_clock_semantics', () => {
  const inside = {latitude: 35.005, longitude: -119.995};
  const insideReading = readingFor(fix(25000, inside), screenOf([feature(RESERVE), feature(square(21000, 0), {NAME: 'Beside'})]));
  assert.equal(insideReading.where, 'inside');
  assert.equal(insideReading.name, 'Synthetic reserve');
  assert.equal(insideReading.distanceM, 0);
  // A partial held set with a closure in reach: still near, with the missing layer, stale flag and clock carried through.
  const partial = readingFor(fix(25000), screenOf([feature(RESERVE)], {current: false, missing: ['closures'], clock: 'old'}));
  assert.equal(partial.kind, 'checked');
  assert.equal(partial.where, 'near');
  assert.equal(partial.stale, true);
  assert.deepEqual(partial.missing, ['closures']);
  assert.equal(partial.clock, 'old');
  assert.equal(partial.checkedAt, '2026-11-09T15:00:00Z');
  // Partial and every held closure beyond the reach: still the incomplete refusal, never outside.
  const far = readingFor(fix(15000), screenOf([feature(RESERVE)], {current: false, missing: ['closures'], clock: 'old'}));
  assert.equal(far.kind, 'incomplete');
  assert.deepEqual(far.missing, ['closures']);
  const farWide = readingFor(fix(20500), screenOf([feature(square(0, 60000))], {missing: ['closures']}));
  assert.equal(farWide.kind, 'incomplete');
  // No boundaries and not covered keep their refusals.
  assert.equal(readingFor(fix(25000), screenOf([])).kind, 'no-boundaries');
  assert.equal(readingFor(fix(25000), null).kind, 'no-boundaries');
  assert.equal(readingFor(fix(25000), screenOf([feature(RESERVE)], {}, () => false)).kind, 'not-covered');
});

test('precise_and_boundary_controls_are_unchanged', () => {
  const screen = screenOf([feature(RESERVE)]);
  for (const accuracyM of [8, null, 0]) {
    const reading = readingFor(fix(accuracyM), screen);
    assert.equal(reading.where, 'outside', `accuracy ${accuracyM}`);
    assert.equal(reading.distanceM, null, 'a precise fix past the 20 km shortcut keeps the more-than-20-km display');
    assert.equal(reading.name, null);
    assert.equal(reading.lowAccuracy, accuracyM === null);
  }
  assert.match(screenText(fix(8), readingFor(fix(8), screen)), /more than 10\.8 nmi \(20\.0 km\) away/);
  // Ordinary accuracy still widens the 70 m margin.
  const close = {latitude: 35.005, longitude: -120.001};
  assert.equal(readingFor(fix(80, close), screen).where, 'near');
  assert.equal(readingFor(fix(0, close), screen).where, 'outside');
  const at50 = {latitude: 35.005, longitude: -120 - 50 * mLon};
  assert.equal(readingFor(fix(0, at50), screen).where, 'near', 'zero accuracy is valid and the margin alone applies');
  assert.equal(readingFor(fix(0, at50), screen).distanceM, tenth(measured(at50, RESERVE)));
  // Equality at the measured reach is near; just below it is outside.
  const r = tenth(measured(fix(25000), RESERVE));
  let exact = r - PLANNING_MARGIN_M;
  while (PLANNING_MARGIN_M + exact < r) exact += exact * Number.EPSILON;
  assert.ok(exact > 20000 - PLANNING_MARGIN_M && PLANNING_MARGIN_M + exact >= r);
  assert.equal(readingFor(fix(exact), screen).where, 'near');
  assert.equal(readingFor(fix(r - PLANNING_MARGIN_M - 0.2), screen).where, 'outside');
  // A wide radius with every held closure beyond its reach is outside, not blanket near.
  const outside = readingFor(fix(25000), screenOf([feature(square(40000, 0), {NAME: 'Far east'}), feature(square(0, 50000), {NAME: 'Far north'})]));
  assert.equal(outside.where, 'outside');
  assert.equal(outside.name, 'Far east');
  assert.ok(outside.distanceM > 25000 + PLANNING_MARGIN_M);
});
