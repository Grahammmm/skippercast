import test from 'node:test';
import assert from 'node:assert/strict';
import {saveTidePack, tidePackURLs, TIDE_DIRECTORY_URL} from '../web/tide-stations.ts';

const station = {id: '9000001', name: 'Fixture reference', lat: 35.1, lng: -121, type: 'R'};
const urls = tidePackURLs(station, Date.parse('2026-10-08T17:00:00Z'));
const enc = value => new TextEncoder().encode(JSON.stringify(value));
const good = {
  [urls[0]]: enc({stations: [station]}),
  [urls[1]]: enc({predictions: [{t: '2026-10-08 18:00', v: '3.2', type: 'H'}]}),
  [urls[2]]: enc({predictions: [{t: '2026-10-08 17:00', v: '1.2'}, {t: '2026-10-08 17:06', v: '1.3'}]}),
};
const LIVE = /^Error: Chosen tide station could not be saved from a live response\. Saved regions are unchanged\.$/;
const UNAVAILABLE = /^Error: Chosen tide predictions are unavailable\. Saved regions are unchanged\.$/;
const signal = new AbortController().signal;

// override: url -> {bytes?, status?, headers?}
const fakeFetcher = (override = {}) => {
  const seen = [];
  const fetcher = async (url, init) => {
    seen.push({url, init});
    const o = override[url] ?? {};
    return new Response(o.bytes ?? good[url], {status: o.status ?? 200, headers: o.headers ?? {'content-type': 'application/json'}});
  };
  return {fetcher, seen};
};
const recordingPut = (rejectAt = -1) => {
  const calls = [];
  const put = async (key, body, headers) => {
    calls.push({key, bytes: new Uint8Array(body), headers});
    if (calls.length - 1 === rejectAt) throw new Error('quota exceeded on put');
  };
  return {put, calls};
};
const failCase = async (override, message) => {
  const {fetcher, seen} = fakeFetcher(override);
  const {put, calls} = recordingPut();
  await assert.rejects(saveTidePack(urls, put, signal, fetcher), err => {
    assert.ok(!(err instanceof SyntaxError), 'no raw SyntaxError');
    assert.match(String(err), message);
    return true;
  });
  assert.equal(calls.length, 0, 'put is never called when any answer fails');
  return seen;
};

test('three good answers: put runs 3 times in URL order with the original bytes, after every fetch', async () => {
  assert.equal(urls.length, 3);
  assert.equal(urls[0], TIDE_DIRECTORY_URL);
  const {fetcher, seen} = fakeFetcher();
  const {put, calls} = recordingPut();
  const order = [];
  const tracingFetcher = async (url, init) => { order.push('fetch'); return fetcher(url, init); };
  const tracingPut = async (...args) => { order.push('put'); return put(...args); };
  await saveTidePack(urls, tracingPut, signal, tracingFetcher);
  assert.deepEqual(order, ['fetch', 'fetch', 'fetch', 'put', 'put', 'put']);
  assert.deepEqual(calls.map(c => c.key), urls);
  calls.forEach((c, i) => assert.deepEqual(c.bytes, good[urls[i]]));
  assert.ok(calls.every(c => c.headers instanceof Headers));
  assert.deepEqual(seen.map(s => s.url), urls);
  assert.ok(seen.every(s => s.init.credentials === 'omit' && s.init.cache === 'no-cache' && s.init.signal === signal));
});

test('6-minute URL answering HTTP 500 gives the live-response message and stores nothing', async () => {
  const seen = await failCase({[urls[2]]: {status: 500}}, LIVE);
  assert.equal(seen.length, 3);
});

test('hilo answering <html> with HTTP 200 gives the unavailable message, not a SyntaxError', async () => {
  const seen = await failCase({[urls[1]]: {bytes: new TextEncoder().encode('<html><body>Bad gateway</body></html>'), headers: {'content-type': 'text/html'}}}, UNAVAILABLE);
  assert.equal(seen.length, 2, 'stops at the failing answer');
});

test('a cut-off JSON body gives the unavailable message', async () => {
  await failCase({[urls[2]]: {bytes: good[urls[2]].slice(0, 20)}}, UNAVAILABLE);
});

test('directory body with invalid UTF-8 (0xff) gives the unavailable message', async () => {
  const bytes = new Uint8Array([...new TextEncoder().encode('{"stations": ["'), 0xff, ...new TextEncoder().encode('"]}')]);
  const seen = await failCase({[urls[0]]: {bytes}}, UNAVAILABLE);
  assert.equal(seen.length, 1);
});

test('X-SC-Offline on the last URL gives the live-response message and stores nothing', async () => {
  await failCase({[urls[2]]: {headers: {'content-type': 'application/json', 'X-SC-Offline': '2026-10-08T16:00:00Z'}}}, LIVE);
});

test('NOAA error body on hilo gives the unavailable message and stores nothing', async () => {
  await failCase({[urls[1]]: {bytes: enc({error: {message: 'No Predictions data was found.'}})}}, UNAVAILABLE);
});

test('a put rejection on the 2nd item propagates unchanged and the 3rd put is not called', async () => {
  const {fetcher} = fakeFetcher();
  const {put, calls} = recordingPut(1);
  await assert.rejects(saveTidePack(urls, put, signal, fetcher), /^Error: quota exceeded on put$/);
  assert.deepEqual(calls.map(c => c.key), urls.slice(0, 2));
});
