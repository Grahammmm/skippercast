// Text Advisor strings (catalog/advisor/strings.json, server/advisor/strings.ts):
// every key has English and Spanish with the same variables; t() fills
// variables and falls back to English; the welcome carries the 10DLC promise;
// the help text is the runbook's wording; every link placeholder resolves.
// TA-A6: a static scan finds no hard-coded user-facing sentence under
// server/advisor/ (outside strings.ts and prompts/), every t() key exists, and
// the consumer's texts follow the contact's language.
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

// ---- TA-A6: the Spanish pass ------------------------------------------------------------------

import {readdirSync, statSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const walk = d => readdirSync(d).flatMap(f => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : p.endsWith('.ts') ? [p] : []; });

/**
 * The string and template literals of a TypeScript source, comments and
 * regular expressions skipped: [{text, start}], a template's `${...}` parts as
 * "{}". A small lexer, enough for this repository's style.
 */
export function literals(src) {
  const out = [], templates = [];
  let i = 0;
  const template = (lit, j) => {
    while (j < src.length) {
      if (src[j] === '\\') { lit.text += src[j + 1]; j += 2; continue; }
      if (src[j] === '`') return j + 1;
      if (src[j] === '$' && src[j + 1] === '{') { lit.text += '{}'; templates.push({lit, depth: 0}); return j + 2; }
      lit.text += src[j++];
    }
    return j;
  };
  while (i < src.length) {
    const c = src[i], n = src[i + 1];
    if (c === '/' && n === '/') { const e = src.indexOf('\n', i); i = e < 0 ? src.length : e; continue; }
    if (c === '/' && n === '*') { const e = src.indexOf('*/', i + 2); i = e < 0 ? src.length : e + 2; continue; }
    if (templates.length) {
      const top = templates.at(-1);
      if (c === '{') top.depth++;
      if (c === '}') { if (top.depth === 0) { templates.pop(); i = template(top.lit, i + 1); continue; } top.depth--; }
    }
    if (c === '"' || c === "'") {
      let j = i + 1, s = '';
      while (j < src.length && src[j] !== c && src[j] !== '\n') { if (src[j] === '\\') { s += src[j + 1]; j += 2; } else s += src[j++]; }
      out.push({text: s, start: i}); i = j + 1; continue;
    }
    if (c === '`') { const lit = {text: '', start: i}; out.push(lit); i = template(lit, i + 1); continue; }
    if (c === '/' && /(?:[(,=:[!&|?{};]|\breturn)\s*$/.test(src.slice(Math.max(0, i - 12), i))) {
      let j = i + 1, inClass = false;
      while (j < src.length && src[j] !== '\n' && (src[j] !== '/' || inClass)) { if (src[j] === '\\') j++; else if (src[j] === '[') inClass = true; else if (src[j] === ']') inClass = false; j++; }
      i = j + 1; continue;
    }
    i++;
  }
  return out;
}

const words = s => s.replace(/\{\}/g, ' ').split(/\s+/).filter(w => /\p{L}{2,}/u.test(w)).length;
// Where a literal is sent to a person: a send/text action's or a tool reply's `text`, `caption` or `reply` (also as either arm of a
// conditional there), an argument of the text-action helpers, or a constant named *_TEXT / *_LINE or used at one of those places.
const SINK = /\b(?:text|caption|reply)\s*:\s*(?:[^,{};]*[?:]\s*)?$|\b(?:textAction|text|sendText)\(\s*(?:[\w.]+\s*,\s*)*$/;
/** The code before a literal with each closed (...) group replaced by one mark, so a call inside a conditional arm reads as one token. */
const flat = code => { let b = code; while (/\([^()]*\)/.test(b)) b = b.replace(/\([^()]*\)/g, '\u00a7'); return b; };
/** Hard-coded user-facing sentences (>= 4 words) in one source, minus the allowlist. */
export function hardCodedSentences(src, allow = []) {
  const found = [];
  const constants = new Map();
  for (const lit of literals(src)) {
    if (words(lit.text) < 4) continue;
    const before = src.slice(Math.max(0, lit.start - 120), lit.start).replace(/\s+/g, ' ');
    const named = /\bconst\s+([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*$/.exec(before)?.[1];
    if (named) constants.set(named, lit);
    const sent = SINK.test(flat(before)) || (named && /_(?:TEXT|LINE)$/.test(named));
    if (sent && !allow.some(a => lit.text.startsWith(a))) found.push(lit.text);
  }
  for (const [name, lit] of constants) {
    if (found.includes(lit.text) || allow.some(a => lit.text.startsWith(a))) continue;
    if (new RegExp(String.raw`\b(?:text|caption|reply)\s*:\s*${name}\b|\b(?:textAction|text)\([^)]*\b${name}\b`).test(src)) found.push(lit.text);
  }
  return found;
}

// Literals at a sink that are not sent to a person, as {'server/advisor/<file>.ts': ['<start of the literal>', ...]}. Log events
// (advisorLog) and error messages (Error, throw) never sit at a sink, so the scan skips them without an entry; the first test
// below proves it. Empty today; a new entry needs a reason next to it.
const ALLOW = {};

test('the static scan finds a hard-coded sentence at a send, and ignores logs, errors and short words', () => {
  const src = [
    "actions.push({type: 'send_text', text: 'Thanks for the report, captain.'});",
    "export const OOPS_TEXT = 'Something broke on our side.';",
    "const LATER = `See you later, ${name}, good luck out there`; out.push({type: 'send_text', text: LATER});",
    "const reply = {text: ok ? t(language, 'x') : 'That did not work this time.'};",
    "advisorLog('warn', 'advisor model turn failed hard', {});",
    "throw Error('no file in the upload');",
    "return {type: 'send_text', text: t(language, 'welcome')};",
    "const re = /what is biting out there/;",
    "// text: 'a comment is never sent anywhere'",
    "{type: 'send_text', text: 'Ok, done.'}",
  ].join('\n');
  assert.deepEqual(hardCodedSentences(src), ['Thanks for the report, captain.', 'Something broke on our side.', 'That did not work this time.', 'See you later, {}, good luck out there']);
});

test('no server/advisor/**/*.ts outside strings.ts and prompts/ sends a hard-coded sentence: every user-facing text goes through t()', () => {
  const files = walk(join(ROOT, 'server/advisor')).filter(f => !f.includes(`${join('advisor', 'prompts')}`) && !f.endsWith(join('advisor', 'strings.ts')));
  assert.ok(files.length > 50);
  const offenders = [];
  for (const file of files) {
    const rel = relative(ROOT, file).split('\\').join('/');
    for (const s of hardCodedSentences(readFileSync(file, 'utf8'), ALLOW[rel] ?? [])) offenders.push(`${rel}: ${s.slice(0, 80)}`);
  }
  assert.deepEqual(offenders, []);
  for (const [rel, entries] of Object.entries(ALLOW)) {
    const src = readFileSync(join(ROOT, rel), 'utf8');
    for (const entry of entries) assert.ok(src.includes(entry), `allowlist entry still needed: ${rel}: ${entry}`);
  }
});

test('every t() key used under server/advisor exists in the catalog', () => {
  const missing = [];
  for (const file of walk(join(ROOT, 'server/advisor'))) {
    const src = readFileSync(file, 'utf8');
    for (const m of src.matchAll(/\bt\(\s*[\w.?!]+(?:\s*\?\?\s*[\w.'"]+)?\s*,\s*'([a-z_0-9]+)'/g)) if (!Object.hasOwn(STRINGS, m[1])) missing.push(`${relative(ROOT, file)}: ${m[1]}`);
  }
  assert.deepEqual(missing, []);
});

test('Spanish: the consumer texts, the AD-2 line and the few-boats phrase come in the contact\'s language', async () => {
  globalThis.REGIONS ??= {'morro-bay': JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json', import.meta.url)))};
  globalThis.DEPLOYMENT ??= JSON.parse(readFileSync(new URL('../deployments/production.json', import.meta.url)));
  const {warmUpHandler, WARM_UP_TEXT, STILL_WORKING_TEXT, APOLOGY_TEXT} = await import('../server/advisor/consumer.ts');
  assert.deepEqual([WARM_UP_TEXT, STILL_WORKING_TEXT, APOLOGY_TEXT], [t('en', 'warming_up'), t('en', 'still_working'), t('en', 'apology')]);
  assert.deepEqual((await warmUpHandler({contact: {status: 'active', language: 'es'}})).actions, [{type: 'send_text', text: 'SkipperCast se está preparando. Vuelve a escribir pronto.'}]);
  assert.equal(t('es', 'ad2_line'), 'Solo zonas generales; no comparto los puntos de nadie.');
  assert.equal(t('es', 'nws_closer'), 'Revisa el pronóstico más reciente del NWS antes de salir.');
  // Local fishing words in the Spanish strings (the system prompt's list): rocote, not "pez roca".
  assert.match(t('es', 'species_reef'), /^rocote y lingcod$/);
});

test('Spanish: every region target has a name in both languages for the daily answer (no raw keys like pacific-halibut)', async () => {
  const {targetWords, TARGET_WORDS} = await import('../server/advisor/answers/reports.ts');
  const regions = readdirSync(join(ROOT, 'regions')).filter(d => { try { return statSync(join(ROOT, 'regions', d, 'region.json')).isFile(); } catch { return false; } });
  const targets = new Set(regions.flatMap(d => JSON.parse(readFileSync(join(ROOT, 'regions', d, 'region.json'), 'utf8')).species ?? []).filter(s => s !== 'dungeness'));
  assert.ok(targets.size >= 5);
  const SAME_WORD = ['halibut', 'barracuda', 'bonito', 'dorado'];   // the same word in English and Spanish: the key is the name
  for (const target of targets) assert.ok(Object.hasOwn(TARGET_WORDS, target) || SAME_WORD.includes(target), `${target} has a name in strings.json`);
  assert.deepEqual(['salmon', 'pacific-halibut', 'halibut', 'albacore', 'bluefin'].map(k => targetWords(k, 'es')), ['salmón', 'halibut del Pacífico', 'halibut', 'albacora', 'atún aleta azul']);
  assert.equal(targetWords('pacific-halibut', 'en'), 'Pacific halibut');
});
