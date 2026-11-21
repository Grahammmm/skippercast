import test from 'node:test';
import assert from 'node:assert/strict';
import {eventStatus, nextAttempt} from '../server/spot-watch-delivery.ts';

// Same retry policy as trip alerts, without loading their runtime.
const retryable = (status, httpStatus, attempt) =>
  status === 'failed' && (httpStatus === 429 || httpStatus !== null && httpStatus >= 500 && httpStatus <= 599) && attempt < 3;

// Coercing a malformed attempt or accepting an empty status can claim the wrong receipt.
test('C1: ignore malformed rows without losing usable history', () => {
  const malformed = Object.freeze([
    null, undefined, 3, 'accepted', {}, [],
    ...[undefined, 0, 4, 1.5, '2', NaN].map(attempt => Object.freeze({attempt, status: 'accepted', http_status: 200})),
    ...[undefined, null, '', 500].map(status => Object.freeze({attempt: 3, status, http_status: 503})),
    {get attempt() { throw new TypeError('unreadable fixture'); }},
  ]);
  assert.deepEqual(nextAttempt(malformed, retryable), {kind: 'send', attempt: 1});
  const usable = Object.freeze({attempt: 2, status: 'failed', http_status: 503});
  assert.deepEqual(nextAttempt(Object.freeze([...malformed, usable]), retryable), {kind: 'send', attempt: 3});
});

// Bad HTTP values must become null, not be rounded or coerced into 429/5xx.
test('C1: pass null for non-integer HTTP status and preserve an integer', () => {
  for (const http_status of [503.5, '503', NaN, Infinity, null, undefined]) {
    assert.deepEqual(nextAttempt([{attempt: 2, status: 'failed', http_status}],
      (status, httpStatus, attempt) => status === 'failed' && httpStatus === null && attempt === 2),
    {kind: 'send', attempt: 3});
  }
  assert.deepEqual(nextAttempt([{attempt: 2, status: 'failed', http_status: 0}],
    (status, httpStatus, attempt) => status === 'failed' && httpStatus === 0 && attempt === 2),
  {kind: 'send', attempt: 3});
});

// An empty receipt history should start at 1, regardless of retry policy.
test('C2: start at attempt 1 with no prior receipts', () => {
  assert.deepEqual(nextAttempt([], retryable), {kind: 'send', attempt: 1});
});

// Looking only at the newest receipt could resend an already accepted event.
test('C2: an accepted receipt wins among failures', () => {
  assert.deepEqual(nextAttempt([
    {attempt: 3, status: 'failed', http_status: 503},
    {attempt: 2, status: 'accepted', http_status: 201},
    {attempt: 1, status: 'failed', http_status: 429},
  ], retryable), {kind: 'delivered'});
});

// Catch off-by-one retries and retries of terminal receipts at each attempt.
test('C2: apply retry policy and cap attempts at three', () => {
  for (const [attempt, expected] of [
    [1, {kind: 'send', attempt: 2}],
    [2, {kind: 'send', attempt: 3}],
    [3, {kind: 'skip'}],
  ]) {
    assert.deepEqual(nextAttempt([{attempt, status: 'failed', http_status: 429}], retryable), expected);
    assert.deepEqual(nextAttempt([{attempt, status: 'expired', http_status: 410}], retryable), {kind: 'skip'});
  }
  assert.deepEqual(nextAttempt([{attempt: 3, status: 'failed', http_status: 503}], () => true), {kind: 'skip'});
});

// Neither input order nor an older retryable failure should override the highest attempt.
test('C2: decide from the highest attempt without sorting the input in place', () => {
  const prior = Object.freeze([
    Object.freeze({attempt: 2, status: 'uncertain', http_status: null}),
    Object.freeze({attempt: 1, status: 'failed', http_status: 503}),
  ]);
  assert.deepEqual(nextAttempt(prior, retryable), {kind: 'skip'});
  assert.deepEqual(nextAttempt([...prior].reverse(), retryable), {kind: 'skip'});
  assert.deepEqual(nextAttempt([
    {attempt: 2, status: 'failed', http_status: 503},
    {attempt: 1, status: 'uncertain', http_status: null},
  ], retryable), {kind: 'send', attempt: 3});
});

const canRetry = Object.freeze({attempt: 2, status: 'failed', httpStatus: 503});
const exhausted = Object.freeze({attempt: 3, status: 'failed', httpStatus: 503});

// A pending subscription must not mask a successful one.
test('C3: delivered wins over an outstanding retry', () => {
  const accepted = Object.freeze({attempt: 1, status: 'accepted', httpStatus: 201});
  assert.equal(eventStatus(Object.freeze([canRetry, accepted]), 2, retryable), 'delivered');
});

// Looking only at the first outcome could put a still-retryable event on hold.
test('C3: pending when any outcome can retry', () => {
  assert.equal(eventStatus(Object.freeze([exhausted, canRetry]), 2, retryable), 'pending');
});

// The subscription count, not the size of the outcomes array, decides the fallback.
test('C3: held with subscriptions and no remaining retry; otherwise in-app', () => {
  assert.equal(eventStatus([exhausted], 1, retryable), 'held');
  assert.equal(eventStatus([], 1, retryable), 'held');
  assert.equal(eventStatus([], 0, retryable), 'in-app');
  assert.equal(eventStatus([exhausted], 0, retryable), 'in-app');
});
