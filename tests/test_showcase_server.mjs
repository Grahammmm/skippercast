// scripts/showcase_skippercast_server.mjs: the showcase's server-side freeze (Worker Date and seed SQL clock),
// applied to a throwaway checkout. The capture itself (browser, Worker) is exercised by e2e/showcase-capture.spec.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync, mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {freeze, freezeSql} from '../scripts/showcase_skippercast_server.mjs';

const ISO = '2026-06-15T19:00:00Z', MS = Date.parse(ISO);

function checkout() {
  const tree = mkdtempSync(join(tmpdir(), 'showcase-freeze-'));
  mkdirSync(join(tree, 'dist/server'), {recursive: true});
  mkdirSync(join(tree, 'e2e/seed'), {recursive: true});
  // A stand-in Worker bundle: what it reads from Date is what a page it renders would show.
  writeFileSync(join(tree, 'dist/server/index.js'), `const loaded = Date.now();
export const named = 'kept';
export default {loaded, now: () => (null ?? Date.now)(), made: () => new Date().toISOString(), given: () => new Date(0).toISOString(),
  isDate: () => new Date() instanceof Date, called: () => typeof Date(), parsed: () => Date.parse('2001-01-01T00:00:00Z')};\n`);
  writeFileSync(join(tree, 'e2e/seed/a.sql'), "INSERT INTO t(d,c,x) VALUES(date('now','-1 day'),datetime('now'),CURRENT_TIMESTAMP);\n");
  return tree;
}

function readWorker(tree) {
  const probe = join(tree, 'probe.mjs');
  writeFileSync(probe, `import app, {named} from './dist/server/index.js';
console.log(JSON.stringify({named, loaded: app.loaded, now: app.now(), made: app.made(), given: app.given(), isDate: app.isDate(), called: app.called(), parsed: app.parsed()}));\n`);
  const run = spawnSync(process.execPath, [probe], {encoding: 'utf8'});
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

test('the wrapped Worker reads the fixed time from Date, whatever the host clock says', () => {
  const tree = checkout();
  const done = freeze(tree, ISO);
  assert.deepEqual(done.seeds, ['a.sql']);
  const seen = readWorker(tree);
  assert.deepEqual(seen, {named: 'kept', loaded: MS, now: MS, made: '2026-06-15T19:00:00.000Z', given: '1970-01-01T00:00:00.000Z',
    isDate: true, called: 'string', parsed: Date.parse('2001-01-01T00:00:00Z')});
  assert.notEqual(Math.floor(Date.now() / 86_400_000), Math.floor(MS / 86_400_000), 'the test date must differ from the host date');
});

test('freezing twice, or again after a rebuild, keeps one wrapper around the current build', () => {
  const tree = checkout();
  freeze(tree, ISO);
  freeze(tree, ISO);
  assert.match(readFileSync(join(tree, 'dist/server/showcase-app.js'), 'utf8'), /export const named = 'kept'/);
  writeFileSync(join(tree, 'dist/server/index.js'), "export default {now: () => Date.now(), rebuilt: true};\n");   // a fresh `pnpm build`
  freeze(tree, ISO);
  assert.match(readFileSync(join(tree, 'dist/server/showcase-app.js'), 'utf8'), /rebuilt: true/);
});

test('every reading of the SQLite clock in the seed becomes the fixed UTC time', () => {
  assert.equal(freezeSql("VALUES(date('now','-1 day'),datetime('NOW'),CURRENT_TIMESTAMP,CURRENT_DATE,'nowhere')", MS),
    "VALUES(date('2026-06-15 19:00:00','-1 day'),datetime('2026-06-15 19:00:00'),'2026-06-15 19:00:00','2026-06-15','nowhere')");
});

test('a checkout without a built Worker is refused, so it is never captured unfrozen', () => {
  const tree = mkdtempSync(join(tmpdir(), 'showcase-freeze-'));
  assert.throws(() => freeze(tree, ISO), /dist\/server\/index\.js is missing/);
  assert.throws(() => freeze(checkout(), 'yesterday'), /not an ISO time/);
});
