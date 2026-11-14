// RF1045-8: a distance that only ROUNDS to 0.0 m is not a closure contact. The wide-accuracy fallback in readingFor measures the nearest held
// closure again; it must take "inside" from exact geometry (geo-screen's raw distance of exactly 0), never from the tenth-metre display value.
// Synthetic held screens, the real shared geometry helpers and the real PositionView.
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import {distanceM, pointGeometry, screenPlace} from '../dist/geo-screen.js';
import {readingFor} from '../web/position-check.ts';

const root = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'position-zero-')), 'view.mjs');
await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export {PositionView} from './web/app/PositionView.tsx';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const view = await import(pathToFileURL(out).href);
const markup = (fix, reading, lang = 'en') => view.render(view.h(view.PositionView, {state: {phase: 'done', result: {located: {ok: true, fix}, reading}}, pack: 'saved', onCheck() {}, lang}));
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ');

const SQUARE = {type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]};
const NAME = 'Synthetic closure', CHECKED_AT = '2026-11-14T00:00:00Z';
const OUTSIDE = {latitude: 0.005, longitude: -0.0000003}; // about 0.0334 m west of the square's west edge
const FARTHER = {latitude: 0.005, longitude: -0.000002};  // about 0.22 m west: rounds to 0.2
const feature = (geometry, properties = {FULLNAME: NAME}) => ({properties, geometry});
const held = (features, extra = {}) => ({current: true, missing: [], clock: 'ok', checked_at: CHECKED_AT, features, ...extra});
const screenOf = (features = [feature(SQUARE)], extra = {}, covers = () => true) => ({heldBoundaries: () => held(features, extra), coversGeometry: covers});
const fix = (accuracyM, p = OUTSIDE) => ({latitude: p.latitude, longitude: p.longitude, accuracyM});
const raw = (p, geometry = SQUARE) => distanceM(pointGeometry(p.longitude, p.latitude), geometry);
const direct = (p, features = [feature(SQUARE)]) => screenPlace({status: 'ready', boundaries: features.map(f => ({name: f.properties.FULLNAME || null, geometry: f.geometry})), coversGeometry: () => true}, p);

test('positive_distance_rounded_to_zero_stays_near', () => {
  const d = raw(OUTSIDE);
  assert.ok(d > 0 && d < 0.05, `the premise: strictly positive and rounds to 0.0 (${d} m)`);
  const shared = direct(OUTSIDE);
  assert.equal(shared.inside, false, 'the shared screen does not call it inside');
  assert.equal(shared.distanceM, 0);
  for (const accuracyM of [19930, 25000]) {
    const reading = readingFor(fix(accuracyM), screenOf());
    assert.equal(reading.kind, 'checked');
    assert.equal(reading.where, 'near', `accuracy ${accuracyM}`);
    assert.equal(reading.distanceM, 0);
    assert.equal(reading.name, NAME);
    assert.equal(reading.lowAccuracy, true);
    assert.equal(reading.stale, false);
    assert.equal(reading.clock, 'ok');
    assert.equal(reading.checkedAt, CHECKED_AT);
    assert.equal(reading.fix.accuracyM, accuracyM);
  }
});

test('fallback_boundary_does_not_change_membership', () => {
  // 19930 + the 70 m planning margin is the 20 km search bound; below it the fallback is off, at and above it the fallback measures again.
  for (const accuracyM of [8, 19929, 19930, 19931]) {
    const reading = readingFor(fix(accuracyM), screenOf());
    assert.equal(reading.where, 'near', `accuracy ${accuracyM}`);
    assert.equal(reading.distanceM, 0);
    assert.equal(reading.lowAccuracy, accuracyM > 100);
  }
  // Another positive distance, above 0.05 m: no epsilon widens "inside".
  assert.ok(raw(FARTHER) > 0.05);
  for (const accuracyM of [8, 19930, 25000]) {
    const reading = readingFor(fix(accuracyM, FARTHER), screenOf());
    assert.equal(reading.where, 'near', `accuracy ${accuracyM}`);
    assert.equal(reading.distanceM, Math.round(raw(FARTHER) * 10) / 10);
  }
});

