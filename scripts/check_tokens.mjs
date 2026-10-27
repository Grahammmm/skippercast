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
import {createHash} from 'node:crypto';
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
/** Linted source scopes; existing baselines may only shrink. */
// These dist/ stylesheets are source inputs, not generated client assets.
// Auxiliary CSS has no baseline: findings must be fixed in its source.
export const SCOPES = [{dir: 'web', baseline: BASELINE}, {dir: 'packages/coast', baseline: COAST_BASELINE},
  {dir: 'dist/advisor', baseline: null, cssOnly: true},
  {dir: 'dist/coast-readable.css', baseline: null, cssOnly: true}];

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
export function sourceFiles(root = ROOT, dir = 'web', cssOnly = false) {
  const out = [];
  const walk = dir => {
    if (!statSync(dir).isDirectory()) {
      if ((cssOnly ? /\.css$/ : EXT).test(dir)) out.push(relative(root, dir).split('\\').join('/'));
      return;
    }
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if ((cssOnly ? /\.css$/ : EXT).test(name)) out.push(relative(root, path).split('\\').join('/'));
    }
  };
  if (existsSync(join(root, dir))) walk(join(root, dir));
  return out.sort();
}

export function lint(root = ROOT, dir = 'web', cssOnly = false) {
  return sourceFiles(root, dir, cssOnly).flatMap(file => lintFile(file, readFileSync(join(root, file), 'utf8')));
}

// N05 source-only seam: callers supply a bounded source map. This helper does
// not enumerate consumers, read files, or participate in checkScope/baselines.
const COAST_COVERAGE_BRIDGE = 'packages/coast/tokens-bridge.css';
const COAST_COVERAGE_PANEL = 'packages/coast/panel.css';
const COAST_EXPLICIT_FALLBACKS = new Set([
  '--coast-bathy-0', '--coast-bathy-1', '--coast-bathy-2', '--coast-bathy-3',
  '--coast-bathy-4', '--coast-bathy-5', '--coast-bathy-6',
  '--coast-current-0', '--coast-current-1', '--coast-current-2',
  '--coast-current-3', '--coast-current-4', '--coast-current-5',
  '--coast-reef-0', '--coast-reef-1', '--coast-reef-2', '--coast-reef-3', '--coast-reef-4',
  '--coast-reef-fit-0', '--coast-reef-fit-1',
  '--coast-shore-0', '--coast-shore-1', '--coast-shore-2',
  '--coast-wave-0', '--coast-wave-1', '--coast-wave-2',
]);

/**
 * Classify each CSS var(--coast-*) occurrence in {relativePath: source}.
 * Only the canonical bridge's existing opt-in selector pair supplies declarations.
 * Comments follow stripComments' limited contract; this is a static textual
 * helper, not a general CSS/JS parser or a claim about loading/the CSS cascade.
 * Returns {uses, findings}; findings are unresolved occurrences in path/position
 * order, independent of all literal exemptions, baseline entries and --update.
 */
