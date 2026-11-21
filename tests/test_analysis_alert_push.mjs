import assert from 'node:assert/strict';
import test from 'node:test';
import {analysisAlertPush, analysisEventId, analysisUrl} from '../server/analysis-alert-push.ts';

const alert = Object.freeze({
  owner: 'private-fixture-owner', region: 'central-2', layer: 'sst-analysis',
  sampleAt: '2026-11-19T04:30:00-08:00',
});
const title = 'Analysis update';
const success = body => ({
  ok: true,
  push: {
    title, body,
    eventId: 'analysis:central-2:sst-analysis:2026-11-19T04:30:00-08:00',
    url: '/map?region=central-2&layers=water-temp',
  },
});

// Owner scoping or timestamp normalization would change the deduplication key.
test('C1: preserve the publication identity verbatim without the owner', () => {
  assert.equal(analysisEventId(alert), 'analysis:central-2:sst-analysis:2026-11-19T04:30:00-08:00');
  assert.equal(analysisEventId({...alert, owner: 'another-owner', layer: 'chlorophyll-observation'}),
    'analysis:central-2:chlorophyll-observation:2026-11-19T04:30:00-08:00');
});

// Defaulting a missing field or accepting a map-layer ID would create a bogus event key.
test('C1: reject empty identity fields and unknown analysis layers', () => {
  for (const overrides of [{region: ''}, {sampleAt: ''}, {layer: 'water-temp'}]) {
    assert.throws(() => analysisEventId({...alert, ...overrides}), TypeError);
  }
});

// The map consumes display layer IDs, not publication layer IDs.
test('C2: link each analysis layer to its matching map overlay', () => {
  assert.equal(analysisUrl('central-2', 'sst-analysis'), '/map?region=central-2&layers=water-temp');
  assert.equal(analysisUrl('south-1', 'chlorophyll-observation'), '/map?region=south-1&layers=chlorophyll');
});

// Encoding alone does not enforce the region allowlist; unknown layers must not silently default.
test('C2: reject malformed region slugs and unsupported layers', () => {
  for (const region of ['', 'Central', 'central_2', 'café', 'central/2', 'central&layers=x', 'central\n']) {
    assert.throws(() => analysisUrl(region, 'sst-analysis'), TypeError, JSON.stringify(region));
  }
  assert.throws(() => analysisUrl('central-2', 'toString'), TypeError);
});

// Whole payload assertions catch leaks (including extra keys) and partial layer wiring.
test('C3: return complete owner-free payloads for both layers', () => {
  const render = name => `Update for ${name}`;
  assert.deepEqual(analysisAlertPush(alert, title, 'Central', render), success('Update for Central'));
  assert.deepEqual(analysisAlertPush({...alert, layer: 'chlorophyll-observation'}, title, 'Central', render), {
    ok: true,
    push: {
      title, body: 'Update for Central',
      eventId: 'analysis:central-2:chlorophyll-observation:2026-11-19T04:30:00-08:00',
      url: '/map?region=central-2&layers=chlorophyll',
    },
  });
});

// Payload assembly must not convert either helper's validation error into a render refusal.
test('C3: propagate ID and URL validation errors', () => {
  assert.throws(() => analysisAlertPush({...alert, sampleAt: ''}, title, 'Central', name => name), TypeError);
  assert.throws(() => analysisAlertPush({...alert, region: 'BAD'}, title, 'Central', name => name), TypeError);
});

// Case-sensitive, singular-only or space-only screening would miss these forms.
test('C3: reject each whole claim form even when the template is also too long', () => {
  for (const word of ['FiSh', 'FISHING', 'Bite', 'bites', 'HOT SPOT', 'hot spots', 'hotspot', 'hotspots',
    'BeSt', 'PREDICT', 'Predicts', 'predicted']) {
    for (const tail of ['', 'x'.repeat(120)]) {
      assert.deepEqual(analysisAlertPush(alert, title, 'Central', name => `${name}: (${word}) ${tail}`),
        {ok: false, reason: 'claim-words'}, word);
    }
  }
});

// Screening the title or the filled body, or omitting word boundaries, would reject this payload.
test('C3: screen only the template and allow substrings of longer words', () => {
  const result = analysisAlertPush(alert, 'Best', 'Fish Rock', name => `${name}: sandbite, bested, unpredictable`);
  const expected = success('Fish Rock: sandbite, bested, unpredictable');
  assert.deepEqual(result, {...expected, push: {...expected.push, title: 'Best'}});
});

// UTF-16 length would truncate the first body, and slicing the body could lose the closing delimiter.
test('C3: accept 120 code points and shorten by re-rendering the longest fitting prefix', () => {
  const prefix = 'é'.repeat(116) + '🐚';
  const render = name => `(${name})`;
  assert.deepEqual(analysisAlertPush(alert, title, prefix + 'z', render), success(`(${prefix}z)`));
  assert.deepEqual(analysisAlertPush(alert, title, prefix + 'Extra', render), success(`(${prefix}…)`));
});

// Off-by-one retries would either skip the last prefix or send an ellipsis without any name.
test('C3: try a one-code-point prefix but refuse if it cannot fit with the ellipsis', () => {
  const render = name => 'x'.repeat(118) + name;
  assert.deepEqual(analysisAlertPush(alert, title, '🐚ét', render), success('x'.repeat(118) + '🐚…'));
  assert.deepEqual(analysisAlertPush(alert, title, '🐚ét', name => 'x' + render(name)),
    {ok: false, reason: 'too-long'});
  assert.deepEqual(analysisAlertPush(alert, title, '', name => 'x'.repeat(121) + name),
    {ok: false, reason: 'too-long'});
});

// Renderer exceptions are not successful payloads or expected copy refusals.
test('C3: propagate renderer errors during screening, rendering and shortening', () => {
  for (const failedName of ['', 'Bay', 'Ba…']) {
    assert.throws(() => analysisAlertPush(alert, title, 'Bay', name => {
      if (name === failedName) throw new RangeError('Fixture renderer failed');
      return 'x'.repeat(121);
    }), RangeError);
  }
});
