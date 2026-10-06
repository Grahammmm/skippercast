#!/usr/bin/env node
// Token lint (FE-02, docs/plans/front-end/design.md § 5): v2 client code
// reads every colour and font through var(--…) from web/tokens.css.
// Rules over web/**/*.{css,ts,tsx} except the tokens file, comments ignored:
//   colour-literal  hex, rgb()/rgba()/hsl()/hsla(), or (CSS only: "black
//                   rockfish" is copy) a named colour as a declaration value;
//   font-family     a font-family declaration or fontFamily style property;
//   token-bridge    getPropertyValue('--…') outside web/map/palette.ts, the
//                   one allowed bridge from CSS to the map and canvas code.
// Baseline scripts/token-lint-baseline.json only shrinks (check_copy's
// contract): a new finding fails; a stale entry fails until `--update` drops
// it; `--base <git-ref>` fails if the baseline grew since that ref.
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

// TOKEN_LINT_ROOT points the lint at another tree (the tests use a temporary one).
export const ROOT = process.env.TOKEN_LINT_ROOT || fileURLToPath(new URL('..', import.meta.url));
export const BASELINE = 'scripts/token-lint-baseline.json';
export const TOKENS_FILE = 'web/tokens.css';
export const BRIDGE_FILE = 'web/map/palette.ts';

const EXT = /\.(?:css|ts|tsx)$/;
const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g;
const FUNCTION = /\b(?:rgb|rgba|hsl|hsla)\(/g;
const NAMED = /:\s*(?:[^;{}]*\s)?(white|black|red|green|blue|yellow|orange|gray|grey|silver|navy|teal|aqua|cyan|magenta|purple|pink|brown)\b/gi;
const FONT = /\bfont-family\s*[:=]|\bfontFamily\b/g;
const BRIDGE = /getPropertyValue\s*\(\s*['"`]--/g;

const clip = text => (text.length > 120 ? text.slice(0, 117) + '...' : text);
const lineOf = (source, index) => source.slice(0, index).split('\n').length;

/** Source with block comments and whole-line `//` comments blanked (positions kept). */
export function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
    .replace(/^([ \t]*)\/\/[^\n]*/gm, (m, lead) => lead + ' '.repeat(m.length - lead.length));
}

/** Findings for one file: {file, rule, text, line}. */
export function lintFile(file, source) {
  if (file === TOKENS_FILE || !EXT.test(file)) return [];
  const text = stripComments(source);
  const found = [];
  const line = i => text.slice(text.lastIndexOf('\n', i - 1) + 1, text.indexOf('\n', i) < 0 ? undefined : text.indexOf('\n', i)).trim();
  const add = (rule, m) => found.push({file, rule, text: clip(line(m.index)), line: lineOf(text, m.index)});
  for (const m of text.matchAll(HEX)) add('colour-literal', m);
  for (const m of text.matchAll(FUNCTION)) add('colour-literal', m);
  if (file.endsWith('.css')) for (const m of text.matchAll(NAMED)) add('colour-literal', m);
  for (const m of text.matchAll(FONT)) add('font-family', m);
  if (file !== BRIDGE_FILE) for (const m of text.matchAll(BRIDGE)) add('token-bridge', m);
  return found;
}

/** Every linted path under web/, relative to root, sorted. */
export function sourceFiles(root = ROOT) {
  const out = [];
  const walk = dir => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (EXT.test(name)) out.push(relative(root, path).split('\\').join('/'));
    }
  };
  if (existsSync(join(root, 'web'))) walk(join(root, 'web'));
  return out.sort();
}

export function lint(root = ROOT) {
  return sourceFiles(root).flatMap(file => lintFile(file, readFileSync(join(root, file), 'utf8')));
}

const key = f => JSON.stringify([f.file, f.rule, f.text]);
export function tally(findings) {
  const counts = new Map();
  for (const f of findings) counts.set(key(f), (counts.get(key(f)) || 0) + 1);
  return counts;
}
export const readBaseline = text => tally(JSON.parse(text).entries.flatMap(e => Array.from({length: e.count || 1}, () => e)));

