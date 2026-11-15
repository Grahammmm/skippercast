// MGL-15: the habitat class CVD pair gate (scripts/check_contrast.mjs) and the map-only colour roles it protects.
// Offline: pure vectors, the repository's own tokens/renderer, and CLI runs against temporary copies outside the repository.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {
  CVD_SIMULATIONS, HABITAT_CLASSES, HABITAT_MIN_DELTA_E, MACHADO_SEVERITY_1, blendHexOver, check, checkHabitatCvd, cvdDeltaE, deltaE2000, evaluateZoomRamp,
  habitatCvdReport, habitatFillAlpha, linearRgbToLab, linearToSrgb, rawThemes, simulateCvd, srgbToLinear, themes,
} from '../scripts/check_contrast.mjs';
import {PALETTE_TOKENS, coastPalette, readPalette} from '../web/map/palette.ts';
import {GLYPH_VERSION, basemapStyle, mapControl} from '../web/map/style.ts';
import {GEOLOGY_PICK, SURVEY_PICK, markStyle} from '../web/map/marks.ts';
import {contoursOverlay, DEPTH_HIT, DEPTH_LABEL, DEPTH_LINE, DEPTH_EDGE} from '../web/map/depth-contours.ts';
import {windOverlay} from '../web/map/wind.ts';
import {stationOverlay} from '../web/map/stations.ts';
import {rankedStyle} from '../web/map/ranked.ts';
import {coastlineLayers} from '../web/map/coastline.ts';
import {mpaLayers} from '../web/map/mpa.ts';
import {seafloorLayers} from '../web/map/seafloor.ts';
import {LAYERS, layerCopy} from '../web/map/layers.ts';

const ROOT = new URL('../', import.meta.url);
const read = path => readFileSync(new URL(path, ROOT), 'utf8');
const TOKENS = read('web/tokens.css');
const RAW = rawThemes(TOKENS);
const ALPHA_Z13 = 0.24666666666666667;
const near = (actual, expected, tolerance, message) => assert.ok(Math.abs(actual - expected) <= tolerance, `${message}: ${actual} is not within ${tolerance} of ${expected}`);
const lab = hex => linearRgbToLab([1, 3, 5].map(i => srgbToLinear(parseInt(hex.slice(i, i + 2), 16) / 255)));
const paletteOf = (theme, extra = {}) => readPalette(name => ({...RAW[theme], ...extra})[name] ?? '');

// The colours the four classes had before MGL-15 (--depth-1, --muted, --amber, --mint in each theme).
const OLD_CLASSES = {
  dark: {'hab-rock': '#2b9c9c', 'hab-mixed': '#8ba5b7', 'hab-soft': '#eabd76', 'hab-kelp': '#69e0bc'},
  light: {'hab-rock': '#2b9c9c', 'hab-mixed': '#4a6373', 'hab-soft': '#8a5a00', 'hab-kelp': '#087354'},
};
/** tokens.css with some custom properties of one theme's rule replaced (a declaration is added when absent). */
function withTokens(css, theme, overrides) {
  const marker = ':root[data-theme="light"] {', at = css.indexOf(marker);
  let [dark, light] = [css.slice(0, at), css.slice(at)];
  const region = theme === 'dark' ? dark : light;
  let next = region;
  for (const [name, value] of Object.entries(overrides)) {
    const re = new RegExp(`--${name}:[^;]*;`);
    next = re.test(next) ? next.replace(re, `--${name}: ${value};`) : next.replace('{', `{\n  --${name}: ${value};`);
  }
  return theme === 'dark' ? next + light : dark + next;
}
const oldPaletteCss = () => withTokens(withTokens(TOKENS, 'dark', OLD_CLASSES.dark), 'light', OLD_CLASSES.light);
const alphas = {dark: ALPHA_Z13, light: ALPHA_Z13};

// ── independent math vectors ────────────────────────────────────────────────────────────────────────────────────

