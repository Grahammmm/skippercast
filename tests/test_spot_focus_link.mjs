import test from 'node:test';
import assert from 'node:assert/strict';
import {spotWatchUrl} from '../server/spot-watch-push.ts';
import {readSpotFocus} from '../web/spot-focus-link.ts';

const region = 'central-2';
const spotId = 'Spot_9-west';
const query = `region=${region}&spot=${spotId}&layers=water-temp`;

test('C1: accept both query forms without filtering unrelated parameters or changing IDs', () => {
  const expected = {region, spotId, layer: 'water-temp'};
  assert.deepEqual(readSpotFocus(query), expected);
  assert.deepEqual(readSpotFocus(`?${query}&mode=&mode=chart`), expected);
  assert.deepEqual(readSpotFocus(new URLSearchParams(query)), expected);
});

// A first- or last-value lookup could pick a focus from an ambiguous link.
for (const key of ['region', 'spot', 'layers']) {
  test(`C1: refuse a missing or repeated ${key}, even an identical repeat`, () => {
    const params = new URLSearchParams(query);
    params.append(key, params.get(key));
    assert.deepEqual(readSpotFocus(params), null);
    params.delete(key);
    assert.deepEqual(readSpotFocus(params), null);
  });
}

// Validate decoded values without trimming, folding case, or accepting URI punctuation.
for (const [key, values] of [
  ['region', ['', 'Central-2', 'central_2', 'central%0A', 'central%2F2']],
  ['spot', ['', 'Spot+9', 'Spot%2F9', 'Spot%ZZ', 'Spot%FF', 'Spot%0A']],
  ['layers', ['', 'sst-fronts', 'Water-temp', 'water-temp%2Cchlorophyll']],
]) {
  test(`C1: refuse malformed ${key} values`, () => {
    const rest = query.split('&').filter(part => !part.startsWith(`${key}=`)).join('&');
    for (const value of values) {
      assert.deepEqual(readSpotFocus(`${rest}&${key}=${value}`), null, `${key}=${value}`);
    }
  });
}

test('C1: preserve IDs at both length limits and refuse oversize IDs rather than truncating', () => {
  for (const size of [1, 64]) {
    const region = 'a'.repeat(size);
    const spotId = '_'.repeat(size);
    assert.deepEqual(readSpotFocus(`region=${region}&spot=${spotId}&layers=chlorophyll`),
      {region, spotId, layer: 'chlorophyll'});
  }
  for (const size of [65, 4096]) {
    assert.deepEqual(readSpotFocus(`region=${'a'.repeat(size)}&spot=${spotId}&layers=water-temp`), null);
    assert.deepEqual(readSpotFocus(`region=${region}&spot=${'s'.repeat(size)}&layers=water-temp`), null);
  }
});

for (const layer of ['water-temp', 'chlorophyll', 'sst-contrast']) {
  test(`C2: read the exact focus from the server's ${layer} link`, () => {
    const url = new URL(spotWatchUrl(region, spotId, layer), 'https://example.test');
    assert.deepEqual(readSpotFocus(url.search), {region, spotId, layer});
  });
}
