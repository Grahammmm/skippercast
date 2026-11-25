import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import test from 'node:test';
import {reliefVerifier} from '../web/map/relief-verify.ts';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const payload = new TextEncoder().encode('fixture relief tile').buffer;
const digest = sha(new Uint8Array(payload));

function verifier(rows, chunkPath = '2/0_0.json', {signal = new AbortController().signal, requests = []} = {}) {
  const chunk = JSON.stringify(rows);
  const root = JSON.stringify({chunks: {[chunkPath]: sha(chunk)}});
  const rootHash = sha(root);
  const objectKey = `tiles/relief/fixture/${'a'.repeat(64)}.pmtiles`;
  const prefix = `/feeds/${objectKey.slice(0, -'.pmtiles'.length)}.digests/${rootHash}/`;
  const fixtures = new Map([[prefix + 'root.json', root], [prefix + chunkPath, chunk]]);
  return reliefVerifier({object_key: objectKey, digest_root_sha256: rootHash}, 'https://chart.test/map',
    async url => {
      assert.ok(fixtures.has(url.pathname), `Unexpected fixture request: ${url.pathname}`);
      requests.push(url.pathname.slice(prefix.length));
      return new Response(fixtures.get(url.pathname));
    }, signal);
}

const validRows = [[0, 0, digest], [3, 3, digest]];

// At z=2, coordinate 4 is outside the matrix but still in block 0.
// The entire chunk must fail even if the requested row is valid and comes first.
for (const [axis, x, y] of [['x', 4, 0], ['y', 0, 4]]) {
  test(`rejects a correctly hashed relief chunk with ${axis} at the matrix limit`, async () => {
    const verify = verifier([...validRows, [x, y, digest]]);
    await assert.rejects(verify(2, 0, 0, payload), /Invalid relief digest row/);
  });
}

// Even a matching negative block cannot authorize a row outside the matrix.
for (const [axis, x, y, chunkPath] of [['x', -1, 0, '2/-1_0.json'], ['y', 0, -1, '2/0_-1.json']]) {
  test(`rejects negative relief ${axis} in its matching block`, async () => {
    const verify = verifier([[x, y, digest]], chunkPath);
    await assert.rejects(verify(2, x, y, payload), /Invalid relief digest row/);
  });
}

// Removing only the impossible row restores the valid tile, both inclusive
// endpoints are legal, and an unindexed coordinate in that chunk stays a hole.
test('verifies both matrix endpoints and preserves a sparse hole after removing the bad row', async () => {
  const requests = [];
  const verify = verifier(validRows, undefined, {requests});
  await verify(2, 0, 0, payload);
  await verify(2, 3, 3, payload);
  assert.equal(await verify(2, 1, 1, undefined), undefined);
  await assert.rejects(verify(2, 0, 0, undefined), /Indexed relief tile missing from archive/);
  await assert.rejects(verify(2, 1, 1, payload), /Missing relief tile digest/);
  await assert.rejects(verify(2, 0, 0, new ArrayBuffer(1)), /Relief tile hash mismatch/);
  assert.deepEqual(requests, ['root.json', '2/0_0.json']);
});

// Once the index is warm, fetch no longer observes teardown: even an
// authentic result must not be delivered to the cancelled Chart owner.
for (const [label, xyz, data] of [
  ['indexed tile', [2, 0, 0], payload],
  ['authenticated hole', [2, 1, 1], undefined],
]) {
  test(`rejects a warm ${label} if the owner was already cancelled`, async () => {
    const owner = new AbortController();
    const requests = [];
    const verify = verifier(validRows, undefined, {signal: owner.signal, requests});
    await verify(...xyz, data);
    owner.abort(new Error('Chart owner disposed'));
    await assert.rejects(verify(...xyz, data), error => error === owner.signal.reason);
    assert.deepEqual(requests, ['root.json', '2/0_0.json']);
  });
}

for (const [join, xyz] of [['root', [7, 64, 0]], ['chunk', [2, 1, 1]]]) {
  test(`rejects an authenticated hole cancelled during the warm ${join} join`, async () => {
    const owner = new AbortController();
    const requests = [];
    const verify = verifier(validRows, undefined, {signal: owner.signal, requests});
    await verify(2, 0, 0, payload);
    assert.equal(await verify(...xyz, undefined), undefined);
    const pending = verify(...xyz, undefined);
    // For the chunk case, let the cached root continuation reach the chunk await.
    if (join === 'chunk') await Promise.resolve();
    owner.abort(new Error('Chart owner disposed'));
    await assert.rejects(pending, error => error === owner.signal.reason);
    assert.deepEqual(requests, ['root.json', '2/0_0.json']);
  });
}

test('discards a matching relief tile cancelled while its digest is pending', async t => {
  const owner = new AbortController();
  const requests = [];
  const verify = verifier(validRows, undefined, {signal: owner.signal, requests});
  await verify(2, 0, 0, payload);

  const started = Promise.withResolvers();
  const release = Promise.withResolvers();
  const digest = crypto.subtle.digest.bind(crypto.subtle);
  t.mock.method(crypto.subtle, 'digest', async (algorithm, bytes) => {
    assert.equal(bytes, payload);
    started.resolve();
    await release.promise;
    return digest(algorithm, bytes);
  });
  const pending = verify(2, 0, 0, payload);
  await Promise.race([started.promise, pending.then(() => assert.fail('Tile returned before hashing'))]);
  owner.abort(new Error('Chart owner disposed'));
  release.resolve();
  await assert.rejects(pending, error => error === owner.signal.reason);
  assert.deepEqual(requests, ['root.json', '2/0_0.json']);
});
