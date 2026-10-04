// Text Advisor prompts (server/advisor/prompts/system.ts, examples.ts;
// docs/plans/text-advisor/04-advisor-engine.md § The system prompt): every
// required phrase is in the prompt in both languages, the few-shots cover the
// six English cases and three Spanish ones, examples follow the format rules
// (plain text, placeholders for links, short, no rule numbers), and no prompt
// or engine fixture carries a non-fictional phone number.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';

// engine.ts reaches the Worker config through server/analytics.ts, which needs the build-time globals.
const json = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': json('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = json('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';

const {systemPrompt, REQUIRED_PHRASES, REFUSAL_EN, ABUSE_EN, LANGUAGE_NAMES} = await import('../server/advisor/prompts/system.ts');
const {EXAMPLES, examplesFor} = await import('../server/advisor/prompts/examples.ts');
const {t} = await import('../server/advisor/strings.ts');
const {statesRuleNumber} = await import('../server/advisor/engine.ts');
const {resolveLinks} = await import('../server/advisor/links.ts');

test('the system prompt contains every required phrase from 04, in both languages', () => {
  for (const language of ['en', 'es']) {
    const prompt = systemPrompt(language);
    for (const phrase of REQUIRED_PHRASES) assert.ok(prompt.includes(phrase), `${language}: ${phrase}`);
    assert.ok(prompt.includes(`Reply in ${LANGUAGE_NAMES[language]}.`), language);
    assert.ok(!prompt.includes('{{language}}'));
  }
  assert.ok(REQUIRED_PHRASES.length >= 25);
});

test('the refusal and stop lines match the strings the engine recognises', () => {
  assert.equal(REFUSAL_EN, t('en', 'refusal'));
  assert.equal(ABUSE_EN, t('en', 'abuse_stop'));
  assert.equal(REFUSAL_EN, "I only do fishing. Ask me what's biting, send a fish photo, or ask how to rig for something.");
});

test('the prompt is stable per language (so caching works) and tells the model the placeholder forms', () => {
  assert.equal(systemPrompt('en'), systemPrompt('en'));
  assert.notEqual(systemPrompt('en'), systemPrompt('es'));
  for (const p of ['{{link:port:<port-id>}}', '{{link:species:<species-key>}}', '{{link:boat:<boat-slug>}}', '{{link:rules}}', '{{link:rules:<species-key>}}', '{{link:map:<port-id>}}', '{{link:home}}'])
    assert.ok(systemPrompt('en').includes(p), p);
});

test('few-shots: six English cases and Spanish versions of the first three', () => {
  const en = EXAMPLES.filter(e => e.language === 'en').map(e => e.name), es = EXAMPLES.filter(e => e.language === 'es').map(e => e.name);
  assert.deepEqual(en, ['first-contact', 'whats-biting', 'trip-planning-advisory', 'fish-id-rules', 'rig-question', 'refusal']);
  assert.deepEqual(es, ['first-contact-es', 'whats-biting-es', 'trip-planning-advisory-es']);
  assert.ok(examplesFor('es').startsWith('person: hola'), 'the reply language comes first');
});

test('every example reply follows the format rules', () => {
  for (const e of EXAMPLES) for (const turn of e.turns.filter(x => x.from === 'SkipperCast')) {
    assert.ok(!/\*\*|^#|^\s*- /m.test(turn.text), `${e.name}: no markdown`);
    assert.ok(!/https?:\/\//.test(turn.text), `${e.name}: links only as placeholders`);
    assert.ok(resolveLinks(turn.text, 'https://skippercast.com').links.length <= 1, `${e.name}: one link at most`);
    assert.ok(!/\{\{(?!link:)/.test(turn.text));
    assert.ok(turn.text.length <= 480, `${e.name}: ${turn.text.length} characters`);
    assert.ok((turn.text.match(/\?/g) ?? []).length <= 1, `${e.name}: one question at a time`);
    assert.ok(!statesRuleNumber(turn.text), `${e.name}: no rule numbers in a few-shot`);
    assert.ok(!/\d+\s*%|\bodds\b|hotspot/i.test(turn.text), `${e.name}: no odds`);
  }
  const advisory = EXAMPLES.find(e => e.name === 'trip-planning-advisory').turns.at(-1).text;
  assert.match(advisory, /^SMALL CRAFT ADVISORY/, 'the advisory leads');
  assert.match(advisory, /Check the latest NWS forecast before you go\.$/);
});

// 02 § privacy invariants: only the fictional 555 series in prompts and engine fixtures.
const E164 = /\+1\d{10}/g, FICTIONAL = /^\+1(?:555\d{7}|\d{3}555\d{4})$/;
const TEN = /\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b/g;
test('prompts and engine fixtures carry no non-fictional phone number', () => {
  const dir = new URL('./fixtures/advisor/engine/', import.meta.url);
  const files = [...readdirSync(dir, {recursive: true}).filter(f => String(f).endsWith('.json')).map(f => new URL(String(f), dir)),
    new URL('../server/advisor/prompts/system.ts', import.meta.url), new URL('../server/advisor/prompts/examples.ts', import.meta.url), new URL('../catalog/advisor/strings.json', import.meta.url)];
  assert.ok(files.length >= 15);
  const offenders = [];
  for (const file of files) {
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(E164)) if (!FICTIONAL.test(m[0])) offenders.push(`${file.pathname}: ${m[0]}`);
    for (const m of text.matchAll(TEN)) if (!/555[\s.-]?\d{4}\b/.test(m[0])) offenders.push(`${file.pathname}: ${m[0]}`);
  }
  assert.deepEqual(offenders, []);
});
