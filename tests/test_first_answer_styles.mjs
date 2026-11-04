// SC2207-11: the first answer's styles (web/app/app.css, the block opened by `SC2207-11: first answer`) come from declared
// tokens only, and every foreground/background pair the block draws is one the existing contrast check already holds.
// Offline: it reads the committed sheets and plants synthetic copies; it rewrites nothing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PAIRS_V2, check, contrast, themes} from '../scripts/check_contrast.mjs';

const read = p => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8');
const appCss = read('web/app/app.css'), tokensCss = read('web/tokens.css'), uiCss = read('web/ui/ui.css');

const START = '/* SC2207-11: first answer';
const END = '/* end SC2207-11 */';
/** The first-answer block of a stylesheet, comments removed; null when it is missing. */
function blockOf(css) {
  const a = css.indexOf(START), b = css.indexOf(END);
  return a < 0 || b < a ? null : css.slice(a, b).replace(/\/\*[\s\S]*?\*\//g, '');
}
/** [selector, declarations] for each plain rule of a comment-free block. */
const rulesOf = css => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => [m[1].trim(), m[2].trim()]);

const SELECTORS = [
  '.app-first-answer', '.app-first-answer-line', '.app-first-answer-reason', '.app-first-answer-rules', '.app-first-answer-more',
  '.app-first-answer-rules a', '.app-first-answer-rules a:focus-visible',
  ...['yes', 'marginal', 'no', 'unknown'].map(s => `.app-first-answer[data-fishable="${s}"] .app-first-answer-line`),
];
const declaredTokens = css => new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map(m => m[1]));

