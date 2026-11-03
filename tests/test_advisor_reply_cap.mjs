// RF1100-4: capReply's fallback cut never ends on a lone high surrogate before the "…" (no
// half emoji in an SMS); every reply not cut through a surrogate pair is identical to main.
import test from 'node:test';
import assert from 'node:assert/strict';
const {capReply, REPLY_MAX} = await import('../server/advisor/reply.ts');
// Any unpaired surrogate anywhere in the string.
const LONE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
// What main's capReply returned, for parity on inputs the fix must not change.
const mainCap = (text, links, max = 480) => {
  if (text.length <= max) return text;
  const link = links[0];
  const body = link ? text.replace(link, '').replace(/\s{2,}/g, ' ').trim() : text;
  const room = link ? max - link.length - 1 : max;
  let out = '';
  for (const s of body.split(/(?<=[.!?])\s+/)) { if ((out ? out.length + 1 : 0) + s.length > room) break; out = out ? `${out} ${s}` : s; }
  if (!out) out = body.slice(0, Math.max(0, room - 1)).replace(/\s+\S*$/, '') + '…';
  return link ? `${out} ${link}` : out;
};

test('an unbroken run cut inside an emoji drops the half pair before the ellipsis', () => {
  assert.equal(REPLY_MAX, 480);
  const out = capReply('x'.repeat(478) + '🎣🎣', []);
  assert.ok(!LONE.test(out), 'no lone surrogate');
  assert.ok(out.endsWith('…'));
  assert.ok(out.length <= 480);
  assert.equal(out, 'x'.repeat(478) + '…');
  assert.ok(LONE.test(mainCap('x'.repeat(478) + '🎣🎣', [])), 'main left a lone surrogate');
});

test('with a link, the half pair is dropped and the link stays at the end', () => {
  const link = 'https://s.example/a';
  const out = capReply('y'.repeat(458) + '🎣'.repeat(5) + ' ' + link, [link]);
  assert.ok(!LONE.test(out), 'no lone surrogate');
  assert.ok(out.endsWith(' ' + link));
  assert.ok(out.length <= 480);
  assert.equal(out, 'y'.repeat(458) + '… ' + link);
});

test('a cut right after a whole emoji keeps the emoji', () => {
  const text = 'x'.repeat(477) + '🎣🎣';
  const out = capReply(text, []);
  assert.equal(out, 'x'.repeat(477) + '🎣…');
  assert.equal(out, mainCap(text, []));
  assert.ok(!LONE.test(out));
});

test('a low surrogate at the cut end (whole pair) is not trimmed', () => {
  const text = 'z'.repeat(9) + '🎣'.repeat(300);
  const out = capReply(text, [], 50);
  assert.ok(!LONE.test(out));
  assert.ok(out.length <= 50);
  assert.equal(out, mainCap(text, [], 50));
});

test('the sentence path is unchanged: whole sentences only', () => {
  const s = 'The bite is on near the kelp line today 🎣.';
  const parts = [s.padEnd(200, 'a') + '.', 'Tides turn at noon.'.padEnd(200, 'b') + '.', 'Bring a jacket.'.padEnd(200, 'c') + '.'];
  const text = parts.join(' ');
  const out = capReply(text, []);
  assert.equal(out, `${parts[0]} ${parts[1]}`);
  assert.equal(out, mainCap(text, []));
  assert.ok(out.length <= 480);
});

test('text within the limit is returned unchanged, emoji included', () => {
  assert.equal(capReply('short', []), 'short');
  const fits = 'Rockfish 🎣 on the reef. '.repeat(10).trim();
  assert.ok(fits.length <= 480);
  assert.equal(capReply(fits, ['https://s.example/a']), fits);
});
