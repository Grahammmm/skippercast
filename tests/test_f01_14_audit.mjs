// F01-14 / SCA-466: the throw-only stubAdapter factory is gone (all four adapters are real and
// registered), while ChannelNotImplemented stays for the optional media capability.
// Contract protected: ADAPTERS has the four concrete transports; none of them is a placeholder that throws
// ChannelNotImplemented; a missing fetchMediaByRef still raises ChannelNotImplemented.
// Bug that fails it: re-adding a placeholder factory or registering one in ADAPTERS (the negative control
// shows the "throws ChannelNotImplemented" probe really detects one), or deleting the error type the
// media path and the consumer's failed-not-unknown classification depend on.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync, readdirSync} from 'node:fs';

globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const channels = await import('../server/advisor/channels/index.ts');
const {ADAPTERS, ChannelNotImplemented, fetchMediaByRef} = channels;

/** True when a send through the adapter, with nothing configured, throws ChannelNotImplemented. */
const isPlaceholder = adapter => adapter.send({id: 'x', to: 'y'}, {}).then(() => false, error => error instanceof ChannelNotImplemented);

test('negative control: a throw-only adapter is what the placeholder probe detects', async () => {
  const fail = async () => { throw new ChannelNotImplemented('synthetic'); };
  assert.equal(await isPlaceholder({send: fail}), true);
});

test('all four concrete adapters are registered and none is a placeholder', async () => {
  assert.deepEqual(Object.keys(ADAPTERS).sort(), ['bluebubbles', 'instagram', 'twilio', 'web']);
  for (const [name, adapter] of Object.entries(ADAPTERS)) {
    assert.equal(adapter.name, name);
    for (const method of ['normalize', 'send', 'health']) assert.equal(typeof adapter[method], 'function', `${name}.${method}`);
    assert.equal(await isPlaceholder(adapter), false, `${name} must not throw ChannelNotImplemented from send`);
  }
});

test('stubAdapter is not exported or referenced anywhere under server/', () => {
  assert.equal('stubAdapter' in channels, false);
  const files = readdirSync(new URL('../server/', import.meta.url), {recursive: true}).filter(file => /\.(ts|tsx|js|mjs)$/.test(file));
  assert.ok(files.length > 50, 'the scan saw the server tree');
  const hits = files.filter(file => /\bstubAdapter\b/.test(readFileSync(new URL(`../server/${file}`, import.meta.url), 'utf8')));
  assert.deepEqual(hits, []);
});

test('positive control: the missing-media capability still raises ChannelNotImplemented', async () => {
  assert.equal(ADAPTERS.web.fetchMediaByRef, undefined, 'the web adapter has no media download');
  await assert.rejects(fetchMediaByRef('x', 'web', {}), error => error instanceof ChannelNotImplemented && error.name === 'ChannelNotImplemented' && /web channel not implemented/.test(error.message));
});
