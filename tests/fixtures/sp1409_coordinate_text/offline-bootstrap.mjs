// Process-local offline bootstrap, loaded before any product modules.
// Original regression tests retain their own injected feeds and in-memory DB.
import {createRequire, syncBuiltinESMExports} from 'node:module';
const require = createRequire(import.meta.url);
const saved = [];
export const attempts = [];
let installed = false;
function replace(object, key, value) {
  saved.push([object, key, Object.getOwnPropertyDescriptor(object, key)]);
  Object.defineProperty(object, key, {configurable: true, writable: true, value});
}
function refuse(kind) {
  return function () {
    attempts.push(kind);
    throw new Error(`SP1409_OFFLINE_REFUSAL:${kind}`);
  };
}
export function install() {
  if (installed) return;
  installed = true;
  attempts.length = 0;
  for (const key of ['fetch', 'WebSocket', 'XMLHttpRequest']) replace(globalThis, key, refuse(key));
  for (const key of ['localStorage', 'sessionStorage', 'caches']) {
    replace(globalThis, key, new Proxy({}, {get: () => refuse(key)}));
  }
  for (const [name, keys] of [
    ['node:http', ['request', 'get']], ['node:https', ['request', 'get']],
    ['node:net', ['connect', 'createConnection']], ['node:tls', ['connect']],
    ['node:dgram', ['createSocket']], ['node:dns', ['lookup', 'resolve']],
  ]) {
    const module = require(name);
    for (const key of keys) replace(module, key, refuse(`${name}.${key}`));
  }
  replace(require('node:net').Socket.prototype, 'connect', refuse('Socket.connect'));
  const sqlite = require('node:sqlite');
  const Database = sqlite.DatabaseSync;
  replace(sqlite, 'DatabaseSync', class extends Database {
    constructor(path, ...options) {
      if (path !== ':memory:') refuse('persistent sqlite')();
      super(path, ...options);
    }
  });
  syncBuiltinESMExports();
}
export function restore() {
  for (const [object, key, descriptor] of saved.splice(0).reverse()) {
    if (descriptor) Object.defineProperty(object, key, descriptor);
    else delete object[key];
  }
  installed = false;
  syncBuiltinESMExports();
}
install();
// Even a caught attempt invalidates the entire process, not just its test.
process.on('exit', () => {
  if (attempts.length) {
    console.error('SP1409_UNEXPECTED_OFFLINE_ATTEMPTS', JSON.stringify(attempts));
    process.exitCode = 1;
  }
  restore();
});
