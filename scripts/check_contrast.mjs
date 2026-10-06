#!/usr/bin/env node
// WCAG 2.x contrast check for the documented text/background token pairs, in
// both themes of both token files: dist/tokens.css (v1, light default) and
// web/tokens.css (v2, dark default; design.md § 5). Fails under 4.5:1.
// Values are read from the files, so editing a token re-runs the check.
import {readFileSync} from 'node:fs';

const MIN = 4.5;
// [foreground, background, what the pair is used for]
export const PAIRS = [
  ...['surface', 'card', 'brand-tint'].flatMap(bg => [
    ['ink', bg, 'primary text'],
    ['ink-2', bg, 'secondary text'],
    ['brand', bg, 'links and brand text'],
  ]),
  ...['go', 'caution', 'rough', 'unknown'].flatMap(fg => ['surface', 'card'].map(bg => [fg, bg, 'status text'])),
  ['on-brand', 'brand', 'primary button label'],
  ['on-deep', 'deep', 'masthead text'],
];
export const PAIRS_V2 = [
  ...['bg', 'bg-deep', 'panel', 'panel-2'].flatMap(bg => [['text', bg, 'body text and readings'], ['muted', bg, 'labels, units and ages']]),
  ...['mint', 'blue', 'coral', 'amber'].flatMap(fg => ['panel', 'panel-2'].map(bg => [fg, bg, 'reading text'])),
  ['bg', 'mint', 'primary button label'],
];

// Which rule holds each theme's tokens. v1: light is :root and dark overrides
// it (the auto and dark blocks must match). v2: dark is :root, light overrides.
export const FILES = {
  'dist/tokens.css': {pairs: PAIRS, base: 'light', overlay: 'dark', selectors: {light: ':root', dark: ':root[data-theme="dark"]', auto: ':root[data-theme="auto"]'}},
  'web/tokens.css': {pairs: PAIRS_V2, base: 'dark', overlay: 'light', selectors: {dark: ':root', light: ':root[data-theme="light"]'}},
};
const V1 = FILES['dist/tokens.css'];

// Custom properties declared directly inside the rule whose selector matches.
function block(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw Error(`tokens.css: missing ${selector}`);
  const open = css.indexOf('{', start);
  const body = css.slice(open + 1, css.indexOf('}', open));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map(m => [m[1], m[2].toLowerCase()]));
}

export function themes(css, spec = V1) {
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

export function check(css, spec = V1) {
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

if (import.meta.url === `file://${process.argv[1]}`) {
  const root = new URL('../', import.meta.url);
  const named = process.argv.slice(2).filter(a => !a.startsWith('--'));
  let failed = false, count = 0;
  for (const file of named.length ? named : Object.keys(FILES)) {
    const spec = FILES[file.replace(/^\.\//, '')] || V1;
    const {failures, rows} = check(readFileSync(named.length ? file : new URL(file, root), 'utf8'), spec);
    if (process.argv.includes('--verbose')) console.log(rows.map(r => `${file}: ${r}`).join('\n'));
    if (failures.length) { failed = true; console.error(`Contrast check failed in ${file}:\n  ${failures.join('\n  ')}`); }
    count += rows.length;
  }
  if (failed) process.exit(1);
  console.log(`Contrast check passed: ${count} text pairs at or above ${MIN}:1 in light and dark themes.`);
}
