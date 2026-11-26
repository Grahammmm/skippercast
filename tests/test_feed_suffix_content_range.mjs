import assert from 'node:assert/strict';
import test from 'node:test';
import {serveFeed, useBucket} from '../server/feeds.ts';

const key = 'tiles/synthetic.pmtiles';
const path = `/feeds/${key}`;

// R2 reports the full size even when it streams only a slice. Treating suffix
// metadata as offset/length labels a short tail as the full object; an unclamped
// suffix calculation can also report bytes outside the object.
const cases = [
  ['bytes=-3', {suffix: 3}, '789', 'bytes 7-9/10'],
  ['bytes=-20', {suffix: 20}, '0123456789', 'bytes 0-9/10'],
  ['bytes=2-5', {offset: 2, length: 4}, '2345', 'bytes 2-5/10'],
  ['bytes=6-', {offset: 6}, '6789', 'bytes 6-9/10'],
  // The Workers runtime returns every R2Range key, unset ones undefined. Hosted stage/production cold reads of
  // bytes=0-16383 answered "bytes NaN-NaN/<size>" (2026-11-25), so the PMTiles relief header read was refused.
  ['bytes=0-3', {offset: 0, length: 4, suffix: undefined}, '0123', 'bytes 0-3/10'],
  ['bytes=2-5', {offset: 2, length: 4, suffix: undefined}, '2345', 'bytes 2-5/10'],
  ['bytes=6-', {offset: 6, length: undefined, suffix: undefined}, '6789', 'bytes 6-9/10'],
  ['bytes=-3', {offset: undefined, length: undefined, suffix: 3}, '789', 'bytes 7-9/10'],
];

for (const [header, range, bytes, contentRange] of cases) {
  test(`cold R2 ${header} ${JSON.stringify(Object.keys(range))} labels exactly the bytes served`, async t => {
    useBucket({FEEDS: {async get(requestedKey, options) {
      assert.equal(requestedKey, key);
      assert.equal(options.range.get('Range'), header);
      return {size: 10, httpEtag: '"fixture"', range, body: new Response(bytes).body};
    }}});
    t.after(() => useBucket(null));

    const response = await serveFeed(new Request(`https://skippercast.com${path}`, {headers: {Range: header}}), path, undefined);
    assert.equal(response.status, 206);
    assert.equal(response.headers.get('X-Feed-Source'), 'r2');
    assert.equal(response.headers.get('Content-Range'), contentRange);
    assert.equal(response.headers.get('Content-Length'), String(bytes.length));
    assert.equal(await response.text(), bytes);
  });
}
