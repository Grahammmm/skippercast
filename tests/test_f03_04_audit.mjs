import assert from 'node:assert/strict';
import test from 'node:test';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {decideHold, visionChain, VisionUnavailable} = await import('../server/advisor/vision/index.ts');

const clear = {kind: 'scenery', kind_confidence: 0.9, has_fish: false, text_present: false,
  has_person: false, person_confidence: 0, nsfw: false};
const image = {media_id: 'synthetic', mime: 'image/png', bytes: async () => new ArrayBuffer(1)};

function chain(answer, extraEnv = {}, providers) {
  let requests = 0;
  const vision = visionChain({ADVISOR_VISION_PROVIDERS: 'hermes', HERMES_VISION_URL: 'https://vision.invalid',
    HERMES_VISION_TOKEN: 'fixture', ...extraEnv}, {
    fetcher: async () => { requests++; return Response.json(answer); },
    now: () => 0, providers,
  });
  return {vision, requests: () => requests};
}

for (const [description, fields] of [
  ['kind only', {kind: 'scenery'}],
  ['missing has_person', {...clear, has_person: undefined}],
  ['mistyped has_person', {...clear, has_person: 'true'}],
  ['missing nsfw', {...clear, nsfw: undefined}],
  ['mistyped nsfw', {...clear, nsfw: 0}],
  ['missing person confidence', {...clear, has_person: true, person_confidence: undefined}],
  ['mistyped person confidence', {...clear, has_person: true, person_confidence: '0.9'}],
  ['negative person confidence', {...clear, has_person: true, person_confidence: -0.1}],
  ['person confidence above one', {...clear, person_confidence: 1.1}],
]) {
  test(`F03-04: ${description} cannot supply a classification when no fallback is available`, async () => {
    assert.equal(decideHold(fields), true, 'invalid moderation evidence must hold');
    const {vision, requests} = chain(fields);
    await assert.rejects(vision.classify(image), VisionUnavailable);
    assert.equal(requests(), 1);
  });
}

test('F03-04: well-formed clear evidence still classifies without a hold', async () => {
  const {vision, requests} = chain(clear);
  const result = await vision.classify(image);
  assert.equal(requests(), 1);
  assert.equal(result.provider, 'hermes');
  assert.equal(result.kind, 'scenery');
  assert.equal(decideHold(result), false);
});

test('F03-04: the fallback provider can supply a hold when Hermes omits safety fields', async () => {
  const claude = {name: 'claude', classify: async () => ({...clear, provider: 'claude', has_person: true, person_confidence: 0.5})};
  const {vision, requests} = chain({kind: 'scenery'}, {ADVISOR_VISION_PROVIDERS: 'hermes,claude'}, {claude});
  const result = await vision.classify(image);
  assert.equal(requests(), 1);
  assert.equal(result.provider, 'claude');
  assert.equal(decideHold(result), true);
});

test('F03-04: a cached partial answer is replaced by valid evidence before deciding a hold', async () => {
  const db = {prepare(query) {
    return {bind() { return {
      first: async () => query.includes('classification_json')
        ? {classification_json: JSON.stringify({classify: {kind: 'scenery'}})} : null,
      run: async () => {},
    }; }};
  }};
  const {vision, requests} = chain({...clear, nsfw: true}, {DB: db});
  const result = await vision.classify(image);
  assert.equal(requests(), 1);
  assert.equal(result.nsfw, true);
  assert.equal(decideHold(result), true);
});
