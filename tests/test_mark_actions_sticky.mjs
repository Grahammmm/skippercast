// SC2222-07: the desktop left column's mark card scrolls beside a tall legend (web/app/app.css .app-chrome-left); its
// action row sticks to the card's foot so the actions stay on screen. The mobile sheet's card is untouched.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8');
const tokens = readFileSync(new URL('../web/tokens.css', import.meta.url), 'utf8');
// Every rule as {selector, at (the enclosing @media or ''), decls}; comments dropped, one level of @media.
function rules(text) {
  const out = [], src = text.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = /([^{}]+)\{([^{}]*)\}|(@media[^{]+)\{|\}/g;
  let at = '', m;
  while ((m = re.exec(src))) {
    if (m[3]) at = m[3].trim();
    else if (m[1] === undefined) at = '';
    else out.push({selector: m[1].trim(), at, decls: Object.fromEntries(m[2].split(';').map(d => d.trim()).filter(Boolean)
      .map(d => [d.slice(0, d.indexOf(':')).trim(), d.slice(d.indexOf(':') + 1).trim()]))});
  }
  return out;
}
const all = rules(css), SCOPED = '.app-chrome-left > .app-mark .app-mark-actions';
const find = selector => all.filter(r => r.selector === selector);

test('the left-column action row sticks to the foot of the scrolling card, in tokens only', () => {
  const [rule, ...extra] = find(SCOPED);
  assert.ok(rule, 'the scoped sticky rule exists');
  assert.equal(extra.length, 0, 'one scoped rule, not two that could disagree');
  assert.equal(rule.at, '', 'not hidden inside a media query');
  assert.equal(rule.decls.position, 'sticky');
  // The card's bottom padding is the first value of `.app-mark`'s padding; the row sits flush in it.
  const pad = find('.app-mark')[0].decls.padding.split(' ')[0];
  assert.equal(rule.decls.bottom, `calc(-1 * ${pad})`, 'bottom offset is minus the card bottom padding');
  assert.equal(rule.decls.background, 'var(--panel)', 'an opaque panel background hides the text scrolling under it');
  assert.deepEqual([rule.decls['z-index'], rule.decls['padding-block'], rule.decls['border-top']], ['1', 'var(--space-2)', '1px solid var(--line)']);
  for (const [prop, value] of Object.entries(rule.decls)) {
    assert.doesNotMatch(value, /#|rgb|hsl|color-mix|transparent|\b\d+(?!px\b)[a-z%]+/i, `${prop} uses no literal colour or unit`);
    for (const [, name] of value.matchAll(/var\((--[a-z0-9-]+)\)/g)) assert.match(tokens, new RegExp(`${name}:`), `${name} is a token`);
  }
  // Sticky needs the card itself to be the scroll container; its scroll padding keeps Tab focus above the row.
  const card = Object.assign({}, ...find('.app-chrome-left > .app-mark').map(r => r.decls));
  assert.equal(card['overflow-y'], 'auto', 'the left-column card scrolls');
  assert.equal(card['scroll-padding-bottom'], 'calc(2 * var(--touch-min) + 3 * var(--space-3))', 'focus scrolls clear of two button rows');
});

test('no sticky reaches the mobile sheet card or any other mark-action rule', () => {
  for (const r of all.filter(r => r.decls.position === 'sticky' && /app-mark/.test(r.selector))) {
    assert.equal(r.selector, SCOPED, `only the left-column row is sticky, not ${r.selector}`);
  }
  for (const r of all.filter(r => /\.app-sheet\b/.test(r.selector) && /app-mark/.test(r.selector))) {
    assert.notEqual(r.decls.position, 'sticky', r.selector);
    assert.ok(!r.decls.bottom && !r.decls['scroll-padding-bottom'], `${r.selector} gains no bottom offset or scroll padding`);
  }
  assert.equal(find('.app-sheet .app-mark, .app-sheet .app-rail, .app-sheet .app-legend')[0]?.decls.position, 'static', 'sheet card stays static');
});

test('the base action-row rules are byte-identical', () => {
  assert.ok(css.includes('\n.app-mark-actions { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-top: var(--space-2); }\n.app-mark-actions a.ui-button { text-decoration: none; }\n'));
  assert.equal(all.filter(r => /\.app-mark-actions/.test(r.selector)).length, 3, 'base, link and the scoped rule only');
});