test('exact_boundary_and_interior_remain_inside', () => {
  const points = {edge: {latitude: 0.005, longitude: 0}, vertex: {latitude: 0, longitude: 0}, interior: {latitude: 0.005, longitude: 0.005}};
  for (const [label, p] of Object.entries(points)) {
    assert.equal(raw(p), 0, `${label} is exact contact or inside for the shared helper`);
    for (const accuracyM of [8, 19930, 25000]) {
      const reading = readingFor(fix(accuracyM, p), screenOf());
      assert.equal(reading.where, 'inside', `${label} at accuracy ${accuracyM}`);
      assert.equal(reading.distanceM, 0);
      assert.equal(reading.name, NAME);
    }
  }
});

test('partial_and_stale_data_preserve_caveats', () => {
  const extra = {missing: ['noaa-closures'], current: false, clock: 'old'};
  const reading = readingFor(fix(25000), screenOf([feature(SQUARE)], extra));
  assert.equal(reading.kind, 'checked');
  assert.equal(reading.where, 'near');
  assert.equal(reading.distanceM, 0);
  assert.deepEqual(reading.missing, ['noaa-closures']);
  assert.equal(reading.stale, true);
  assert.equal(reading.clock, 'old');
  assert.equal(reading.checkedAt, CHECKED_AT);
  // Existing refusals are unchanged: partial data and a far outside point stay incomplete; no data / outside coverage give no verdict.
  const far = readingFor(fix(8, {latitude: 0.5, longitude: 0.5}), screenOf([feature(SQUARE)], extra));
  assert.equal(far.kind, 'incomplete');
  assert.deepEqual(far.missing, ['noaa-closures']);
  assert.equal(readingFor(fix(25000), screenOf([])).kind, 'no-boundaries');
  assert.equal(readingFor(fix(25000), screenOf([feature(SQUARE)], {}, () => false)).kind, 'not-covered');
});

test('rendered_headline_uses_geometry_not_display_zero', () => {
  const f = fix(25000), reading = readingFor(f, screenOf());
  for (const [lang, near, inside] of [['en', /You are near Synthetic closure/, /You are inside/], ['es', /Estás cerca de Synthetic closure/, /Estás dentro de/]]) {
    const html = markup(f, reading, lang), s = text(html);
    assert.match(s, near, lang);
    assert.ok(!inside.test(s), `${lang}: not the inside headline`);
    assert.match(html, /data-where="near"/);
    assert.match(s, lang === 'en' ? /Low accuracy/ : /Precisión baja/);
    assert.match(s, lang === 'en' ? /Position accuracy: ±13\.\d nmi \(25\.0 km\)/ : /Precisión de la posición: ±13[.,]\d nmi/);
    assert.match(s, lang === 'en' ? /Official CDFW rules govern/ : /Rigen las reglas oficiales del CDFW/);
  }
  // Exact contact still reads inside in the same view.
  const touching = fix(25000, {latitude: 0.005, longitude: 0});
  assert.match(text(markup(touching, readingFor(touching, screenOf()))), /You are inside Synthetic closure/);
});

test('nearest_selection_and_far_controls_remain', () => {
  const RESERVE = {type: 'Polygon', coordinates: [[[0.2, 0], [0.21, 0], [0.21, 0.01], [0.2, 0.01], [0.2, 0]]]}; // about 22 km east of the square
  const features = [feature(RESERVE, {FULLNAME: 'Far reserve'}), feature(SQUARE, {FULLNAME: 'Near square'})];
  const reading = readingFor(fix(25000), screenOf(features));
  assert.equal(reading.where, 'near');
  assert.equal(reading.name, 'Near square', 'the nearest held closure is chosen by raw distance, not published order');
  // A distant point at ordinary accuracy is still outside.
  const faraway = readingFor(fix(8, {latitude: 0.005, longitude: 0.1}), screenOf());
  assert.equal(faraway.where, 'outside');
  // Equal raw distances keep the first in held order; an unnamed closure reads null.
  const tie = readingFor(fix(25000), screenOf([feature(SQUARE, {FULLNAME: 'First'}), feature(SQUARE, {FULLNAME: 'Second'})]));
  assert.equal(tie.name, 'First');
  assert.equal(readingFor(fix(25000), screenOf([feature(SQUARE, {})])).name, null);
});
