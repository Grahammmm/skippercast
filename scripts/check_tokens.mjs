#!/usr/bin/env node
// Token lint (FE-02, docs/plans/front-end/design.md § 5): v2 client code
// reads every colour and font through var(--…) from web/tokens.css.
// Rules over web/**/*.{css,ts,tsx} except the tokens file, comments ignored:
//   colour-literal  hex, rgb()/rgba()/hsl()/hsla(), or (CSS only: "black
//                   rockfish" is copy) a named colour as a declaration value;
//   font-family     a font-family declaration or fontFamily style property;
//   token-bridge    getPropertyValue('--…') outside web/map/palette.ts, the
//                   one allowed bridge from CSS to the map and canvas code.
// packages/coast/** (FE-76, design § 3A.4) is a second scope with the same
// rules, except that a literal may stand as the fallback of a
// var(--coast-…, literal) (v1 pages render it until FE-61) or in
// packages/coast/src/palette.ts, and @font-face descriptors are allowed.
// Each scope's baseline only shrinks (check_copy's contract): a new finding
// fails; a stale entry fails until `--update` drops it; `--base <git-ref>`
// fails if the baseline grew since that ref.
import {execFileSync} from 'node:child_process';
import {existsSync, readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

// TOKEN_LINT_ROOT points the lint at another tree (the tests use a temporary one).
export const ROOT = process.env.TOKEN_LINT_ROOT || fileURLToPath(new URL('..', import.meta.url));
export const BASELINE = 'scripts/token-lint-baseline.json';
export const TOKENS_FILE = 'web/tokens.css';
export const BRIDGE_FILE = 'web/map/palette.ts';
export const COAST_BASELINE = 'scripts/token-lint-coast-baseline.json';
export const COAST_PALETTE_FILE = 'packages/coast/src/palette.ts';
/** Linted trees, each with its own shrink-only baseline. */
export const SCOPES = [{dir: 'web', baseline: BASELINE}, {dir: 'packages/coast', baseline: COAST_BASELINE}];

const EXT = /\.(?:css|ts|tsx)$/;
const HEX = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/g;
const FUNCTION = /\b(?:rgb|rgba|hsl|hsla)\(/g;
const NAMED = /:\s*(?:[^;{}]*\s)?(white|black|red|green|blue|yellow|orange|gray|grey|silver|navy|teal|aqua|cyan|magenta|purple|pink|brown)\b/gi;
const FONT = /\bfont-family\s*[:=]|\bfontFamily\b/g;
const BRIDGE = /getPropertyValue\s*\(\s*['"`]--/g;
const COAST_VAR = /var\(\s*--coast-[\w-]+\s*,/g;
const FONT_FACE = /@font-face\s*\{[^}]*\}/g;

const clip = text => (text.length > 120 ? text.slice(0, 117) + '...' : text);
const lineOf = (source, index) => source.slice(0, index).split('\n').length;

/** Source with block comments and whole-line `//` comments blanked (positions kept). */
export function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
    .replace(/^([ \t]*)\/\/[^\n]*/gm, (m, lead) => lead + ' '.repeat(m.length - lead.length));
}

/** [start, end) of each var(--coast-…, fallback) fallback, parentheses balanced. */
function fallbacks(text) {
  const spans = [];
  for (const m of text.matchAll(COAST_VAR)) {
    let depth = 1, i = m.index + m[0].length;
    for (; i < text.length && depth; i++) depth += text[i] === '(' ? 1 : text[i] === ')' ? -1 : 0;
    spans.push([m.index + m[0].length, i - 1]);
  }
  return spans;
}

/** Findings for one file: {file, rule, text, line}. */
export function lintFile(file, source) {
  if (file === TOKENS_FILE || !EXT.test(file)) return [];
  const text = stripComments(source);
  const found = [];
  const coast = file.startsWith('packages/coast/');
  const spans = coast ? [...fallbacks(text), ...[...text.matchAll(FONT_FACE)].map(m => [m.index, m.index + m[0].length])] : [];
  const allowed = i => spans.some(([a, b]) => i >= a && i < b);
  const line = i => text.slice(text.lastIndexOf('\n', i - 1) + 1, text.indexOf('\n', i) < 0 ? undefined : text.indexOf('\n', i)).trim();
  const add = (rule, m, at = m.index) => { if (!allowed(at)) found.push({file, rule, text: clip(line(at)), line: lineOf(text, at)}); };
  const colours = file !== COAST_PALETTE_FILE;
  if (colours) for (const m of text.matchAll(HEX)) add('colour-literal', m);
  if (colours) for (const m of text.matchAll(FUNCTION)) add('colour-literal', m);
  if (colours && file.endsWith('.css')) for (const m of text.matchAll(NAMED)) add('colour-literal', m, m.index + m[0].length - m[1].length);
  for (const m of text.matchAll(FONT)) if (!(coast && /^[\s:='"`]*var\(\s*--coast-/.test(text.slice(m.index + m[0].length, m.index + m[0].length + 40)))) add('font-family', m);
  if (file !== BRIDGE_FILE) for (const m of text.matchAll(BRIDGE)) add('token-bridge', m);
  return found;
}

/** Every linted path under `dir` (web/ by default), relative to root, sorted. */
export function sourceFiles(root = ROOT, dir = 'web') {
  const out = [];
  const walk = dir => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (EXT.test(name)) out.push(relative(root, path).split('\\').join('/'));
    }
  };
  if (existsSync(join(root, dir))) walk(join(root, dir));
  return out.sort();
}

export function lint(root = ROOT, dir = 'web') {
  return sourceFiles(root, dir).flatMap(file => lintFile(file, readFileSync(join(root, file), 'utf8')));
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

/** Errors for one scope; logs its pass line when there are none. */
function checkScope({dir, baseline: file}, update, baseRef) {
  if (!existsSync(join(ROOT, dir))) return [];
  const findings = lint(ROOT, dir), current = tally(findings);
  const baseline = existsSync(join(ROOT, file)) ? readBaseline(readFileSync(join(ROOT, file), 'utf8')) : new Map();
  const {added, stale} = compare(current, baseline);
  const list = keys => keys.map(k => { const [path, rule, text] = JSON.parse(k); return `  ${path}:${findings.find(f => key(f) === k)?.line ?? '?'} [${rule}] ${text}`; }).join('\n');
  const errors = [];
  const fix = dir === 'web' ? `Use var(--…) from ${TOKENS_FILE}; read tokens into JavaScript only through ${BRIDGE_FILE}.`
    : `Write var(--coast-…, literal) and map the role in packages/coast/tokens-bridge.css; renderer colours belong in ${COAST_PALETTE_FILE}.`;
  if (added.length) errors.push(`${added.length} new finding(s). ${fix} Do not add these to ${file}.\n${list(added)}`);
  if (stale.length && update && !added.length) {
    writeFileSync(join(ROOT, file), formatBaseline(current));
    console.log(`Token lint: removed ${stale.length} fixed entr${stale.length === 1 ? 'y' : 'ies'} from ${file}.`);
  } else if (stale.length) errors.push(`${stale.length} baseline entr${stale.length === 1 ? 'y' : 'ies'} no longer occur; the baseline only shrinks, so run node scripts/check_tokens.mjs --update:\n${list(stale)}`);
  if (baseRef) {
    let previous = null;
    try { previous = execFileSync('git', ['show', `${baseRef}:${file}`], {cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}); }
    catch { console.log(`Token lint: ${file} does not exist at ${baseRef}; nothing to compare.`); }
    const more = previous === null ? [] : grown(baseline, readBaseline(previous));
    if (more.length) errors.push(`${file} has more entries than at ${baseRef}; the baseline only shrinks:\n${list(more)}`);
  }
  const total = [...baseline.values()].reduce((a, b) => a + b, 0);
  if (!errors.length) console.log(`Token lint passed: ${sourceFiles(ROOT, dir).length} files, ${findings.length} finding(s), all in the baseline (${total} entr${total === 1 ? 'y' : 'ies'} left to fix) [${dir}].`);
  return errors;
}

function main(argv) {
  const update = argv.includes('--update');
  const baseRef = argv.includes('--base') ? argv[argv.indexOf('--base') + 1] : null;
  const errors = SCOPES.flatMap(scope => checkScope(scope, update, baseRef));
  if (errors.length) { for (const e of errors) console.error(`Token lint: ${e}`); process.exit(1); }
}

if (process.argv[1] && relative(process.argv[1], fileURLToPath(import.meta.url)) === '') main(process.argv.slice(2));
