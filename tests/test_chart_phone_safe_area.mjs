// M21 (Morro phone hit targets): on a phone the Chart's MapLibre group (Sources link, scale, Zoom in/out) is anchored to
// the bottom, just above the Readings sheet's peek and the tab bar, so a taller top strip (a preview region's card, the
// activity row) or the presentation notes under it can no longer sit on Zoom in or the Sources link. Measured on the real
// Chart at 390x844 and 430x932 (finish/morro/central-header-hit-target, agent-work): Morro Zoom in went from 97% covered
// (a tap did not zoom) to uncovered, the Sources link from fully covered to tappable; the desktop rules are unchanged.
// M23: the group sits on the LEFT edge on phones. Measured on the real Chart (finish/morro/short-phone-composition):
// at 375x667 the right-hand group left Zoom in 97% under the "Zoom in to use 3D" note and the Sources link under the
// depth notice; at 414x736 the Sources link was 75% covered. On the left: both uncovered, taps land, notice unchanged.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const chart = readFileSync(new URL('../web/map/chart.css', import.meta.url), 'utf8');
const app = readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8');
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
const GROUP = '.app-chart .maplibregl-ctrl-bottom-right';
const PHONE = `.app-mobile ${GROUP}`, MARK = `.app-mobile:has(.app-sheet--mark) ${GROUP}`;
const chartRules = rules(chart), appRules = rules(app);
const one = (list, selector, at = '') => {
  const found = list.filter(r => r.selector === selector && r.at === at);
  assert.equal(found.length, 1, `exactly one ${selector} rule${at ? ` in ${at}` : ''}`);
  return found[0].decls;
};
const peek = selector => {
  const found = appRules.filter(r => r.selector === selector && '--sheet-peek' in r.decls);
  assert.equal(found.length, 1, `one ${selector} rule sets --sheet-peek`);
  return Number(/^(\d+)px$/.exec(found[0].decls['--sheet-peek'])?.[1]);
};

test('phone: the map control group is fixed to the bottom, above the Readings peek and the tab bar', () => {
  const decls = one(chartRules, PHONE);
  assert.deepEqual(Object.keys(decls).sort(), ['align-items', 'bottom', 'left', 'position', 'right', 'top']);
  assert.equal(decls.position, 'fixed', 'viewport-anchored: the stage box can extend below the screen');
  assert.equal(decls.top, 'auto', 'no offset from the top strip, whose height grows with a preview card');
  assert.equal(decls.bottom, `calc(var(--app-tabs) + ${peek('.app-sheet')}px + var(--space-3))`, 'clears the tab bar and the sheet peek');
  assert.match(app, /\.app-mobile \{ --app-tabs: /, 'the phone shell defines --app-tabs');
  assert.match(tokens, /--space-3:/, '--space-3 is a token');
});

test('phone: the map control group is on the LEFT edge, opposite the presentation stack (M23 short phones)', () => {
  const decls = one(chartRules, PHONE);
  assert.equal(decls.left, 'var(--space-4)', 'the same 16 px inset the desktop group keeps on the right');
  assert.equal(decls.right, 'auto', 'released from the right column');
  assert.equal(decls['align-items'], 'flex-start', 'Sources, scale and zoom line up on the left edge');
  // The presentation stack (Chart/2D/3D, the depth notice, "Zoom in to use 3D") stays right-anchored in the phone
  // shell and at most 280 px wide; on a 375 px phone that leaves 375 - 16 - 280 = 79 px on the left, enough for the
  // 16 px inset plus the Sources link (54 px) and the zoom buttons (44 px) without touching the stack.
  const pres = appRules.filter(r => r.selector === '.app-presentation' && r.at === '' && 'right' in r.decls);
  assert.equal(pres.length, 1, 'one base .app-presentation placement');
  assert.equal(pres[0].decls.right, 'var(--space-4)');
  assert.equal(pres[0].decls['max-width'], 'min(280px, calc(100% - 2 * var(--space-4)))');
  const phonePres = appRules.filter(r => r.selector === '.app-mobile .app-presentation');
  assert.ok(phonePres.length >= 1 && phonePres.every(r => !('left' in r.decls) && !('right' in r.decls)),
    'the phone shell does not move the presentation stack off the right edge');
});

test('phone: a mark card raises the group above its taller peek', () => {
  const decls = one(chartRules, MARK);
  assert.deepEqual(Object.keys(decls), ['bottom']);
  assert.equal(decls.bottom, `calc(var(--app-tabs) + ${peek('.app-sheet--mark')}px + var(--space-3))`);
  assert.ok(peek('.app-sheet--mark') > peek('.app-sheet'), 'the mark peek is the taller one');
});

test('the desktop and narrow-window placements are unchanged, and nothing is hidden or resized', () => {
  assert.deepEqual(one(chartRules, GROUP), {bottom: 'calc(2 * var(--touch-min) + var(--space-7) + var(--space-3))', right: 'var(--space-4)',
    display: 'flex', 'flex-direction': 'column', 'align-items': 'flex-end', gap: 'var(--space-2)'});
  assert.deepEqual(one(chartRules, GROUP, '@media (max-width: 1023px)'),
    {top: 'calc(var(--app-strip, 84px) + 2 * var(--touch-min) + var(--space-5) + var(--space-4))', bottom: 'auto'});
  for (const r of chartRules.filter(r => r.selector.includes('.app-mobile'))) {
    for (const prop of ['display', 'visibility', 'opacity', 'width', 'height', 'max-height', 'overflow', 'clip-path', 'z-index']) {
      assert.ok(!(prop in r.decls), `${r.selector} sets no ${prop}`);
    }
  }
});
