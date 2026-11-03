// RF1050-3: advisorLog's redact scrubs US numbers written the way people type them
// ((805) 555-0100, 805-555-0100, 805.555.0100, 805 555 0100, +1 805-555-0100, 1-805-555-0100),
// not only bare digit runs, while dates, versions, money and 7-digit numbers stay readable.
// Numbers are in the fictional 555-01xx range.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorLog, redact} from '../server/advisor/log.ts';

function capture(fn) {
  const lines = [], saved = {log: console.log, warn: console.warn, error: console.error};
  for (const level of ['log', 'warn', 'error']) console[level] = (...args) => lines.push(args.join(' '));
  try { fn(); } finally { Object.assign(console, saved); }
  return lines;
}

test('every formatted NANP number inside a sentence becomes [redacted], surrounding words intact', () => {
  for (const number of ['(805) 555-0100', '(805)555-0100', '805-555-0100', '805.555.0100', '805 555 0100',
    '+1 805-555-0100', '1-805-555-0100', '+1 (805) 555-0100', '1.805.555.0100', '( 805 ) 555-0100']) {
    assert.equal(redact(`call ${number} back today`), 'call [redacted] back today', number);
    assert.equal(redact(`${number}, then hang up.`), '[redacted], then hang up.', number);
  }
  assert.equal(redact('two: 805-555-0100 and (213) 555-0199.'), 'two: [redacted] and [redacted].');
});

test('dates, times, versions, money, 7-digit numbers and a 0/1 area code are not redacted', () => {
  for (const text of ['at 2026-11-02T10:15:00Z', 'on 2026-11-02 10:15', 'version 1.2.3', 'v10.20.3000',
    'dial 555-0100', 'paid $1,234.56', 'area 055-555-0100', 'area 155-555-0100', 'exchange 805-055-0100',
    'id c_0123abcd', 'sha ab12cd34', 'coords 34.405 -119.692', 'count 805 555']) {
    assert.equal(redact(text), text, text);
  }
});

test('numbers redacted before are redacted identically', () => {
  assert.equal(redact('+18055550100'), '[redacted]');
  assert.equal(redact('8055550100'), '[redacted]');
  assert.equal(redact('18055550100'), '[redacted]');
  assert.equal(redact('+442079460123'), '[redacted]');
  assert.equal(redact('to +18055550100 now'), 'to [redacted] now');
  assert.equal(redact('chat iMessage;-;+18055550100'), 'chat iMessage;-;[redacted]');
  assert.equal(redact('x8055550100'), 'x[redacted]');
  assert.equal(redact('8055550100x'), '[redacted]x');
});

test('a formatted number in a nested key, an array and an Error message is redacted', () => {
  const lines = capture(() => advisorLog('error', 'send failed for (805) 555-0100', {
    error: new Error('relay: no chat for 805-555-0100'),
    nested: {deep: [{n: 'call 805.555.0100 back'}], ['+1 805 555 0199']: 1},
  }));
  assert.equal(lines.length, 1);
  assert.ok(!/555[ .-]?01\d\d/.test(lines[0]), lines[0]);
  const row = JSON.parse(lines[0]);
  assert.equal(row.event, 'send failed for [redacted]');
  assert.deepEqual(row.error, {name: 'Error', message: 'relay: no chat for [redacted]'});
  assert.deepEqual(row.nested, {deep: [{n: 'call [redacted] back'}], '[redacted]': 1});
});

test('depth and truncation behaviour is unchanged', () => {
  let deep = '805-555-0100';
  for (let i = 0; i < 10; i += 1) deep = {d: deep};
  let cut = redact(deep);
  for (let i = 0; i < 8; i += 1) cut = cut.d;
  assert.equal(cut, '[truncated]');
  assert.deepEqual(redact({a: {b: '805-555-0100'}}), {a: {b: '[redacted]'}});
  assert.equal(redact(42), 42);
  assert.equal(redact(null), null);
});

test('a number split across a line break is not matched (documented choice)', () => {
  assert.equal(redact('805\n555-0100'), '805\n555-0100');
  assert.equal(redact('805-555\n0100'), '805-555\n0100');
  assert.equal(redact('(805)\n555-0100'), '(805)\n555-0100');
});
