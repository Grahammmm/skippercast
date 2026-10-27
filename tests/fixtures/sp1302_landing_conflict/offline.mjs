// Acceptance-only preload. No global hooks when this file is merely inventoried.
import fs from 'node:fs';
import net from 'node:net';
import tls from 'node:tls';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import dgram from 'node:dgram';
import dns from 'node:dns';
import {syncBuiltinESMExports} from 'node:module';
import path from 'node:path';

if (process.env.SP1302_OFFLINE === '1') {
  const root = process.env.TMPDIR;
  if (!root || fs.realpathSync(root) !== path.resolve(root)) throw Error('candidate-local temporary root required');
  const deny = () => { throw Error('SP1302 offline network/model-call tripwire'); };
  globalThis.fetch = deny;
  globalThis.WebSocket = class { constructor() { deny(); } };
  net.connect = net.createConnection = net.Server.prototype.listen = net.Socket.prototype.connect = deny;
  tls.connect = tls.createServer = deny;
  http.request = http.get = http.createServer = deny;
  https.request = https.get = https.createServer = deny;
  http2.connect = http2.createServer = http2.createSecureServer = deny;
  dgram.createSocket = deny;
  dns.lookup = dns.resolve = deny;
  dns.promises.lookup = dns.promises.resolve = deny;
  syncBuiltinESMExports();
}
