#!/usr/bin/env node
// RF1935-4: appended focus-only layout; contrast paint, roles and thresholds unchanged.
// MGL-15: adds the offline habitat class CVD pair gate (exported helpers, `--habitat-cvd`, and the default run) and the two map text pairs;
// every legacy check, threshold, exit and transparent refusal is unchanged.
// WCAG 2.x contrast check for the documented text/background token pairs, in
// both themes of web/tokens.css (v2, dark default; design.md § 5). Fails under 4.5:1.
// FE-61 Accept 2 retired v1 dist/tokens.css once no page loaded it.
// Values are read from the files, so editing a token re-runs the check.
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

const MIN = 4.5;
// [foreground, background, what the pair is used for]
export const PAIRS_V2 = [
  ...['bg', 'bg-deep', 'panel', 'panel-2'].flatMap(bg => [['text', bg, 'body text and readings'], ['muted', bg, 'labels, units and ages']]),
  ...['mint', 'blue', 'coral', 'amber'].flatMap(fg => ['panel', 'panel-2'].map(bg => [fg, bg, 'reading text'])),
  ['bg', 'mint', 'primary button label'],
  // MGL-15: the map-only text roles, each on its own halo.
  ['map-ink', 'map-ink-halo', 'map text on its halo'],
  ['map-label', 'map-halo', 'map labels on their halo'],
];
// UXFIX-04: input and select borders are non-text UI, held to WCAG 1.4.11 (3:1), not the 4.5:1 text floor.
export const NON_TEXT_MIN = 3;
export const NON_TEXT_PAIRS = ['panel', 'panel-2'].map(bg => ['line-strong', bg, 'input and select border']);

// Which rule holds each theme's tokens: dark is :root and light overrides it.
export const FILES = {
  'web/tokens.css': {pairs: PAIRS_V2, base: 'dark', overlay: 'light', selectors: {dark: ':root', light: ':root[data-theme="light"]'}},
};
const V2 = FILES['web/tokens.css'];

// Custom properties declared directly inside the rule whose selector matches.
function block(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw Error(`tokens.css: missing ${selector}`);
  const open = css.indexOf('{', start);
  const body = css.slice(open + 1, css.indexOf('}', open));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map(m => [m[1], m[2].toLowerCase()]));
}

export function themes(css, spec = V2) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const base = block(text, spec.selectors[spec.base]);
  const overlay = block(text, spec.selectors[spec.overlay]);
  if (spec.selectors.auto) {
    const auto = block(text, spec.selectors.auto);
    if (JSON.stringify(auto) !== JSON.stringify(overlay)) throw Error('tokens.css: data-theme="auto" and "dark" colour tokens differ');
  }
  return {[spec.base]: base, [spec.overlay]: {...base, ...overlay}};
}

