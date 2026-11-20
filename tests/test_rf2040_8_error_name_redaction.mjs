// RF2040-8: the shared advisor logger scrubs phone-like text in an Error's name, not only its message.
// Synthetic Errors and fictional 555-01xx numbers only; console is captured locally.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorLog, redact} from '../server/advisor/log.ts';

function named(name, message) { const e = new Error(message); e.name = name; return e; }

function capture(fn) {
  const calls = [], saved = {log: console.log, warn: console.warn, error: console.error};
  for (const level of ['log', 'warn', 'error']) console[level] = (...args) => calls.push([level, args.join(' ')]);
  try { fn(); } finally { Object.assign(console, saved); }
  return calls;
}

test('error_name_phone_is_redacted: formatted, bare-digit and E.164 names', () => {
  const out = redact(named('Relay (805) 555-0100', 'contact 805-555-0100 unavailable'));
  assert.deepEqual(out, {name: 'Relay [redacted]', message: 'contact [redacted] unavailable'});
  assert.equal(redact(named('Relay 8055550100', 'x')).name, 'Relay [redacted]');
  assert.equal(redact(named('Relay +442079460123', 'x')).name, 'Relay [redacted]');
});

test('logger_error_name_redacted_at_all_levels, including nested values', () => {
  const expected = {info: 'log', warn: 'warn', error: 'error'};
  for (const [level, method] of Object.entries(expected)) {
    const calls = capture(() => advisorLog(level, 'synthetic', {
      error: named('Relay (805) 555-0100', 'call (805) 555-0100'),
      nested: {list: [named('Hop 805-555-0100', 'ok')]},
    }));
    assert.equal(calls.length, 1, level);
    assert.equal(calls[0][0], method, level);
    assert.ok(!/555[ .-]?01\d\d/.test(calls[0][1]), calls[0][1]);
    const row = JSON.parse(calls[0][1]);
    assert.deepEqual(row.error, {name: 'Relay [redacted]', message: 'call [redacted]'});
    assert.deepEqual(row.nested.list[0], {name: 'Hop [redacted]', message: 'ok'});
  }
});

test('error_name_depth_boundary: depth 7 scrubbed, depth 8 truncated', () => {
  assert.deepEqual(redact(named('R 805-555-0100', 'm 805-555-0100'), 7), {name: 'R [redacted]', message: 'm [redacted]'});
  assert.equal(redact(named('R 805-555-0100', 'm'), 8), '[truncated]');
});

test('ordinary_error_control_preserves_projection and does not mutate input', () => {
  for (const [Ctor, name] of [[Error, 'Error'], [TypeError, 'TypeError']]) {
    const e = new Ctor('safe');
    e.cause = 'c'; e.extra = 'x';
    assert.deepEqual(redact(e), {name, message: 'safe'});
  }
  assert.deepEqual(redact(named('TimeoutError', 'safe')), {name: 'TimeoutError', message: 'safe'});
  const bad = named('Relay (805) 555-0100', 'call (805) 555-0100');
  redact(bad);
  assert.equal(bad.name, 'Relay (805) 555-0100');
  assert.equal(bad.message, 'call (805) 555-0100');
});
