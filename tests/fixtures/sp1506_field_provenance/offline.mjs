// Process-scoped sentinels, loaded before any product/test module.
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
const saved = [];
function replace(object, key) {
  saved.push([object, key, object[key]]);
  object[key] = () => { throw new Error(`SP1506_OFFLINE: ${key} forbidden`); };
}
replace(globalThis, 'fetch');
for (const module of [http, https]) for (const key of ['request', 'get']) replace(module, key);
for (const key of ['connect', 'createConnection']) replace(net, key);
replace(net.Socket.prototype, 'connect');
replace(tls, 'connect');
replace(dgram, 'createSocket');
syncBuiltinESMExports();
export function restoreOffline() {
  for (const [object, key, value] of saved.reverse()) object[key] = value;
  saved.length = 0;
  syncBuiltinESMExports();
}
