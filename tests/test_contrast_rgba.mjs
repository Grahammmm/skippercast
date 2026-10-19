// Isolated synthetic qualification for P10 helpers. These colours are fixtures,
// not accepted map backdrops or evidence about production contrast.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {
  FILES, PAIRS_BRIDGE, check, checkBridge, classifyContrast, evaluateContrast,
  resolveRgba, sourceOver, checkTransparentBridge,
} from '../scripts/check_contrast.mjs';

const BLACK = [0, 0, 0, 1], WHITE = [255, 255, 255, 1];
const PROVENANCE = 'Synthetic unit fixture: uniform solid backing';
const declarations = values => Object.entries(values).map(([key, value]) => `--${key}: ${value};`).join('\n');
const V2_CSS = `:root {
${declarations({bg: '#000000', 'bg-deep': '#000000', panel: '#000000', 'panel-2': '#000000',
  text: '#ffffff', muted: '#ffffff', mint: '#ffffff', blue: '#ffffff', coral: '#ffffff', amber: '#ffffff'})}
}
:root[data-theme="light"] { }`;
const BRIDGE_CSS = `[data-coast-theme="tokens"] {
${declarations(Object.fromEntries(Object.entries({ground: 'bg', panel: 'panel', 'panel-2': 'panel-2',
  hover: 'panel', 'mint-wash': 'panel', text: 'text', muted: 'muted', mint: 'mint',
  blue: 'blue', coral: 'coral', amber: 'amber', 'on-mint': 'bg'}).map(([role, token]) => [`coast-${role}`, `var(--${token})`])))}
--coast-panel-glass: color-mix(in srgb, var(--panel) 94%, transparent);
--coast-sheen: color-mix(in srgb, var(--panel-2) 27%, transparent);
}`;
const REQUEST = {id: 'synthetic-backed', fg: 'text', bg: 'panel-glass', backing: 'panel', backingProvenance: PROVENANCE};
const assertUnresolved = (result, status) => {
  assert.equal(result.status, status);
  assert.equal(result.ratio, null);
  assert.equal(typeof result.reason, 'string');
  assert.ok(result.reason.length > 0);
};

test('transparent mix alpha 0 and 1 preserve backing and surface identities', () => {
  const tokens = {paint: '#804020'};
  const clear = resolveRgba('color-mix(in srgb, var(--paint) 0%, transparent)', tokens);
  const solid = resolveRgba('color-mix(in srgb, var(--paint) 100%, transparent)', tokens);
  assert.deepEqual(clear, [0, 0, 0, 0]);
  assert.deepEqual(solid, [128, 64, 32, 1]);
  assert.deepEqual(sourceOver(clear, WHITE), WHITE);
  assert.deepEqual(sourceOver(solid, WHITE), solid);
  assert.deepEqual(resolveRgba('color-mix(in srgb, var(--paint) 50%, transparent)', tokens), [128, 64, 32, 0.5]);
  assert.deepEqual(resolveRgba('var(--alias)', {alias: 'var(--paint)', ...tokens}), solid);
});

test('encoded-sRGB half-black over white keeps 127.5 without hex rounding', () => {
  const surface = [0, 0, 0, 0.5], backing = [...WHITE];
  assert.deepEqual(sourceOver(surface, backing), [127.5, 127.5, 127.5, 1]);
  assert.deepEqual(resolveRgba('color-mix(in srgb, #000000 50%, #ffffff)'), [127.5, 127.5, 127.5, 1]);
  assert.deepEqual(surface, [0, 0, 0, 0.5]);
  assert.deepEqual(backing, WHITE);
  assert.deepEqual(sourceOver([0, 0, 0, 0], [0, 0, 0, 0]), [0, 0, 0, 0]);
});

