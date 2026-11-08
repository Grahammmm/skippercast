// SC-GPSOFFLINE-1 (t_a0686aad): the position check over a region with a SECOND boundary layer (Southern California: CDFW MPAs plus NOAA groundfish exclusion
// areas), composed through the real planner screen (dist/protected-areas.js initProtectedAreas -> readingFor -> the rendered PositionView). An offline device can
// hold the first file and have lost the second; that must never read as "outside every closed area", and a missing layer must never be called "old".
// Own file: it switches the active region, which the single-layer tests in test_position_check.mjs must not inherit.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
const {assetURL, getRegion, setRegion} = await import('../dist/region.js');
setRegion(JSON.parse(readFileSync(new URL('../dist/regions/southern-california/region.json', import.meta.url), 'utf8')));
assert.ok(assetURL('closures'), 'Southern California configures a second boundary layer');
const {initProtectedAreas} = await import('../dist/protected-areas.js'); // after setRegion: the module's query envelope is the active region's
const {readingFor} = await import('../web/position-check.ts');

const dist = new URL('../dist/', import.meta.url);
const mpas = JSON.parse(readFileSync(new URL(assetURL('protected_areas'), dist), 'utf8'));
const closures = JSON.parse(readFileSync(new URL(assetURL('closures'), dist), 'utf8'));
const NOW = Date.now(), at = ms => new Date(NOW + ms).toISOString();
globalThis.document = {getElementById: () => null, createElement: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};

// The reviewer's real case: inside Seamount 109 Groundfish Exclusion Area, which only the second layer holds.
const SEAMOUNT = {latitude: 32.5295, longitude: -119.50000000000009};
const fix = (p, accuracyM = 8) => ({latitude: p.latitude, longitude: p.longitude, accuracyM});

/** The planner's screen over files that each read or fail, as the service worker answers them offline; `requests` records every path asked for. */
async function screenWith({mpasAt = at(-3600000), closuresAt = at(-3600000), closuresReadable = true, mpasReadable = true} = {}) {
  const requests = [];
  const screen = await initProtectedAreas(null, () => {}, async path => {
    requests.push(path);
    if (path === assetURL('protected_areas') && mpasReadable) return {...mpas, checked_at: mpasAt};
    if (path === assetURL('closures') && closuresReadable) return {...closures, checked_at: closuresAt};
    throw new Error('offline: file not saved');
  });
  return {screen, requests};
}

const out = join(await mkdtemp(join(tmpdir(), 'position-layers-')), 'view.mjs');
await build({stdin: {resolveDir: root, loader: 'ts', contents: `
    export {PositionView} from './web/app/PositionView.tsx';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const view = await import(pathToFileURL(out).href);
const screenText = (f, reading, pack = 'partial') => view.render(view.h(view.PositionView, {state: {phase: 'done', result: {located: {ok: true, fix: f}, reading}}, pack, onCheck() {}, lang: 'en'}))
  .replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ');

test('control: with both files held, the Seamount 109 position is inside, at 0 m, and nothing is missing', async () => {
  const {screen} = await screenWith();
  const held = screen.heldBoundaries();
  assert.deepEqual(held.missing, []);
  assert.equal(held.clock, 'ok');
  assert.equal(held.current, true);
  const reading = readingFor(fix(SEAMOUNT), screen);
  assert.equal(reading.kind, 'checked');
  assert.equal(reading.where, 'inside');
  assert.match(reading.name, /Seamount 109/);
  assert.equal(reading.distanceM, 0);
  assert.match(screenText(fix(SEAMOUNT), reading, 'saved'), /You are inside .*Seamount 109/);
});

test('offline with the second layer missing: the same position is NOT called outside, no nearest-closure claim, and the missing dataset is named', async () => {
  const {screen, requests} = await screenWith({closuresReadable: false});
  assert.ok(requests.includes(assetURL('closures')), 'the screen did try the second file');
  const held = screen.heldBoundaries();
  assert.deepEqual(held.missing, ['closures']);
  assert.equal(held.current, false);
  assert.equal(held.clock, 'ok', 'today\'s check of the first file is not old');
  const reading = readingFor(fix(SEAMOUNT), screen);
  assert.equal(reading.kind, 'incomplete');
  assert.deepEqual(reading.missing, ['closures']);
  const shown = screenText(fix(SEAMOUNT), reading);
  assert.match(shown, /can't tell whether you are outside the closed areas/);
  assert.match(shown, /NOAA groundfish exclusion areas/);
  assert.match(shown, /not an all-clear/);
  assert.match(shown, /Position accuracy: ±8 m/);
  assert.match(shown, /Check the official rules/);
  assert.doesNotMatch(shown, /You are outside/);
  assert.doesNotMatch(shown, /nearest closure is more than/i);
  assert.doesNotMatch(shown, /more than 36 hours ago/, 'a missing file is not an old one');
});

test('a closure the held layer does have still stands with the other layer missing, and the angler is told the answer is partial', async () => {
  const {screen} = await screenWith({closuresReadable: false});
  // A vertex of the first MPA the region's envelope covers: on the boundary counts as inside.
  const vertexOf = f => { const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0]; return {longitude: ring[0][0], latitude: ring[0][1]}; };
  const onBoundary = mpas.features.map(vertexOf).find(p => readingFor(fix(p), screen).kind === 'checked');
  assert.ok(onBoundary, 'a covered MPA vertex exists');
  const reading = readingFor(fix(onBoundary), screen);
  assert.equal(reading.kind, 'checked');
  assert.equal(reading.where, 'inside');
  assert.deepEqual(reading.missing, ['closures']);
  const shown = screenText(fix(onBoundary), reading);
  assert.match(shown, /You are inside/);
  assert.match(shown, /NOAA groundfish exclusion areas/);
  assert.match(shown, /other, closer closures that are not shown/);
});

test('a first layer that is gone is "not available", whatever the second layer holds', async () => {
  const {screen} = await screenWith({mpasReadable: false});
  assert.equal(screen.heldBoundaries(), null);
  assert.equal(readingFor(fix(SEAMOUNT), screen).kind, 'no-boundaries');
});

test('old, future-dated and undated check times are each told apart from missing data', async () => {
  const cases = [
    ['old', {closuresAt: at(-5 * 86400000)}, /last checked \d{4}-\d{2}-\d{2}, more than 36 hours ago/],
    ['future', {closuresAt: at(3 * 86400000)}, /in the future, so we cannot tell how current/],
    ['unknown', {closuresAt: 'not a date'}, /missing or unreadable, so we cannot tell how current/],
  ];
  for (const [clock, options, words] of cases) {
    const {screen} = await screenWith(options);
    const held = screen.heldBoundaries();
    assert.equal(held.clock, clock, clock);
    assert.deepEqual(held.missing, [], clock);
    const reading = readingFor(fix(SEAMOUNT), screen);
    assert.equal(reading.kind, 'checked', clock);
    assert.equal(reading.where, 'inside', clock);
    assert.equal(reading.clock, clock);
    const shown = screenText(fix(SEAMOUNT), reading, 'saved');
    assert.match(shown, words, clock);
    assert.doesNotMatch(shown, /not on this device/, `${clock}: the file is held, only its date is wrong`);
  }
});

test('the composed offline case carries no coordinates in any file request', async () => {
  const {requests} = await screenWith({closuresReadable: false});
  const forms = ['32.5295', '119.5', '119.50000000000009', '32.529'];
  for (const r of requests) for (const f of forms) assert.ok(!r.includes(f), `${r} carries ${f}`);
  assert.equal(getRegion().id, 'southern-california');
});