/** Findings for a first-answer block against the tokens a sheet declares; [] means the contract holds. */
function audit(css, tokens = declaredTokens(tokensCss)) {
  const block = blockOf(css);
  if (block === null) return ['block: the SC2207-11 block is missing'];
  const rules = rulesOf(block), findings = [];
  for (const sel of SELECTORS) if (!rules.some(([s]) => s === sel)) findings.push(`selector: ${sel} is missing`);
  for (const [sel, body] of rules) {
    if (/#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch)\(/i.test(body)) findings.push(`literal colour in ${sel}`);
    if (/(?<![-\w])(?:white|black|red|green|blue|gray|grey|orange|yellow)(?![-\w])/i.test(body.replace(/var\([^)]*\)/g, ''))) findings.push(`named colour in ${sel}`);
    if (/font(?:-family)?\s*:[^;]*(?:"|'|\b(?:Inter|Arial|Helvetica|sans-serif|serif|monospace)\b)/.test(body.replace(/var\([^)]*\)/g, ''))) findings.push(`literal font in ${sel}`);
    if (/!important/.test(body)) findings.push(`!important in ${sel}`);
    if (/(?:^|;)\s*--[a-z0-9-]+\s*:/.test(body)) findings.push(`token override in ${sel}`);
    if (/color-mix\(|transparent|opacity\s*:|rgb\(|backdrop-filter/.test(body)) findings.push(`translucent paint in ${sel}`);
    if (/(?:^|;)\s*(?:height|max-height|-webkit-line-clamp|text-overflow)\s*:/.test(body)) findings.push(`fixed height or clamp in ${sel}`);
    if (/display\s*:\s*none|visibility\s*:\s*hidden/.test(body)) findings.push(`hidden content in ${sel}`);
    for (const [, name] of body.matchAll(/var\((--[a-z0-9-]+)/g)) if (!tokens.has(name)) findings.push(`undefined token ${name} in ${sel}`);
  }
  const root = rules.find(([s]) => s === '.app-first-answer')?.[1] ?? '';
  if (!/background\s*:\s*var\(--panel\)/.test(root)) findings.push('backing: the section is not the opaque --panel');
  if (!/(?<![-\w])min-width\s*:\s*0/.test(root)) findings.push('min-width: the section can impose a minimum width');
  if (!/overflow-wrap\s*:\s*anywhere/.test(root)) findings.push('wrap: long words cannot break');
  // Only the first-answer classes: no global or shell selector is touched.
  for (const [sel] of rules) if (!sel.startsWith('.app-first-answer')) findings.push(`scope: ${sel}`);
  return findings;
}

test('first_answer_styles_use_declared_tokens', () => {
  assert.deepEqual(audit(appCss), []);
  assert.equal(appCss.split(START).length, 2, 'one block');
  // Every var() in the block names a token that web/tokens.css or web/ui/ui.css declares.
  assert.ok(appCss.indexOf(START) > appCss.indexOf('.app-brief-footer'), 'after the shell/brief styles it follows');
});

test('first_answer_styles_use_declared_tokens: synthetic bad copies fail without rewriting the checkout', () => {
  const before = appCss;
  const fails = (css, what) => assert.ok(audit(css).some(f => f.startsWith(what)), `${what}: ${audit(css).join(' | ')}`);
  fails(appCss.replace(START, '/* gone'), 'block');
  fails(appCss.replace('.app-first-answer-more {', '.app-first-answer-moar {'), 'selector: .app-first-answer-more');
  fails(appCss.replace('.app-first-answer-rules a:focus-visible {', '.app-first-answer-rules a:hover {'), 'selector: .app-first-answer-rules a:focus-visible');
  fails(appCss.replace('.app-first-answer-line { margin: 0; color: var(--text);', '.app-first-answer-line { margin: 0; color: #fff;'), 'literal colour');
  fails(appCss.replace('.app-first-answer-line { color: var(--coral); }', '.app-first-answer-line { color: var(--rosy); }'), 'undefined token --rosy');
  fails(appCss.replace('background: var(--panel); color: var(--text); overflow-wrap', 'background: color-mix(in srgb, var(--panel) 90%, transparent); color: var(--text); overflow-wrap'), 'translucent');
  fails(appCss.replace('background: var(--panel); color: var(--text); overflow-wrap', 'background: var(--panel-2); color: var(--text); overflow-wrap'), 'backing');
  fails(appCss.replace('.app-first-answer-reason { margin: 0;', '.app-first-answer-reason { margin: 0; --text: #000;'), 'token override');
  fails(appCss.replace('.app-first-answer-reason { margin: 0;', '.app-first-answer-reason { margin: 0 !important;'), '!important');
  fails(appCss.replace('.app-first-answer-reason { margin: 0;', '.app-first-answer-reason { margin: 0; font-family: Inter, sans-serif;'), 'literal font');
  fails(appCss.replace('.app-first-answer-reason { margin: 0;', '.app-first-answer-reason { margin: 0; max-height: 2em; text-overflow: ellipsis;'), 'fixed height');
  fails(appCss.replace('.app-first-answer-reason { margin: 0;', '.app-first-answer-reason { margin: 0; display: none;'), 'hidden');
  fails(appCss.replace('min-width: 0; box-sizing', 'box-sizing'), 'min-width');
  fails(appCss.replace(END, '.app-brief { background: var(--panel); }\n' + END), 'scope: .app-brief');
  assert.equal(appCss, before);
  assert.equal(readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8'), before, 'the checkout is unread-only');
});

// The colour roles the block resolves to, read from the sheets (not retyped): [foreground, background, what].
const PANEL_BACKING = 'panel';
function roleOf(block, selector, prop) {
  const body = rulesOf(block).find(([s]) => s === selector)?.[1] ?? '';
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*var\\(--([a-z0-9-]+)\\)`).exec(body);
  return m ? m[1] : null;
}
function pairsOf(css) {
  const block = blockOf(css), root = '.app-first-answer';
  const backing = roleOf(block, root, 'background');
  const ghost = /\.ui-button--ghost\s*\{[^}]*background\s*:\s*var\(--([a-z0-9-]+)\)/.exec(uiCss)?.[1];
  const buttonText = /\.ui-button\s*\{[^}]*?color\s*:\s*var\(--([a-z0-9-]+)\)/.exec(uiCss)?.[1];
  return [
    ['yes', roleOf(block, `${root}[data-fishable="yes"] .app-first-answer-line`, 'color'), backing],
    ['marginal', roleOf(block, `${root}[data-fishable="marginal"] .app-first-answer-line`, 'color'), backing],
    ['no', roleOf(block, `${root}[data-fishable="no"] .app-first-answer-line`, 'color'), backing],
    ['unknown', roleOf(block, `${root}[data-fishable="unknown"] .app-first-answer-line`, 'color'), backing],
    ['default', roleOf(block, '.app-first-answer-line', 'color'), backing],
    ['reason', roleOf(block, '.app-first-answer-reason', 'color'), backing],
    ['rules', roleOf(block, '.app-first-answer-rules', 'color'), backing],
    ['anchor', roleOf(block, '.app-first-answer-rules a', 'color'), backing],
    ['action', buttonText, ghost],
  ].map(([id, fg, bg]) => ({id, fg, bg}));
}
const held = (fg, bg) => PAIRS_V2.some(([f, b]) => f === fg && b === bg);

test('first_answer_states_keep_checked_pairs', () => {
  const pairs = pairsOf(appCss);
  assert.deepEqual(pairs.map(p => [p.id, p.fg, p.bg]), [
    ['yes', 'mint', PANEL_BACKING], ['marginal', 'amber', PANEL_BACKING], ['no', 'coral', PANEL_BACKING], ['unknown', 'muted', PANEL_BACKING],
    ['default', 'text', PANEL_BACKING], ['reason', 'text', PANEL_BACKING], ['rules', 'muted', PANEL_BACKING], ['anchor', 'blue', PANEL_BACKING],
    ['action', 'text', 'panel-2'],
  ]);
  const both = themes(tokensCss);
  assert.deepEqual(Object.keys(both).sort(), ['dark', 'light']);
  for (const {id, fg, bg} of pairs) {
    assert.ok(held(fg, bg), `${id}: --${fg} on --${bg} is a pair check_contrast.mjs already holds`);
    for (const [theme, tokens] of Object.entries(both)) {
      const ratio = contrast(tokens[fg], tokens[bg]);
      assert.ok(ratio >= 4.5, `${theme} ${id}: --${fg} on --${bg} is ${ratio.toFixed(2)}:1`);
    }
  }
  // The existing check, unchanged, still passes both themes.
  assert.deepEqual(check(tokensCss).failures, []);
});

test('first_answer_states_keep_checked_pairs: unknown is not drawn as success, and an equal or unchecked pair fails', () => {
  const pairs = pairsOf(appCss), by = Object.fromEntries(pairs.map(p => [p.id, p]));
  assert.notEqual(by.unknown.fg, by.yes.fg);
  assert.notEqual(by.unknown.fg, 'mint');
  assert.equal(new Set(['yes', 'marginal', 'no', 'unknown'].map(s => by[s].fg)).size, 4, 'four states, four distinct roles');
  // A planted copy that colours the heading the same as its backing has no contrast, and its pair is not a held one.
  const planted = appCss.replace('.app-first-answer[data-fishable="no"] .app-first-answer-line { color: var(--coral); }', '.app-first-answer[data-fishable="no"] .app-first-answer-line { color: var(--panel); }');
  assert.notEqual(planted, appCss);
  const bad = pairsOf(planted).find(p => p.id === 'no');
  assert.equal(bad.fg, 'panel');
  assert.equal(bad.fg, bad.bg);
  assert.ok(!held(bad.fg, bad.bg));
  for (const tokens of Object.values(themes(tokensCss))) assert.ok(contrast(tokens[bad.fg], tokens[bad.bg]) < 4.5);
  // A pair the check does not hold (--mint on --bg) is refused even when it would pass.
  assert.ok(!held('mint', 'bg'));
  // Both themes are really read: light mint differs from dark mint.
  const t = themes(tokensCss);
  assert.notEqual(t.dark.mint, t.light.mint);
});
