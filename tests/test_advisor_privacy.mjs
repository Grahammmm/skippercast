// Text Advisor privacy invariants (docs/plans/text-advisor/02-data-model.md
// § Privacy invariants): advisorLog redacts phone numbers at any depth, the
// advisor's fixtures and plan carry only fictional +1555 numbers, and nothing
// under server/advisor/ logs except through advisorLog.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync, statSync} from 'node:fs';
import {join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {advisorLog, redact} from '../server/advisor/log.ts';

const root = fileURLToPath(new URL('..', import.meta.url));
function files(dir) {
  const abs = join(root, dir);
  if (!existsSync(abs)) return [];
  return readdirSync(abs, {recursive: true}).map(f => join(abs, String(f))).filter(f => statSync(f).isFile());
}

function capture(fn) {
  const lines = [], saved = {log: console.log, warn: console.warn, error: console.error};
  for (const level of ['log', 'warn', 'error']) console[level] = (...args) => lines.push({level, text: args.join(' ')});
  try { fn(); } finally { Object.assign(console, saved); }
  return lines;
}

test('advisorLog writes one JSON line per call at the right console level', () => {
  const lines = capture(() => { advisorLog('info', 'turn', {ms: 12}); advisorLog('warn', 'slow', {}); advisorLog('error', 'failed', {code: 'x'}); });
  assert.deepEqual(lines.map(l => l.level), ['log', 'warn', 'error']);
  const first = JSON.parse(lines[0].text);
  assert.deepEqual(first, {ms: 12, level: 'info', event: 'turn', scope: 'advisor'});
  assert.equal(JSON.parse(lines[2].text).event, 'failed');
  assert.ok(lines.every(l => !l.text.includes('\n')));
});

test('advisorLog redacts phone numbers in every string, at any depth, keys included', () => {
  const lines = capture(() => advisorLog('error', 'send failed for +18055550100', {
    error: new Error('BlueBubbles: chat iMessage;-;+18055550100 not found'),
    to: '8055550100', also: '18055550100', intl: '+447700900123', nested: {deep: [{n: 'call +15555550123 back'}], ['+18055550199']: 1},
    keep: {count: 3, id: 'c_0123abcd', date: '2026-10-03', boat: 'Test Boat', sha: 'ab12cd34'},
  }));
  const text = lines[0].text, data = JSON.parse(text);
  for (const digits of ['8055550100', '447700900123', '5555550123', '8055550199']) assert.ok(!text.includes(digits), digits);
  assert.equal(data.event, 'send failed for [redacted]');
  assert.equal(data.error.message, 'BlueBubbles: chat iMessage;-;[redacted] not found');
  assert.equal(data.to, '[redacted]'); assert.equal(data.also, '[redacted]'); assert.equal(data.intl, '[redacted]');
  assert.equal(data.nested.deep[0].n, 'call [redacted] back'); assert.ok('[redacted]' in data.nested);
  assert.deepEqual(data.keep, {count: 3, id: 'c_0123abcd', date: '2026-10-03', boat: 'Test Boat', sha: 'ab12cd34'}, 'ordinary values pass through');
});

test('redact covers the patterns in 02: \\+?1?\\d{10} and \\+\\d{10,15}', () => {
  for (const s of ['8055550100', '18055550100', '+18055550100', '+447700900123', '+861012345678901']) assert.equal(redact(s), '[redacted]', s);
  assert.equal(redact('805-555-0100'), '805-555-0100', 'separated digits are not a 10-digit run (the engine never logs bodies)');
  assert.equal(redact(42), 42); assert.equal(redact(null), null); assert.equal(redact(true), true);
  const deep = {}; let at = deep; for (let i = 0; i < 20; i++) at = at.next = {};
  assert.doesNotThrow(() => JSON.stringify(redact(deep)));
});

// The fictional series the repository allows (02 § privacy invariants): +1555XXXXXXX and +1NPA555XXXX.
const E164 = /\+1\d{10}/g, FICTIONAL = /^\+1(?:555\d{7}|\d{3}555\d{4})$/;
test('advisor fixtures and the plan contain no E.164 number outside the fictional 555 series', () => {
  const scanned = [...files('tests/fixtures/advisor'), ...files('docs/plans/text-advisor'), join(root, 'tests', 'test_advisor_contacts.mjs'), join(root, 'tests', 'test_advisor_privacy.mjs')];
  assert.ok(scanned.length >= 13, 'the plan documents are scanned');
  const offenders = [];
  for (const file of scanned) for (const match of readFileSync(file, 'utf8').matchAll(E164)) if (!FICTIONAL.test(match[0])) offenders.push(`${relative(root, file)}: ${match[0]}`);
  assert.deepEqual(offenders, []);
});

test('nothing under server/advisor/ calls console.* except log.ts', () => {
  const offenders = [];
  for (const file of files('server/advisor').filter(f => f.endsWith('.ts'))) {
    if (relative(root, file) === join('server', 'advisor', 'log.ts')) continue;
    const code = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    if (/\bconsole\s*(?:\.|\[)/.test(code)) offenders.push(relative(root, file));
  }
  assert.deepEqual(offenders, [], 'log through advisorLog() so numbers are redacted');
});