export function collectCoastRoleCoverage(sources) {
  const files = Object.keys(sources)
    .filter(file => file.startsWith('packages/coast/') && EXT.test(file)).sort();
  const texts = new Map(files.map(file => [file, stripComments(sources[file])]));
  const declared = new Set();
  const optIn = '[data-coast-theme="tokens"],:host([data-coast-theme="tokens"])';
  for (const block of (texts.get(COAST_COVERAGE_BRIDGE) || '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (block[1].replace(/\s+/g, '') !== optIn) continue;
    for (const declaration of block[2].matchAll(/(?:^|;)\s*(--coast-[\w-]+)\s*:/g)) declared.add(declaration[1]);
  }
  const uses = [];
  for (const [file, text] of texts) {
    for (const match of text.matchAll(/var\(\s*(--coast-[\w-]+)\s*(?=[,)])/g)) {
      const afterRole = match.index + match[0].length;
      let depth = 1, end = afterRole;
      for (; end < text.length && depth; end++) depth += text[end] === '(' ? 1 : text[end] === ')' ? -1 : 0;
      const hasFallback = text[afterRole] === ',' && depth === 0 && text.slice(afterRole + 1, end - 1).trim().length > 0;
      const role = match[1];
      const classification = declared.has(role) ? 'declared'
        : file === COAST_COVERAGE_PANEL && hasFallback && COAST_EXPLICIT_FALLBACKS.has(role) ? 'explicitfallback' : 'unresolved';
      const index = match.index;
      const lineEnd = text.indexOf('\n', index);
      uses.push({file, line: lineOf(text, index), column: index - text.lastIndexOf('\n', index - 1),
        role, classification, hasFallback,
        text: clip(text.slice(text.lastIndexOf('\n', index - 1) + 1, lineEnd < 0 ? undefined : lineEnd).trim())});
    }
  }
  const findings = uses.filter(use => use.classification === 'unresolved')
    .map(({file, line, role, text}) => ({file, line, rule: 'coast-role-undeclared', role, text}));
  return {uses, findings};
}


// Approved retained inventory is the coverage boundary, not a license to scan
// arbitrary consumers or grow the literal baselines. Any changed source fails
// closed until a separately reviewed inventory delta is supplied.
export const COAST_INVENTORY_SHA256 = 'a7530a98af1aff484b4b81059378569cd0266b90969bf060b2887e6f24d0e8eb';
const sha256 = text => createHash('sha256').update(text).digest('hex');

/** Evaluate only pinned occurrence locations. This does not discover uses.
 * Caller authenticates the inventory; the CLI pins its complete serialized hash.
 * Existing helper alone supplies declaration/fallback classification semantics.
 */
export function checkCoastInventory(sources, inventory) {
  const failures = [], uses = [], sourceHashes = {};
  try {
    const evidence = [...inventory.production_inventory.evidence,
      inventory.evidence.find(e => e.path === COAST_COVERAGE_BRIDGE)];
    const paths = new Set();
    for (const entry of evidence) {
      if (!entry || !/^packages\/coast\/[\w/.-]+\.(?:css|ts|tsx)$/.test(entry.path) || entry.path.split('/').includes('..') || paths.has(entry.path)) throw Error('Invalid/duplicate inventory source');
      paths.add(entry.path);
      if (typeof sources[entry.path] !== 'string') throw Error(`Missing inventory source: ${entry.path}`);
      sourceHashes[entry.path] = sha256(sources[entry.path]);
      if (sourceHashes[entry.path] !== entry.sha256) failures.push({file: entry.path, rule: 'coast-inventory-stale', expected: entry.sha256, actual: sourceHashes[entry.path]});
    }
    if (failures.length) return {failures, uses, sourceHashes};
    for (const item of inventory.production_used_role_matrix) {
      for (const occurrence of item.occurrences) {
        const {file, line, column} = occurrence;
        if (!paths.has(file) || !Number.isSafeInteger(line) || line < 1 || !Number.isSafeInteger(column) || column < 1) throw Error('Invalid occurrence location');
        const lines = sources[file].split('\n');
        if (line > lines.length || column > lines[line - 1].length) throw Error(`Invalid occurrence: ${file}:${line}:${column}`);
        const offset = lines.slice(0, line - 1).reduce((n, text) => n + text.length + 1, 0) + column - 1;
        const tail = sources[file].slice(offset);
        const start = tail.match(/^var\(\s*(--coast-[\w-]+)\s*(?=[,)])/);
        if (!start || start[1] !== item.role) throw Error(`Inventory occurrence mismatch: ${file}:${line}:${column} ${item.role}`);
        let depth = 1, end = start[0].length;
        for (; end < tail.length && depth; end++) depth += tail[end] === '(' ? 1 : tail[end] === ')' ? -1 : 0;
        if (depth) throw Error(`Unclosed inventory occurrence: ${file}:${line}:${column}`);
        const classified = collectCoastRoleCoverage({[COAST_COVERAGE_BRIDGE]: sources[COAST_COVERAGE_BRIDGE], [file]: tail.slice(0, end)}).uses
          .find(use => use.file === file && use.line === 1 && use.column === 1);
        if (!classified || classified.role !== item.role || classified.hasFallback !== occurrence.has_fallback) throw Error(`Unsupported inventory occurrence: ${file}:${line}:${column}`);
        const use = {...classified, line, column};
        uses.push(use);
        if (use.classification === 'unresolved') failures.push({file, line, column, role: item.role, rule: 'coast-role-undeclared'});
        const expected = item.classification === 'intentionalfallback' ? 'explicitfallback' : item.classification;
        if (use.classification !== expected && use.classification !== 'unresolved') failures.push({file, line, column, role: item.role, rule: 'coast-inventory-classification-changed'});
      }
    }
  } catch (error) {
    failures.push({rule: 'coast-inventory-resolution-error', reason: error.message});
  }
  return {failures, uses, sourceHashes};
}

/** Dedicated production gate; no baseline mutation or whole-consumer rescan. */
export function runCoastInventoryGate(root, inventoryText) {
  if (sha256(inventoryText) !== COAST_INVENTORY_SHA256) return {failures: [{rule: 'coast-inventory-unapproved', reason: 'Retained inventory serialization hash differs'}], uses: []};
  try {
    const inventory = JSON.parse(inventoryText);
    const paths = [...inventory.production_inventory.evidence.map(e => e.path), COAST_COVERAGE_BRIDGE];
    const sources = Object.fromEntries(paths.map(file => [file, readFileSync(join(root, file), 'utf8')]));
    return {...checkCoastInventory(sources, inventory), inventorySha256: COAST_INVENTORY_SHA256,
      inventoryRevision: inventory.production_inventory.revision, scope: 'retained-occurrences-only'};
  } catch (error) {
    return {failures: [{rule: 'coast-inventory-resolution-error', reason: error.message}], uses: []};
  }
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
function checkScope({dir, baseline: file, cssOnly = false}, update, baseRef) {
  if (!existsSync(join(ROOT, dir))) return [];
  const findings = lint(ROOT, dir, cssOnly), current = tally(findings);
  const baseline = file && existsSync(join(ROOT, file)) ? readBaseline(readFileSync(join(ROOT, file), 'utf8')) : new Map();
  const {added, stale} = compare(current, baseline);
  const list = keys => keys.map(k => { const [path, rule, text] = JSON.parse(k); return `  ${path}:${findings.find(f => key(f) === k)?.line ?? '?'} [${rule}] ${text}`; }).join('\n');
  const errors = [];
  const fix = !dir.startsWith('packages/coast') ? `Use var(--…) from ${TOKENS_FILE}; read tokens into JavaScript only through ${BRIDGE_FILE}.`
    : `Write var(--coast-…, literal) and map the role in packages/coast/tokens-bridge.css; renderer colours belong in ${COAST_PALETTE_FILE}.`;
  if (added.length) errors.push(`${added.length} new finding(s). ${fix} ${file ? `Do not add these to ${file}.` : 'This source CSS has no baseline; fix the source.'}\n${list(added)}`);
  if (stale.length && update && !added.length) {
    writeFileSync(join(ROOT, file), formatBaseline(current));
    console.log(`Token lint: removed ${stale.length} fixed entr${stale.length === 1 ? 'y' : 'ies'} from ${file}.`);
  } else if (stale.length) errors.push(`${stale.length} baseline entr${stale.length === 1 ? 'y' : 'ies'} no longer occur; the baseline only shrinks, so run node scripts/check_tokens.mjs --update:\n${list(stale)}`);
  if (baseRef && file) {
    let previous = null;
    try { previous = execFileSync('git', ['show', `${baseRef}:${file}`], {cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}); }
    catch { console.log(`Token lint: ${file} does not exist at ${baseRef}; nothing to compare.`); }
    const more = previous === null ? [] : grown(baseline, readBaseline(previous));
    if (more.length) errors.push(`${file} has more entries than at ${baseRef}; the baseline only shrinks:\n${list(more)}`);
  }
  const total = [...baseline.values()].reduce((a, b) => a + b, 0);
  if (!errors.length) console.log(`Token lint passed: ${sourceFiles(ROOT, dir, cssOnly).length} files, ${findings.length} finding(s), all in the baseline (${total} entr${total === 1 ? 'y' : 'ies'} left to fix) [${dir}].`);
  return errors;
}

function main(argv) {
  if (argv.includes('--coast-inventory')) {
    if (argv.length !== 2 || argv[0] !== '--coast-inventory' || argv[1].startsWith('--')) {
      console.error('Token coverage: use --coast-inventory <approved-inventory.json> alone; baselines are never updated by this gate.');
      process.exit(1);
    }
    let result;
    try { result = runCoastInventoryGate(ROOT, readFileSync(argv[1], 'utf8')); }
    catch (error) { result = {failures: [{rule: 'coast-inventory-resolution-error', reason: error.message}], uses: []}; }
    console.log(JSON.stringify({...result, uses: undefined, occurrences: result.uses.length,
      declared: result.uses.filter(u => u.classification === 'declared').length,
      intentionalFallback: result.uses.filter(u => u.classification === 'explicitfallback').length}));
    process.exit(result.failures.length ? 1 : 0);
  }
  const update = argv.includes('--update');
  const baseRef = argv.includes('--base') ? argv[argv.indexOf('--base') + 1] : null;
  const errors = SCOPES.flatMap(scope => checkScope(scope, update, baseRef));
  if (errors.length) { for (const e of errors) console.error(`Token lint: ${e}`); process.exit(1); }
}

if (process.argv[1] && relative(process.argv[1], fileURLToPath(import.meta.url)) === '') main(process.argv.slice(2));
