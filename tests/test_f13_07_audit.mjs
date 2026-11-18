// SCA-291 / F13-07: saving the first-use boat length must not overwrite a saved boat it cannot read or understand.
// Required suite: node --test tests/test_f13_07_audit.mjs
// Contract protected: only a genuinely empty key gets the default boat; a malformed or future-schema record keeps its
// exact bytes and the result says the boat was not saved; a valid v1 edit keeps its unrelated fields.
// Believable bug it catches: JSON.parse failure or schema_version !== 1 falling into the new-boat branch, so a bare
// length replaces the whole value and reports boat:true. Synthetic in-memory storage only: no browser or network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const KEY = 'skippercast-boat-v1';
const out = join(await mkdtemp(join(tmpdir(), 'f13-07-')), 'boat-entry.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: "export {saveFirstUse, ENTRY_COPY} from './web/boat-entry.ts';"},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', plugins: [preparedCatalogue],
});
const {saveFirstUse, ENTRY_COPY} = await import(pathToFileURL(out).href);

const memory = initial => {
  const map = new Map(Object.entries(initial));
  return {map, getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }};
};
const save = (initial, length = '25') => {
  const storage = memory(initial);
  return {storage, result: saveFirstUse({lengthFt: length, profile: 'boat'}, storage)};
};

// Negative controls: the cited failure. Each existing value must come back byte for byte, with a notice and no boat claim.
const unreadable = {
  'malformed JSON': '{not json',
  'truncated JSON': '{"schema_version":1,"boat":{"name":"Ruby","loa_',
  'future schema': JSON.stringify({schema_version: 2, boat: {name: 'Ruby', loa_ft: 26, new_field: [1, 2]}, saved_at: 't'}),
  'schema 1 without a boat': JSON.stringify({schema_version: 1, query: 'x'}),
  'JSON null literal': 'null',
  'non-record JSON': '[1,2,3]',
  // Believable bug: typeof [] === 'object' let an array pass as the v1 boat, which was then rewritten as an object.
  'v1 envelope whose boat is an array': JSON.stringify({schema_version: 1, boat: [{name: 'Ruby', loa_ft: 23}]}),
  'v1 envelope whose boat is a string': JSON.stringify({schema_version: 1, boat: 'Ruby'}),
};
for (const [label, bytes] of Object.entries(unreadable)) {
  test(`negative control: ${label} is preserved byte for byte and a notice is shown`, () => {
    const {storage, result} = save({[KEY]: bytes});
    assert.equal(storage.getItem(KEY), bytes);
    assert.equal(result.boat, false);
    assert.deepEqual(result.notices, [ENTRY_COPY.failed]);
  });
}

// Positive controls.
test('valid control: a genuinely empty key gets the default boat', () => {
  for (const initial of [{}, {[KEY]: ''}]) {
    const {storage, result} = save(initial);
    const boat = JSON.parse(storage.getItem(KEY));
    assert.equal(result.boat, true);
    assert.deepEqual(result.notices, []);
    assert.deepEqual([boat.schema_version, boat.boat.loa_ft, boat.boat.name], [1, 25, '25 ft boat']);
  }
});

test('valid control: a v1 edit changes the length and keeps unrelated fields', () => {
  const full = {schema_version: 1, boat: {name: 'Ruby', loa_ft: 23, beam_ft: 8.5, hull: 'modified-v', extra: {k: 1}},
    query: 'Parker 2320', preset: 'p', saved_at: '2026-01-01T00:00:00Z', lookup: {source: 'x'}, future_top: 'kept'};
  const {storage, result} = save({[KEY]: JSON.stringify(full)});
  assert.equal(result.boat, true);
  assert.deepEqual(result.notices, []);
  assert.deepEqual(JSON.parse(storage.getItem(KEY)), {...full, boat: {...full.boat, loa_ft: 25}});
});

test('an out-of-range length leaves an unreadable record alone without a notice', () => {
  const {storage, result} = save({[KEY]: '{not json'}, '7');
  assert.equal(storage.getItem(KEY), '{not json');
  assert.deepEqual(result, {boat: false, notices: []});
});
