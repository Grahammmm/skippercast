// File-based offline preload, confined to this acceptance child process.
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import {syncBuiltinESMExports} from 'node:module';
import {readFileSync} from 'node:fs';

export function installOffline() {
  const undo = [];
  const replace = (obj, key, value) => {
    const descriptor = Object.getOwnPropertyDescriptor(obj, key);
    Object.defineProperty(obj, key, {configurable: true, writable: true, value});
    undo.push(() => descriptor ? Object.defineProperty(obj, key, descriptor) : Reflect.deleteProperty(obj, key));
  };
  const denied = () => { throw new Error('SP1407_OFFLINE_SIDE_EFFECT'); };
  for (const [obj, keys] of [[http, ['request', 'get']], [https, ['request', 'get']], [net, ['connect', 'createConnection']], [tls, ['connect']]]) {
    for (const key of keys) replace(obj, key, denied);
  }
  replace(globalThis, 'fetch', denied);
  replace(globalThis, 'WebSocket', denied);
  replace(globalThis, 'caches', {open: denied, match: denied, put: denied, delete: denied});
  replace(globalThis, 'localStorage', {getItem: () => null, setItem: denied, removeItem: denied});
  const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
  replace(globalThis, 'REGIONS', {
    'morro-bay': read('../../../regions/morro-bay/region.json'),
    'southern-california': read('../../../regions/southern-california/region.json'),
  });
  replace(globalThis, 'DEPLOYMENT', read('../../../deployments/production.json'));
  replace(globalThis, 'SHELLS', {'/': '/index.0123456789.html'});
  replace(globalThis, 'BUILD_ID', 'sp1407-synthetic');
  syncBuiltinESMExports();
  return () => { for (const restore of undo.reverse()) restore(); syncBuiltinESMExports(); };
}
// The CLI loads this before original tests and before their transitive imports.
// The test runner isolates files; direct imports restore the preload in the suite hook.
export const restorePreload = installOffline();
