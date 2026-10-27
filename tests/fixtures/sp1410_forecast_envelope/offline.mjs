// SP1410 offline boundary (card-owned test support, not product code).
//
// Importing this module replaces the process's network entry points and the
// browser storage globals with sentinels that throw and count the attempt. The
// card's test imports it first, before any product module (so bound defaults such
// as feeds.ts readFeed can never reach the network), and the acceptance launcher
// also preloads it with --import. It is confined to the Node process that loads it.
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import {syncBuiltinESMExports} from 'node:module';

const KEY = Symbol.for('sp1410.offline');
const TARGETS = [[globalThis, 'fetch'], [http, 'request'], [http, 'get'], [https, 'request'], [https, 'get'],
  [net, 'connect'], [net, 'createConnection'], [net.Socket.prototype, 'connect'], [tls, 'connect'], [dgram, 'createSocket']];
const STORAGE = ['caches', 'localStorage', 'sessionStorage', 'indexedDB', 'WebSocket'];

function install() {
  const state = {attempts: [], originals: [], storage: []};
  const deny = name => function sp1410Denied() {
    state.attempts.push(name);
    throw new Error(`SP1410 offline boundary: ${name} is not allowed in this test process`);
  };
  for (const [object, key] of TARGETS) {
    state.originals.push([object, key, object[key]]);
    object[key] = deny(key);
  }
  for (const key of STORAGE) {
    state.storage.push([key, Object.getOwnPropertyDescriptor(globalThis, key)]);
    const trap = new Proxy({}, {get: (_, prop) => prop === Symbol.toPrimitive ? undefined : deny(`${key}.${String(prop)}`)});
    Object.defineProperty(globalThis, key, {configurable: true, enumerable: false, writable: true, value: trap});
  }
  syncBuiltinESMExports();
  state.sentinels = TARGETS.map(([object, key]) => object[key]);
  return state;
}

const state = globalThis[KEY] ?? (globalThis[KEY] = install());

/** Network/storage attempts recorded since the boundary was installed (expected: none). */
export const offlineAttempts = () => [...state.attempts];

/** True while every network entry point is still this module's sentinel. */
export const offlineIntact = () => TARGETS.every(([object, key], i) => object[key] === state.sentinels[i]);

/** Put back the original entry points and storage globals (the test's final teardown). */
export function restoreOnline() {
  for (const [object, key, value] of state.originals) object[key] = value;
  for (const [key, descriptor] of state.storage) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor);
    else delete globalThis[key];
  }
  syncBuiltinESMExports();
  delete globalThis[KEY];
}
