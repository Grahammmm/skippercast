// Text Advisor strings (catalog/advisor/strings.json, server/advisor/strings.ts):
// every key has English and Spanish with the same variables; t() fills
// variables and falls back to English; the welcome carries the 10DLC promise;
// the help text is the runbook's wording; every link placeholder resolves.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {STRINGS, LANGUAGES, t, variablesOf} = await import('../server/advisor/strings.ts');
const {resolveLinks, linkPath} = await import('../server/advisor/links.ts');

test('every key has both languages, non-empty, with the same variables and placeholders', () => {
  assert.deepEqual(LANGUAGES, ['en', 'es']);
  assert.ok(Object.keys(STRINGS).length >= 25);
  for (const [key, entry] of Object.entries(STRINGS)) {
    assert.deepEqual(Object.keys(entry).sort(), ['en', 'es'], key);
    for (const l of LANGUAGES) assert.ok(entry[l].trim().length > 1, `${key}.${l}`);
    assert.deepEqual(variablesOf(entry.es), variablesOf(entry.en), `${key}: variables`);
    const links = s => [...s.matchAll(/\{\{link:([^}]+)\}\}/g)].map(m => m[1]);
    assert.deepEqual(links(entry.es), links(entry.en), `${key}: link placeholders`);
    assert.notEqual(entry.es, entry.en, `${key}: translated`);
  }
});

test('t fills variables, leaves unknown ones, and falls back to English', () => {
  assert.equal(t('en', 'link_code_text', {code: '123456'}), "Your SkipperCast code is 123456. If you didn't ask for it, ignore this text.");
  assert.equal(t('fr', 'stop_done'), t('en', 'stop_done'));
  assert.equal(t('es', 'admin_not_found'), 'Ninguna revisión abierta coincide con {code}.');
  assert.throws(() => t('en', 'nope'));
});

test('the welcome carries the 10DLC promise once; HELP is the runbook wording, word for word', () => {
  const welcome = t('en', 'welcome');
  assert.equal(welcome.split('Msg & data rates may apply. Reply HELP for help, STOP to opt out.').length, 2);
  assert.match(welcome, /^SkipperCast here\./);
  const runbook = readFileSync(new URL('../docs/operations/runbooks/advisor-port-to-twilio.md', import.meta.url), 'utf8');
  assert.equal(t('en', 'help'), /### HELP and STOP wording[\s\S]*?\n> (.+)\n/.exec(runbook)[1]);
  assert.equal(t('en', 'stop_done'), "Done. You won't hear from me unless you text START.");
  assert.match(t('es', 'stop_done'), /^Listo/);
});

test('links: every placeholder kind, ?s=txt, one link at most, unknown ones dropped', () => {
  const base = 'https://skippercast.com';
  assert.equal(linkPath('port:morro-bay'), '/ports/morro-bay?s=txt');
  assert.equal(linkPath('species:lingcod'), '/species/lingcod?s=txt');
  assert.equal(linkPath('species:california-halibut'), '/species/halibut?s=txt', 'synonyms resolve to the catalog key');
  assert.equal(linkPath('boat:example-boat'), '/boats/example-boat?s=txt');
  assert.equal(linkPath('rules'), '/?s=txt#species-regulations');
  assert.equal(linkPath('rules:vermilion'), '/species/vermilion?s=txt#rules');
  assert.equal(linkPath('map:port-san-luis'), '/?region=morro-bay&s=txt');
  assert.equal(linkPath('home'), '/?s=txt');
  for (const bad of ['port:atlantis', 'species:unicorn', 'boat:Bad Slug', 'map:nowhere', 'admin', 'home:x', 'port:morro-bay:x']) assert.equal(linkPath(bad), null, bad);
  assert.deepEqual(resolveLinks('A {{link:port:morro-bay}} and B {{link:home}}.', base), {text: 'A https://skippercast.com/ports/morro-bay?s=txt and B.', links: ['https://skippercast.com/ports/morro-bay?s=txt']});
  assert.deepEqual(resolveLinks("Back tomorrow, or see {{link:port:atlantis}}", base), {text: 'Back tomorrow', links: []}, 'an unknown link takes its lead-in with it');
  assert.deepEqual(resolveLinks('Rules: {{link:rules}}', 'https://example.test/sub'), {text: 'Rules: https://example.test/sub/?s=txt#species-regulations', links: ['https://example.test/sub/?s=txt#species-regulations']});
  for (const [key, entry] of Object.entries(STRINGS)) for (const l of LANGUAGES) {
    const filled = t(l, key, {target: 'home', link: 'L', code: 'C', decision: 'd', kind: 'k', reason: 'r', slug: 'rita-g'});   // slug: TA-I2's {{link:boat:{slug}}}
    assert.ok(!/\{\{/.test(resolveLinks(filled, base).text), `${key}.${l}: placeholders resolve`);
    void entry;
  }
});
