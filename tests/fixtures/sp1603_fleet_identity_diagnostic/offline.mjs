// Installed only in fixture-owned child processes, never ordinary suite peers.
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import {syncBuiltinESMExports, registerHooks} from 'node:module';
// Native SQLite bypasses fs.open and its ESM exports are not synchronized by
// syncBuiltinESMExports. Route only this child process through a file-based
// in-memory-only constructor, before the unchanged adapter imports node:sqlite.
const sqliteGuard = new URL('./sqlite_guard.mjs', import.meta.url).href;
registerHooks({resolve(specifier, context, nextResolve) {
  if (specifier === 'node:sqlite' && context.parentURL !== sqliteGuard) return {url: sqliteGuard, shortCircuit: true};
  return nextResolve(specifier, context);
}});
export function denied() { throw Error('SP1603_OFFLINE_NETWORK_MODEL_SENTINEL'); }
globalThis.fetch = denied;
http.request = http.get = https.request = https.get = denied;
net.connect = net.createConnection = tls.connect = denied;
net.Socket.prototype.connect = denied;
dgram.createSocket = denied;
syncBuiltinESMExports();
