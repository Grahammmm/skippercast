// Process-local, reversible offline sentinels; install BEFORE product imports.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import dgram from 'node:dgram';
import dns from 'node:dns';
import {syncBuiltinESMExports} from 'node:module';

export function installOffline() {
  const undo = [], attempts = [];
  function replace(object, key, value) {
    const descriptor = Object.getOwnPropertyDescriptor(object, key);
    Object.defineProperty(object, key, {...descriptor, value});
    undo.push(() => Object.defineProperty(object, key, descriptor));
  }
  const refuse = label => function () {
    attempts.push(label);
    throw Error(`SP1601 offline sentinel: ${label}`);
  };
  replace(globalThis, 'fetch', refuse('fetch/network/model'));
  for (const [object, keys] of [
    [net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']],
    [tls, ['connect']], [http, ['request', 'get']], [https, ['request', 'get']],
    [http2, ['connect']], [dgram, ['createSocket']],
    [dns, ['lookup', 'resolve']], [dns.promises, ['lookup', 'resolve']],
  ]) for (const key of keys) replace(object, key, refuse(`network:${key}`));
  syncBuiltinESMExports();
  return {attempts, restore() { for (const restore of undo.reverse()) restore(); syncBuiltinESMExports(); }};
}