test('foreground is composited after background and floats reach luminance', () => {
  const result = evaluateContrast({foreground: [255, 255, 255, 0.5], background: BLACK});
  assert.deepEqual(result.foreground, [127.5, 127.5, 127.5, 1]);
  assert.deepEqual(result.background, BLACK);
  assert.equal(result.status, 'pass');
  assert.ok(Math.abs(result.ratio - 5.280822809644651) < 1e-12);
  const layered = evaluateContrast({foreground: [255, 255, 255, 0.5], background: [0, 0, 0, 0.5],
    backing: WHITE, backingProvenance: PROVENANCE});
  assert.deepEqual(layered.background, [127.5, 127.5, 127.5, 1]);
  assert.deepEqual(layered.foreground, [191.25, 191.25, 191.25, 1]);
  assert.equal(layered.status, 'measured_failure');
  assert.equal(evaluateContrast({foreground: [255, 255, 255, 0], background: BLACK}).ratio, 1);
});

test('white on opaque black passes; transparent black on white fails', () => {
  const opaque = evaluateContrast({foreground: WHITE, background: BLACK});
  assert.equal(opaque.status, 'pass');
  assert.equal(opaque.ratio, 21);
  const transparent = evaluateContrast({foreground: WHITE, background: [0, 0, 0, 0],
    backing: WHITE, backingProvenance: PROVENANCE});
  assert.equal(transparent.status, 'measured_failure');
  assert.equal(transparent.ratio, 1);
});

test('missing, translucent or unsourced backings remain unresolved', () => {
  const request = {foreground: WHITE, background: [0, 0, 0, 0.5]};
  for (const evidence of [{}, {backing: null}, {backing: BLACK},
    {backing: BLACK, backingProvenance: ''}, {backing: BLACK, backingProvenance: ' '},
    {backing: [0, 0, 0, 0.5], backingProvenance: PROVENANCE}]) {
    assertUnresolved(evaluateContrast({...request, ...evidence}), 'missing_background_evidence');
  }
  const checked = checkTransparentBridge(BRIDGE_CSS, V2_CSS);
  assert.equal(checked.results.length, 8);
  assert.equal(checked.failures.length, 8);
  assert.deepEqual(checked.rows, []);
  for (const result of checked.results) assertUnresolved(result, 'missing_background_evidence');
  assert.deepEqual(new Set(checked.results.map(result => result.theme)), new Set(['dark', 'light']));
});

test('malformed, unsupported, missing and cyclic colour expressions cannot resolve', () => {
  for (const value of [undefined, null, '', '#fff', '#gggggg', 'rgb(0 0 0)',
    'color-mix(in srgb, #000000 101%, transparent)',
    'color-mix(in srgb, #000000 -1%, transparent)',
    'color-mix(in srgb, #000000 50%, transparent', 'var(--missing)']) {
    assert.throws(() => resolveRgba(value));
  }
  assert.throws(() => resolveRgba('var(--a)', {a: 'var(--b)', b: 'var(--a)'}), /Cyclic/);
  for (const bridge of [BRIDGE_CSS.replace('var(--text)', 'var(--missing)'),
    BRIDGE_CSS.replace('var(--text)', 'rgb(0 0 0)'),
    BRIDGE_CSS.replace('--coast-panel-glass:', '--coast-absent:'),
    BRIDGE_CSS.replace('94%', '101%')]) {
    const result = checkTransparentBridge(bridge, V2_CSS, [REQUEST]);
    assert.equal(result.failures.length, 2);
    for (const row of result.results) assertUnresolved(row, 'resolution_error');
  }
  for (const result of [checkTransparentBridge('', V2_CSS, [REQUEST]),
    checkTransparentBridge(BRIDGE_CSS, '', [REQUEST]),
    checkTransparentBridge(BRIDGE_CSS, V2_CSS, []),
    checkTransparentBridge(BRIDGE_CSS, V2_CSS, [null])]) {
    assert.ok(result.failures.length > 0);
    assert.deepEqual(result.rows, []);
    for (const row of result.results) assertUnresolved(row, 'resolution_error');
  }
});