export function formatBaseline(counts) {
  const entries = [...counts].map(([k, count]) => { const [file, rule, text] = JSON.parse(k); return count > 1 ? {file, rule, text, count} : {file, rule, text}; })
    .sort((a, b) => a.file.localeCompare(b.file) || a.rule.localeCompare(b.rule) || a.text.localeCompare(b.text));
  const note = 'Literals that predate the token lint (scripts/check_tokens.mjs). This list only shrinks: replace the literal with a var(--…) token, then run `node scripts/check_tokens.mjs --update`. Never add entries.';
  const body = entries.map((e, i) => '  ' + JSON.stringify(e) + (i < entries.length - 1 ? ',' : '') + '\n').join('');
  return `{\n "note": ${JSON.stringify(note)},\n "entries": [\n${body} ]\n}\n`;
}

/** New findings (not covered by the baseline) and stale entries (no longer occurring). */
export function compare(current, baseline) {
  const added = [], stale = [];
  for (const [k, n] of current) if (n > (baseline.get(k) || 0)) added.push(k);
  for (const [k, n] of baseline) if (n > (current.get(k) || 0)) stale.push(k);
  return {added, stale};
}

/** Keys whose count grew compared with `previous` (the base ref's baseline). */
export const grown = (baseline, previous) => [...baseline].filter(([k, n]) => n > (previous.get(k) || 0)).map(([k]) => k);

function main(argv) {
  const update = argv.includes('--update');
  const baseRef = argv.includes('--base') ? argv[argv.indexOf('--base') + 1] : null;
  const findings = lint(), current = tally(findings);
  const baseline = readBaseline(readFileSync(join(ROOT, BASELINE), 'utf8'));
  const {added, stale} = compare(current, baseline);
  const list = keys => keys.map(k => { const [file, rule, text] = JSON.parse(k); return `  ${file}:${findings.find(f => key(f) === k)?.line ?? '?'} [${rule}] ${text}`; }).join('\n');
  const errors = [];
  if (added.length) errors.push(`${added.length} new finding(s). Use var(--…) from ${TOKENS_FILE}; read tokens into JavaScript only through ${BRIDGE_FILE}. Do not add these to ${BASELINE}.\n${list(added)}`);
  if (stale.length && update && !added.length) {
    writeFileSync(join(ROOT, BASELINE), formatBaseline(current));
    console.log(`Token lint: removed ${stale.length} fixed entr${stale.length === 1 ? 'y' : 'ies'} from ${BASELINE}.`);
  } else if (stale.length) errors.push(`${stale.length} baseline entr${stale.length === 1 ? 'y' : 'ies'} no longer occur; the baseline only shrinks, so run node scripts/check_tokens.mjs --update:\n${list(stale)}`);
  if (baseRef) {
    let previous = null;
    try { previous = execFileSync('git', ['show', `${baseRef}:${BASELINE}`], {cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}); }
    catch { console.log(`Token lint: ${BASELINE} does not exist at ${baseRef}; nothing to compare.`); }
    const more = previous === null ? [] : grown(baseline, readBaseline(previous));
    if (more.length) errors.push(`${BASELINE} has more entries than at ${baseRef}; the baseline only shrinks:\n${list(more)}`);
  }
  if (errors.length) { for (const e of errors) console.error(`Token lint: ${e}`); process.exit(1); }
  const total = [...baseline.values()].reduce((a, b) => a + b, 0);
  console.log(`Token lint passed: ${sourceFiles().length} files, ${findings.length} finding(s), all in the baseline (${total} entr${total === 1 ? 'y' : 'ies'} left to fix).`);
}

if (process.argv[1] && relative(process.argv[1], fileURLToPath(import.meta.url)) === '') main(process.argv.slice(2));
