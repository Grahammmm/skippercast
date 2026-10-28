import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, mkdirSync, writeFileSync, realpathSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {boundSurfaceContrast, checkSurfaceSource, evaluateContrast, SURFACE_SOURCE_SHA256} from '../scripts/check_contrast.mjs';
const BLACK = [0, 0, 0, 1], WHITE = [255, 255, 255, 1];
const sourcePaths = {panelCss: 'packages/coast/panel.css', bridgeCss: 'packages/coast/tokens-bridge.css',
  tokensCss: 'web/tokens.css', appCss: 'web/app/app.css', legendTsx: 'web/app/Legend.tsx'};
const sources = () => Object.fromEntries(Object.entries(sourcePaths).map(([key, path]) => [key, readFileSync(new URL('../' + path, import.meta.url), 'utf8')]));
const request = {foreground: WHITE, surface: BLACK, alphaRange: [1, 1], backingMin: BLACK, backingMax: WHITE};

test('surface bound: opaque and clear identities and fractional source-over', () => {
  const opaque = boundSurfaceContrast(request);
  assert.equal(opaque.status, 'source_pass');
  assert.equal(opaque.lowerBound, 21);
  const clear = boundSurfaceContrast({...request, alphaRange: [0, 0], backingMin: WHITE});
  assert.equal(clear.lowerBound, 1);
  assert.equal(clear.status, 'not_proven');
  const half = boundSurfaceContrast({...request, alphaRange: [0.5, 0.5], backingMin: WHITE});
  assert.deepEqual(half.channels, [[127.5, 127.5], [127.5, 127.5], [127.5, 127.5]]);
  assert.equal(half.lowerBound, evaluateContrast({foreground: WHITE, background: [127.5, 127.5, 127.5, 1]}).ratio);
});

test('surface bound: passing black/white samples cannot hide an interior backdrop failure', () => {
  const foreground = [117, 117, 117, 1];
  for (const background of [BLACK, WHITE]) assert.ok(evaluateContrast({foreground, background}).ratio >= 4.5);
  const bound = boundSurfaceContrast({...request, foreground, alphaRange: [0, 0]});
  assert.equal(bound.status, 'not_proven');
  assert.equal(bound.lowerBound, 1);
  assert.equal(evaluateContrast({foreground, background: foreground}).ratio, 1);
});

test('surface bound: passing alpha endpoints cannot hide interior foreground equality', () => {
  const foreground = [117, 117, 117, 1];
  const bound = boundSurfaceContrast({foreground, surface: WHITE, alphaRange: [0, 1], backingMin: BLACK, backingMax: BLACK});
  assert.equal(bound.status, 'not_proven');
  assert.equal(bound.lowerBound, 1);
  const interior = evaluateContrast({foreground, background: [255, 255, 255, 117 / 255],
    backing: BLACK, backingProvenance: 'synthetic alpha interior equality'});
  assert.equal(interior.ratio, 1);
});

test('surface bound: the historical transfer-function split is conservatively enclosed', () => {
  const split = 0.03928, below = split - 1e-8, above = split + 1e-8;
  const bound = boundSurfaceContrast({...request, alphaRange: [0, 0],
    backingMin: [below * 255, below * 255, below * 255, 1],
    backingMax: [above * 255, above * 255, above * 255, 1]});
  const highSideLimit = ((split + 0.055) / 1.055) ** 2.4;
  assert.ok(bound.luminanceRange[0] <= highSideLimit + 1e-15);
  assert.ok(bound.luminanceRange[1] >= split / 12.92 - 1e-15);
  assert.ok(highSideLimit < below / 12.92); // An endpoint-only monotonic proof would miss this.
});

test('surface bound: unsupported opacity, malformed domains and missing requests fail closed', () => {
  for (const bad of [null, {}, {...request, foreground: [255, 255, 255, 0.9]},
    {...request, backingMin: [0, 0, 0, 0.5]}, {...request, backingMin: WHITE, backingMax: BLACK},
    {...request, alphaRange: Array(2)}, {...request, alphaRange: [0, NaN]},
    {...request, alphaRange: [0.5, 0.4]}, {...request, alphaRange: [0, 1.1]},
    {...request, surface: [0, 0, 0, 0.27]}, {...request, surface: [256, 0, 0, 1]}]) {
    const result = boundSurfaceContrast(bad);
    assert.equal(result.status, 'resolution_error');
    assert.equal(result.lowerBound, null);
    assert.equal(result.rendered, false);
  }
});

