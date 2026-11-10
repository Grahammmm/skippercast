// RF1935-2 (UX audit S4-15): SOURCE-CONTRACT tests for the desktop layer rail's preset containment. They read web/app/app.css and
// web/ui/ui.css only; they are NOT geometry proof. The measured widths, wrapping and clearance are in e2e/v2-map.spec.ts
// ("desktop: ..." tests). Offline; rewrites nothing.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8');
const appCss = read('web/app/app.css').replace(/\/\*[\s\S]*?\*\//g, ''), uiCss = read('web/ui/ui.css').replace(/\/\*[\s\S]*?\*\//g, '');

/** Top-level `@media (<query>) { ... }` bodies and the CSS outside every @media, with comments already removed. */
function split(css) {
  const media = [];
  let outside = '', i = 0;
  while (i < css.length) {
    const at = css.indexOf('@media', i);
    if (at < 0) { outside += css.slice(i); break; }
    outside += css.slice(i, at);
    const open = css.indexOf('{', at), query = css.slice(at + 6, open).trim();
    let depth = 1, j = open + 1;
    while (j < css.length && depth) { if (css[j] === '{') depth++; else if (css[j] === '}') depth--; j++; }
    media.push({query, body: css.slice(open + 1, j - 1)});
    i = j;
  }
  return {media, outside};
}
const rulesOf = css => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(m => ({selector: m[1].trim().replace(/\s+/g, ' '), decl: m[2].trim().replace(/\s+/g, ' ')}));
const {media, outside} = split(appCss);
const DESKTOP = '(min-width: 1024px)';
const desktopRules = media.filter(m => m.query === DESKTOP).flatMap(m => rulesOf(m.body));
const rule = (rules, selector) => rules.filter(r => r.selector === selector);

test('the desktop rail keeps its width and terrain reservation and gains a native vertical scroll track', () => {
  const [rail, ...extra] = rule(desktopRules, '.app-stage > .app-rail');
  assert.ok(rail && extra.length === 0, 'one desktop rail rule');
  assert.match(rail.decl, /width: min\(280px, calc\(100% - 2 \* var\(--space-4\)\)\)/);
  assert.match(rail.decl, /max-height: calc\(100% - var\(--space-4\) - var\(--app-terrain-controls-bottom\) - var\(--app-terrain-controls-height\) - var\(--space-3\)\)/);
  assert.match(rail.decl, /overflow-y: scroll/);
  assert.match(rail.decl, /scrollbar-gutter: stable/);
  assert.doesNotMatch(appCss, /overflow-x\s*:\s*(hidden|clip)/, 'a failed layout is never concealed by clipping sideways');
  assert.match(outside, /--app-terrain-controls-height: calc\(4 \* var\(--touch-min\) \+ 2px\)/, 'the four-button reservation is kept');
});

test('the preset group wraps inside the rail from 1024px up, scoped structurally', () => {
  const [group] = rule(desktopRules, '.app-stage > .app-rail > .ui-segmented');
  assert.ok(group, 'a desktop rule for the rail\'s own segmented header group');
  for (const decl of ['display: flex', 'flex-wrap: wrap', 'box-sizing: border-box', 'min-width: 0', 'max-width: 100%', 'border-radius: var(--radius-lg)']) {
    assert.ok(group.decl.includes(decl), `group declares ${decl}`);
  }
  const [chip] = rule(desktopRules, '.app-stage > .app-rail > .ui-segmented .ui-chip');
  assert.ok(chip, 'a desktop rule for the preset chips');
  for (const decl of ['min-width: 0', 'max-width: 100%', 'white-space: normal', 'overflow-wrap: anywhere']) assert.ok(chip.decl.includes(decl), `chip declares ${decl}`);
  assert.doesNotMatch(chip.decl, /font-size|min-height|height/, 'no smaller type or target');
  const mine = rulesOf(appCss).filter(r => r.selector.includes('.app-rail > .ui-segmented'));
  assert.equal(mine.length, 2);
  for (const r of mine) assert.doesNotMatch(r.selector, /aria-label|Layer presets|Preajustes/, 'the translated name is not a style hook');
});

test('no preset-wrap rule applies below 1024px or to any other segmented control', () => {
  assert.equal(rulesOf(outside).filter(r => r.selector.includes('.app-rail') && r.selector.includes('.ui-segmented')).length, 0, 'no ungated rail preset rule');
  assert.equal(rulesOf(outside).filter(r => r.selector === '.ui-segmented' || r.selector === '.app-presentation .ui-segmented').filter(r => /flex-wrap/.test(r.decl)).length, 0, 'the generic and presentation groups do not wrap');
  for (const m of media.filter(m => m.query !== DESKTOP)) {
    assert.ok(!rulesOf(m.body).some(r => r.selector.includes('.app-rail > .ui-segmented')), `${m.query} has no preset rule`);
  }
  const generic = rulesOf(uiCss).find(r => r.selector === '.ui-segmented');
  assert.ok(generic, 'the generic segmented rule exists');
  assert.ok(generic.decl.includes('display: inline-flex') && generic.decl.includes('border-radius: var(--radius-pill)'));
  assert.doesNotMatch(generic.decl, /flex-wrap/, 'the generic segmented control is unchanged and does not wrap');
});