test('independent_math_vectors: CIEDE2000 matches the published Sharma, Wu and Dalal (2005) test pairs to their 4 printed decimals', () => {
  // Table 1 of "The CIEDE2000 Color-Difference Formula: Implementation Notes, Supplementary Test Data, and Mathematical Observations".
  const published = [
    [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425], [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
    [[50, 2.8361, -74.02], [50, 0, -82.7485], 3.4412], [[50, -1.3802, -84.2814], [50, 0, -82.7485], 1.0],
    [[50, -1.1848, -84.8006], [50, 0, -82.7485], 1.0], [[50, -0.9009, -85.5211], [50, 0, -82.7485], 1.0],
    [[50, 0, 0], [50, -1, 2], 2.3669], [[50, 2.5, 0], [50, 0, -2.5], 4.3065],
    [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644], [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
  ];
  for (const [a, b, expected] of published) {
    near(deltaE2000(a, b), expected, 5e-5, `dE00 ${a} vs ${b}`);
    near(deltaE2000(b, a), expected, 5e-5, 'symmetric');
    assert.equal(deltaE2000(a, a), 0);
  }
  assert.equal(deltaE2000([50, 0, 0], [50, 0, 0]), 0);
});

test('independent_math_vectors: Lab of white, black and the sRGB primaries (published D65 values)', () => {
  near(lab('#ffffff')[0], 100, 1e-4, 'white L'); near(lab('#ffffff')[1], 0, 1e-3, 'white a'); near(lab('#ffffff')[2], 0, 1e-3, 'white b');
  assert.deepEqual(linearRgbToLab([0, 0, 0]), [0, 0, 0]);
  for (const [hex, [L, a, b]] of Object.entries({'#ff0000': [53.2408, 80.0925, 67.2032], '#00ff00': [87.7347, -86.1827, 83.1793], '#0000ff': [32.297, 79.1875, -107.8602]})) {
    const got = lab(hex);
    near(got[0], L, 5e-3, `${hex} L`); near(got[1], a, 5e-3, `${hex} a`); near(got[2], b, 5e-3, `${hex} b`);
  }
  const grey = lab('#777777');
  near(grey[1], 0, 1e-3, 'neutral grey a'); near(grey[2], 0, 1e-3, 'neutral grey b');
});

test('independent_math_vectors: sRGB transfer boundary, round trip and gamut clipping', () => {
  near(srgbToLinear(0.04045), 0.04045 / 12.92, 1e-15, 'linear segment ends at 0.04045');
  near(srgbToLinear(0.04045 + 1e-9), 0.0031308, 1e-6, 'power segment continues it');
  near(linearToSrgb(0.0031308), 0.04045, 1e-6, 'inverse at the boundary');
  assert.equal(srgbToLinear(0), 0); assert.equal(srgbToLinear(1), 1);
  near(srgbToLinear(0.5), 0.2140411, 1e-6, 'mid grey');
  for (const v of [0, 0.01, 0.2, 0.5, 0.99, 1]) near(linearToSrgb(srgbToLinear(v)), v, 1e-12, 'round trip');
  for (const bad of [-0.001, 1.001, NaN, Infinity]) { assert.throws(() => srgbToLinear(bad), /\[0,1\]/); assert.throws(() => linearToSrgb(bad), /\[0,1\]/); }
  // Out-of-gamut simulation results clamp back into [0,1] rather than leaving it.
  assert.deepEqual(simulateCvd([0, 0, 1], 'protanopia'), [0, 0.099216, 1]);
  assert.deepEqual(simulateCvd([0, 0, 1], 'deuteranopia'), [0, 0.047413, 0.968881]);
  assert.ok(Math.max(...simulateCvd([1, 1, 0], 'tritanopia')) <= 1);
});

test('independent_math_vectors: the Machado 2009 severity-1.0 matrices are pinned', () => {
  // Published entries; each row of a CVD matrix sums to 1 so neutral greys stay neutral.
  assert.deepEqual(MACHADO_SEVERITY_1.protanopia[0], [0.152286, 1.052583, -0.204868]);
  assert.deepEqual(MACHADO_SEVERITY_1.deuteranopia[1], [0.280085, 0.672501, 0.047413]);
  assert.deepEqual(MACHADO_SEVERITY_1.tritanopia[2], [0.004733, 0.691367, 0.3039]);
  for (const name of ['protanopia', 'deuteranopia', 'tritanopia']) {
    for (const row of MACHADO_SEVERITY_1[name]) near(row.reduce((a, b) => a + b, 0), 1, 2e-6, `${name} row sum`);
    const white = simulateCvd([1, 1, 1], name);
    white.forEach(v => near(v, 1, 2e-6, `${name} keeps white`));
  }
  assert.deepEqual(simulateCvd([0.3, 0.6, 0.9], 'normal'), [0.3, 0.6, 0.9]);
  // Protan red keeps only what the first column leaves: (0.152286, 0.114503, -0.003882 clamped to 0).
  assert.deepEqual(simulateCvd([1, 0, 0], 'protanopia'), [0.152286, 0.114503, 0]);
  assert.deepEqual(CVD_SIMULATIONS, ['normal', 'protanopia', 'deuteranopia', 'tritanopia']);
  assert.throws(() => simulateCvd([0.1, 0.2, 0.3], 'achromatopsia'), /Unknown colour-vision simulation/);
  assert.throws(() => simulateCvd([0.1, 0.2, 0.3], '__proto__'), /Unknown colour-vision simulation/);
  assert.throws(() => simulateCvd([0.1, 0.2], 'normal'), /RGB triple/);
});

// ── the gate on the final tokens ─────────────────────────────────────────────────────────────────────────────────

test('all_pairs_all_simulations_both_themes: every unordered pair, every simulation, solid and fill, in both themes', () => {
  const report = checkHabitatCvd(TOKENS, alphas);
  assert.deepEqual(report.failures, []);
  assert.equal(HABITAT_CLASSES.length, 4);
  assert.equal(report.results.length, 2 * 4 * 6 * 2);
  const keys = new Set(report.results.map(r => `${r.theme} ${r.simulation} ${r.pair} ${r.kind}`));
  assert.equal(keys.size, 96, 'no row is reported twice or skipped');
  for (const theme of ['dark', 'light']) for (const simulation of CVD_SIMULATIONS) {
    for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++) for (const kind of ['solid', 'fill']) {
      assert.ok(keys.has(`${theme} ${simulation} ${HABITAT_CLASSES[i]}/${HABITAT_CLASSES[j]} ${kind}`), `${theme} ${simulation} ${i}/${j} ${kind}`);
    }
  }
  for (const r of report.results) {
    assert.equal(r.threshold, HABITAT_MIN_DELTA_E[r.kind]);
    assert.equal(r.alpha, r.kind === 'solid' ? 1 : ALPHA_Z13);
    assert.ok(r.deltaE >= r.threshold, `${r.theme} ${r.simulation} ${r.pair} ${r.kind}: ${r.deltaE}`);
  }
  assert.deepEqual(HABITAT_MIN_DELTA_E, {solid: 12, fill: 6});
  assert.equal(report.lines.length, 96);
  // Display rounds to 3 places; the stored value and the comparison are the unrounded number.
  const row = report.results[0];
  assert.notEqual(row.deltaE, Number(row.deltaE.toFixed(3)));
  assert.ok(report.lines[0].includes(String(row.deltaE)), 'the unrounded value is printed');
});

test('all_pairs_all_simulations_both_themes: a failing palette reports every failing row, not only the worst', () => {
  const same = withTokens(TOKENS, 'dark', {'hab-mixed': '#2d9a9a'});
  const report = checkHabitatCvd(same, alphas);
  const rows = report.results.filter(r => r.theme === 'dark' && r.pair === 'rock/mixed');
  assert.equal(rows.length, 8);
  assert.ok(rows.every(r => r.deltaE === 0 && r.status === 'measured_failure'), 'identical classes give zero and fail in every simulation, solid and fill');
  assert.ok(report.failures.length >= 8);
  assert.equal(report.results.filter(r => r.theme === 'light' && r.status !== 'pass').length, 0, 'the other theme is judged on its own tokens');
});

test('old_hard_mixed_regression: the pre-MGL-15 dark palette fails the gate where the ~1.9 dE was measured', () => {
  const report = checkHabitatCvd(oldPaletteCss(), alphas);
  const row = (simulation, kind) => report.results.find(r => r.theme === 'dark' && r.pair === 'rock/mixed' && r.simulation === simulation && r.kind === kind);
  assert.ok(row('protanopia', 'solid').deltaE < 12, 'hard/mixed outline under protanopia');
  near(row('protanopia', 'solid').deltaE, 6.9862, 5e-3, 'measured protan outline');
  assert.ok(row('deuteranopia', 'fill').deltaE < 6, 'hard/mixed blended fill under deuteranopia');
  near(row('deuteranopia', 'fill').deltaE, 1.8776, 1e-3, 'measured deutan fill (~1.9)');
  assert.ok(report.failures.length > 0, 'the old palette is never reported as passing');
  assert.ok(report.failures.some(f => f.startsWith('dark deuteranopia rock/mixed fill')));
  // A control that matters: at the rounded 0.25 the number would be different, so the fill alpha really is the one passed in.
  const rounded = checkHabitatCvd(oldPaletteCss(), {dark: 0.25, light: 0.25}).results.find(r => r.theme === 'dark' && r.pair === 'rock/mixed' && r.simulation === 'deuteranopia' && r.kind === 'fill');
  assert.notEqual(rounded.deltaE, row('deuteranopia', 'fill').deltaE);
  assert.equal(cvdDeltaE([0.2, 0.4, 0.6], [0.2, 0.4, 0.6], 'deuteranopia'), 0);
});

// ── the alpha is the renderer's ─────────────────────────────────────────────────────────────────────────────────

test('renderer_alpha_not_rounded: the checker reads the real survey fill at zoom 13 and distinguishes 0.25', () => {
  for (const theme of ['dark', 'light']) {
    const layer = markStyle(paletteOf(theme)).habitat.find(l => l.id === SURVEY_PICK);
    const alpha = evaluateZoomRamp(layer.paint['fill-opacity'], 13);
    near(alpha, ALPHA_Z13, 1e-15, 'renderer alpha at z13');
    assert.notEqual(alpha, 0.25);
    assert.equal(habitatFillAlpha(markStyle, readPalette, RAW[theme], SURVEY_PICK), alpha);
  }
  const report = checkHabitatCvd(TOKENS, alphas), fill = report.results.find(r => r.kind === 'fill');
  assert.equal(fill.alpha, ALPHA_Z13);
});

test('renderer_alpha_not_rounded: a changed renderer control moves the gate; a huge multiplier caps at the renderer\'s 0.6', async () => {
  const only = (theme, value) => withTokens(withTokens(TOKENS, 'dark', {'map-habitat-opacity': theme === 'dark' ? value : '1'}), 'light', {'map-habitat-opacity': theme === 'light' ? value : '1'});
  const doubled = only('dark', '2');
  const report = await habitatCvdReport(doubled);
  const dark = report.results.find(r => r.theme === 'dark' && r.kind === 'fill'), light = report.results.find(r => r.theme === 'light' && r.kind === 'fill');
  near(dark.alpha, 2 * ALPHA_Z13, 1e-12, 'dark follows the doubled control');
  assert.equal(light.alpha, ALPHA_Z13, 'light keeps its own');
  const huge = await habitatCvdReport(only('dark', '1000'));
  assert.equal(huge.results.find(r => r.theme === 'dark' && r.kind === 'fill').alpha, 0.6);
  const normal = await habitatCvdReport(TOKENS);
  assert.deepEqual(normal.failures, []);
  assert.equal(normal.results.length, 96);
  assert.equal(normal.results.find(r => r.kind === 'fill').alpha, ALPHA_Z13);
  // A malformed multiplier stops the gate instead of passing it.
  for (const bad of ['', 'NaN', '-1', '0', '1e3', 'abc']) {
    const refused = await habitatCvdReport(withTokens(TOKENS, 'dark', {'map-habitat-opacity': bad}));
    assert.ok(refused.failures.length > 0 && refused.rows.length === 0, `--map-habitat-opacity ${JSON.stringify(bad)} is refused`);
  }
});

test('renderer_alpha_not_rounded: the zoom ramp evaluator refuses what it cannot evaluate', () => {
  const ramp = ['interpolate', ['linear'], ['zoom'], 9, 0.12, 12, 0.22, 15, 0.3];
  assert.equal(evaluateZoomRamp(ramp, 9), 0.12); assert.equal(evaluateZoomRamp(ramp, 12), 0.22); assert.equal(evaluateZoomRamp(ramp, 20), 0.3); assert.equal(evaluateZoomRamp(ramp, 0), 0.12);
  near(evaluateZoomRamp(ramp, 10.5), 0.17, 1e-15, 'between stops');
  for (const bad of [0.3, ['interpolate', ['exponential', 2], ['zoom'], 9, 1, 12, 2], ['interpolate', ['linear'], ['get', 'x'], 9, 1, 12, 2], ['interpolate', ['linear'], ['zoom'], 9, 1],
    ['interpolate', ['linear'], ['zoom'], 12, 1, 9, 2], ['interpolate', ['linear'], ['zoom'], 9, 'a', 12, 2], ['interpolate', ['linear'], ['zoom'], 9, 1, 12, 2, 15]]) {
    assert.throws(() => evaluateZoomRamp(bad, 13), /Unsupported zoom ramp/, JSON.stringify(bad));
  }
  assert.throws(() => evaluateZoomRamp(ramp, NaN), /Unsupported/);
});

// ── malformed input is never a pass ──────────────────────────────────────────────────────────────────────────────

test('malformed_input_is_not_pass: absent, invalid or non-hex class and water tokens refuse deterministically', () => {
  const before = TOKENS.slice();
  for (const [theme, name, value] of [['dark', 'hab-kelp', 'rgb(1 2 3)'], ['dark', 'hab-rock', '#abc'], ['light', 'map-water', 'var(--bg)'], ['light', 'hab-soft', '#12345g']]) {
    const report = checkHabitatCvd(withTokens(TOKENS, theme, {[name]: value}), alphas);
    assert.ok(report.failures.some(f => f.startsWith(`${theme} `) && f.includes(`--${name}`)), `${theme} --${name} ${value}: ${report.failures.join('|')}`);
    assert.equal(report.results.filter(r => r.theme === theme && r.status === 'pass').length, 0, 'the broken theme reports no pass row');
    assert.deepEqual(checkHabitatCvd(withTokens(TOKENS, theme, {[name]: value}), alphas).failures, report.failures, 'deterministic');
  }
  const absent = TOKENS.replace(/--hab-mixed: #a199ff;\n/, '');
  assert.notEqual(absent, TOKENS);
  const missing = checkHabitatCvd(absent, alphas);
  assert.ok(missing.failures.some(f => f.startsWith('dark ') && f.includes('--hab-mixed')));
  assert.ok(checkHabitatCvd('not a stylesheet', alphas).failures.length > 0);
  assert.ok(checkHabitatCvd('', alphas).failures.length > 0);
  assert.equal(TOKENS, before, 'no input is mutated');
});

test('malformed_input_is_not_pass: an invalid fill alpha refuses; so do blends of bad colours', () => {
  for (const alpha of [NaN, Infinity, -Infinity, 0, -0.1, 1.0001, '0.25', null, undefined]) {
    const report = checkHabitatCvd(TOKENS, {dark: alpha, light: ALPHA_Z13});
    assert.ok(report.failures.some(f => f.startsWith('dark ') && f.includes('fill alpha')), `alpha ${String(alpha)}`);
    assert.equal(report.results.filter(r => r.theme === 'dark' && r.status === 'pass').length, 0);
  }
  assert.ok(checkHabitatCvd(TOKENS, undefined).failures.length > 0);
  assert.ok(checkHabitatCvd(TOKENS, Number.NaN).failures.length > 0);
  for (const alpha of [NaN, 0, 1.5, Infinity]) assert.throws(() => blendHexOver('#112233', '#445566', alpha), /fill alpha/);
  assert.throws(() => blendHexOver('#12', '#445566', 0.5), /#rrggbb/);
  assert.throws(() => deltaE2000([1, 2], [1, 2, 3]), /Lab/);
  assert.throws(() => deltaE2000([1, 2, NaN], [1, 2, 3]), /Lab/);
  assert.deepEqual(blendHexOver('#ffffff', '#000000', 1), [1, 1, 1]);
  assert.deepEqual(blendHexOver('#ffffff', '#000000', 0.5), [0.5, 0.5, 0.5]);
});

// ── command line, on copies outside the repository ───────────────────────────────────────────────────────────────

const cli = (...args) => spawnSync(process.execPath, [new URL('scripts/check_contrast.mjs', ROOT).pathname, ...args], {encoding: 'utf8', cwd: tmpdir()});
const sha = text => createHash('sha256').update(text).digest('hex');

test('checker_compatibility: --habitat-cvd passes on the final tokens and fails on old or corrupt copies', () => {
  const dir = mkdtempSync(join(tmpdir(), 'mgl15-'));
  try {
    const repoBefore = sha(TOKENS);
    const put = (name, text) => { const file = join(dir, name); writeFileSync(file, text); return file; };
    const good = cli('--habitat-cvd');
    assert.equal(good.status, 0, good.stderr);
    assert.match(good.stdout, /Habitat CVD check passed: 96 rows/);
    assert.equal(good.stdout.split('\n').filter(l => l.startsWith('PASS ')).length, 96);
    assert.match(good.stdout, /PASS dark protanopia rock\/mixed solid alpha 1: dE2000 [\d.]+ \([\d.]+\) >= 12/);
    assert.match(good.stdout, /PASS light deuteranopia soft\/kelp fill alpha 0\.24666666666666667: dE2000 [\d.]+ \([\d.]+\) >= 6/);
    const copy = cli('--habitat-cvd', put('final.css', TOKENS));
    assert.equal(copy.status, 0, copy.stderr);
    const old = cli('--habitat-cvd', put('old.css', oldPaletteCss()));
    assert.equal(old.status, 1);
    assert.match(old.stdout, /FAIL dark deuteranopia rock\/mixed fill alpha 0\.24666666666666667: measured_failure dE2000 1\.878 \(1\.877/);
    assert.match(old.stderr, /Habitat CVD check failed: \d+ of 96 rows/);
    const corrupt = cli('--habitat-cvd', put('corrupt.css', withTokens(TOKENS, 'light', {'hab-kelp': 'green'})));
    assert.equal(corrupt.status, 1);
    assert.match(corrupt.stdout, /FAIL light .*--hab-kelp is not a hex colour token/);
    const noNumbers = cli('--habitat-cvd', put('nonumbers.css', withTokens(TOKENS, 'dark', {'map-habitat-opacity': 'nope'})));
    assert.equal(noNumbers.status, 1);
    assert.match(noNumbers.stdout, /FAIL habitat CVD gate could not run: .*map-habitat-opacity/);
    const absent = cli('--habitat-cvd', join(dir, 'missing.css'));
    assert.equal(absent.status, 1);
    assert.match(absent.stderr, /could not read its tokens/);
    assert.equal(sha(read('web/tokens.css')), repoBefore, 'the mode is read-only');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});

test('checker_compatibility: the default run still refuses the same transparent evidence and adds no habitat failure', () => {
  const run = cli();
  assert.equal(run.status, 1, 'the baseline missing_background_evidence refusals are unchanged');
  const transparent = run.stderr.split('\n').filter(l => l.includes('missing_background_evidence'));
  assert.equal(transparent.length, 8);
  assert.doesNotMatch(run.stderr, /Habitat CVD check failed/);
  const dir = mkdtempSync(join(tmpdir(), 'mgl15-'));
  try {
    assert.ok(check(TOKENS).failures.length === 0, 'the map text pairs and every legacy pair clear 4.5:1 in both themes');
    const pairs = check(TOKENS).rows.filter(r => r.includes('--map-ink on --map-ink-halo') || r.includes('--map-label on --map-halo'));
    assert.equal(pairs.length, 4);
    const broken = check(withTokens(TOKENS, 'dark', {'map-ink': '#07131e'}));
    assert.ok(broken.failures.some(f => f.includes('--map-ink')), 'a map ink that vanishes into its halo fails the existing 4.5:1 rule');
  } finally { rmSync(dir, {recursive: true, force: true}); }
  const t = themes(TOKENS);
  assert.equal(t.dark['map-water'], '#07131d');
  assert.equal(t.light['hab-kelp'], '#207053');
});

// ── role split ───────────────────────────────────────────────────────────────────────────────────────────────────

const NUMERIC = /^map-.*-(?:opacity|width)$/;
const MAP_ROLE = /^(?:map|hab|mark)-/;
/** Map-only tokens read `map(--x)`, every chrome token `chrome(--x)`, and the numeric controls their neutral 1. */
const roleSentinel = (extra = {}) => readPalette(name => extra[name] ?? (NUMERIC.test(name) ? '1' : `${MAP_ROLE.test(name) ? 'map' : 'chrome'}(--${name})`));
const walk = layers => layers.flatMap(layer => Object.entries({...layer.paint, ...layer.layout}).filter(([k]) => k.endsWith('-color')).map(([k, v]) => [layer.id, k, v]));
const colourOf = (layers, id, property) => layers.find(l => l.id === id).paint[property];

test('roles_not_chrome: the new keys exist, read their own tokens, and a missing one fails loudly', () => {
  const expected = {mapWater: 'map-water', mapLand: 'map-land', mapPark: 'map-park', mapRoad: 'map-road', mapRoadMinor: 'map-road-minor', mapBoundary: 'map-boundary',
    mapLabel: 'map-label', mapHalo: 'map-halo', mapInk: 'map-ink', mapInkHalo: 'map-ink-halo', mapCoast: 'map-coast', mapContour: 'map-contour',
    habRock: 'hab-rock', habMixed: 'hab-mixed', habSoft: 'hab-soft', habKelp: 'hab-kelp', markRing: 'mark-ring',
    mapLabelOpacity: 'map-label-opacity', mapRoadOpacity: 'map-road-opacity', mapHabitatOpacity: 'map-habitat-opacity', mapContourWidth: 'map-contour-width'};
  for (const [key, token] of Object.entries(expected)) assert.equal(PALETTE_TOKENS[key], token, key);
  for (const token of Object.values(expected)) {
    assert.throws(() => readPalette(name => (name === token ? '' : '1')), new RegExp(`missing --${token}`), token);
    assert.ok(RAW.dark[token] !== undefined && RAW.light[token] !== undefined, `${token} resolves in both themes`);
  }
});

test('roles_not_chrome: the day basemap, overlays and legend swatches draw from map roles; night keeps the landing roles', () => {
  const p = roleSentinel(), OPTIONS = {archive: 'https://example.test/a.pmtiles', assets: 'https://example.test/b/'};
  const day = basemapStyle(p, {...OPTIONS, variant: 'day'}), night = basemapStyle(p, {...OPTIONS, variant: 'night'});
  const dayColours = day.layers.flatMap(l => walk([l]).map(c => c[2])), nightColours = night.layers.flatMap(l => walk([l]).map(c => c[2]));
  assert.ok(dayColours.length >= 8 && dayColours.every(v => v.startsWith('map(')), `day basemap colours: ${[...new Set(dayColours)]}`);
  assert.ok(nightColours.length >= 6 && nightColours.every(v => v.startsWith('chrome(')), `night keeps the chrome roles: ${[...new Set(nightColours)]}`);
  const marks = markStyle(p), habitat = marks.habitat.flatMap(l => walk([l]).map(c => c[2]));
  for (const expression of habitat) assert.ok(JSON.stringify(expression).match(/(?:map|chrome)\(--[a-z-]+\)/g).every(m => m.startsWith('map(--hab-')), JSON.stringify(expression));
  assert.deepEqual(colourOf(marks.habitat, SURVEY_PICK, 'fill-color'), ['match', ['get', 'kind'], 'rock', 'map(--hab-rock)', 'mixed', 'map(--hab-mixed)', 'sediment', 'map(--hab-soft)', 'kelp', 'map(--hab-kelp)', 'map(--hab-mixed)'], 'unknown falls to mixed');
  assert.equal(colourOf(marks.habitat, GEOLOGY_PICK, 'fill-color'), colourOf(marks.habitat, SURVEY_PICK, 'fill-color'));
  const m = Object.fromEntries(marks.marks.map(l => [l.id, l.paint]));
  assert.equal(m['marks-ring']['circle-stroke-color'], 'map(--mark-ring)');
  assert.equal(m['marks-ring']['circle-color'], 'map(--map-ink-halo)');
  assert.equal(m['marks-fit']['text-color'], 'map(--map-ink)');
  assert.equal(m['marks-depth']['text-color'], 'map(--map-ink)'); assert.equal(m['marks-depth']['text-halo-color'], 'map(--map-ink-halo)');
  assert.equal(m['selection-ring']['circle-stroke-color'], 'map(--map-ink)');
  const contours = contoursOverlay(p, {type: 'FeatureCollection', features: []}).layers;
  assert.equal(colourOf(contours, DEPTH_LINE, 'line-color'), 'map(--map-contour)');
  assert.equal(colourOf(contours, DEPTH_HIT, 'line-color'), 'map(--map-contour)');
  assert.equal(colourOf(contours, DEPTH_EDGE, 'line-color'), 'map(--map-label)');
  assert.equal(colourOf(contours, DEPTH_LABEL, 'text-color'), 'map(--map-contour)'); assert.equal(colourOf(contours, DEPTH_LABEL, 'text-halo-color'), 'map(--map-ink-halo)');
  const wind = Object.fromEntries(windOverlay(p).layers.map(l => [l.id, l.paint]));
  assert.equal(wind['wind-casing']['line-color'], 'map(--map-ink-halo)');
  assert.ok(Object.values(wind).filter(v => v['line-color'] === 'map(--map-ink)' || v['text-color'] === 'map(--map-ink)').length === 2);
  const dots = stationOverlay(p).layers.find(l => l.id.endsWith('dots')).paint;
  assert.equal(dots['circle-stroke-color'], 'map(--map-ink-halo)'); assert.equal(dots['circle-color'][2], 'map(--map-label)');
  const ranked = rankedStyle(p).layers.map(l => l.paint);
  assert.ok(ranked.some(v => v['circle-stroke-color'] === 'map(--map-ink-halo)') && ranked.some(v => v['text-color'] === 'map(--map-ink)' && v['text-halo-color'] === 'map(--map-ink-halo)'));
  assert.equal(coastlineLayers(p).at(-1).paint['line-color'], 'map(--map-coast)');
  assert.equal(mpaLayers(p).at(-1).paint['text-halo-color'], 'map(--map-ink-halo)');
  const tones = seafloorLayers(p).flatMap(l => walk([l]).map(c => c[2])).filter(Array.isArray);
  assert.ok(tones.length > 0 && tones.every(expression => expression.at(-1) === 'map(--map-label)'), 'unknown seafloor tone');
});

test('roles_not_chrome: changing a map role leaves chrome and the general coast roles alone, and the reverse', () => {
  const base = readPalette(name => RAW.dark[name] ?? ''), OPTIONS = {archive: 'https://example.test/a.pmtiles', assets: 'https://example.test/b/'};
  const withMap = readPalette(name => ({'map-ink': '#ff00ff', 'map-water': '#00ff00', 'hab-rock': '#123456'})[name] ?? RAW.dark[name] ?? '');
  const withChrome = readPalette(name => ({text: '#ff00ff', bg: '#00ff00', muted: '#123456', mint: '#654321', amber: '#abcdef', 'depth-1': '#fedcba'})[name] ?? RAW.dark[name] ?? '');
  const coast = coastPalette(base), coastMap = coastPalette(withMap), coastChrome = coastPalette(withChrome);
  for (const key of Object.keys(coast)) {
    if (key === 'water') assert.notEqual(coastMap.water, coast.water, 'the coast embed follows the day map water');
    else assert.equal(coastMap[key], coast[key], `${key} does not move with map ink/water`);
  }
  assert.equal(coastChrome.water, coast.water); assert.equal(coastChrome.land, coast.land); assert.equal(coastChrome.label, coast.label);
  const jsonOf = (palette, variant) => JSON.stringify(basemapStyle(palette, {...OPTIONS, variant}));
  assert.equal(jsonOf(withChrome, 'day'), jsonOf(base, 'day'), 'chrome tokens no longer reach the day basemap');
  assert.notEqual(jsonOf(withMap, 'day'), jsonOf(base, 'day'));
  assert.equal(jsonOf(withMap, 'night'), jsonOf(base, 'night'), 'map roles never reach the landing night map');
  assert.notEqual(jsonOf(withChrome, 'night'), jsonOf(base, 'night'));
  assert.equal(JSON.stringify(windOverlay(withChrome)), JSON.stringify(windOverlay(base)));
  assert.notEqual(JSON.stringify(windOverlay(withMap)), JSON.stringify(windOverlay(base)));
  assert.equal(JSON.stringify(markStyle(withChrome).habitat), JSON.stringify(markStyle(base).habitat), 'habitat classes ignore chrome tokens');
  assert.notEqual(JSON.stringify(markStyle(withMap).habitat), JSON.stringify(markStyle(base).habitat));
});

test('legend_and_language_parity: each migrated swatch is the palette key its layer paints, in English and Spanish', () => {
  const p = roleSentinel(), keyOf = (id, lang, i) => layerCopy(id, lang).legend[i].swatch;
  const marks = markStyle(p), contours = contoursOverlay(p, {type: 'FeatureCollection', features: []}).layers;
  const kind = colourOf(marks.habitat, SURVEY_PICK, 'fill-color');
  for (const lang of ['en', 'es']) {
    const habitat = ['habRock', 'habMixed', 'habSoft', 'habKelp'];
    habitat.forEach((key, i) => { assert.equal(keyOf('habitat', lang, i), key, `${lang} habitat row ${i}`); assert.equal(kind[3 + 2 * i], p[key]); });
    assert.equal(keyOf('wind', lang, 0), 'mapInk'); assert.equal(p.mapInk, windOverlay(p).layers[1].paint['line-color']);
    assert.equal(keyOf('depth-contours', lang, 0), 'mapContour'); assert.equal(p.mapContour, colourOf(contours, DEPTH_LINE, 'line-color'));
    assert.equal(keyOf('depth-contours', lang, 1), 'mapLabel'); assert.equal(p.mapLabel, colourOf(contours, DEPTH_EDGE, 'line-color'));
    assert.equal(keyOf('marks', lang, 0), 'markRing'); assert.equal(p.markRing, marks.marks.find(l => l.id === 'marks-ring').paint['circle-stroke-color']);
    assert.equal(keyOf('marks', lang, 1), 'depth1', 'the density ramp swatch is unchanged');
    assert.equal(keyOf('stations', lang, 2), 'mapLabel');
    assert.equal(p[keyOf('stations', lang, 2)], stationOverlay(p).layers.find(l => l.id.endsWith('dots')).paint['circle-color'][2], 'the stale dot is drawn in the swatch colour');
    assert.equal(keyOf('stations', lang, 0), 'blue'); assert.equal(keyOf('stations', lang, 1), 'mint');
    assert.equal(keyOf('seafloor', lang, 0), 'depth0'); assert.equal(keyOf('shore-runs', lang, 0), 'amber');
    for (const id of ['habitat', 'wind', 'depth-contours', 'marks', 'stations']) {
      layerCopy(id, lang).legend.forEach((row, i) => assert.equal(row.label, layerCopy(id, lang).legend[i].label) && assert.ok(row.label.length > 0));
    }
  }
  const en = LAYERS.find(l => l.id === 'habitat').legend, es = layerCopy('habitat', 'es').legend;
  assert.ok(en.every((row, i) => row.swatch === es[i].swatch), 'the swatches are the same in both languages');
  for (const entry of LAYERS) for (const row of entry.legend) if (row.swatch) assert.ok(Object.hasOwn(PALETTE_TOKENS, row.swatch), `${entry.id}: ${row.swatch}`);
});

// ── numeric controls ─────────────────────────────────────────────────────────────────────────────────────────────

test('numeric_controls_and_zero: zero label and road opacity are valid; blank, non-finite, negative and out-of-range controls refuse', () => {
  const OPTIONS = {archive: 'https://example.test/a.pmtiles', assets: 'https://example.test/b/'};
  const styleWith = extra => basemapStyle(roleSentinel(extra), {...OPTIONS, variant: 'day'});
  const zero = styleWith({'map-label-opacity': '0', 'map-road-opacity': '0'});
  assert.ok(zero.layers.filter(l => l.type === 'symbol').every(l => l.paint['text-opacity'] === 0));
  assert.ok(zero.layers.filter(l => l.id.startsWith('roads-') && l.type === 'line').every(l => l.paint['line-opacity'] === 0));
  assert.equal(styleWith({'map-label-opacity': ' 0.5 ', 'map-road-opacity': '.25'}).layers.find(l => l.id === 'roads-highway').paint['line-opacity'], 0.25);
  for (const token of ['map-label-opacity', 'map-road-opacity']) {
    assert.throws(() => roleSentinel({[token]: ''}), new RegExp(`missing --${token}`), 'a blank control never reaches the style');
    for (const bad of ['NaN', 'Infinity', '-0.1', '1.01', '2', 'abc', '1e0', '0x1', '1,5', '+1']) {
      assert.throws(() => styleWith({[token]: bad}), new RegExp(`--${token} must be a number from 0 to 1`), `${token}=${JSON.stringify(bad)}`);
    }
  }
  const night = basemapStyle(roleSentinel({'map-label-opacity': 'junk', 'map-road-opacity': 'junk'}), {...OPTIONS, variant: 'night'});
  assert.ok(night.layers.filter(l => l.type === 'symbol').every(l => l.paint['text-opacity'] === 0.8), 'night keeps its 0.8');
  assert.ok(night.layers.filter(l => l.type === 'line' && l['source-layer'] === 'roads').every(l => l.paint['line-opacity'] === 0.6), 'night keeps its 0.6');
  assert.equal(mapControl('0', 't', 'unit'), 0); assert.equal(mapControl('1', 't', 'unit'), 1); assert.equal(mapControl('1.5', 't', 'positive'), 1.5);
  assert.throws(() => mapControl(undefined, 't', 'unit'), /--t must be/); assert.throws(() => mapControl('0', 't', 'positive'), /positive number/);
  assert.throws(() => mapControl('1'.padEnd(400, '0'), 't', 'positive'), /positive number/, 'a number that overflows to Infinity');
  for (const bad of ['NaN', 'Infinity', '-1', '0', '1e2', 'x']) {
    assert.throws(() => markStyle(roleSentinel({'map-habitat-opacity': bad})), /--map-habitat-opacity must be a positive number/, bad);
    assert.throws(() => contoursOverlay(roleSentinel({'map-contour-width': bad}), {type: 'FeatureCollection', features: []}), /--map-contour-width must be a positive number/, bad);
  }
});

test('numeric_controls_and_zero: multiplier 1 keeps the ramps, a large habitat multiplier caps at 0.6, contour width keeps its outermost zoom curve', () => {
  const opacity = (palette, id) => markStyle(palette).habitat.find(l => l.id === id).paint['fill-opacity'];
  const one = roleSentinel();
  assert.ok(isDeepStrictEqual(opacity(one, SURVEY_PICK), ['interpolate', ['linear'], ['zoom'], 9, 0.12, 12, 0.22, 15, 0.3]), 'the exact zoom ramp');
  assert.equal(opacity(one, GEOLOGY_PICK), 0.06);
  const big = roleSentinel({'map-habitat-opacity': '1000'});
  assert.ok(isDeepStrictEqual(opacity(big, SURVEY_PICK), ['interpolate', ['linear'], ['zoom'], 9, 0.6, 12, 0.6, 15, 0.6]));
  assert.equal(opacity(big, GEOLOGY_PICK), 0.6);
  const two = roleSentinel({'map-habitat-opacity': '2'});
  near(opacity(two, SURVEY_PICK)[4], 0.24, 1e-12, 'x2 at zoom 9'); near(opacity(two, GEOLOGY_PICK), 0.12, 1e-12, 'x2 geology');
  const width = palette => contoursOverlay(palette, {type: 'FeatureCollection', features: []}).layers.find(l => l.id === DEPTH_LINE).paint['line-width'];
  const base = width(roleSentinel());
  assert.equal(base[0], 'interpolate', 'the zoom curve stays outermost');
  assert.ok(isDeepStrictEqual(base[4], ['*', ['case', ['==', ['get', 'index'], true], 0.9, 0.4], ['case', ['==', ['get', 'provenance'], 'verified'], 1.25, 1]]));
  const heavy = width(roleSentinel({'map-contour-width': '2'}));
  assert.equal(heavy[0], 'interpolate');
  assert.deepEqual(heavy[4][2], ['case', ['==', ['get', 'provenance'], 'verified'], 2.5, 2], 'the verified factor multiplies each stop');
});

// ── today's resolved paint, except the four classes ─────────────────────────────────────────────────────────────

test('today_except_classes: map-only defaults equal the chrome roles the map used before, in each theme', () => {
  const alias = {'map-water': 'bg', 'map-land': 'panel', 'map-park': 'panel-2', 'map-road': 'line', 'map-road-minor': 'panel-2', 'map-boundary': 'line', 'map-label': 'muted',
    'map-halo': 'bg', 'map-ink': 'text', 'map-ink-halo': 'bg', 'map-coast': 'muted', 'map-contour': 'depth-1', 'mark-ring': 'mint'};
  for (const theme of ['dark', 'light']) {
    for (const [token, chrome] of Object.entries(alias)) assert.equal(RAW[theme][token], RAW[theme][chrome], `${theme} --${token} is --${chrome}`);
    for (const token of ['map-label-opacity', 'map-road-opacity', 'map-habitat-opacity', 'map-contour-width']) assert.equal(RAW[theme][token], '1', `${theme} --${token}`);
    for (const name of HABITAT_CLASSES) assert.notEqual(RAW[theme][`hab-${name}`], undefined);
  }
});

// sha256 of each module's JSON output under each theme's resolved tokens, taken from main 9312858 (before MGL-15; legend re-taken after SC1407-15 added the planning-route swatch), with the four
// habitat tokens set back to their old class colours. A different hash means something other than the four classes moved.
const PRE_MGL15 = {
  dark: {basemapDay: '4c3bc2f4888541e7279e39d822ed576c0b69703e0bfd9539c74b3da2df869ced', basemapNight: 'bcd35d05c97dac8ee923eeabc227cbf6f55466faedb2498c9a124245f8a648c0',
    markStyle: 'ea4bf9a688dd566c5dd776e5ec731ed1433bec2a67c5efc987441dc5bca9e07b', contours: '00340163df880b797d9a2d7618277d8d46435e711ae3eeed649b149286a7896c',
    wind: '0b39b8c9ca321f0b4edac7d2da696b68d87884ef90d1eafe3d875a8092b55d70', stations: '2ffaa0dd2f9eead93bf5d5ab0122048ae7c93e90f004e6a7d94f54d911a44ecf',
    ranked: '5f4127c8c0d72021a8285e8dba62acf1e60e1a21f044ff0fca925ff4f3d66c8c', coastline: 'ba45dddc66343939c5869bf19d43cf62f43797ad54e86f6899ada7bfc7d51d3a',
    mpa: 'ec0211f82aa47296adaedd43b08910d776b99bf7b0cdcda64f4c5f10febc9367', seafloor: 'dc2f2708205ac09f4b0f2e50c9f434d85fbab23f3827933af731607a5c1ecb7f',
    coastPalette: '6dc9df3acfc5197dc77636fa4d3bb3b4dc4711155b9ded4a33e7ebb6e5ce3fab', legend: '8ba22780365f22f0cfcd38f121423c8a8f7d910c21b771cbb99a16679b8b3f6c'},
  light: {basemapDay: 'd808bc498fdc45f2afb6a1e78fa9fe0a44a24bd41ebd933e9aaa93b9acf63ea6', basemapNight: 'e06ca75e8eee8e3d3cc39b35d0d6f3c78404603525d097cc19b68c351c8b8c95',
    markStyle: '809d30a296625c020206b7c6d6dfdf5fceb15c878ece7c68e87622d385baab25', contours: '02807f64e2f88064e66e7ff212445e02c00ab4a51220ecac6ffcae312a6c8ce6',
    wind: 'fcc72707149c69fd25582f517d81f968536cc73d011d46e8a7711170e698a475', stations: 'a8fbbc67164a536694a7c71b042a290847f5edcdb7caaf8f35801b5f58f00261',
    ranked: '1d31b678781879b866ea49adafe7e877f5ff19219639ad66f1b1c6500e66b1c1', coastline: 'a0a3e42e80196c3f02c5f912c53b0e635ec2635b3d204b354ab52d63df702dad',
    mpa: '28aac4da0865d837142fb538317a8d01da24ffa4566e8f2c01f917482f581b43', seafloor: 'e3b06a039c89eb28a9fc8f2fa1935b59c350940bcbc99c6d0c05fda3e0d786b4',
    coastPalette: '94883d376f41ef9d69047d7a6820f0de872bec5fdf149ec1da59c9c587da0ea8', legend: '7ccd143ff8b59aa72011d96bdc8b3abce7cac6b8511199680d09ef7dbc8d1a40'},
};
test('today_except_classes: day and night basemap, every overlay and every legend swatch resolve exactly as before, apart from the four classes', () => {
  const OPTIONS = {archive: 'https://example.test/tiles/basemap/ca-coast.pmtiles', assets: 'https://example.test/basemap/'}, empty = {type: 'FeatureCollection', features: []};
  const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
  // R4-SC-08 moved only the glyph URL under its content version; the pins predate it, so compare with the old URL.
  const basemap = (p, variant) => { const style = basemapStyle(p, {...OPTIONS, variant}); return {...style, glyphs: style.glyphs.replace(`/v/${GLYPH_VERSION}/`, '/')}; };
  for (const theme of ['dark', 'light']) {
    const p = paletteOf(theme, OLD_CLASSES[theme]);
    const got = {
      basemapDay: digest(basemap(p, 'day')), basemapNight: digest(basemap(p, 'night')), markStyle: digest(markStyle(p)),
      contours: digest(contoursOverlay(p, empty)), wind: digest(windOverlay(p)), stations: digest(stationOverlay(p)), ranked: digest(rankedStyle(p)), coastline: digest(coastlineLayers(p)),
      mpa: digest(mpaLayers(p)), seafloor: digest(seafloorLayers(p)), coastPalette: digest(coastPalette(p)),
      legend: digest(['en', 'es'].map(lang => LAYERS.map(e => [e.id, layerCopy(e.id, lang).legend.map(r => [r.label, r.swatch ? p[r.swatch] : null])]))),
    };
    for (const [name, hash] of Object.entries(PRE_MGL15[theme])) assert.equal(got[name], hash, `${theme} ${name} moved`);
  }
});

test('today_except_classes: only the four class colours differ, and they change in both themes', () => {
  for (const theme of ['dark', 'light']) {
    const now = markStyle(paletteOf(theme)).habitat, then = markStyle(paletteOf(theme, OLD_CLASSES[theme])).habitat;
    assert.notEqual(JSON.stringify(now), JSON.stringify(then));
    for (let i = 0; i < now.length; i++) {
      const strip = layer => JSON.stringify({...layer, paint: {...layer.paint, 'fill-color': undefined, 'line-color': undefined}});
      assert.equal(strip(now[i]), strip(then[i]), `${theme} ${now[i].id}: widths, opacity, filter and source unchanged`);
    }
    assert.ok(Object.entries(OLD_CLASSES[theme]).some(([token, old]) => RAW[theme][token] !== old));
  }
});
