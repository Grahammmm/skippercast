// Acceptance-only preload; merely importing this fixture does not patch globals.
// All inputs are committed catalogs or migration-backed in-memory SQLite.
import {syncBuiltinESMExports} from 'node:module';
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import dns from 'node:dns';

let restoreOffline;
export function installOffline() {
  if (restoreOffline) return restoreOffline;
  const saved = [];
  const attempts = [];
  function replace(obj, key) {
    const original = obj[key];
    saved.push(() => { obj[key] = original; });
    obj[key] = function () {
      attempts.push(key);
      throw new Error(`SP1809_OFFLINE_NETWORK_FORBIDDEN:${key}`);
    };
  }
  replace(globalThis, 'fetch');
  if ('WebSocket' in globalThis) replace(globalThis, 'WebSocket');
  replace(net.Socket.prototype, 'connect');
  replace(net.Server.prototype, 'listen');
  for (const [obj, keys] of [[net, ['connect', 'createConnection']], [tls, ['connect']],
    [http, ['request', 'get']], [https, ['request', 'get']], [dgram, ['createSocket']],
    [dns, ['lookup', 'resolve']], [dns.promises, ['lookup', 'resolve']]]) {
    for (const key of keys) replace(obj, key);
  }
  syncBuiltinESMExports();
  restoreOffline = () => {
    process.removeListener('exit', restoreOffline);
    for (const restore of saved.reverse()) restore();
    syncBuiltinESMExports();
    restoreOffline = undefined;
    if (attempts.length) throw new Error(`SP1809_OFFLINE_ATTEMPTS:${attempts.join(',')}`);
  };
  // Also fail caught attempts in unchanged compatibility suites, which have no
  // teardown hook of their own for this preload.
  process.once('exit', restoreOffline);
  return restoreOffline;
}

if (process.env.SP1809_OFFLINE === '1') installOffline();
