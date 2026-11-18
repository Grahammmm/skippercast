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
  assert.equal(redact('805-555-0100'), '[redacted]', 'a formatted NANP number is redacted too (RF1050-3)');
  assert.equal(redact(42), 42); assert.equal(redact(null), null); assert.equal(redact(true), true);
  const deep = {}; let at = deep; for (let i = 0; i < 20; i++) at = at.next = {};
  assert.doesNotThrow(() => JSON.stringify(redact(deep)));
});

// The fictional series the repository allows (02 § privacy invariants): +1555XXXXXXX and +1NPA55501XX
// (NANP's fictional 555-0100 to 555-0199; scripts/check_repository.py applies the same rule).
const E164 = /\+1\d{10}/g, FICTIONAL = /^\+1(?:555\d{7}|\d{3}55501\d{2})$/;
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

// Hardening (docs/legal/threat-model.md § 9.1, § 9.3): this covers webhook
// tokens and old-form upload/export tokens at the real logging boundary.
test('API errors log route classes, not request paths or details', async t => {
  globalThis.REGIONS ??= {};
  globalThis.DEPLOYMENT ??= {allowed_origins: []};
  const {onError} = await import('../server/middleware/error.ts');
  const {requestId} = await import('../server/middleware/request-id.ts');
  const {ClientError, RateLimited} = await import('../server/errors.ts');
  const {Hono} = await import('hono');
  const app = new Hono();
  app.use('*', requestId);
  app.onError(onError);
  const detail = 'synthetic-exception-detail', unavailable = 'This service is temporarily unavailable. Your existing records are preserved.';
  const dependency = [Error, detail, 503, 'dependency', unavailable];
  const advisorRoutes = ['inbound/bluebubbles', 'inbound/twilio', 'inbound/twilio-status', 'upload', 'export']
    .map(path => `/api/advisor/${path}/:token`);
  const cases = [
    ['/api/spots/:id', '/api/spots/:id', 'fixture-private-record', ...dependency],
    ...advisorRoutes.map(route => [route, route, ' fixture-token ', ...dependency]),
    ['/api/catch-log/:id', '/api/catch-log/:id', 'fixture-catch', ClientError, 'Invalid entry', 400, 'validation', 'Invalid entry'],
    ['/api/boat/lookup', '/api/boat/lookup', '', RateLimited, detail, 429, 'rate', 'Please try again shortly'],
    ['/api/*', 'unmatched', 'fixture-unknown-tail', ...dependency],
  ];
  const urlFor = (pattern, value) => `https://example.test${pattern.replace(/:id|:token|\*/, encodeURIComponent(value))}?q=fixture-private-query`;
  app.get('/api/control/:id', c => c.json({ok: true}));
  for (const [pattern, , , Failure, message] of cases) app.get(pattern, () => { throw new Failure(message); });

  const saved = console.error, calls = [];
  console.error = (...args) => calls.push(args);
  try {
    for (const [pattern, route, value, , , status, type, error] of cases) {
      await t.test(pattern, async () => {
        calls.length = 0;
        const response = await app.request(urlFor(pattern, value));
        const id = response.headers.get('X-Request-Id');
        assert.match(id, /^[0-9a-f-]{36}$/);
        assert.equal(response.status, status);
        assert.deepEqual(await response.json(), {error, request_id: id});
        // Exact fields: no path value, query, exception details or extra arguments.
        assert.deepEqual(calls, [['SkipperCast request failed', {route, status, type, request_id: id}]]);
      });
    }
    calls.length = 0;
    const ok = await app.request(urlFor('/api/control/:id', 'fixture-private-record'));
    assert.equal(ok.status, 200);
    assert.deepEqual(await ok.json(), {ok: true});
    assert.deepEqual(calls, [], 'a successful request does not log an error');
  } finally { console.error = saved; }
});
