import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {fixtureImages, runConformance} from '../scripts/advisor/vision-conformance.mjs';

const fixtures = fixtureImages(); // Committed synthetic images, not customer photos.
const fixtureInput = name => JSON.parse(readFileSync(new URL(`./fixtures/advisor/vision/${name}.json`, import.meta.url))).content[0].input;
const answers = {
  '/v1/vision/classify': fixtureInput('classify-fish'),
  '/v1/vision/count-board': fixtureInput('count-board'),
  '/v1/vision/fish-id': fixtureInput('fish-id'),
};

async function run(images) {
  const posts = [];
  const result = await runConformance({
    base: 'https://vision.invalid', token: 'fixture-only', clock: () => 0, images,
    fetcher: async (url, {method, headers, body}) => {
      const path = new URL(url).pathname;
      if (method === 'GET' && path === '/v1/health') return Response.json({ok: true, models: {classify: 'synthetic'}});
      assert.equal(method, 'POST');
      assert.ok(Object.hasOwn(answers, path), path);
      const name = body.get('image').name;
      const authorized = typeof headers.authorization === 'string';
      posts.push({path, name, authorized});
      if (!authorized) return Response.json({error: 'unauthorized'}, {status: 401});
      return Response.json(answers[path], {headers: {'x-vision-model': 'synthetic'}});
    },
  });
  return {...result, posts};
}

// A healthy service used to PASS without images; merely checking the length
// would still allow a missing named case or a zero-byte placeholder.
for (const [label, images, missing] of [
  ['empty', [], ['blank.png', 'count-board.png', 'deck-person.png', 'fish.png']],
  ['wrong names despite a full count', fixtures.map(i => i.name === 'deck-person.png' ? {...i, name: 'replacement.png'} : i), ['deck-person.png']],
  ['empty required image', fixtures.map(i => i.name === 'fish.png' ? {...i, bytes: Buffer.alloc(0)} : i), ['fish.png']],
]) {
  test(`healthy service does not pass with fixture set: ${label}`, async () => {
    const {results, failed, posts} = await run(images);
    assert.equal(results.find(r => r.check === 'GET /v1/health')?.status, 'PASS');
    assert.equal(failed, true, JSON.stringify(results));
    const fixtureFailure = results.find(r => r.status === 'FAIL' && r.check === 'required image fixtures');
    assert.ok(fixtureFailure, JSON.stringify(results));
    for (const name of missing) assert.ok(fixtureFailure.detail.includes(name), fixtureFailure.detail);
    assert.deepEqual(posts, []);
  });
}

// A full set must actually send each image to each endpoint; neither health
// nor the single unauthenticated classify request counts as method coverage.
test('full set passes with an authenticated check for every image and method', async () => {
  const {results, failed, posts} = await run(fixtures);
  assert.equal(failed, false, JSON.stringify(results));
  const expected = ['blank.png', 'count-board.png', 'deck-person.png', 'fish.png'].flatMap(name =>
    ['/v1/vision/classify', '/v1/vision/count-board', '/v1/vision/fish-id'].map(path => `${path} ${name}`),
  );
  assert.deepEqual(posts.filter(p => p.authorized).map(p => `${p.path} ${p.name}`).sort(), expected.sort());
  assert.deepEqual(posts.filter(p => !p.authorized).map(p => p.path), ['/v1/vision/classify']);
  assert.equal(results.find(r => r.check === 'a request without the token is refused')?.status, 'PASS');
});
