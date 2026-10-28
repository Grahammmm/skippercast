// Offline preload for the two unchanged regression test files only.
import assert from 'node:assert/strict';
import {after} from 'node:test';
const names = ['fetch', 'localStorage', 'sessionStorage'];
const descriptors = new Map(names.map(k => [k, Object.getOwnPropertyDescriptor(globalThis, k)]));
const originals = new Map();
let assertionChecks = 0, fetchCalls = 0;
for (const key of ['equal', 'strictEqual', 'deepEqual', 'deepStrictEqual', 'notEqual', 'notStrictEqual', 'ok', 'match', 'doesNotMatch', 'throws', 'doesNotThrow', 'rejects', 'doesNotReject', 'notDeepEqual', 'notDeepStrictEqual']) {
  originals.set(key, assert[key]);
  assert[key] = (...args) => {assertionChecks++; return originals.get(key)(...args);};
}
const storage = () => {
  const values = new Map();
  return {getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, String(v)), removeItem: k => values.delete(k), clear: () => values.clear()};
};
Object.defineProperty(globalThis, 'fetch', {configurable: true, writable: true, value: async () => {fetchCalls++; throw Error('SP-MAP-NOW offline fetch refused');}});
Object.defineProperty(globalThis, 'localStorage', {configurable: true, value: storage()});
Object.defineProperty(globalThis, 'sessionStorage', {configurable: true, value: storage()});
after(() => {
  for (const [key, fn] of originals) assert[key] = fn;
  for (const [key, desc] of descriptors) {
    if (desc) Object.defineProperty(globalThis, key, desc);
    else delete globalThis[key];
  }
  console.log('SP_MAP_NOW_REGRESSION_RESULT ' + JSON.stringify({script: process.argv[1], assertion_checks: assertionChecks, fetch_calls: fetchCalls}));
});