test('invalid RGBA channels become errors rather than passes or missing evidence', () => {
  for (const value of [undefined, null, {}, [0, 0, 0], [0, 0, 0, 1, 1], Array(4),
    [-1, 0, 0, 1], [256, 0, 0, 1], [NaN, 0, 0, 1], [Infinity, 0, 0, 1],
    ['0', 0, 0, 1], [0, 0, 0, -0.1], [0, 0, 0, 1.1]]) {
    assert.throws(() => sourceOver(value, BLACK));
    assert.throws(() => sourceOver(BLACK, value));
    assertUnresolved(evaluateContrast({foreground: value, background: BLACK}), 'resolution_error');
    assertUnresolved(evaluateContrast({foreground: WHITE, background: value}), 'resolution_error');
  }
  assertUnresolved(evaluateContrast(null), 'resolution_error');
  assertUnresolved(evaluateContrast(), 'resolution_error');
  assertUnresolved(evaluateContrast({foreground: WHITE, background: [0, 0, 0, 0.5],
    backing: [NaN, 0, 0, 1], backingProvenance: PROVENANCE}), 'resolution_error');
});

test('invalid ranges error; a valid continuous interval remains unresolved', () => {
  const request = {foreground: WHITE, background: [0, 0, 0, 0.27],
    backing: BLACK, backingProvenance: PROVENANCE};
  for (const alphaRange of [[], [0], [0, 0.27, 1], Array(2), [-1, 0.27],
    [0, 1.1], [0.5, 0.2], [0, NaN], [0, undefined], '0..0.27']) {
    assertUnresolved(evaluateContrast({...request, alphaRange}), 'resolution_error');
  }
  const unresolved = evaluateContrast({...request, alphaRange: [0, 0.27]});
  assertUnresolved(unresolved, 'missing_background_evidence');
  assert.match(unresolved.reason, /Continuous.*endpoints are insufficient/);
});

test('classification uses exact 4.5 and the immediately preceding float', () => {
  assert.deepEqual(classifyContrast(4.5), {status: 'pass', ratio: 4.5});
  const below = 4.5 - Number.EPSILON * 4;
  assert.ok(below < 4.5);
  assert.equal(below.toFixed(2), '4.50');
  assert.deepEqual(classifyContrast(below), {status: 'measured_failure', ratio: below});
  for (const value of [undefined, null, '4.5', NaN, Infinity, -Infinity, 0, 0.99, 21.01]) {
    assertUnresolved(classifyContrast(value), 'resolution_error');
  }
});

test('opaque checks retain both themes, full pair counts and failure sensitivity', () => {
  for (const [css, spec] of [[V2_CSS, FILES['web/tokens.css']]]) {
    const result = check(css, spec);
    assert.deepEqual(result.failures, []);
    assert.equal(result.rows.length, 2 * spec.pairs.length);
    assert.ok(result.rows.every(row => row.includes('21.00:1')));
  }
  const bridge = checkBridge(BRIDGE_CSS, V2_CSS);
  assert.deepEqual(bridge.failures, []);
  assert.equal(bridge.rows.length, 2 * PAIRS_BRIDGE.length);
  assert.match(check(V2_CSS.replace('--text: #ffffff;', '--text: #000000;'), FILES['web/tokens.css']).failures.join('\n'), /below 4.5/);
  assert.match(checkBridge(BRIDGE_CSS.replace('--coast-coral: var(--coral);', ''), V2_CSS).failures.join('\n'), /does not resolve/);
  const backed = checkTransparentBridge(BRIDGE_CSS, V2_CSS, [REQUEST]);
  assert.deepEqual(backed.failures, []);
  assert.equal(backed.results.length, 2);
  assert.ok(backed.results.every(result => result.status === 'pass' && result.ratio === 21));
});

