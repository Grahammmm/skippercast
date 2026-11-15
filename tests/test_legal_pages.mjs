// SCB-05: the privacy notice and terms pages say what the code does. The numbers in the notice
// (retention, limits, session length) are read from the same source lines the server runs on,
// so the notice cannot drift from the code without this test failing.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const flat = path => read(path).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
const privacy = flat('dist/privacy.html'), terms = flat('dist/terms.html');
const has = pattern => assert.ok(new RegExp(pattern).test(privacy), `the notice does not say: ${pattern}`);
const need = (source, pattern, what) => { const m = pattern.exec(source); assert.ok(m, `${what}: pattern ${pattern} not found in the source`); return m; };

test('the notice retention and limits equal the constants in the server', () => {
  const trips = read('server/trips.ts'), auth = read('server/auth.ts');
  const tripDays = Number(need(trips, /const cutoff=new Date\(now-(\d+)\*86400000\)/, 'trip and alert retention')[1]);
  const feedbackDays = Number(need(trips, /comfort_feedback WHERE observed_at<\?'\)\.bind\(new Date\(now-(\d+)\*86400000\)/, 'feedback retention')[1]);
  const sessionDays = Number(need(auth, /SESSION_SECONDS=(\d+)\*86400/, 'session length')[1]);
  const nameChars = Number(need(auth, /\.trim\(\)\.slice\(0,(\d+)\)/, 'display name length')[1]);
  const uaChars = Number(need(auth, /replace\(\/\[\^\\x20-\\x7e\]\/g,''\)\.slice\(0,(\d+)\)/, 'User-Agent length')[1]);
  const spots = Number(need(read('server/routes/spots.ts'), /MAX_SPOTS = (\d+)/, 'spot limit')[1]);
  const devices = Number(need(read('server/routes/subscriptions.ts'), /COUNT\(\*\) FROM subscriptions WHERE owner=\?\) < (\d+)/, 'device limit')[1]);
  assert.equal(tripDays, 90); assert.equal(feedbackDays, 365);
  has(`Removed ${tripDays} days after the trip date`);
  has(`Alerts we sent you and delivery records .{0,60}${tripDays} days`);
  has(`${feedbackDays} days\\.`);
  has(`Until they expire \\(${sessionDays} days after last use\\)`);
  has(`keeps you signed in for ${sessionDays} days`);
  has(`display name \\(up to ${nameChars} characters\\)`);
  has(`first ${uaChars} characters of your browser`);
  has(`optional note; up to ${spots}\\)`);
  has(`push address and keys; up to ${devices}\\)`);
});

test('the boat lookup is described as not available and the notice sends no text to an AI provider (G SPLIT decision, 2026-11-14)', () => {
  has('The boat lookup is not available yet');
  assert.ok(!/Anthropic|Claude/.test(privacy), 'the Anthropic paragraph returns only when G confirms the lookup is live');
});

test('usage statistics are described as off: nothing is stored while ENABLE_ANALYTICS is unset', () => {
  has('We do not collect usage statistics');
  assert.ok(!/Do Not Track|Global Privacy Control|map_viewed/.test(privacy), 'the OFF text replaces the whole section; the DNT line is left out (ITEM-07)');
  has('Our host keeps standard request logs');
  assert.ok(!/three months/.test(privacy), 'no unverified Cloudflare retention claim');
  const config = read('scripts/wrangler_config.mjs');
  assert.match(config, /analytics: on\('ENABLE_ANALYTICS'\)/, 'the binding is added only when ENABLE_ANALYTICS is set; if this changes, update the notice first');
});

test('the notice names the one cookie the server sets', () => {
  assert.equal(need(read('server/auth.ts'), /export const COOKIE='([^']+)'/, 'cookie name')[1], '__Host-sc_session');
  assert.ok(privacy.includes('__Host-sc_session'));
});

test('both pages are drafts, name their canonical address and link each other and the landing', () => {
  for (const [name, canonical] of [['privacy.html', 'https://skippercast.com/privacy'], ['terms.html', 'https://skippercast.com/terms.html']]) {
    const page = read(`dist/${name}`);
    assert.ok(page.includes('Draft — pending review by counsel'), name);
    assert.ok(page.includes(`<link rel="canonical" href="${canonical}" />`), name);
    assert.ok(!/ChatGPT|OpenAI/.test(page), `${name} carries no hosting or sign-in claim the code does not support`);
  }
  assert.match(read('dist/privacy.html'), /href="terms\.html"/);
  assert.match(read('dist/terms.html'), /href="\/privacy"/);
  const landing = read('dist/landing.html');
  assert.match(landing, /<li><a href="\/privacy" data-i18n="landing\.link\.privacy">Privacy<\/a><\/li>/);
  assert.match(landing, /<li><a href="\/terms\.html" data-i18n="brief\.terms">Terms<\/a><\/li>/);
});

test('the terms keep the four owner caveats of docs/legal/disclaimers.md', () => {
  for (const phrase of ['not a navigation aid or a nautical chart', 'Forecasts and scores are estimates', 'the official regulations govern', 'You decide, and you take the risks']) {
    assert.ok(terms.replace(/\s+/g, ' ').includes(phrase), phrase);
  }
});

test('the notice does not mention the Text Advisor, which is off', () => {
  assert.ok(!/Text Advisor|Instagram inbox|web chat/i.test(privacy.replace('whether the visit came from a text, Instagram, Facebook', '')), 'no advisor section until it launches');
});
