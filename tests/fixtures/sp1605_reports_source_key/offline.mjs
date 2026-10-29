// Loaded before any product/test module in this process. Synthetic fixtures
// only; these guards are not a hostile-code sandbox. Restore globals on exit.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import {syncBuiltinESMExports} from 'node:module';
const saved = [];
const violations = [];
const deny = (...args) => { violations.push('unadmitted external/model/live I/O'); throw new Error('SP1605 offline I/O sentinel'); };
function replace(object, key, value) { saved.push([object, key, object[key]]); object[key] = value; }
for (const [object, keys] of [[net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']],
  [tls, ['connect']], [http, ['request', 'get']], [https, ['request', 'get']]])
  for (const key of keys) replace(object, key, deny);
replace(globalThis, 'fetch', async url => {
  // Actual loadCoasts is allowed only its synthetic unavailable directory.
  if (url === 'data/coasts.json') return new Response('unavailable', {status: 503});
  return deny();
});
for (const key of ['WebSocket', 'localStorage', 'sessionStorage']) replace(globalThis, key, deny);
syncBuiltinESMExports();
process.on('exit', () => {
  for (const [object, key, value] of saved.reverse()) {
    if (value === undefined) delete object[key]; else object[key] = value;
  }
  syncBuiltinESMExports();
  if (violations.length) { console.error(`SP1605 sentinel violations: ${violations.length}`); process.exitCode = 1; }
});
