// RF2135-6: source contract for the account dialog's bounded scrollport and CSS scroll-edge cues (geometry is in
// e2e/v2-account-scrollport.spec.ts).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../web/app/account.css', import.meta.url), 'utf8');
const block = css.slice(css.indexOf('/* RF2135-6'));
const rule = sel => { const i = block.indexOf(sel + ' {'); assert.ok(i >= 0, `rule ${sel}`); return block.slice(i, block.indexOf('}', i)); };

test('account card is bounded by the viewport including padding and border', () => {
  const r = rule('.account-scrim > .account-card');
  assert.match(r, /box-sizing: border-box/);
  assert.match(r, /max-height: calc\(100vh - 2 \* var\(--space-4\)\);\s*max-height: calc\(100dvh - 2 \* var\(--space-4\)\)/);
  assert.match(r, /overflow-y: auto/);
  assert.doesNotMatch(r, /overflow-x: (hidden|clip)/);
});

test('scroll cues: local covers above scroll shadows, native scrollbar kept', () => {
  const r = rule('.account-scrim > .account-card');
  assert.equal((r.match(/\blocal\b/g) ?? []).length, 2);
  assert.equal((r.match(/\bscroll,/g) ?? []).length, 2);
  assert.ok(r.indexOf('local') < r.indexOf('scroll,'), 'covers listed first (painted on top)');
  assert.doesNotMatch(block, /scrollbar-width\s*:\s*none|::-webkit-scrollbar/);
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgba?\(/i, 'no new color literals');
});

test('children keep natural height, the block is account-only and forced colors drops the gradients', () => {
  assert.match(block, /flex-shrink: 0/);
  assert.doesNotMatch(block, /(^|\n)\.home-port-(card|scrim)\b/);
  assert.match(block, /@media \(forced-colors: active\) \{ \.account-scrim > \.account-card \{ background: Canvas; \} \}/);
});

