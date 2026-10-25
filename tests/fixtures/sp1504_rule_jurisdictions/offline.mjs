// Process-local pre-import sentinels. Installed with --import before ANY product import.
// Not a hostile-code sandbox; the complete species-page import closure is pure
// catalog/time/render code. Its only store is the explicitly supplied in-memory D1.
import {after} from 'node:test';
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import dgram from 'node:dgram';
import childProcess from 'node:child_process';

const restores = [];
let attempts = 0;
const denied = () => { attempts++; throw new Error('SP1504_OFFLINE_BOUNDARY: network/model/child process forbidden'); };
function replace(object, key, value) {
  const descriptor = Object.getOwnPropertyDescriptor(object, key);
  Object.defineProperty(object, key, {configurable: true, writable: true, value});
  restores.push(() => descriptor ? Object.defineProperty(object, key, descriptor) : delete object[key]);
}
for (const key of ['fetch', 'WebSocket', 'EventSource']) replace(globalThis, key, denied);
for (const [object, keys] of [
  [http, ['request', 'get']], [https, ['request', 'get']],
  [net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']],
  [tls, ['connect']], [dns, ['lookup', 'resolve']], [dns.promises, ['lookup', 'resolve']],
  [dgram, ['createSocket']],
  [childProcess, ['exec', 'execFile', 'execSync', 'execFileSync', 'spawn', 'spawnSync', 'fork']],
]) for (const key of keys) replace(object, key, denied);
syncBuiltinESMExports();

// Every unexpected Env binding (R2, AI, queues, etc.) fails rather than touching
// a live default. The actual page receives only the synthetic, migration-backed DB.
export function offlineEnv(db) {
  return new Proxy({DB: db}, {get(target, key) {
    if (key === 'DB') return target.DB;
    attempts++;
    throw new Error(`SP1504_LIVE_STORE_BOUNDARY: unexpected Env binding ${String(key)}`);
  }});
}
after(() => {
  for (const restore of restores.reverse()) restore();
  syncBuiltinESMExports();
  if (attempts !== 0) throw new Error(`SP1504 offline boundary attempted ${attempts} times`);
});
