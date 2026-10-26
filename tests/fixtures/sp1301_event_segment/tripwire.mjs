// SP1301-EVENT-SEGMENT acceptance tripwire, preloaded with `node --import` by
// scripts/accept_sp1301_event_segment.py before any product or test module loads.
// Any network attempt (fetch, sockets, DNS, http/https) throws and is counted, so a
// test that reaches the network fails loudly. It catches mistakes; it is not a sandbox.
import net from 'node:net';
import dns from 'node:dns';
import http from 'node:http';
import https from 'node:https';
import tls from 'node:tls';

const hits = [];
const trip = what => function tripped() {
  hits.push(what);
  process.stderr.write(`SP1301_TRIPWIRE ${what}\n`);
  throw new Error(`SP1301 tripwire: ${what} is not allowed in offline acceptance`);
};
globalThis.fetch = trip('fetch');
globalThis.WebSocket = trip('WebSocket');
net.Socket.prototype.connect = trip('net.Socket.connect');
net.connect = trip('net.connect');
net.createConnection = trip('net.createConnection');
tls.connect = trip('tls.connect');
dns.lookup = trip('dns.lookup');
dns.resolve = trip('dns.resolve');
for (const mod of [http, https]) {
  mod.request = trip(`${mod === http ? 'http' : 'https'}.request`);
  mod.get = trip(`${mod === http ? 'http' : 'https'}.get`);
}
globalThis.__sp1301Tripwire = {installed: true, hits};
process.on('exit', () => { if (hits.length) process.stderr.write(`SP1301_TRIPWIRE_HITS ${hits.length}\n`); });
