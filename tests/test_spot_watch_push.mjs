import test from 'node:test';
import assert from 'node:assert/strict';
import {PUSH_BODY_MAX, spotWatchEventId, spotWatchPush, spotWatchUrl} from '../server/spot-watch-push.ts';

const input = Object.freeze({
  watchId: 'w-7', sampleAt: '2026-11-19T12:30:00Z', region: 'central-2',
  spotId: 's-9', layer: 'water-temp', spotName: 'Ridge 41', title: 'Water update',
});
const success = body => ({
  ok: true,
  push: {
    title: 'Water update', body,
    eventId: 'spotwatch:w-7:2026-11-19T12:30:00Z',
    url: '/map?region=central-2&spot=s-9&layers=water-temp',
  },
});

// Normalizing the timestamp or encoding the ID would change the deduplication key.
test('C1: preserve the ID and timestamp verbatim in the event key', () => {
  assert.equal(spotWatchEventId('w/7', '2026-11-19T04:30:00-08:00'),
    'spotwatch:w/7:2026-11-19T04:30:00-08:00');
});

// Neither required part may silently produce an incomplete key.
test('C1: reject either missing event-key component', () => {
  assert.throws(() => spotWatchEventId('', input.sampleAt), TypeError);
  assert.throws(() => spotWatchEventId(input.watchId, ''), TypeError);
});

// A spot ID must not split the query or set a fragment; a layer must not default silently.
test('C2: encode the spot ID and select each supported layer', () => {
  for (const layer of ['water-temp', 'chlorophyll', 'sst-contrast']) {
    assert.equal(spotWatchUrl('central-2', 'Café /?&=#%🐚', layer),
      `/map?region=central-2&spot=Caf%C3%A9%20%2F%3F%26%3D%23%25%F0%9F%90%9A&layers=${layer}`);
  }
});

// Encoding is not a substitute for rejecting malformed region slugs and unsupported inputs.
test('C2: reject bad region slugs, an empty spot ID and unsupported layers', () => {
  for (const region of ['', 'Central', 'central_2', 'central &west', 'café', 'central/2']) {
    assert.throws(() => spotWatchUrl(region, 's-9', 'water-temp'), TypeError, JSON.stringify(region));
  }
  assert.throws(() => spotWatchUrl('central-2', '', 'water-temp'), TypeError);
  assert.throws(() => spotWatchUrl('central-2', 's-9', 'fronts'), TypeError);
});

// The transport consumes all four fields, and the renderer owns the full short body.
test('C3: return the complete payload for a short body', () => {
  const watch = {...input, watchId: 'w-8', region: 'south-1', spotId: 's/9', layer: 'chlorophyll', title: 'Watch 8'};
  assert.deepEqual(spotWatchPush(watch, name => `${name}: 1 mg/m³`), {
    ok: true,
    push: {title: 'Watch 8', body: 'Ridge 41: 1 mg/m³', eventId: 'spotwatch:w-8:2026-11-19T12:30:00Z',
      url: '/map?region=south-1&spot=s%2F9&layers=chlorophyll'},
  });
});

// Do not convert helper errors into refusals or wrap them in a generic error.
test('C3: propagate event-ID and URL errors', () => {
  assert.throws(() => spotWatchPush({...input, watchId: ''}, name => name), TypeError);
  assert.throws(() => spotWatchPush({...input, region: 'BAD'}, name => name), TypeError);
  assert.throws(() => spotWatchPush({...input, spotId: '\uD800'}, name => name), URIError);
});

// A failure on a later retry must not be swallowed as a length refusal.
test('C3: propagate the original renderer error at every stage', () => {
  const error = new RangeError('fixture render failed');
  for (const failedName of ['', 'Ridge 41', 'Ridge 4…']) {
    assert.throws(() => spotWatchPush(input, name => {
      if (name === failedName) throw error;
      return 'x'.repeat(121);
    }), thrown => thrown === error);
  }
});

// Counting UTF-16 code units would truncate a body that already fits.
test('C4: preserve a body of exactly 120 code points', () => {
  const spotName = '🐚'.repeat(118) + 'é';
  assert.equal(PUSH_BODY_MAX, 120);
  assert.deepEqual(spotWatchPush({...input, spotName}, name => `${name}!`), success(`${spotName}!`));
});

// Cutting UTF-16 units can split the emoji; clipping the body would lose the closing paren.
test('C4: shorten an overlong accented name to exactly 120 code points', () => {
  const prefix = 'é'.repeat(116) + '🐚';
  assert.deepEqual(spotWatchPush({...input, spotName: prefix + 'Extra'}, name => `(${name})`),
    success(`(${prefix}…)`));
});

// Counting graphemes instead of code points would keep the second combining mark.
test('C4: count combining marks separately and keep the longest fitting prefix', () => {
  const frame = 'x'.repeat(116);
  const spotName = 'e\u0301e\u0301z';
  assert.deepEqual(spotWatchPush({...input, spotName}, name => frame + name),
    success(frame + 'e\u0301e…'));
});

// The last retry must accept a fitting one-code-point prefix rather than refuse it.
test('C4: retain one code point when that is all that fits', () => {
  const frame = 'x'.repeat(118);
  assert.deepEqual(spotWatchPush({...input, spotName: '🐚ét'}, name => frame + name),
    success(frame + '🐚…'));
});

// Ellipsis alone would erase the name; clipping fixed text would hide the template overflow.
test('C4: refuse when even a one-code-point name plus the ellipsis will not fit', () => {
  for (const frame of ['x'.repeat(119), 'x'.repeat(121)]) {
    assert.deepEqual(spotWatchPush(input, name => frame + name), {ok: false, reason: 'too-long'});
  }
  assert.deepEqual(spotWatchPush({...input, spotName: ''}, name => 'x'.repeat(121) + name),
    {ok: false, reason: 'too-long'});
});

// Checking the rendered body instead of the empty-name template would reject a user's name.
test('C5: keep claim words in a spot name and allow template substrings', () => {
  assert.deepEqual(spotWatchPush({...input, spotName: 'Fish Rock'}, name => `${name}: sandbite shelf`),
    success('Fish Rock: sandbite shelf'));
});

// A case-sensitive, singular-only or space-only matcher would miss a forbidden template.
test('C5: reject each claim form in the template before deciding length', () => {
  for (const word of ['FiSh', 'FISHING', 'Bite', 'bites', 'HOT SPOT', 'hot spots', 'hotspot', 'hotspots']) {
    for (const tail of ['', 'x'.repeat(120)]) {
      const result = spotWatchPush(input, name => `${name}: (${word}) ${tail}`);
      assert.deepEqual(result, {ok: false, reason: 'claim-words'}, word);
    }
  }
});
