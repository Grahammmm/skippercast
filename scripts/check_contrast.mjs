#!/usr/bin/env node
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
];

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

// Deliberately snapshot-bound evidence mode. These hashes authenticate ALL
// source bytes, including later overrides, rather than claiming a partial CSS
// parser proves the cascade. A changed source must be reviewed/rebound; default
// CLI and generic missing-background behavior remain unchanged pending review.
export const SURFACE_SOURCE_SHA256 = {
  "panelCss": "fda5b83480f2c32243d5ff90b99e2581d459a46f88543d6a264705bdc8e821fb",
  "bridgeCss": "8ea4a379a3e516817d4472ad434da797482c4b96e07697aa29269464f433e6d5",
  "tokensCss": "06db13ad1e8eeca76f9ebdcf01d95125abd52ad0f4bc21a51d7611e428d02428",
  "appCss": "7172217e46b2f0eee4f3becd85755d15a6cf9c2137c96ced196d04ed7bd5a34b",
  // CI6-08 adds a row using existing text/muted roles; no backing, opacity or text paint changes.
  // The new decorative scale remains outside this proof's legend-ramp scope.
  "legendTsx": "44668645969b2884f016bd5c0932931d224d9ac420145e7e20ee1c788d41b1ac"
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
        ['app-legend-text', 'text', nativeGlass, [nativeGlass[3], nativeGlass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'app.css:11,157,186,202; Legend.tsx:284'],
        ['app-legend-muted', 'muted', nativeGlass, [nativeGlass[3], nativeGlass[3]], [0, 0, 0, 1], [255, 255, 255, 1], 'app.css:157,168,215; Legend.tsx:79,186,284'],
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
  }
  if (failed) process.exit(1);
  console.log(`Contrast check passed: ${count} text pairs at or above ${MIN}:1 in light and dark themes.`);
}
