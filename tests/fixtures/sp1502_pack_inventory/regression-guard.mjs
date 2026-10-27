// Pre-import offline guards for unchanged original Node selectors. Per-process only.
// Originals may replace fetch with their fixture-owned fetch, then restore this sentinel.
const blocked = label => () => { throw new Error(`SP1502 offline sentinel: ${label}`); };
for (const [key, value] of Object.entries({
  fetch: blocked('network/model fetch'), WebSocket: blocked('WebSocket'), XMLHttpRequest: blocked('XMLHttpRequest'),
  caches: {keys: blocked('live caches.keys'), open: blocked('live caches.open'), delete: blocked('live caches.delete')},
  localStorage: {getItem: () => null, setItem: blocked('storage write'), removeItem: blocked('storage remove')},
  sessionStorage: {getItem: () => null, setItem: blocked('session write'), removeItem: blocked('session remove')},
  indexedDB: {open: blocked('indexedDB')},
})) Object.defineProperty(globalThis, key, {value, writable: true, configurable: true});
