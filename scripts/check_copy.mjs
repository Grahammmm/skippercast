#!/usr/bin/env node
// Copy lint (P4-04, guide §5.8): user-facing text should lead with the answer
// and keep limitations and method notes inside disclosures.
//
// Rules, over the app's pages (dist/*.html), browser modules (dist/*.js) and
// client TypeScript (web/):
//   consecutive-not  two consecutive sentences that both contain "not";
//   method-name      GFS, ECMWF, MLLW or "datum" outside a disclosure.
// A disclosure is the body of a <details> (not its <summary>), a confidence
// badge's why (class "confidence-why"), web/disclaimers.ts, or a page that is
// itself the full disclosure (sources and research pages allow method names;
// the legal pages are skipped entirely: their wording belongs to the owner).
//
// Existing copy is listed in scripts/copy-lint-baseline.json so CI passes
// today. The baseline only shrinks:
//   - a finding not in the baseline fails (fix the copy or move it into a
//     disclosure; do not add it to the baseline);
//   - a baseline entry that no longer occurs fails until it is removed, so
//     every fix shrinks the file (`--update` removes them; it never adds);
//   - `--base <git-ref>` fails if the baseline has an entry the baseline at
//     that ref did not (CI passes the pull request's base branch).
//
//   node scripts/check_copy.mjs                 check
//   node scripts/check_copy.mjs --update        drop fixed entries from the baseline
//   node scripts/check_copy.mjs --base origin/main
import {execFileSync} from 'node:child_process';
import {readFileSync, readdirSync, writeFileSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

// COPY_LINT_ROOT points the lint at another tree (the tests use a temporary one).
export const ROOT = process.env.COPY_LINT_ROOT || fileURLToPath(new URL('..', import.meta.url));
export const BASELINE = 'scripts/copy-lint-baseline.json';

/** Pages skipped entirely (legal text, owned by the owner and counsel). */
export const LEGAL_PAGES = new Set(['dist/terms.html', 'dist/privacy.html', 'dist/licenses.html']);
/** Pages that are themselves the "how we know" disclosure: method names allowed. */
export const DISCLOSURE_PAGES = new Set(['dist/sources.html', 'dist/species-research.html', 'dist/commercial-ais.html']);
/** Modules whose strings are disclosures by definition. */
// web/confidence.ts builds the badges' why text, shown only when a badge is opened.
export const DISCLOSURE_MODULES = new Set(['web/disclaimers.ts', 'web/confidence.ts']);
/**
 * Generated from regions/ and catalog/ (region notes, research_only_note,
 * coverage reasons): data wording owned by the data pipeline, not app copy.
 */
export const GENERATED_FILES = new Set(['dist/region-default.js']);
/**
 * A sentence that states a limitation is a caveat. Method names inside a caveat
 * ("source datum is unverified") are exempt, so the lint never pushes authors
 * to hide or drop a datum or model caveat to get green.
 */
export const CAVEAT = /\b(?:not|no|unverified|unresolved|unknown|unavailable|uncertain(?:ty)?|verify|validate|research-only|nominal|estimated|provisional)\b/i;

const BLOCK = new Set(['p', 'div', 'section', 'article', 'aside', 'header', 'footer', 'main', 'nav', 'li', 'ul', 'ol',
  'dl', 'dt', 'dd', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'summary', 'details', 'table', 'tr', 'td', 'th', 'caption',
  'figure', 'figcaption', 'label', 'option', 'select', 'button', 'form', 'fieldset', 'legend', 'br', 'hr', 'dialog',
  'title', 'blockquote', 'pre', 'textarea', 'input', 'img', 'canvas', 'svg', 'body', 'head', 'html', 'meta', 'link']);
const SKIP_CONTENT = new Set(['script', 'style', 'svg', 'code', 'pre']);

const NOT = /\bnot\b/i;
const METHOD = /\b(?:GFS|ECMWF|MLLW)\b|\bdatums?\b/i;
const ACRONYM = /\b(?:GFS|ECMWF|MLLW)\b/;

/** Split text into sentences (after . ! ? followed by space and a capital, digit or quote). */
export function sentences(text) {
  return text.split(/(?<=[.!?])\s+(?=[A-Z0-9“"(‘'])/).map(s => s.trim()).filter(Boolean);
}

const words = text => (text.match(/[A-Za-z][A-Za-z'’-]*/g) || []).length;
const normal = text => text.replace(/\s+/g, ' ').trim();
const clip = text => (text.length > 200 ? text.slice(0, 197) + '...' : text);

/** True for text that reads as prose shown to people, not code, markup or identifiers. */
export function isProse(text) {
  const t = text.trim();
  if (words(t) < 3 || !/[a-z]{2,}\s+[a-z]{2,}/i.test(t)) return false;
  if (/^[\w.-]+\/[\w./-]*$/.test(t) || /^https?:\/\//.test(t)) return false;
  if (/[{};]\s*$|=>|\bfunction\b|\bconst\b|\breturn\b|===|!==|&&|\|\|/.test(t)) return false;
  return true;
}

/**
 * Walk HTML (a page, or the concatenated literals of a module) and return
 * text units: runs of text between block-level tags, with whether they sit in
 * a disclosure. `state` carries open <details>/why depth across calls.
 */
export function htmlUnits(html, state = {details: [], why: 0, skip: 0, stack: []}, offset = 0) {
  const units = [];
  let text = '', start = -1;
  const flush = () => {
    const t = normal(text.replace(/&nbsp;|&#160;/g, ' ').replace(/&amp;/g, '&').replace(/&[a-z]+;|&#\d+;/g, ' '));
    if (t) units.push({text: t, index: offset + start, disclosure: state.details.some(d => !d.summary) || state.why > 0});
    text = ''; start = -1;
  };
  const tag = /<\/?([a-zA-Z][\w-]*)\b((?:[^>"']|"[^"]*"|'[^']*')*)>|<!--[\s\S]*?-->/g;
  let last = 0;
  for (const m of html.matchAll(tag)) {
    if (state.skip === 0 && m.index > last) {
      if (start < 0) start = last;
      text += html.slice(last, m.index);
    }
    last = m.index + m[0].length;
    if (!m[1]) continue;
    const name = m[1].toLowerCase(), closing = m[0][1] === '/', attrs = m[2] || '';
    if (SKIP_CONTENT.has(name)) {
      if (!/\/\s*$/.test(attrs)) state.skip = Math.max(0, state.skip + (closing ? -1 : 1));
      flush();
      continue;
    }
    if (BLOCK.has(name)) flush();
    if (name === 'details') { if (closing) state.details.pop(); else state.details.push({summary: false}); }
    if (name === 'summary' && state.details.length) state.details.at(-1).summary = !closing;
    // A badge's why is a disclosure even when it is an inline element.
    if (!closing && /class\s*=\s*["'][^"']*\bconfidence-why\b/.test(attrs)) { flush(); state.why++; state.stack.push(name); }
    else if (closing && state.stack.length && state.stack.at(-1) === name) { flush(); state.stack.pop(); state.why = Math.max(0, state.why - 1); }
  }
  if (state.skip === 0 && last < html.length) { if (start < 0) start = last; text += html.slice(last); }
  flush();
  return units;
}

/**
 * String and template literals in JavaScript/TypeScript source, in order,
 * with their offsets. Template `${...}` expressions become " X " and are
 * scanned for nested literals. Regular expressions and comments are skipped.
 */
export function literals(source) {
  const out = [];
  let i = 0;
  const n = source.length;
  const regexAllowed = () => {
    let j = i - 1;
    while (j >= 0 && /\s/.test(source[j])) j--;
    if (j < 0) return true;
    if (/[(,=:[!&|?{};+\-*%<>~^]/.test(source[j])) return true;
    return /\b(?:return|typeof|case|in|of|delete|void|throw|new|yield|await)$/.test(source.slice(Math.max(0, j - 10), j + 1));
  };
  // The character an escape sequence at i stands for; advances past it.
  function escape() {
    const next = source[i + 1];
    const hex = next === 'u' ? (source[i + 2] === '{' ? source.slice(i + 3, source.indexOf('}', i + 3)) : source.slice(i + 2, i + 6))
      : next === 'x' ? source.slice(i + 2, i + 4) : null;
    if (hex && /^[0-9a-fA-F]+$/.test(hex)) {
      i += next === 'u' && source[i + 2] === '{' ? hex.length + 4 : hex.length + 2;
      return String.fromCodePoint(parseInt(hex, 16));
    }
    i += 2;
    return next === 'n' ? '\n' : next === 't' ? ' ' : next ?? '';
  }
  function quoted(q) {
    const begin = i++;
    let value = '';
    while (i < n && source[i] !== q) {
      if (source[i] === '\\') { value += escape(); continue; }
      if (source[i] === '\n') break;
      value += source[i++];
    }
    i++;
    out.push({value, index: begin});
  }
  function template() {
    const begin = i++;
    let value = '';
    while (i < n && source[i] !== '`') {
      if (source[i] === '\\') { value += escape(); continue; }
      if (source[i] === '$' && source[i + 1] === '{') {
        i += 2; value += ' X ';
        code('}');
        i++;
        continue;
      }
      value += source[i++];
    }
    i++;
    out.push({value, index: begin});
  }
  function code(until) {
    let depth = 0;
    while (i < n) {
      const c = source[i];
      if (until && c === until && depth === 0) return;
      if (c === '{') depth++;
      else if (c === '}') depth--;
      if (c === '/' && source[i + 1] === '/') { while (i < n && source[i] !== '\n') i++; continue; }
      if (c === '/' && source[i + 1] === '*') { const end = source.indexOf('*/', i + 2); i = end < 0 ? n : end + 2; continue; }
      if (c === '"' || c === "'") { quoted(c); continue; }
      if (c === '`') { template(); continue; }
      if (c === '/' && regexAllowed()) {
        i++;
        let inClass = false;
        while (i < n && source[i] !== '\n') {
          if (source[i] === '\\') { i += 2; continue; }
          if (source[i] === '[') inClass = true;
          else if (source[i] === ']') inClass = false;
          else if (source[i] === '/' && !inClass) break;
          i++;
        }
        i++;
        continue;
      }
      i++;
    }
  }
  code(null);
  return out.sort((a, b) => a.index - b.index);
}

/** JSX text between tags in a .tsx file (outside `{...}`), as literals. */
export function jsxText(source) {
  return [...source.matchAll(/>([^<>{}]*[A-Za-z][^<>{}]*)</g)].map(m => ({value: m[1], index: m.index + 1}));
}

/** Findings in one unit of text. */
export function unitFindings(text, {disclosure = false, methodsAllowed = false} = {}) {
  const found = [];
  const list = sentences(text);
  for (let k = 1; k < list.length; k++)
    if (NOT.test(list[k - 1]) && NOT.test(list[k])) found.push({rule: 'consecutive-not', text: clip(`${list[k - 1]} ${list[k]}`)});
  if (!disclosure && !methodsAllowed)
    for (const s of list) {
      const m = s.match(METHOD);
      // Lower-case acronyms are identifiers (gfs025), not copy.
      if (m && (/datum/i.test(m[0]) || ACRONYM.test(s)) && !CAVEAT.test(s)) found.push({rule: 'method-name', text: clip(s)});
    }
  return found;
}

const lineOf = (source, index) => source.slice(0, index).split('\n').length;

/** Findings for one repository file (path relative to ROOT, forward slashes). */
export function lintFile(path, source) {
  if (LEGAL_PAGES.has(path) || GENERATED_FILES.has(path)) return [];
  const methodsAllowed = DISCLOSURE_PAGES.has(path) || DISCLOSURE_MODULES.has(path);
  const findings = [];
  const add = (units) => {
    for (const u of units) {
      if (!isProse(u.text)) continue;
      for (const f of unitFindings(u.text, {disclosure: u.disclosure, methodsAllowed}))
        findings.push({file: path, line: lineOf(source, Math.max(0, u.index)), ...f});
    }
  };
  if (path.endsWith('.html')) { add(htmlUnits(source)); return findings; }
  const state = {details: [], why: 0, skip: 0, stack: []};
  const items = [...literals(source), ...(path.endsWith('.tsx') ? jsxText(source) : [])].sort((a, b) => a.index - b.index);
  for (const item of items) {
    // Messages for developers, not people using the app.
    if (/(?:console\.\w+|Error)\(\s*$/.test(source.slice(Math.max(0, item.index - 40), item.index))) continue;
    if (/^\s*(?:import|export)\b[^;\n]*$/.test(source.slice(source.lastIndexOf('\n', item.index) + 1, item.index))) continue;
    add(htmlUnits(item.value, state, item.index));
  }
  return findings;
}

/** The files the lint reads: pages and modules shipped to the browser. */
export function copyFiles(root = ROOT) {
  const list = [];
  for (const name of readdirSync(join(root, 'dist')).sort())
    if (/\.(html|js)$/.test(name) && !/\.min\.js$/.test(name)) list.push(`dist/${name}`);
  const walk = dir => {
    for (const entry of readdirSync(join(root, dir), {withFileTypes: true}).sort((a, b) => a.name.localeCompare(b.name))) {
      const path = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(path);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith('.d.ts')) list.push(path);
    }
  };
  walk('web');
  return list;
}

export function lint(root = ROOT) {
  return copyFiles(root).flatMap(path => lintFile(path, readFileSync(join(root, path), 'utf8')));
}

/** Multiset of finding keys (file, rule, text); line numbers are not part of a key. */
export function tally(findings) {
  const counts = new Map();
  for (const f of findings) {
    const key = JSON.stringify([f.file, f.rule, f.text]);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return counts;
}

export function readBaseline(text) {
  const data = JSON.parse(text);
  return tally(data.entries.flatMap(e => Array.from({length: e.count || 1}, () => e)));
}

export function formatBaseline(counts) {
  const entries = [...counts].map(([key, count]) => {
    const [file, rule, text] = JSON.parse(key);
    return count > 1 ? {file, rule, text, count} : {file, rule, text};
  }).sort((a, b) => a.file.localeCompare(b.file) || a.rule.localeCompare(b.rule) || a.text.localeCompare(b.text));
  // One entry per line, so a fix shows as a one-line deletion.
  const note = 'Copy that predates the copy lint (scripts/check_copy.mjs). This list only shrinks: fix or move copy, then run `node scripts/check_copy.mjs --update`. Never add entries.';
  return `{\n "note": ${JSON.stringify(note)},\n "entries": [\n${entries.map(e => '  ' + JSON.stringify(e)).join(',\n')}\n ]\n}\n`;
}

const groupOf = key => { const [file, rule] = JSON.parse(key); return JSON.stringify([file, rule]); };

/**
 * Compare current findings with the baseline: new findings and stale entries.
 * An edited baselined sentence (a typo fixed, a number changed) shows up as one
 * stale entry and one new finding in the same file under the same rule; those
 * pairs are `replaced`, not `added`, so editing old copy never fails the lint.
 * The count per file and rule still can never grow.
 */
export function compare(current, baseline) {
  let added = [], stale = [];
  for (const [key, count] of current) if (count > (baseline.get(key) || 0)) added.push({key, count: count - (baseline.get(key) || 0)});
  for (const [key, count] of baseline) if (count > (current.get(key) || 0)) stale.push({key, count: count - (current.get(key) || 0)});
  const replaced = [];
  const spare = new Map();
  for (const s of stale) spare.set(groupOf(s.key), (spare.get(groupOf(s.key)) || 0) + s.count);
  added = added.flatMap(a => {
    const g = groupOf(a.key), free = Math.min(spare.get(g) || 0, a.count);
    if (free) { spare.set(g, spare.get(g) - free); replaced.push({key: a.key, count: free}); }
    return a.count > free ? [{key: a.key, count: a.count - free}] : [];
  });
  return {added, stale, replaced};
}

/** Count of entries per file and rule. */
function groups(counts) {
  const out = new Map();
  for (const [key, count] of counts) out.set(groupOf(key), (out.get(groupOf(key)) || 0) + count);
  return out;
}

/** File and rule groups whose entry count grew compared with `previous` (the base's baseline). */
export function grown(baseline, previous) {
  const now = groups(baseline), before = groups(previous), out = [];
  for (const [group, count] of now) if (count > (before.get(group) || 0)) out.push({key: group, count: count - (before.get(group) || 0)});
  return out;
}

function main(argv) {
  const update = argv.includes('--update');
  const baseRef = argv.includes('--base') ? argv[argv.indexOf('--base') + 1] : null;
  const findings = lint();
  const current = tally(findings);
  const baseline = readBaseline(readFileSync(join(ROOT, BASELINE), 'utf8'));
  const {added, stale, replaced} = compare(current, baseline);
  let failed = false;
  const show = key => { const [file, rule, text] = JSON.parse(key); return {file, rule, text}; };
  if (added.length) {
    failed = true;
    console.error(`Copy lint: ${added.length} new finding(s). Lead with the answer; put limitations and method names (GFS, ECMWF, MLLW, datum) in a badge's why or a <details> disclosure, and never write two "not" sentences in a row. Do not add these to ${BASELINE}.`);
    for (const {key} of added) {
      const f = show(key), at = findings.find(x => x.file === f.file && x.rule === f.rule && x.text === f.text);
      console.error(`  ${f.file}:${at?.line ?? '?'} [${f.rule}] ${f.text}`);
    }
  }
  if (stale.length) {
    if (update && !added.length) {
      writeFileSync(join(ROOT, BASELINE), formatBaseline(current));
      console.log(`Copy lint: removed ${stale.length} fixed entr${stale.length === 1 ? 'y' : 'ies'} from ${BASELINE}.`);
    } else {
      failed = true;
      const edited = replaced.length ? ` (${replaced.length} edited in place; --update records the new wording)` : '';
      console.error(`Copy lint: ${stale.length} baseline entr${stale.length === 1 ? 'y no longer occurs' : 'ies no longer occur'}${edited}; the baseline only shrinks, so run node scripts/check_copy.mjs --update:`);
      for (const {key} of stale) { const f = show(key); console.error(`  ${f.file} [${f.rule}] ${f.text}`); }
    }
  }
  if (baseRef) {
    let previous = null;
    try { previous = execFileSync('git', ['show', `${baseRef}:${BASELINE}`], {cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore']}); }
    catch { console.log(`Copy lint: ${BASELINE} does not exist at ${baseRef}; nothing to compare.`); }
    if (previous !== null) {
      const more = grown(baseline, readBaseline(previous));
      if (more.length) {
        failed = true;
        console.error(`Copy lint: ${BASELINE} has more entries than at ${baseRef} for ${more.length} file/rule pair(s); the baseline only shrinks:`);
        for (const {key, count} of more) { const [file, rule] = JSON.parse(key); console.error(`  ${file} [${rule}] +${count}`); }
      }
    }
  }
  if (failed) process.exit(1);
  const total = [...baseline.values()].reduce((a, b) => a + b, 0);
  console.log(`Copy lint passed: ${copyFiles().length} files, ${findings.length} finding(s), all in the baseline (${total} entr${total === 1 ? 'y' : 'ies'} left to fix).`);
}

if (process.argv[1] && relative(process.argv[1], fileURLToPath(import.meta.url)) === '') main(process.argv.slice(2));
