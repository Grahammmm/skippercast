// RF0721-4: a carried boat-entry request read from session storage is still
// answered true when removing its marker fails (web/boat-entry.ts takeAsk).
// Cleanup is best-effort; a failed removal may let a later read ask again.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'boat-ask-')), 'boat-entry.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: "export {takeAsk, ASK_KEY, ASK_PARAM} from './web/boat-entry.ts';"},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent',
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

const MAP = 'https://map.example.invalid/map?region=morro-bay';

// Synthetic storage with independent failure switches and call counters.
function store(initial = {}, {failGet = false, failRemove = false} = {}) {
  const s = {
    map: new Map(Object.entries(initial)), failGet, failRemove,
    gets: [], removes: [], sets: [],
    getItem(k) { s.gets.push(k); if (s.failGet) throw new Error('get denied'); return s.map.has(k) ? s.map.get(k) : null; },
    removeItem(k) { s.removes.push(k); if (s.failRemove) throw new Error('remove denied'); s.map.delete(k); },
    setItem(k, v) { s.sets.push(k); s.map.set(k, v); },
  };
  return s;
}

test('read_marker_cleanup_throws_still_asks', async () => {
  const {takeAsk, ASK_KEY} = await load();
  const s = store({[ASK_KEY]: 'ask'}, {failRemove: true});
  assert.equal(takeAsk(MAP, s), true);
  assert.equal(s.gets.length, 1);
  assert.equal(s.removes.length, 1);
  assert.equal(s.sets.length, 0);
});

test('healthy_cleanup_consumes_once', async () => {
  const {takeAsk, ASK_KEY} = await load();
  const s = store({[ASK_KEY]: 'ask', other: 'keep'});
  assert.equal(takeAsk(MAP, s), true);
  assert.equal(s.map.has(ASK_KEY), false);
  assert.equal(takeAsk(MAP, s), false);
  assert.ok(s.gets.every(k => k === ASK_KEY) && s.removes.every(k => k === ASK_KEY), 'only the ask key is touched');
  assert.equal(s.map.get('other'), 'keep');
  assert.equal(s.sets.length, 0);
});

test('read_failure_has_no_cleanup_but_url_still_works', async () => {
  const {takeAsk, ASK_PARAM} = await load();
  const s = store({}, {failGet: true});
  assert.equal(takeAsk(MAP, s), false);
  assert.equal(takeAsk(`${MAP}&${ASK_PARAM}=ask`, s), true);
  assert.equal(s.removes.length, 0);
  assert.equal(s.sets.length, 0);
});

test('missing_marker_and_storage_remain_nonasking', async () => {
  const {takeAsk, ASK_KEY, ASK_PARAM} = await load();
  assert.equal(takeAsk(MAP, null), false);
  assert.equal(takeAsk(`${MAP}&${ASK_PARAM}=ask`, null), true);
  assert.equal(takeAsk(`${MAP}&${ASK_PARAM}=other`, null), false);
  for (const initial of [{}, {[ASK_KEY]: ''}]) {
    const s = store(initial);
    assert.equal(takeAsk(MAP, s), false);
    assert.equal(s.removes.length, 0);
    assert.equal(takeAsk(`${MAP}&${ASK_PARAM}=ask`, s), true);
    assert.equal(s.removes.length, 0);
  }
});

test('cleanup_failure_then_retry_can_consume', async () => {
  const {takeAsk, ASK_KEY} = await load();
  const s = store({[ASK_KEY]: 'ask'}, {failRemove: true});
  assert.equal(takeAsk(MAP, s), true);
  assert.equal(s.map.has(ASK_KEY), true);   // the marker remains: not exactly-once under failed cleanup
  s.failRemove = false;
  assert.equal(takeAsk(MAP, s), true);
  assert.equal(s.map.has(ASK_KEY), false);
  assert.equal(takeAsk(MAP, s), false);
  assert.equal(s.removes.length, 2);
});

test('malformed_href_cannot_erase_stored_truth', async () => {
  const {takeAsk, ASK_KEY} = await load();
  const withMarker = store({[ASK_KEY]: 'ask'}, {failRemove: true});
  assert.equal(takeAsk('not a url', withMarker), true);
  const without = store();
  assert.equal(takeAsk('not a url', without), false);
  assert.equal(withMarker.sets.length + without.sets.length, 0);
});