const channel = v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
export function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map(i => channel(parseInt(hex.slice(i, i + 2), 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

export function check(css, spec = V2) {
  const failures = [], rows = [];
  for (const [name, tokens] of Object.entries(themes(css, spec))) {
    for (const [fg, bg, use] of spec.pairs) {
      if (!tokens[fg] || !tokens[bg]) { failures.push(`${name}: --${fg} or --${bg} is not a hex colour token`); continue; }
      const ratio = contrast(tokens[fg], tokens[bg]);
      rows.push(`${name.padEnd(5)} --${fg} on --${bg}: ${ratio.toFixed(2)}:1 (${use})`);
      if (ratio < MIN) failures.push(`${name}: --${fg} ${tokens[fg]} on --${bg} ${tokens[bg]} is ${ratio.toFixed(2)}:1, below ${MIN}:1 (${use})`);
    }
  }
  if (spec === V2) {
    for (const [name, tokens] of Object.entries(themes(css, spec))) {
      for (const [fg, bg, use] of NON_TEXT_PAIRS) {
        if (!tokens[fg] || !tokens[bg]) { failures.push(`${name}: --${fg} or --${bg} is not a hex colour token`); continue; }
        const ratio = contrast(tokens[fg], tokens[bg]);
        rows.push(`${name.padEnd(5)} --${fg} on --${bg}: ${ratio.toFixed(2)}:1 (${use}, non-text minimum ${NON_TEXT_MIN}:1)`);
        if (ratio < NON_TEXT_MIN) failures.push(`${name}: --${fg} ${tokens[fg]} on --${bg} ${tokens[bg]} is ${ratio.toFixed(2)}:1, below ${NON_TEXT_MIN}:1 (${use})`);
      }
    }
  }
  return {failures, rows};
}

// packages/coast under data-coast-theme="tokens" (FE-77, design.md § 3A.4):
// the bridge maps --coast-* roles onto web/tokens.css, and panel.css draws
// these text roles on these background roles.
export const BRIDGE = 'packages/coast/tokens-bridge.css';
export const PAIRS_BRIDGE = [
  ...['ground', 'panel', 'panel-2', 'hover', 'mint-wash'].flatMap(bg => [['text', bg, 'coast body text'], ['muted', bg, 'coast labels and units']]),
  ...['mint', 'blue', 'coral', 'amber'].flatMap(fg => ['panel', 'panel-2'].map(bg => [fg, bg, 'coast reading text'])),
  ['mint', 'mint-wash', 'coast selected tab and day text'],
  ['on-mint', 'mint', 'coast primary button label'],
];

const hex = rgb => '#' + rgb.map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
const rgbOf = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
/** Each --coast-* role as hex per web/tokens.css theme; translucent roles (color-mix with transparent) are left out. */
export function bridged(bridgeCss, tokensCss) {
  const body = bridgeCss.replace(/\/\*[\s\S]*?\*\//g, '').match(/\{([^}]*)\}/)[1];
  const roles = [...body.matchAll(/--coast-([a-z0-9-]+):\s*([^;]+);/g)];
  const out = {};
  for (const [theme, tokens] of Object.entries(themes(tokensCss, FILES['web/tokens.css']))) {
    out[theme] = {};
    for (const [, role, value] of roles) {
      const plain = value.match(/^var\(--([a-z0-9-]+)\)$/);
      const mix = value.match(/^color-mix\(in srgb, var\(--([a-z0-9-]+)\) (\d+)%, var\(--([a-z0-9-]+)\)\)$/);
      if (plain && tokens[plain[1]]) out[theme][role] = tokens[plain[1]];
      else if (mix && tokens[mix[1]] && tokens[mix[3]]) {
        const [a, b, p] = [rgbOf(tokens[mix[1]]), rgbOf(tokens[mix[3]]), Number(mix[2]) / 100];
        out[theme][role] = hex(a.map((v, i) => v * p + b[i] * (1 - p)));
      }
    }
  }
  return out;
}
export function checkBridge(bridgeCss, tokensCss) {
  const failures = [], rows = [];
  for (const [name, roles] of Object.entries(bridged(bridgeCss, tokensCss))) {
    for (const [fg, bg, use] of PAIRS_BRIDGE) {
      if (!roles[fg] || !roles[bg]) { failures.push(`${name}: --coast-${fg} or --coast-${bg} does not resolve to an opaque web/tokens.css colour`); continue; }
      const ratio = contrast(roles[fg], roles[bg]);
      rows.push(`${name.padEnd(5)} --coast-${fg} on --coast-${bg}: ${ratio.toFixed(2)}:1 (${use})`);
      if (ratio < MIN) failures.push(`${name}: --coast-${fg} ${roles[fg]} on --coast-${bg} ${roles[bg]} is ${ratio.toFixed(2)}:1, below ${MIN}:1 (${use})`);
    }
  }
  return {failures, rows};
}

// P10: separate from the legacy opaque checks above. RGBA channels are encoded
// sRGB in [0,255], alpha in [0,1]; never quantize before luminance/contrast.
function validRgba(value) {
  if (!Array.isArray(value) || value.length !== 4 ||
      !Array.from(value).every((v, i) => Number.isFinite(v) && v >= 0 && v <= (i === 3 ? 1 : 255))) {
    throw Error('Expected finite RGBA channels in [0,255] and alpha in [0,1]');
  }
  return value;
}

/** Deliberately bounded parser for bridge expressions, not a CSS evaluator.
 * Supports #rrggbb, transparent, token var(), and the bridge's srgb mixes
 * (first percentage explicit, second omitted). Unsupported input is an error.
 */
export function resolveRgba(value, tokens = {}, seen = new Set()) {
  if (typeof value !== 'string') throw Error('Missing colour expression');
  const text = value.trim();
  if (/^#[0-9a-f]{6}$/i.test(text)) return [...rgbOf(text), 1];
  if (text === 'transparent') return [0, 0, 0, 0];
  const variable = text.match(/^var\(--([a-z0-9-]+)\)$/);
  if (variable) {
    const key = variable[1];
    if (!Object.hasOwn(tokens, key)) throw Error(`Missing colour token --${key}`);
    if (seen.has(key)) throw Error(`Cyclic colour token --${key}`);
    return resolveRgba(tokens[key], tokens, new Set([...seen, key]));
  }
  const mix = text.match(/^color-mix\(in srgb,\s*(var\(--[a-z0-9-]+\)|#[0-9a-f]{6}|transparent)\s+(\d+(?:\.\d+)?|\.\d+)%,\s*(var\(--[a-z0-9-]+\)|#[0-9a-f]{6}|transparent)\s*\)$/i);
  if (!mix) throw Error(`Unsupported colour expression: ${text}`);
  const p = Number(mix[2]) / 100;
  if (p < 0 || p > 1) throw Error('Mix percentage outside [0,100]');
  const a = resolveRgba(mix[1], tokens, seen), b = resolveRgba(mix[3], tokens, seen);
  // color-mix uses premultiplied alpha: transparent contributes no pigment.
  const alpha = a[3] * p + b[3] * (1 - p);
  return alpha === 0 ? [0, 0, 0, 0] : [
    ...a.slice(0, 3).map((v, i) => (v * a[3] * p + b[i] * b[3] * (1 - p)) / alpha),
    alpha,
  ];
}

/** Source-over in encoded sRGB, retaining fractional channels and alpha. */
export function sourceOver(surface, backing) {
  validRgba(surface); validRgba(backing);
  const alpha = surface[3] + backing[3] * (1 - surface[3]);
  return alpha === 0 ? [0, 0, 0, 0] : [
    ...surface.slice(0, 3).map((v, i) => (v * surface[3] + backing[i] * backing[3] * (1 - surface[3])) / alpha),
    alpha,
  ];
}

const unresolved = (status, reason) => ({status, ratio: null, reason});
export function classifyContrast(ratio) {
  if (!Number.isFinite(ratio) || ratio < 1 || ratio > 21) return unresolved('resolution_error', 'Invalid contrast ratio');
  return {status: ratio < MIN ? 'measured_failure' : 'pass', ratio};
}

/** A backing is one accepted solid colour with provenance, never a sample
 * purporting to bound arbitrary imagery. Missing proof never becomes a pass.
 * alphaRange requests remain unresolved pending continuous worst-case analysis.
 */
export function evaluateContrast(request = {}) {
  try {
    const {foreground, background, backing = null, backingProvenance = null, alphaRange = null} = request;
    validRgba(foreground); validRgba(background);
    if (alphaRange !== null) {
      if (!Array.isArray(alphaRange) || alphaRange.length !== 2 ||
          !Array.from(alphaRange).every(v => Number.isFinite(v) && v >= 0 && v <= 1) || alphaRange[0] > alphaRange[1]) {
        throw Error('Invalid alpha range');
      }
    }
    let bg = background;
    if (background[3] < 1 || alphaRange !== null) {
      if (backing !== null) validRgba(backing);
      if (backing === null || backing[3] !== 1 || typeof backingProvenance !== 'string' || !backingProvenance.trim()) {
        return unresolved('missing_background_evidence', 'An accepted opaque backing with provenance is required');
      }
      if (alphaRange !== null) return unresolved('missing_background_evidence', 'Continuous alpha-range worst-case proof is required; endpoints are insufficient');
      bg = sourceOver(background, backing);
    }
    const fg = sourceOver(foreground, bg);
    const lum = rgba => rgba.slice(0, 3).map(v => channel(v / 255)).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    return {...classifyContrast((hi + 0.05) / (lo + 0.05)), foreground: fg, background: bg};
  } catch (error) {
    return unresolved('resolution_error', error.message);
  }
}

// Source-bound requests from BUFFER-P10-ADMISSION. No map backing is supplied:
// ground is not evidence of the effective filtered map backdrop. Sheen's
// explicit panel backing does not qualify its continuous alpha interval.
export const TRANSPARENT_CASES = [
  {id: 'legend-title', fg: 'text', bg: 'panel-glass'},
  {id: 'legend-labels', fg: 'muted', bg: 'panel-glass'},
  ...['text', 'muted'].map(fg => ({id: `sheen-${fg}`, fg, bg: 'sheen', backing: 'panel',
    backingProvenance: 'panel.css:1194-1200; tokens-bridge.css:20,24 (BUFFER-P10-ADMISSION)', alphaRange: [0, 0.27]})),
];

/** Requested roles use the RGBA path; existing opaque checkBridge stays intact.
 * Each request names fg/bg bridge roles and optionally a backing role plus
 * backingProvenance. Multiple accepted backings require separate requests.
 * Callers must supply their actual supported backdrop contract, not samples.
 */
export function checkTransparentBridge(bridgeCss, tokensCss, requests = TRANSPARENT_CASES) {
  const failures = [], rows = [], results = [];
  const record = result => {
    results.push(result);
    if (result.status === 'pass') rows.push(`${result.theme} ${result.id}: ${result.ratio.toFixed(2)}:1`);
    else failures.push(`${result.theme} ${result.id}: ${result.status}${result.ratio === null ? '' : ` (${result.ratio.toFixed(2)}:1)`}${result.reason ? `: ${result.reason}` : ''}`);
  };
  try {
    if (!Array.isArray(requests) || !requests.length) throw Error('At least one transparent contrast request is required');
    const body = bridgeCss.replace(/\/\*[\s\S]*?\*\//g, '').match(/\{([^}]*)\}/);
    if (!body) throw Error('Missing bridge declaration block');
    const roles = Object.fromEntries([...body[1].matchAll(/--coast-([a-z0-9-]+):\s*([^;]+);/g)].map(m => [m[1], m[2]]));
    for (const [theme, tokens] of Object.entries(themes(tokensCss, FILES['web/tokens.css']))) {
      const resolve = role => {
        if (!Object.hasOwn(roles, role)) throw Error(`Missing bridge role --coast-${role}`);
        return resolveRgba(roles[role], tokens);
      };
      for (const request of requests) {
        try {
          const foreground = resolve(request.fg), background = resolve(request.bg);
          const backing = request.backing == null ? null : resolve(request.backing);
          record({theme, id: request.id, ...evaluateContrast({foreground, background, backing,
            backingProvenance: request.backingProvenance, alphaRange: request.alphaRange})});
        } catch (error) {
          record({theme, id: request?.id, ...unresolved('resolution_error', error.message)});
        }
      }
    }
  } catch (error) {
    record({theme: 'unresolved', id: 'requested-cases', ...unresolved('resolution_error', error.message)});
  }
  return {failures, rows, results};
}


/** Source proof for the production catch row, not a browser/cascade receipt.
 * Explicit sRGB interpolation plus componentwise ordered opaque stops makes
 * endpoint luminance bounds valid for every point of the continuous gradient.
 * A deliberately narrow contract fails closed when the supported paint changes.
 */
export function checkCatchGradient(panelCss, bridgeCss, tokensCss) {
  const hashes = Object.fromEntries(Object.entries({panelCss, bridgeCss, tokensCss})
    .map(([name, value]) => [name, createHash('sha256').update(value).digest('hex')]));
  const results = [];
  try {
    const clean = css => css.replace(/\/\*[\s\S]*?\*\//g, '');
    const normalize = value => value.trim().replace(/\s+/g, ' ');
    // FE-61 part 3: panel.css reads the bridge's roles without v1 literal fallbacks.
    const contract = {
      '.catch-counts': 'margin: 18px 0; display: grid; gap: 7px;',
      '.catch-counts > div': 'position: relative; display: flex; justify-content: space-between; gap: 15px; padding: 7px 9px; background: var(--coast-panel); border-radius: 3px; overflow: hidden;',
      '.catch-bar': 'position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg in srgb, var(--coast-mint-wash), var(--coast-panel));',
      '.catch-counts dt, .catch-counts dd': 'position: relative; font-size: 12px; margin: 0;',
      '.catch-counts dt small': 'color: var(--coast-muted); margin-left: 5px;',
      '.catch-counts dd': 'font-family: var(--coast-mono); color: var(--coast-mint);',
    };
    const seen = new Set();
    for (const match of clean(panelCss).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const selector = normalize(match[1]);
      if (!/\.catch-(?:counts|bar)\b/.test(selector)) continue;
      if (!Object.hasOwn(contract, selector) || seen.has(selector) || normalize(match[2]) !== contract[selector]) {
        throw Error(`Unsupported catch selector/paint contract: ${selector}`);
      }
      seen.add(selector);
    }
    if (seen.size !== Object.keys(contract).length) throw Error('Missing catch selector');
    const bridge = clean(bridgeCss).match(/^\s*\[data-coast-theme="tokens"\],\s*:host\(\[data-coast-theme="tokens"\]\)\s*\{([^{}]*)\}\s*$/);
    if (!bridge) throw Error('Unsupported bridge selector/grammar');
    const declarations = body => {
      const values = {};
      for (const declaration of body.split(';').map(s => s.trim()).filter(Boolean)) {
        const match = declaration.match(/^--([a-z0-9-]+):\s*(.+)$/s);
        if (!match) continue; // Non-custom declarations (e.g. color-scheme).
        if (Object.hasOwn(values, match[1])) throw Error(`Duplicate role --${match[1]}`);
        values[match[1]] = match[2].trim();
      }
      return values;
    };
    const roles = declarations(bridge[1]);
    const themeBlock = selector => {
      const matches = [...clean(tokensCss).matchAll(/^(:root(?:\[data-theme="light"\])?) \{([^{}]*)^\}/gm)].filter(m => m[1] === selector);
      if (matches.length !== 1) throw Error(`Missing/duplicate theme ${selector}`);
      return declarations(matches[0][2]);
    };
    const dark = themeBlock(':root'), light = {...dark, ...themeBlock(':root[data-theme="light"]')};
    for (const [theme, tokens] of Object.entries({dark, light})) {
      const resolve = role => {
        if (!Object.hasOwn(roles, `coast-${role}`)) throw Error(`Missing role --coast-${role}`);
        return resolveRgba(roles[`coast-${role}`], tokens);
      };
      const foreground = resolve('mint'), start = resolve('mint-wash'), end = resolve('panel');
      if (![foreground, start, end].every(v => v[3] === 1)) throw Error('Opaque catch proof requires opaque foreground and stops');
      const ordered = (a, b) => a.slice(0, 3).every((v, i) => v <= b[i]);
      if (!(ordered(start, end) || ordered(end, start))) throw Error('Unordered gradient channels: continuous proof unavailable');
      if (!((ordered(foreground, start) && ordered(foreground, end)) ||
            (ordered(start, foreground) && ordered(end, foreground)))) throw Error('Foreground crosses gradient bounds');
      const endpoints = [start, end].map(background => evaluateContrast({foreground, background}));
      if (endpoints.some(r => r.ratio === null)) throw Error('Unresolved endpoint');
      const minimum = Math.min(...endpoints.map(r => r.ratio));
      results.push({theme, status: minimum >= MIN ? 'source_pass' : 'source_failure', minimum,
        foreground, start, end, uncoveredPanel: endpoints[1].ratio,
        proof: 'Opaque explicit sRGB interpolation; componentwise ordered stops and foreground; monotone luminance bounds cover the closed interval.'});
    }
  } catch (error) {
    results.push({status: 'resolution_error', minimum: null, reason: error.message});
  }
  return {hashes, results, failures: results.filter(r => r.status !== 'source_pass'), rendered: false};
}

// A conservative analytical bound, not pixel sampling or a rendered-cascade
// result. Each channel of a*S+(1-a)*B is bilinear on the supplied closed
// alpha/backdrop rectangle, so its extrema occur at that rectangle's corners.
// Summing independent channel luminance intervals can widen the attainable
// set, never exclude a real background. A bound below MIN is NOT a measured
// failure: correlated channels may make the bound unattainable.
export function boundSurfaceContrast(request = {}) {
  try {
    const {foreground, surface, alphaRange, backingMin, backingMax} = request;
    for (const rgba of [foreground, surface, backingMin, backingMax]) validRgba(rgba);
    if (foreground[3] !== 1 || backingMin[3] !== 1 || backingMax[3] !== 1) {
      throw Error('Bound requires opaque foreground and opaque backdrop bounds');
    }
    if (!Array.isArray(alphaRange) || alphaRange.length !== 2 ||
        !Array.from(alphaRange).every(a => Number.isFinite(a) && a >= 0 && a <= surface[3]) ||
        alphaRange[0] > alphaRange[1]) throw Error('Invalid surface alpha interval');
    if (backingMin.slice(0, 3).some((v, i) => v > backingMax[i])) throw Error('Reversed backdrop bounds');
    const channels = surface.slice(0, 3).map((pigment, i) => {
      const corners = alphaRange.flatMap(a => [backingMin[i], backingMax[i]].map(b => a * pigment + (1 - a) * b));
      return [Math.min(...corners), Math.max(...corners)];
    });
    const linearBounds = ([lo, hi]) => {
      lo /= 255; hi /= 255;
      // Preserve the existing checker transfer function exactly. Its historical
      // 0.03928 split has a tiny discontinuity: bound BOTH one-sided values,
      // rather than incorrectly assuming the whole piecewise function is monotone.
      const split = 0.03928, values = [];
      if (lo <= split) values.push(lo / 12.92, Math.min(hi, split) / 12.92);
      if (hi > split) values.push(((Math.max(lo, split) + 0.055) / 1.055) ** 2.4, ((hi + 0.055) / 1.055) ** 2.4);
      return [Math.min(...values), Math.max(...values)];
    };
    const weights = [0.2126, 0.7152, 0.0722];
    const linear = channels.map(linearBounds);
    const luminanceRange = [0, 1].map(end => linear.reduce((sum, range, i) => sum + weights[i] * range[end], 0));
    const fgLum = foreground.slice(0, 3).reduce((sum, value, i) => sum + weights[i] * channel(value / 255), 0);
    const [lo, hi] = luminanceRange;
    const lowerBound = fgLum < lo ? (lo + 0.05) / (fgLum + 0.05) :
      fgLum > hi ? (fgLum + 0.05) / (hi + 0.05) : 1;
    return {status: lowerBound >= MIN ? 'source_pass' : 'not_proven', lowerBound,
      channels, luminanceRange, foregroundLuminance: fgLum, rendered: false,
      domain: {alphaRange, backingMin, backingMax},
      reason: lowerBound >= MIN ? 'Entire channel enclosure clears the unchanged threshold' :
        'Enclosure cannot guarantee contrast; this is not an observed pixel or a measured counterexample'};
  } catch (error) {
    return {status: 'resolution_error', lowerBound: null, reason: error.message, rendered: false};
  }
}

// MGL-15: habitat class separation under colour-vision deficiency. A reference
// check for the vector-water map with solid outlines: it is not proof for
// aerial imagery, lower zooms, the real translucent stroke pixels, legal
// clearance or biological accuracy. Every value stays unrounded until compared.
export const HABITAT_CLASSES = ['rock', 'mixed', 'soft', 'kelp'];
export const CVD_SIMULATIONS = ['normal', 'protanopia', 'deuteranopia', 'tritanopia'];
export const HABITAT_MIN_DELTA_E = {solid: 12, fill: 6};
export const HABITAT_FILL_ZOOM = 13;
// Machado, Oliveira and Fernandes 2009, severity 1.0, applied to linear sRGB.
export const MACHADO_SEVERITY_1 = {
  normal: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  protanopia: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deuteranopia: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
  tritanopia: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
};
const HEX6 = /^#[0-9a-f]{6}$/i;
const unit = v => (Number.isFinite(v) && v >= 0 && v <= 1) || (() => { throw Error(`Expected a finite value in [0,1], got ${v}`); })();

/** sRGB transfer function (IEC 61966-2-1): encoded [0,1] to linear [0,1]. */
export function srgbToLinear(v) {
  unit(v);
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}
export function linearToSrgb(v) {
  unit(v);
  return v <= 0.0031308 ? v * 12.92 : 1.055 * v ** (1 / 2.4) - 0.055;
}
/** Linear sRGB triple after a colour-vision simulation, clamped back into gamut. */
export function simulateCvd(linear, simulation) {
  if (!Object.hasOwn(MACHADO_SEVERITY_1, simulation)) throw Error(`Unknown colour-vision simulation: ${simulation}`);
  if (!Array.isArray(linear) || linear.length !== 3) throw Error('Expected a linear RGB triple');
  linear.forEach(unit);
  const m = MACHADO_SEVERITY_1[simulation];
  return m.map(row => Math.min(1, Math.max(0, row[0] * linear[0] + row[1] * linear[1] + row[2] * linear[2])));
}
/** Linear sRGB to CIE Lab under D65 (white 0.95047, 1, 1.08883). */
export function linearRgbToLab([r, g, b]) {
  const x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b;
  const y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b;
  const z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b;
  const f = t => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
  const [fx, fy, fz] = [f(x / 0.95047), f(y), f(z / 1.08883)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}
/** CIEDE2000 (Sharma, Wu and Dalal 2005), unrounded. */
export function deltaE2000(lab1, lab2) {
  const [L1, a1, b1] = lab1, [L2, a2, b2] = lab2;
  if (![...lab1, ...lab2].every(Number.isFinite) || lab1.length !== 3 || lab2.length !== 3) throw Error('Expected finite Lab triples');
  const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI, p7 = 25 ** 7;
  const mean = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2;
  const g = 0.5 * (1 - Math.sqrt(mean ** 7 / (mean ** 7 + p7)));
  const [a1p, a2p] = [(1 + g) * a1, (1 + g) * a2];
  const [c1p, c2p] = [Math.hypot(a1p, b1), Math.hypot(a2p, b2)];
  const hue = (b, a) => (b === 0 && a === 0 ? 0 : (deg(Math.atan2(b, a)) + 360) % 360);
  const [h1p, h2p] = [hue(b1, a1p), hue(b2, a2p)];
  const chromatic = c1p * c2p !== 0;
  let dh = 0;
  if (chromatic) { dh = h2p - h1p; if (dh > 180) dh -= 360; else if (dh < -180) dh += 360; }
  const dL = L2 - L1, dC = c2p - c1p, dH = 2 * Math.sqrt(c1p * c2p) * Math.sin(rad(dh / 2));
  const lMean = (L1 + L2) / 2, cMean = (c1p + c2p) / 2;
  let hMean = h1p + h2p;
  if (chromatic) hMean = Math.abs(h1p - h2p) <= 180 ? hMean / 2 : (hMean < 360 ? (hMean + 360) / 2 : (hMean - 360) / 2);
  const t = 1 - 0.17 * Math.cos(rad(hMean - 30)) + 0.24 * Math.cos(rad(2 * hMean)) + 0.32 * Math.cos(rad(3 * hMean + 6)) - 0.2 * Math.cos(rad(4 * hMean - 63));
  const sl = 1 + 0.015 * (lMean - 50) ** 2 / Math.sqrt(20 + (lMean - 50) ** 2);
  const sc = 1 + 0.045 * cMean, sh = 1 + 0.015 * cMean * t;
  const rt = -Math.sin(rad(2 * 30 * Math.exp(-(((hMean - 275) / 25) ** 2)))) * 2 * Math.sqrt(cMean ** 7 / (cMean ** 7 + p7));
  return Math.sqrt((dL / sl) ** 2 + (dC / sc) ** 2 + (dH / sh) ** 2 + rt * (dC / sc) * (dH / sh));
}
/** Encoded-sRGB source-over of a hex class colour on a hex backdrop; the result is encoded channels in [0,1]. */
export function blendHexOver(foreground, backdrop, alpha) {
  if (!HEX6.test(foreground) || !HEX6.test(backdrop)) throw Error('Expected #rrggbb colours');
  if (!Number.isFinite(alpha) || !(alpha > 0) || alpha > 1) throw Error(`Expected a fill alpha in (0,1], got ${alpha}`);
  const [f, b] = [rgbOf(foreground), rgbOf(backdrop)];
  return f.map((v, i) => (v * alpha + b[i] * (1 - alpha)) / 255);
}
/** CIEDE2000 between two encoded-sRGB triples as seen under `simulation`. */
export function cvdDeltaE(encodedA, encodedB, simulation) {
  const lab = encoded => linearRgbToLab(simulateCvd(encoded.map(srgbToLinear), simulation));
  return deltaE2000(lab(encodedA), lab(encodedB));
}

/** The zoom-`zoom` value of a linear `interpolate` on ['zoom'], the form the survey fill opacity is written in. */
export function evaluateZoomRamp(expression, zoom) {
  const stops = Array.isArray(expression) ? expression.slice(3) : [];
  if (!Number.isFinite(zoom) || !Array.isArray(expression) || expression[0] !== 'interpolate' || !Array.isArray(expression[1]) || expression[1][0] !== 'linear' ||
      !Array.isArray(expression[2]) || expression[2][0] !== 'zoom' || expression[2].length !== 1 || expression[1].length !== 1 || expression.length !== 3 + stops.length ||
      stops.length < 4 || stops.length % 2 || !stops.every(Number.isFinite) || stops.some((v, i) => i % 2 === 0 && i > 0 && v <= stops[i - 2])) {
    throw Error('Unsupported zoom ramp expression');
  }
  if (zoom <= stops[0]) return stops[1];
  for (let i = 2; i < stops.length; i += 2) {
    if (zoom <= stops[i]) return stops[i - 1] + (zoom - stops[i - 2]) / (stops[i] - stops[i - 2]) * (stops[i + 1] - stops[i - 1]);
  }
  return stops[stops.length - 1];
}

/** Every `--name: value;` (any value) declared directly in the rule for `selector`. */
function rawBlock(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw Error(`tokens.css: missing ${selector}`);
  const open = css.indexOf('{', start);
  return Object.fromEntries([...css.slice(open + 1, css.indexOf('}', open)).matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
}
/** Each theme's custom properties as text (light overrides dark), numbers included; `themes()` keeps to hex colours. */
export function rawThemes(css, spec = V2) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const base = rawBlock(text, spec.selectors[spec.base]);
  return {[spec.base]: base, [spec.overlay]: {...base, ...rawBlock(text, spec.selectors[spec.overlay])}};
}

/** The survey fill's effective opacity at `zoom` for one theme's raw tokens, evaluated from the renderer's own paint expression. */
export function habitatFillAlpha(markStyle, readPalette, rawTokens, surveyLayerId, zoom = HABITAT_FILL_ZOOM) {
  const layer = markStyle(readPalette(name => rawTokens[name] ?? '')).habitat.find(l => l.id === surveyLayerId);
  if (!layer) throw Error(`Renderer has no ${surveyLayerId} layer`);
  return evaluateZoomRamp(layer.paint['fill-opacity'], zoom);
}

/**
 * Every unordered pair of the four habitat classes, in both themes and under
 * normal vision plus protan/deutan/tritan simulation, once as solid colours
 * (outlines) and once as the fill blended over --map-water at `alpha`.
 * Reports every row; nothing is reduced to a best pair or a minimum.
 * `alphas` maps a theme name to its fill alpha (or pass one number for all).
 */
export function checkHabitatCvd(css, alphas, spec = V2) {
  const failures = [], rows = [], results = [], lines = [];
  const record = r => {
    results.push(r);
    const label = `${r.theme} ${r.simulation} ${r.pair} ${r.kind}`;
    if (r.status === 'pass') rows.push(`${label} alpha ${r.alpha}: dE2000 ${r.deltaE.toFixed(3)} (${r.deltaE}) >= ${r.threshold}`);
    else failures.push(`${label}${r.alpha === undefined ? '' : ` alpha ${r.alpha}`}: ${r.status}${r.deltaE === undefined ? '' : ` dE2000 ${r.deltaE.toFixed(3)} (${r.deltaE}) < ${r.threshold}`}${r.reason ? `: ${r.reason}` : ''}`);
    lines.push(r.status === 'pass' ? `PASS ${rows.at(-1)}` : `FAIL ${failures.at(-1)}`);
  };
  try {
    for (const [theme, tokens] of Object.entries(rawThemes(css, spec))) {
      const alpha = typeof alphas === 'number' ? alphas : alphas?.[theme];
      const water = tokens['map-water'], classes = HABITAT_CLASSES.map(name => [name, tokens[`hab-${name}`]]);
      const missing = [['map-water', water], ...classes.map(([name, value]) => [`hab-${name}`, value])].filter(([, value]) => !HEX6.test(value ?? '')).map(([name]) => `--${name}`);
      if (missing.length) { record({theme, simulation: 'all', pair: 'all', kind: 'tokens', status: 'resolution_error', reason: `${missing.join(', ')} is not a hex colour token`}); continue; }
      if (typeof alpha !== 'number' || !Number.isFinite(alpha) || !(alpha > 0) || alpha > 1) {
        record({theme, simulation: 'all', pair: 'all', kind: 'fill', status: 'resolution_error', reason: `fill alpha must be a finite number in (0,1], got ${alpha}`}); continue;
      }
      for (const simulation of CVD_SIMULATIONS) {
        for (let i = 0; i < classes.length; i++) {
          for (let j = i + 1; j < classes.length; j++) {
            for (const [kind, a] of [['solid', 1], ['fill', alpha]]) {
              const threshold = HABITAT_MIN_DELTA_E[kind], pair = `${classes[i][0]}/${classes[j][0]}`;
              try {
                const deltaE = cvdDeltaE(blendHexOver(classes[i][1], water, a), blendHexOver(classes[j][1], water, a), simulation);
                record({theme, simulation, pair, kind, alpha: a, deltaE, threshold, status: deltaE >= threshold ? 'pass' : 'measured_failure'});
              } catch (error) {
                record({theme, simulation, pair, kind, alpha: a, threshold, status: 'resolution_error', reason: error.message});
              }
            }
          }
        }
      }
    }
    if (!results.length) throw Error('No habitat class rows were produced');
  } catch (error) {
    record({theme: 'unresolved', simulation: 'all', pair: 'all', kind: 'tokens', status: 'resolution_error', reason: error.message});
  }
  return {failures, rows, results, lines};
}

/**
 * The gate on `css` with each theme's fill alpha read from the real renderer
 * (markStyle's survey fill at zoom 13 under that theme's numeric tokens), so a
 * changed ramp or control moves the gate with it. Never throws: any failure to
 * evaluate is a failure line, not a pass.
 */
export async function habitatCvdReport(css) {
  try {
    const {markStyle, SURVEY_PICK} = await import(new URL('../web/map/marks.ts', import.meta.url).href);
    const {readPalette} = await import(new URL('../web/map/palette.ts', import.meta.url).href);
    const alphas = Object.fromEntries(Object.entries(rawThemes(css)).map(([theme, raw]) => [theme, habitatFillAlpha(markStyle, readPalette, raw, SURVEY_PICK)]));
    return checkHabitatCvd(css, alphas);
  } catch (error) {
    const reason = `habitat CVD gate could not run: ${error.message}`;
    return {failures: [reason], rows: [], results: [{status: 'resolution_error', reason}], lines: [`FAIL ${reason}`]};
  }
}

// Deliberately snapshot-bound evidence mode. These hashes authenticate ALL
// source bytes, including later overrides, rather than claiming a partial CSS
// parser proves the cascade. A changed source must be reviewed/rebound; default
// CLI and generic missing-background behavior remain unchanged pending review.
// SC1722-14: form typography changes layout, not colour, alpha, backing or contrast thresholds.
// SC1922-04: appended preview layout/text roles leave existing legend/catch paint unchanged.
export const SURFACE_SOURCE_SHA256 = {
  // BF-wcag only adds min-height (24 px target floor) to .text-link, .history-provenance a and .sheet-links a; no paint changed.
  // SC1722-08 only raises the History chart scroller's focus ring to 2 px and adds one .history-measurement-note > summary focus ring; no unfocused paint changed.
  "panelCss": "f765e1221775a652f300a63e657f99eff3538179376a85f53361befa5de2b385",
  "bridgeCss": "8ea4a379a3e516817d4472ad434da797482c4b96e07697aa29269464f433e6d5",
  "tokensCss": "7a9832ee99cc3b71fa40e3eacabaf40b0479a6c48eb141f5cca0cc55bb43abbb",
  // CI6-18 only adds layout declarations scoped to .app-legend-stations; sampled Reports paint is unaffected.
  // SC-N3 only adds overflow/min-width rules for the phone sheet Day row and Target select and hides .app-top-card .app-location-coords.
  // SC2222-07 only adds a sticky .app-mark-actions row (opaque --panel) and scroll padding inside the left-column mark card; legend paint is unaffected.
  // BF-wcag only adds a 24 px min-height to .app-brand and .app-brief-footer a; no paint changed.
  // SC-E2E-GREEN only lets the left-column legend shrink and scroll (flex/min-height/overflow) beside a mark-card min height,
  // wraps the phone sheet's .app-area row, and gives the brief's .app-verdict-rules line margins, size and the existing
  // .app-mark-regs a link rule; legend text paint and backing are unchanged.
  // SC-POPOVER only places the desktop legend's basis popovers against their own button (position: fixed + anchor positioning) so the
  // scrolling legend does not clip them; the popover keeps its existing ui.css paint, and legend text paint and backing are unchanged.
  // SC2207-11 only appends a scoped .app-first-answer* block at the end of app.css (opaque --panel, token text roles); no existing rule or
  // legend paint changed, and the cited line numbers above are unmoved.
  // SC-PERF-INSTANT-1 only appends a scoped .app-saved block at the end of app.css (token text roles on the brief, not the legend glass);
  // no legend paint or backing changed and the cited line numbers above are unmoved.
  // SC-PERF-JUMP-1 only appends layout rules at the end of app.css (a masthead min-height and no-wrap row on the desktop, a minimum width on the target menu,
  // a minimum height on the desktop legend); no colour, opacity, backing or text paint changed, and the cited line numbers above are unmoved.
  // SC-TIDAL-1 only appends a scoped .app-entrance* block at the end of app.css (token text roles on the brief's run line, not the legend glass);
  // no legend paint or backing changed and the cited line numbers above are unmoved.
  // UXFIX-04 only adds --line-strong to tokens.css, re-points input/select border colour to it and deletes duplicate focus outlines (shared rule in ui.css); no text role, backing or legend paint changed.
  // SC1722-08 only consolidates link focus outlines (removes the .app-views and first-answer duplicates; the shared a:focus-visible rule is in ui.css), so
  // focus paint intentionally changes; unfocused legend text and backing are unchanged. Cited app.css lines after :29 moved up by one.
  // SC1722-07 only adds the phone sheet's --sheet-hidden-offset custom property (vh and @supports dvh values mirroring the existing transforms) to the .app-sheet rules;
  // no colour, opacity, backing or text paint changed and the cited line numbers above are unmoved.
  // SC1722-06: Limits box sizing/scroll and opaque token-backed sticky actions only; Reports does not mount them.
  // RF1925-1: masthead minimum-width only; legend paint and backing unchanged.
  // SC1722-01 only appends a scoped .app-forecast-failed* block at the end of app.css (token text roles on the brief, not the legend glass);
  // no legend paint or backing changed and the cited line numbers above are unmoved.
  // SC1722-19: app.css adds only desktop (min-width 1024px) layout rules (the app scrolls inside itself, the stage clips, a sticky time dock); no colour, backing or token changes and no line citation moves.
  // RF1935-2 only appends a desktop-only (min-width: 1024px) .app-stage > .app-rail > .ui-segmented wrap block at the end of app.css and sets the desktop rail's
  // overflow-y: scroll with a stable scrollbar gutter (layout, no paint); no colour, opacity, backing or text paint changed and the cited line numbers above are unmoved.
  // SC1922-03 only adds a scoped .app-conditions-head model-family wrap/min-height rule after .app-conditions-head, plus a pointer-events-only rule for .app-presentation--placing (no paint); no colour, opacity, backing or text paint changed and legend glass is untouched.
  // SC1922-08 lets the .app-fresh chip wrap (flex-wrap, max-width, same line) and appends only a [data-refresh-line] wrap rule at the end of app.css (no colour, opacity or backing; the chip keeps its muted text role); no legend paint changed and the cited line numbers above are unmoved.
  // RF2135-5 only appends a scoped landscape-phone (max-height: 500px) .app-mobile .app-top layout block at the end of app.css (row direction, flex bases, --app-strip); no colour, opacity, backing or text paint changed, legend glass untouched and the cited line numbers above are unmoved.
  // RF2135-5 (size fix) also folds six identical focus-ring rules into the first one, one 44px link-target rule for five links and the two blue link colours into one rule (same declarations and selectors, no paint changed); that removes two rules before the legend rules, so the cited app.css lines after :29 moved up by two.
  // SC1722-20 only appends a scoped .app-skip-link block at the end of app.css (token colours; a clipped 1 px anchor at rest, a ringed 44 px panel when focused);
  // no legend paint, backing or text role changed and the cited line numbers above are unmoved. It also folds the .app-history layout rules into the .app-conditions ones (same declarations, same order; no paint changed) to stay inside the app styles size budget.
  // MGL-15 adds map-only tokens (--map-*, --hab-*, --mark-ring) to tokens.css and repoints only the two depth-contour legend swatch rules in app.css to them;
  // existing text and legend-glass backing paint, thresholds and cited line numbers are unchanged (map-only additions and swatch colours are not text or backing).
  // UXFIX-09: app.css adds one tile-basis margin rule scoped to .app-tiles and raises the phone .app-top z-index by one; no colour, backing or text paint changed. Rebound from the final bytes.
  "appCss": "ca69925a654b429f6374b4f7336243e134198c124ac177203f263efcb5df459b",
  // SC1407-15: one decorative dashed route swatch; existing text roles/backing unchanged. Later citations shift by one.
  // UXFIX-10 only appends a scoped .app-account[data-top] block at the end of app.css (the phone top-card account button: icon size, hidden label, open-state text/panel colour, z-index);
  // no legend paint, backing or text role changed and the cited line numbers above are unmoved.
  // CI6-08 adds a chlorophyll row and CI6-18 a Stations row, both using the existing text/muted glass roles.
  // CI6-09 adds the existing Segmented control for swell partitions; the pinned text paint is unchanged.
  // No backing, opacity, text paint or threshold changed; swatches, decorative scales and controls remain excluded.
  // SC2007-02 adds the shared quiet Button (Try again) to the Protected areas row; no text paint changed.
  // BF-sst-fronts adds a Temp fronts row using the existing app-legend-note text role; no backing, opacity or text paint changed.
  // SC0922-04 adds the Your saved spots row (a native checkbox label and an app-legend-note status in the existing text roles, the shared quiet Button); no backing, opacity or text paint changed.
  // SC0922-04 CI fix sizes only the saved-spots checkbox to 24px; declared text and backing paints are unchanged.
  // SC0452-04 adds two coarse-drape notes (MPA and charter-grounds rows) that reuse the existing app-legend-note paint; no backing, opacity, token or threshold changed.
  // Main-merge reconciliation: both additions retain existing text roles and paint; rebind the combined source only.
  // SC1952-08 adds a Shore runs "not yet reviewed" note using the existing app-legend-note text role; no backing, opacity or text paint changed.
  // SC0707-09 moves the Legend's fixed words and basis sentences to the string catalogue and labels run-time English; every row keeps its
  // existing app-legend-note/ui-mono text roles and no backing, opacity, token or threshold changed. Line citations above moved with the source.
  // SC1352-02 resolves a layer's status note, reason and stamp in the page's language (one Status wrapper around the existing text);
  // every row keeps its app-legend-note/ui-mono text roles and no backing, opacity, token or threshold changed. Line citations above moved with the source.
  // SC1352-03 gives the Currents, Wind and Swell rows the same Status wrapper (a reason or stamp in the page's language); no text role,
  // backing, opacity, token or threshold changed, and the Depth row's citation moved one line.
  // SC1352-04 resolves the protected-areas row's note and basis detail in the page's language through the same Status wrapper (copy only, no paint);
  // the note and basis keep their app-mpa-note and popover text roles, and no backing, opacity, token or threshold changed.
  // SC1352-05 shows the Stations note and the nearshore-ring summary and basis in the page's language (copy only, no paint); the same text roles
  // stay, and no backing, opacity, token or threshold changed.
  // SC1352-06 shows the saved-spots status in the page’s language through the same Status wrapper (copy only, no paint); the same note text role stays, and no backing, opacity, token or threshold changed.
  // SC1352-07 shows the evidence layers' status lines (charter grounds, commercial AIS, temperature fronts) and the fronts basis in the page's language through the same Status wrapper (copy only, no paint); the same note text roles stay, and two lines were added above the cited rows.
  // SCFEAT-FRESH-1 adds an "Updates: cadence" line under each drawn layer row and the protected-areas row, using the existing app-legend-note text role (copy only); no backing, opacity, token or threshold changed.
  // SC1407-15: planning-route row uses existing text/muted glass roles; no paint math, thresholds or backing changed.
  "legendTsx": "045a0f55859fc8aace47ab6b23a6ee7fed0736d41e13ee3835bc1f1215f24ce9"
};
export function checkSurfaceSource(sources) {
  const hashes = {}, results = [];
  try {
    for (const [name, expected] of Object.entries(SURFACE_SOURCE_SHA256)) {
      if (typeof sources?.[name] !== 'string') throw Error(`Missing surface source ${name}`);
      hashes[name] = createHash('sha256').update(sources[name]).digest('hex');
      if (hashes[name] !== expected) throw Error(`Surface source binding changed: ${name}`);
    }
    const bridgeBody = sources.bridgeCss.replace(/\/\*[\s\S]*?\*\//g, '').match(/\{([^}]*)\}/)[1];
    const roles = Object.fromEntries([...bridgeBody.matchAll(/--coast-([a-z0-9-]+):\s*([^;]+);/g)].map(m => [m[1], m[2]]));
    for (const [theme, tokens] of Object.entries(themes(sources.tokensCss, FILES['web/tokens.css']))) {
      const resolve = role => resolveRgba(roles[role], tokens);
      const panel = resolve('panel'), glass = resolve('panel-glass'), sheen = resolve('sheen');
      const nativeGlass = resolveRgba('color-mix(in srgb, var(--panel) 92%, transparent)', tokens);
      for (const [id, role, surface, alphaRange, backingMin, backingMax, binding] of [
        ['legend-title', 'text', glass, [glass[3], glass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'panel.css:807-824; bridge:21,26'],
        ['legend-labels', 'muted', glass, [glass[3], glass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'panel.css:858-868,2678-2684; bridge:21,27'],
        ['sheen-text', 'text', sheen, [0, sheen[3]], panel, panel, 'panel.css:1191-1201; bridge:20,24,26'],
        ['sheen-muted', 'muted', sheen, [0, sheen[3]], panel, panel, 'panel.css:1191-1201; bridge:20,24,27'],
        ['app-legend-text', 'text', nativeGlass, [nativeGlass[3], nativeGlass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'app.css:11,173,213,227; Legend.tsx:394'],
        ['app-legend-muted', 'muted', nativeGlass, [nativeGlass[3], nativeGlass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'app.css:173,194,242; Legend.tsx:111,245,394'],
      ]) {
        const foreground = resolve(role);
        results.push({theme, id, binding, foreground, surface,
          ...boundSurfaceContrast({foreground, surface, alphaRange, backingMin, backingMax})});
      }
    }
  } catch (error) {
    results.push({status: 'resolution_error', lowerBound: null, reason: error.message});
  }
  return {hashes, results, failures: results.filter(r => r.status !== 'source_pass'), rendered: false,
    scope: 'Pinned declared paint chains only; opaque text/muted; encoded-sRGB source-over. Legend covers the whole RGB cube, sheen covers every alpha in [0,0.27].',
    exclusions: 'No browser load/cascade/visibility/ancestor-opacity/filter/overlay/HDR/legacy-fallback acceptance. No legend ramp or interactive-control color claim.'};
}

if (import.meta.url === `file://${process.argv[1]}`) {
  if (process.argv.includes('--surface-source')) {
    const root = new URL('../', import.meta.url);
    const sources = Object.fromEntries(Object.entries({panelCss: 'packages/coast/panel.css',
      bridgeCss: BRIDGE, tokensCss: 'web/tokens.css', appCss: 'web/app/app.css', legendTsx: 'web/app/Legend.tsx'})
      .map(([name, path]) => [name, readFileSync(new URL(path, root), 'utf8')]));
    const result = checkSurfaceSource(sources);
    console.log(JSON.stringify(result));
    process.exit(result.failures.length ? 1 : 0);
  }

  if (process.argv.includes('--catch-source')) {
    const root = new URL('../', import.meta.url);
    const result = checkCatchGradient(...['packages/coast/panel.css', BRIDGE, 'web/tokens.css'].map(path => readFileSync(new URL(path, root), 'utf8')));
    console.log(JSON.stringify(result));
    process.exit(result.failures.length ? 1 : 0);
  }
  const root = new URL('../', import.meta.url);
  const named = process.argv.slice(2).filter(a => !a.startsWith('--'));
  // MGL-15: read-only habitat class CVD gate; an optional file argument checks that tokens.css instead of the repository's.
  if (process.argv.includes('--habitat-cvd')) {
    let css;
    try { css = readFileSync(named.length ? named[0] : new URL('web/tokens.css', root), 'utf8'); } catch (error) {
      console.error(`Habitat CVD check could not read its tokens: ${error.message}`);
      process.exit(1);
    }
    const {failures, lines, rows} = await habitatCvdReport(css);
    console.log(lines.join('\n'));
    if (failures.length) { console.error(`Habitat CVD check failed: ${failures.length} of ${lines.length} rows.`); process.exit(1); }
    console.log(`Habitat CVD check passed: ${rows.length} rows (solid >= ${HABITAT_MIN_DELTA_E.solid}, fill >= ${HABITAT_MIN_DELTA_E.fill} dE2000).`);
    process.exit(0);
  }
  let failed = false, count = 0;
  for (const file of named.length ? named : Object.keys(FILES)) {
    const spec = FILES[file.replace(/^\.\//, '')] || V2;
    const {failures, rows} = check(readFileSync(named.length ? file : new URL(file, root), 'utf8'), spec);
    if (process.argv.includes('--verbose')) console.log(rows.map(r => `${file}: ${r}`).join('\n'));
    if (failures.length) { failed = true; console.error(`Contrast check failed in ${file}:\n  ${failures.join('\n  ')}`); }
    count += rows.length;
  }
  if (!named.length) {
    const {failures, rows} = checkBridge(readFileSync(new URL(BRIDGE, root), 'utf8'), readFileSync(new URL('web/tokens.css', root), 'utf8'));
    if (process.argv.includes('--verbose')) console.log(rows.map(r => `${BRIDGE}: ${r}`).join('\n'));
    if (failures.length) { failed = true; console.error(`Contrast check failed in ${BRIDGE}:\n  ${failures.join('\n  ')}`); }
    count += rows.length;
    const transparent = checkTransparentBridge(readFileSync(new URL(BRIDGE, root), 'utf8'), readFileSync(new URL('web/tokens.css', root), 'utf8'));
    if (process.argv.includes('--verbose')) console.log(transparent.rows.map(r => `${BRIDGE}: ${r}`).join('\n'));
    if (transparent.failures.length) { failed = true; console.error(`Transparent contrast check failed in ${BRIDGE}:\n  ${transparent.failures.join('\n  ')}`); }
    count += transparent.rows.length;
    // MGL-15: habitat classes are part of the default run; their failures are reported apart from the transparent-evidence ones above.
    const habitat = await habitatCvdReport(readFileSync(new URL('web/tokens.css', root), 'utf8'));
    if (process.argv.includes('--verbose')) console.log(habitat.rows.map(r => `habitat CVD: ${r}`).join('\n'));
    if (habitat.failures.length) { failed = true; console.error(`Habitat CVD check failed in web/tokens.css:\n  ${habitat.failures.join('\n  ')}`); }
  }
  if (failed) process.exit(1);
  console.log(`Contrast check passed: ${count} text pairs at or above ${MIN}:1 in light and dark themes.`);
}
