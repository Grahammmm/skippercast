// File-based pre-import offline boundary. Used by --import and by ordinary test discovery.
// This is an accidental-side-effect sentinel, not a hostile-code sandbox.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import child from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';

const saved = [];
export const attempts = [];
const refuse = name => (..._args) => { attempts.push(name); throw Error(`SP1406 offline sentinel: ${name}`); };
function replace(target, name, value) {
  saved.push([target, name, Object.getOwnPropertyDescriptor(target, name)]);
  Object.defineProperty(target, name, {value, configurable: true, writable: true});
}
for (const name of ['fetch', 'WebSocket', 'XMLHttpRequest']) replace(globalThis, name, refuse(name));
replace(globalThis, 'localStorage', {getItem: () => null, setItem: refuse('localStorage.setItem'), removeItem: refuse('localStorage.removeItem')});
for (const name of ['DB', 'FEEDS', 'ASSETS', 'caches']) {
  replace(globalThis, name, new Proxy({}, {get: (_t, key) => refuse(`${name}.${String(key)}`)}));
}
for (const [target, names] of [
  [http, ['request', 'get']], [https, ['request', 'get']],
  [net, ['connect', 'createConnection']], [net.Socket.prototype, ['connect']],
  [tls, ['connect']], [dgram, ['createSocket']],
  [child, ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']],
  [fs, ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'createWriteStream',
    'rm', 'rmSync', 'unlink', 'unlinkSync', 'mkdir', 'mkdirSync', 'rename', 'renameSync',
    'copyFile', 'copyFileSync', 'truncate', 'truncateSync', 'symlink', 'symlinkSync']],
  [fsp, ['writeFile', 'appendFile', 'rm', 'unlink', 'mkdir', 'rename', 'copyFile', 'truncate', 'symlink']],
]) for (const name of names) replace(target, name, refuse(name));
// Read-only opens remain available to Node's module loader and recorded fixture readers.
for (const target of [fs, fsp]) for (const name of target === fs ? ['open', 'openSync'] : ['open']) {
  const original = target[name];
  replace(target, name, function(path, flags, ...rest) {
    if (flags !== 'r' && flags !== fs.constants.O_RDONLY) return refuse(`${name}:write`)();
    return original.call(this, path, flags, ...rest);
  });
}
syncBuiltinESMExports();
let restored = false;
export function restoreOffline() {
  if (restored) return;
  restored = true;
  for (const [target, name, descriptor] of saved.reverse()) {
    if (descriptor) Object.defineProperty(target, name, descriptor);
    else delete target[name];
  }
  syncBuiltinESMExports();
}
