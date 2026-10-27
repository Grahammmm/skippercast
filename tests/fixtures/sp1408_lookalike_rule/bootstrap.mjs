// File-based preload: no product import occurs before these offline sentinels.
// Native Node >=22.18 strips TypeScript in the complete modules unchanged.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import child from 'node:child_process';
import sqlite from 'node:sqlite';
import {syncBuiltinESMExports} from 'node:module';
import {fileURLToPath} from 'node:url';

const deny = () => { throw Error('SP1408 offline sentinel: external IO forbidden'); };
globalThis.fetch = deny;
globalThis.WebSocket = class { constructor() { deny(); } };
http.request = http.get = https.request = https.get = deny;
net.connect = net.createConnection = net.Socket.prototype.connect = tls.connect = deny;
dgram.createSocket = deny;
for (const key of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) child[key] = deny;
const NativeDatabase = sqlite.DatabaseSync;
sqlite.DatabaseSync = class extends NativeDatabase {
  constructor(filename, ...args) {
    if (filename !== ':memory:') deny();
    super(filename, ...args);
  }
};
// Only original importer tests may write/remove their own temporary fixtures.
// New focused tests cannot write storage at all. TMPDIR is candidate-local.
const temporary = process.env.SP1408_TEMP_ROOT;
const regression = process.env.SP1408_SUITE === 'regression';
function checked(value) {
  if (!regression || !temporary) deny();
  const p = path.resolve(value instanceof URL ? fileURLToPath(value) : String(value));
  const rel = path.relative(temporary, p);
  if (!rel || rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) deny();
  let cursor = temporary;
  if (fs.lstatSync(cursor).isSymbolicLink()) deny();
  for (const part of rel.split(path.sep)) {
    cursor = path.join(cursor, part);
    try { if (fs.lstatSync(cursor).isSymbolicLink()) deny(); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return p;
}
for (const api of [fs, fsp]) {
  for (const key of ['writeFile', 'writeFileSync', 'appendFile', 'appendFileSync', 'mkdir', 'mkdirSync', 'mkdtemp', 'mkdtempSync', 'rm', 'rmSync', 'unlink', 'unlinkSync', 'rmdir', 'rmdirSync']) {
    if (typeof api[key] !== 'function') continue;
    const original = api[key];
    api[key] = function(p, ...args) { checked(p); return original.call(this, p, ...args); };
  }
  for (const key of ['rename', 'renameSync', 'copyFile', 'copyFileSync', 'symlink', 'symlinkSync', 'link', 'linkSync', 'truncate', 'truncateSync', 'createWriteStream']) {
    if (typeof api[key] === 'function') api[key] = deny;
  }
  for (const key of ['open', 'openSync']) {
    if (typeof api[key] !== 'function') continue;
    const original = api[key];
    api[key] = function(p, flags, ...args) {
      if (typeof flags !== 'string' || flags !== 'r') checked(p);
      return original.call(this, p, flags, ...args);
    };
  }
}
if (regression && os.tmpdir() !== temporary) deny();
syncBuiltinESMExports();
