// Process-local offline boundaries, installed before complete product imports.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import {syncBuiltinESMExports} from 'node:module';
export function installOffline() {
  const saved = [], attempts = [];
  const deny = name => () => { attempts.push(name); throw new Error(`SP1402 offline sentinel: ${name}`); };
  const replace = (object, key, value) => {
    saved.push([object, key, Object.getOwnPropertyDescriptor(object, key)]);
    Object.defineProperty(object, key, {configurable: true, writable: true, value});
  };
  for (const key of ['fetch', 'WebSocket', 'EventSource', 'Worker']) replace(globalThis, key, deny(key));
  for (const key of ['localStorage', 'sessionStorage', 'indexedDB', 'caches'])
    replace(globalThis, key, new Proxy({}, {get: deny(key)}));
  for (const [object, key] of [[net.Socket.prototype, 'connect'], [net, 'connect'], [net, 'createConnection'],
    [tls, 'connect'], [http, 'request'], [http, 'get'], [https, 'request'], [https, 'get'], [dgram, 'createSocket']])
    replace(object, key, deny(key));
  syncBuiltinESMExports();
  return () => {
    for (const [object, key, descriptor] of saved.reverse()) {
      if (descriptor) Object.defineProperty(object, key, descriptor); else delete object[key];
    }
    syncBuiltinESMExports();
    if (attempts.length) throw new Error(`SP1402 forbidden attempts: ${attempts.join(', ')}`);
  };
}