test('surface source: twelve exact theme/foreground cases clear 4.5 over complete domains', () => {
  const result = checkSurfaceSource(sources());
  assert.deepEqual(result.failures, []);
  assert.deepEqual(result.hashes, SURFACE_SOURCE_SHA256);
  assert.equal(result.results.length, 12);
  assert.equal(new Set(result.results.map(r => r.theme + ':' + r.id)).size, 12);
  for (const row of result.results) {
    assert.equal(row.status, 'source_pass');
    assert.ok(row.lowerBound >= 4.5);
    assert.equal(row.rendered, false);
    if (row.id.startsWith('sheen-')) {
      assert.deepEqual(row.domain.alphaRange, [0, 0.27]);
      assert.deepEqual(row.domain.backingMin, row.domain.backingMax);
    } else {
      assert.deepEqual(row.domain.backingMin, BLACK);
      assert.deepEqual(row.domain.backingMax, WHITE);
    }
  }
  console.log('surface source proof ' + JSON.stringify(result));
});

test('surface source: changed paint, role, theme, renderer or later override invalidates binding', () => {
  const original = sources();
  for (const [key, mutate] of [
    ['panelCss', s => s.replace('blur(15px)', 'blur(15px) brightness(2)')],
    ['bridgeCss', s => s.replace('94%', '4%')],
    ['tokensCss', s => s.replace('--muted: #4a6373;', '--muted: #ffffff;')],
    ['appCss', s => s.replace('92%', '2%')],
    ['legendTsx', s => s.replace('class="app-legend"', 'class="other-legend"')],
    ['panelCss', s => s + '\n.map-legend {opacity:.1}'],
    ['tokensCss', s => s + '\n@media (min-width:1px) {:root {--muted:#ffffff}}'],
  ]) {
    const changed = mutate(original[key]);
    assert.notEqual(changed, original[key]);
    const result = checkSurfaceSource({...original, [key]: changed});
    assert.equal(result.failures.length, 1);
    assert.equal(result.failures[0].status, 'resolution_error');
    assert.match(result.failures[0].reason, /binding changed/);
    assert.equal(result.results.length, 1);
  }
  assert.equal(checkSurfaceSource({}).failures[0].status, 'resolution_error');
});

test('surface source CLI: snapshot passes and a changed backing fails without a pass claim', {concurrency: false}, async () => {
  for (const changed of [false, true]) {
    const root = realpathSync(mkdtempSync(join(tmpdir(), 'contrast-surface-')));
    const original = {argv: process.argv, exit: process.exit, log: console.log};
    const output = [], exits = [], signal = new Error('surface fixture exit');
    try {
      const fixture = sources();
      if (changed) fixture.bridgeCss = fixture.bridgeCss.replace('94%', '4%');
      for (const [key, path] of Object.entries(sourcePaths)) {
        mkdirSync(dirname(join(root, path)), {recursive: true});
        writeFileSync(join(root, path), fixture[key]);
      }
      const script = join(root, 'scripts/check_contrast.mjs');
      mkdirSync(dirname(script), {recursive: true});
      writeFileSync(script, readFileSync(new URL('../scripts/check_contrast.mjs', import.meta.url)));
      process.argv = [process.execPath, script, '--surface-source'];
      process.exit = code => { exits.push(code); throw signal; };
      console.log = (...args) => output.push(args.join(' '));
      await assert.rejects(import(pathToFileURL(script).href), error => error === signal);
    } finally {
      process.argv = original.argv; process.exit = original.exit; console.log = original.log;
      rmSync(root, {recursive: true, force: true});
    }
    assert.deepEqual(exits, [changed ? 1 : 0]);
    assert.equal(output.length, 1);
    const result = JSON.parse(output[0]);
    assert.equal(result.rendered, false);
    assert.equal(result.failures.length, changed ? 1 : 0);
    assert.equal(result.results.length, changed ? 1 : 12);
    if (changed) assert.equal(result.results.some(r => r.status === 'source_pass'), false);
  }
});
