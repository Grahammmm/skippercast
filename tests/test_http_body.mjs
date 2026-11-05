// server/http.ts body(): invalid UTF-8 is refused as 'invalid JSON body' (fatal decoder) instead of
// being accepted with U+FFFD; a BOM is still stripped, and the size cap, empty-body and object-only rules
// are unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

// http.ts imports server/config.ts, which reads the build-time globals.
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {body} = await import('../server/http.ts');
const {ClientError} = await import('../server/errors.ts');

const enc = new TextEncoder();
const bytes = (...parts) => new Uint8Array(parts.flatMap(p => typeof p === 'string' ? [...enc.encode(p)] : p));
const post = (data, headers = {}) => new Request('https://example.test/', {method: 'POST', body: data, headers});
/** A body streamed in chunks with no content-length header. */
const streamed = (...chunks) => new Request('https://example.test/', {method: 'POST', duplex: 'half', body: new ReadableStream({start(c) { for (const chunk of chunks) c.enqueue(chunk); c.close(); }})});
const refused = async (request, message) => {
  await assert.rejects(body(request), error => error instanceof ClientError && error.message === message);
};

test('valid UTF-8 with non-ASCII text is returned with identical text', async () => {
  const name = 'Señor Ño 🎣';
  const value = await body(post(bytes(JSON.stringify({name}))));
  assert.equal(value.name, name);
  assert.ok(!value.name.includes('\uFFFD'));
});

test('invalid UTF-8 inside a string is refused as invalid JSON body', async () => {
  await refused(post(bytes('{"a":"', [0xC3, 0x28], '"}')), 'invalid JSON body');
});

test('a lone continuation byte is refused', async () => {
  await refused(post(bytes('{"a":"', [0x80], '"}')), 'invalid JSON body');
});

test('an overlong encoding is refused', async () => {
  await refused(post(bytes('{"a":"', [0xC0, 0xAF], '"}')), 'invalid JSON body');
});

test('a multi-byte character cut at the end is refused', async () => {
  const cut = bytes('{"a":"é').slice(0, -1);
  await refused(post(cut), 'invalid JSON body');
});

test('a multi-byte character split across stream chunks still decodes', async () => {
  const whole = bytes('{"a":"é"}'), at = whole.indexOf(0xC3) + 1;
  assert.deepEqual(await body(streamed(whole.slice(0, at), whole.slice(at))), {a: 'é'});
});

test('a UTF-8 BOM is stripped (unchanged)', async () => {
  assert.deepEqual(await body(post(bytes([0xEF, 0xBB, 0xBF], '{"a":1}'))), {a: 1});
});

test('a BOM followed by invalid UTF-8 is still refused', async () => {
  await refused(post(bytes([0xEF, 0xBB, 0xBF], '{"a":"', [0x80], '"}')), 'invalid JSON body');
});

test('unchanged: an array and an empty stream are invalid JSON body', async () => {
  await refused(post(bytes('[]')), 'invalid JSON body');
  await refused(streamed(), 'invalid JSON body');
});

test('unchanged: no body is invalid empty body', async () => {
  await refused(new Request('https://example.test/', {method: 'POST'}), 'invalid empty body');
});

test('unchanged: content-length over the cap is body too large', async () => {
  await refused(post(bytes('{}'), {'content-length': '9000'}), 'body too large');
});

test('unchanged: a streamed 8193-byte body without content-length is body too large', async () => {
  const big = bytes(`{"a":"${'x'.repeat(8193 - 8)}"}`);
  assert.equal(big.length, 8193);
  const request = streamed(big.slice(0, 4096), big.slice(4096));
  assert.equal(request.headers.get('content-length'), null);
  await refused(request, 'body too large');
});

test('unchanged: exactly 8192 bytes of a valid object is accepted', async () => {
  const exact = bytes(`{"a":"${'é'.repeat((8192 - 8) / 2)}"}`);
  assert.equal(exact.length, 8192);
  const value = await body(streamed(exact));
  assert.equal(value.a.length, (8192 - 8) / 2);
});

/** A pull-driven stream (no read-ahead) that counts pulls and cancels; `cancel` decides how cancellation fails. */
const open = (chunks, cancel) => {
  const seen = {cancels: 0, pulls: 0};
  const stream = new ReadableStream({
    pull(c) { seen.pulls++; if (chunks.length) c.enqueue(chunks.shift()); else c.close(); },
    cancel() { seen.cancels++; return cancel(); },
  }, {highWaterMark: 0});
  return {seen, request: new Request('https://example.test/', {method: 'POST', duplex: 'half', body: stream})};
};
const big = n => bytes(`{"a":"${'x'.repeat(n - 8)}"}`);

test('oversize_cancel_rejects_keeps_client_error: a rejecting cancel does not replace body too large', async () => {
  const {seen, request} = open([big(8193)], () => Promise.reject(Error('synthetic cancel failure')));
  await refused(request, 'body too large');
  assert.equal(seen.cancels, 1);
});

test('oversize_cancel_throws_keeps_client_error: a throwing cancel, crossing split over chunks, custom cap', async () => {
  const whole = big(40), {seen, request} = open([whole.slice(0, 15), whole.slice(15, 30), whole.slice(30), bytes('late')], () => { throw Error('synthetic cancel throw'); });
  await assert.rejects(body(request, 32), error => error instanceof ClientError && error.message === 'body too large');
  assert.equal(seen.cancels, 1);
  assert.equal(seen.pulls, 3, "no read after the crossing chunk");
});

test('oversize_successful_cancel_and_exact_limit_unchanged', async () => {
  const {seen, request} = open([big(8193)], () => undefined);
  await refused(request, 'body too large');
  assert.equal(seen.cancels, 1);
  const exact = open([bytes(`{"a":"${'é'.repeat((8192 - 8) / 2)}"}`)], () => { throw Error('must not cancel'); });
  assert.equal((await body(exact.request)).a.length, (8192 - 8) / 2);
  assert.equal(exact.seen.cancels, 0);
});

test('read_error_is_not_relabelled_oversize: a read failure before the cap keeps its own rejection', async () => {
  const failing = new ReadableStream({pull(c) { c.error(Error('synthetic read failure')); }});
  const request = new Request('https://example.test/', {method: 'POST', duplex: 'half', body: failing});
  await assert.rejects(body(request), error => !(error instanceof ClientError) && error.message === 'synthetic read failure');
});