test('default CLI fails closed on unresolved synthetic requests in this Node process', {concurrency: false}, async () => {
  // Match package.json engines; the synthetic loader uses only Node builtins.
  const [major, minor] = process.versions.node.split('.').map(Number);
  assert.ok(major > 22 || (major === 22 && minor >= 18), 'fixture requires Node >=22.18');
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'contrast-rgba-unit-')));
  const original = {argv: process.argv, exit: process.exit, log: console.log, error: console.error};
  const stdout = [], stderr = [], exitCodes = [], exitSignal = new Error('intercepted fixture exit');
  try {
    for (const dir of ['scripts', 'dist', 'web', 'packages/coast']) mkdirSync(join(root, dir), {recursive: true});
    const script = join(root, 'scripts/check_contrast.mjs');
    writeFileSync(script, readFileSync(new URL('../scripts/check_contrast.mjs', import.meta.url)));
    writeFileSync(join(root, 'web/tokens.css'), V2_CSS);
    writeFileSync(join(root, 'packages/coast/tokens-bridge.css'), BRIDGE_CSS);
    process.argv = [process.execPath, script];
    process.exit = code => { exitCodes.push(code); throw exitSignal; };
    console.log = (...args) => stdout.push(args.join(' '));
    console.error = (...args) => stderr.push(args.join(' '));
    await assert.rejects(import(pathToFileURL(script).href), error => error === exitSignal);
  } finally {
    process.argv = original.argv;
    process.exit = original.exit;
    console.log = original.log;
    console.error = original.error;
    rmSync(root, {recursive: true, force: true});
  }
  assert.deepEqual(exitCodes, [1]);
  assert.deepEqual(stdout, []);
  assert.equal(stderr.length, 1);
  assert.match(stderr[0], /^Transparent contrast check failed/);
  assert.equal((stderr[0].match(/missing_background_evidence/g) || []).length, 8);
  assert.doesNotMatch(stderr[0], /measured_failure|resolution_error/);
});

// These cases exercise the new source-bound production proof only.
import {checkCatchGradient} from '../scripts/check_contrast.mjs';
const catchSources = () => ['packages/coast/panel.css', 'packages/coast/tokens-bridge.css', 'web/tokens.css'].map(path => readFileSync(new URL('../' + path, import.meta.url), 'utf8'));
test('catch production: continuous light/dark proof and uncovered panel', () => {
  const owner = readFileSync(new URL('../packages/coast/src/ui/catches.ts', import.meta.url), 'utf8');
  assert.match(owner, /<dl class="catch-counts">[\s\S]*<div><span class="catch-bar"[\s\S]*<dt>[\s\S]*<dd>/);
  assert.match(owner, /Math\.max\(0,Math\.min\(100,p\.count\/maximum\*100\)\)\.toFixed\(1\)/);
  const result = checkCatchGradient(...catchSources());
  assert.deepEqual(result.failures, []);
  assert.deepEqual(result.results.map(r => r.theme), ['dark', 'light']);
  assert.ok(result.results.every(r => r.minimum >= 4.5 && r.uncoveredPanel >= 4.5));
  assert.equal(result.rendered, false);
  assert.ok(Object.values(result.hashes).every(h => /^[a-f0-9]{64}$/.test(h)));
  console.log('catch source proof ' + JSON.stringify(result));
});
test('catch production: rejects translucent endpoint and changed interpolation/selector', () => {
  const [panel, bridge, tokens] = catchSources();
  for (const changed of [
    // FE-61 part 3: panel.css reads the bridged roles without v1 literal fallbacks.
    panel.replace('90deg in srgb, var(--coast-mint-wash), var(--coast-panel)', '90deg in srgb, var(--coast-mint-wash), var(--coast-mint-glow)'),
    panel.replace('90deg in srgb, var(--coast-mint-wash', '90deg in oklab, var(--coast-mint-wash'),
    panel.replace('.catch-counts dd {', '.unrelated dd {'),
    panel + '\n.catch-counts dd {color: red;}',
  ]) {
    assert.notEqual(changed, panel, 'each mutation must actually change the sheet');
    assert.equal(checkCatchGradient(changed, bridge, tokens).failures[0].status, 'resolution_error');
  }
});
test('catch production: actual role mutations fail at equality and missing binding', () => {
  const [panel, bridge, tokens] = catchSources();
  const equal = checkCatchGradient(panel, bridge.replace('--coast-mint: var(--mint);', '--coast-mint: var(--panel);').replace('--coast-mint-wash: color-mix(in srgb, var(--mint) 14%, var(--panel));', '--coast-mint-wash: var(--panel);'), tokens);
  assert.equal(equal.failures.length, 2);
  assert.ok(equal.results.every(r => r.status === 'source_failure' && r.minimum === 1));
  const missing = checkCatchGradient(panel, bridge.replace('--coast-panel: var(--panel);', ''), tokens);
  assert.equal(missing.failures[0].status, 'resolution_error');
});
