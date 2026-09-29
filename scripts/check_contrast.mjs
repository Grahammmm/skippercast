#!/usr/bin/env node
// WCAG 2.x contrast check for the documented text/background token pairs in
// dist/tokens.css, in both the light and dark themes. Fails under 4.5:1.
// Values are read from tokens.css, so editing a token re-runs the check.
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

// Custom properties declared directly inside the rule whose selector matches.
function block(css, selector) {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw Error(`tokens.css: missing ${selector}`);
  const open = css.indexOf('{', start);
  const body = css.slice(open + 1, css.indexOf('}', open));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map(m => [m[1], m[2].toLowerCase()]));
}

export function themes(css) {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const light = block(text, ':root');
  const auto = block(text, ':root[data-theme="auto"]');
  const dark = block(text, ':root[data-theme="dark"]');
  if (JSON.stringify(auto) !== JSON.stringify(dark)) throw Error('tokens.css: data-theme="auto" and "dark" colour tokens differ');
  return {light, dark: {...light, ...dark}};
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

export function check(css) {
  const failures = [], rows = [];
  for (const [name, tokens] of Object.entries(themes(css))) {
    for (const [fg, bg, use] of PAIRS) {
      if (!tokens[fg] || !tokens[bg]) { failures.push(`${name}: --${fg} or --${bg} is not a hex colour token`); continue; }
      const ratio = contrast(tokens[fg], tokens[bg]);
      rows.push(`${name.padEnd(5)} --${fg} on --${bg}: ${ratio.toFixed(2)}:1 (${use})`);
      if (ratio < MIN) failures.push(`${name}: --${fg} ${tokens[fg]} on --${bg} ${tokens[bg]} is ${ratio.toFixed(2)}:1, below ${MIN}:1 (${use})`);
    }
  }
  return {failures, rows};
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const file = process.argv.slice(2).find(a => !a.startsWith('--')) || new URL('../dist/tokens.css', import.meta.url);
  const {failures, rows} = check(readFileSync(file, 'utf8'));
  if (process.argv.includes('--verbose')) console.log(rows.join('\n'));
  if (failures.length) {
    console.error(`Contrast check failed:\n  ${failures.join('\n  ')}`);
    process.exit(1);
  }
  console.log(`Contrast check passed: ${rows.length} text pairs at or above ${MIN}:1 in light and dark themes.`);
}
