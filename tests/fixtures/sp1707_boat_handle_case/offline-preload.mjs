// Dedicated test-child preload, never imported by ordinary discovery peers.
// Install before product imports. This is an accidental-I/O sentinel, not a sandbox.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import {syncBuiltinESMExports} from 'node:module';

const originals = [];
const attempts = [];
function replace(target, key, label) {
  const original = target[key];
  const deny = () => { attempts.push(label); throw new Error(`SP1707_OFFLINE_IO: ${label}`); };
  Object.defineProperty(deny, 'sp1707Offline', {value: true});
  target[key] = deny;
  originals.push(() => { target[key] = original; });
}
replace(globalThis, 'fetch', 'external-fetch/model');
replace(net, 'connect', 'net.connect');
replace(net, 'createConnection', 'net.createConnection');
replace(net.Socket.prototype, 'connect', 'socket.connect');
replace(tls, 'connect', 'tls.connect');
for (const [module, name] of [[http, 'http'], [https, 'https']]) {
  replace(module, 'request', `${name}.request`);
  replace(module, 'get', `${name}.get`);
}
replace(dgram, 'createSocket', 'dgram.createSocket');
syncBuiltinESMExports();
globalThis.SP1707_OFFLINE = {attempts};
// Every preload runs in its own short-lived child; restore before that process exits.
process.once('exit', () => {
  for (const restore of originals.reverse()) restore();
  syncBuiltinESMExports();
  if (attempts.length) process.exitCode = 1;
});
