// M36 (Morro R8 legend reach): at the half detent the sheet body's end padding lets a user SCROLL the last rows above the tab bar,
// but focus() and scrollIntoView() (keyboard, find-in-page, a legend row brought into view) only honour scroll-padding, so they left
// the survey-confidence rows under the tabs. Source contract: the body's scroll-padding-bottom equals its padding-bottom (both follow
// the settled detent's --sheet-hidden-offset), and peek keeps its own unscrolled override. Geometry was measured on the hosted Morro
// preview (finish/morro/m36-accept/ACCEPT.json: chips hit 0/3 -> 3/3 with scrollIntoView, light and dark).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../web/ui/ui.css', import.meta.url), 'utf8');
const rule = sel => {
  const i = css.indexOf('\n' + sel + ' {');
  assert.ok(i >= 0, `rule ${sel}`);
  return css.slice(i, css.indexOf('}', i));
};
const decl = (r, prop) => {
  const m = r.match(new RegExp(`(?:^|[;{\\s])${prop}:\\s*([^;]+);`));
  return m ? m[1].trim() : null;
};

test('sheet body scroll-padding-bottom matches its detent-following end padding', () => {
  const r = rule('.ui-sheet-body');
  const padding = decl(r, 'padding');
  assert.ok(padding, 'padding shorthand present');
  const end = padding.replace(/^0 var\(--space-4\) /, '');
  assert.equal(end, 'calc(var(--space-5) + max(0px, var(--sheet-hidden-offset)))');
  assert.equal(decl(r, 'scroll-padding-bottom'), end);
});

test('the scroll padding is not set anywhere it could fight the detent rules', () => {
  const hits = css.match(/scroll-padding-bottom:/g) ?? [];
  assert.equal(hits.length, 1, 'only the sheet body sets it in ui.css');
  assert.doesNotMatch(rule('.ui-sheet[data-detent="peek"] .ui-sheet-body'), /scroll-padding/);
});

test('full detent zeroes the hidden offset, so the scroll padding shrinks to the end gap', () => {
  assert.match(css, /\.ui-sheet\[data-detent="full"\] \{[^}]*--sheet-hidden-offset: 0px;/);
});
