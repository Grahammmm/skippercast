// RF2135-5 (UX audit S4-08, top-chrome slice): source contract for the ordinary landscape-phone compact header.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../web/app/app.css', import.meta.url), 'utf8');
const START = '/* RF2135-5:';
const END = '/* end RF2135-5 */';

function block(source = css) {
  const a = source.indexOf(START), b = source.indexOf(END);
  assert.ok(a >= 0 && b > a, 'the RF2135-5 delimited block exists');
  return source.slice(a, b);
}
const MEDIA = '@media (min-width: 600px) and (max-width: 1023px) and (max-height: 500px) and (orientation: landscape)';

test('the block is one landscape-phone media query', () => {
  const b = block();
  assert.ok(b.includes(MEDIA), 'exact media condition');
  assert.equal(b.split('@media').length - 1, 1);
  assert.ok(css.indexOf(END) > css.indexOf('/* end RF1935-4 */'), 'appended after the focused-edit block');
});

test('rules are scoped under .app-mobile and keep the strip, tabs and detents alone', () => {
  const b = block();
  const rules = [...b.matchAll(/^\s{2}(\.[^{]+)\{([^}]*)\}/gm)];
  assert.ok(rules.length >= 5);
  for (const [, sel] of rules) assert.ok(sel.trim().startsWith('.app-mobile'), `scoped: ${sel}`);
  assert.ok(b.includes('--app-strip: calc(72px + env(safe-area-inset-top, 0px))'));
  assert.ok(!/--app-tabs|--sheet-peek|transform|\.app-sheet|\.app-tabs/.test(b), 'no tab, peek or detent rewrite');
});

test('no hidden controls, no !important, no font or target shrink', () => {
  const b = block();
  const bodies = [...b.matchAll(/\{([^}]*)\}/g)].map(m => m[1]).join('\n');
  assert.ok(!/display:\s*none|visibility|!important|font-size|(^|[\s;])(min-)?height:|(^|[\s;])width:/.test(bodies), 'layout-only');
  assert.ok(b.includes('flex: 0 0 240px'), 'profile switch basis is 240px, no shrink');
  assert.ok(b.includes('flex-direction: row'));
});

test('mutation negatives: the checks fail on a broken block', () => {
  const broken = css.replace('(max-height: 500px)', '(max-height: 900px)');
  assert.ok(!block(broken).includes(MEDIA));
  const hiding = css.replace(END, '.app-mobile .app-profile { display: none; }\n' + END);
  assert.ok(/display:\s*none/.test(block(hiding)));
});

test('the focused-edit override out-specifies the media-query strip variable', () => {
  assert.ok(css.includes('.app-mobile:has(.app-sheet .app-target-search:focus) {\n  --app-tabs'), 'RF1935-4 override is kept');
});
