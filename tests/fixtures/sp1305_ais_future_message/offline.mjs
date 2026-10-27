// Preloaded only in acceptance children, before any product/test imports.
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import dgram from 'node:dgram';
import dns from 'node:dns';
import {syncBuiltinESMExports} from 'node:module';
import {realpathSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve, sep} from 'node:path';
const root = process.env.SP1305_TEMP;
if (!root || !realpathSync(tmpdir()).startsWith(realpathSync(root) + sep)) {
  throw new Error('SP1305 requires an explicit candidate-local temporary directory');
}
const deny = () => { throw new Error('SP1305 offline tripwire: network/model call forbidden'); };
globalThis.fetch = deny;
globalThis.WebSocket = class { constructor() { deny(); } };
for (const [mod, names] of [[net, ['connect', 'createConnection', 'createServer']],
  [tls, ['connect', 'createServer']], [http, ['request', 'get', 'createServer']],
  [https, ['request', 'get', 'createServer']], [dgram, ['createSocket']],
  [dns, ['lookup', 'resolve', 'resolve4', 'resolve6']]]) {
  for (const name of names) mod[name] = deny;
}
net.Socket.prototype.connect = deny;
net.Server.prototype.listen = deny;
for (const name of ['lookup', 'resolve', 'resolve4', 'resolve6']) dns.promises[name] = deny;
syncBuiltinESMExports();
// The route's clock is captured before its module graph executes. Restore it at
// process exit; no hooks escape this dedicated native-test child.
if (['baseline', 'focused'].includes(process.env.SP1305_SUITE)) {
  const originalDate = globalThis.Date;
  const instant = originalDate.parse('2026-10-05T12:30:00.000Z');
  globalThis.Date = class extends originalDate {
    constructor(...args) { super(...(args.length ? args : [instant])); }
    static now() { return instant; }
  };
  process.once('exit', () => { globalThis.Date = originalDate; });
}
// No credentials are consumed; all endpoint constants remain inert metadata.
if (resolve(root) !== root) throw new Error('temporary root must be absolute');
