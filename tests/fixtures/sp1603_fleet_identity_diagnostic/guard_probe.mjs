// Fresh process: prove built-in export synchronization before product imports.
import './offline.mjs';
import assert from 'node:assert/strict';
import path from 'node:path';
const {DatabaseSync} = await import('node:sqlite');
import {request} from 'node:https';
import {createConnection} from 'node:net';
assert.throws(() => fetch('https://offline.invalid'), /SP1603_OFFLINE/);
assert.throws(() => request('https://offline.invalid'), /SP1603_OFFLINE/);
assert.throws(() => createConnection({host: 'offline.invalid', port: 443}), /SP1603_OFFLINE/);
assert.throws(() => new DatabaseSync(path.join(process.env.TMPDIR, 'synthetic-sentinel.sqlite')), /SP1603_LIVE_STORE/);
const memory = new DatabaseSync(':memory:');
assert.equal(memory.prepare('SELECT 1 n').get().n, 1);
memory.close();
console.log(JSON.stringify({checks: 5, passed: 5, skipped: 0}));
