// Re-keying stored phone numbers to a new ADVISOR_PHONE_KEY
// (scripts/advisor/rekey-phones.mjs; docs/operations/runbooks/secrets-rotation.md
// § ADVISOR_PHONE_KEY). Runs the script's main() against node:sqlite with the
// real migrations through a fake `wrangler d1 execute`: dry run by default,
// one transaction on --apply, resumable, refuses unreadable rows, reports
// duplicates made during the switch, and never prints a number.
import test from 'node:test';
import assert from 'node:assert/strict';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const R = await import('../scripts/advisor/rekey-phones.mjs');
const {deriveKeys, phoneHash, encryptPhone, decryptPhone} = await import('../server/advisor/contacts.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const OLD = Buffer.alloc(32, 7).toString('base64'), NEW = Buffer.alloc(32, 9).toString('base64');
const NUMBERS = ['+18055550101', '+18055550102', '+18055550103'];

async function seed() {
  const {sql, db} = advisorDatabase();
  const keys = await deriveKeys(OLD);
  for (const [i, n] of NUMBERS.entries())
    sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES(?,?,?,'sms','x','x','x')`).run(`c${i + 1}`, await phoneHash(keys, n), await encryptPhone(keys, n));
  sql.prepare(`INSERT INTO advisor_contacts(id,web_session,channel,last_seen_at,created_at,updated_at) VALUES('web1','s','web','x','x','x')`).run();
  sql.prepare(`INSERT INTO job_state(key,value,updated_at) VALUES('advisor.link.web1','{}','x'),('advisor.flow.c1','{}','x')`).run();
  return {sql, db};
}
/** A fake `npx wrangler d1 execute`: --json --command answers the SELECT; --file runs the file in one transaction. */
function fakeWrangler(sql, files, {failFile = false} = {}) {
  const calls = [];
  const run = (cmd, args) => {
    calls.push(args);
    assert.equal(cmd, 'npx');
    assert.deepEqual(args.slice(0, 6), ['--yes', 'wrangler', 'd1', 'execute', 'skippercast', '--remote']);
    if (args.includes('--file')) {
      if (failFile) return {status: 1};
      sql.exec('BEGIN');
      try { sql.exec(files.get(args[args.indexOf('--file') + 1])); sql.exec('COMMIT'); } catch (e) { sql.exec('ROLLBACK'); throw e; }
      return {status: 0};
    }
    const query = args[args.indexOf('--command') + 1];
    return {status: 0, stdout: JSON.stringify([{results: sql.prepare(query).all().map(r => ({...r}))}])};
  };
  return {run, calls};
}
const env = {OLD_ADVISOR_PHONE_KEY: OLD, NEW_ADVISOR_PHONE_KEY: NEW};
const harness = sql => { const files = new Map(), lines = [], w = fakeWrangler(sql, files); return {files, lines, w, deps: {run: w.run, env, log: l => lines.push(l), write: (p, text) => files.set(p, text)}}; };

dbTest('rekey: the dry run reads and checks every row and writes nothing', async () => {
  const {sql} = await seed();
  const before = sql.prepare('SELECT id,phone_hash,phone_enc FROM advisor_contacts ORDER BY id').all().map(r => ({...r}));
  const h = harness(sql);
  assert.equal(await R.main([], h.deps), 0);
  assert.deepEqual(sql.prepare('SELECT id,phone_hash,phone_enc FROM advisor_contacts ORDER BY id').all().map(r => ({...r})), before);
  assert.equal(h.files.size, 0);
  assert.ok(h.w.calls.every(a => !a.includes('--file')), 'no write in a dry run');
  assert.match(h.lines.join('\n'), /contacts to re-key: 3; already under the new key: 0; duplicates: 0; cannot read: 0/);
  assert.ok(!h.lines.join('\n').includes('555'), 'no number printed');
});

dbTest('rekey --apply: every number re-hashed and re-encrypted under the new key in one file, link codes cleared, verified, and a second run changes nothing', async () => {
  const {sql} = await seed();
  const h = harness(sql);
  assert.equal(await R.main(['--apply'], h.deps), 0, h.lines.join('\n'));
  const keys = await deriveKeys(NEW);
  for (const [i, n] of NUMBERS.entries()) {
    const row = sql.prepare('SELECT phone_hash,phone_enc FROM advisor_contacts WHERE id=?').get(`c${i + 1}`);
    assert.equal(row.phone_hash, await phoneHash(keys, n));
    assert.equal(await decryptPhone(keys, row.phone_enc), n);
    await assert.rejects(decryptPhone(await deriveKeys(OLD), row.phone_enc), 'the old key no longer reads it');
  }
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM job_state WHERE key LIKE 'advisor.link.%'").get().n, 0);
  assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM job_state WHERE key='advisor.flow.c1'").get().n, 1, 'nothing else touched');
  assert.equal(h.files.get(R.SQL_FILE), '', 'the SQL file is emptied afterwards');
  assert.equal(h.w.calls.filter(a => a.includes('--file')).length, 1, 'one file, one transaction');
  assert.match(h.lines.join('\n'), /Re-keyed 3 contact\(s\)/);
  const again = harness(sql);
  assert.equal(await R.main(['--apply'], again.deps), 0);
  assert.match(again.lines.join('\n'), /contacts to re-key: 0; already under the new key: 3/);
});

dbTest('rekey refuses to write when a row decrypts with neither key, and a failed transaction changes nothing', async () => {
  const {sql} = await seed();
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES('bad',?,?,'sms','x','x','x')`)
    .run('a'.repeat(64), await encryptPhone(await deriveKeys(Buffer.alloc(32, 3).toString('base64')), '+18055550199'));
  const h = harness(sql);
  assert.equal(await R.main(['--apply'], h.deps), 1);
  assert.match(h.lines.join('\n'), /cannot read contact bad: decrypts with neither key/);
  assert.ok(h.w.calls.every(a => !a.includes('--file')));
  sql.prepare("DELETE FROM advisor_contacts WHERE id='bad'").run();
  const files = new Map(), w = fakeWrangler(sql, files, {failFile: true}), lines = [];
  assert.equal(await R.main(['--apply'], {run: w.run, env, log: l => lines.push(l), write: (p, t) => files.set(p, t)}), 1);
  assert.match(lines.join('\n'), /nothing was changed/);
  assert.equal(sql.prepare('SELECT phone_hash FROM advisor_contacts WHERE id=?').get('c1').phone_hash, await phoneHash(await deriveKeys(OLD), NUMBERS[0]));
});

dbTest('rekey reports a contact made with the old key during the switch as a duplicate instead of colliding', async () => {
  const {sql} = await seed();
  assert.equal(await R.main(['--apply'], harness(sql).deps), 0);
  // A text arrived before the Worker had the new key: a second contact for +18055550101 under the old key.
  const old = await deriveKeys(OLD);
  sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES('dup',?,?,'sms','x','x','x')`).run(await phoneHash(old, NUMBERS[0]), await encryptPhone(old, NUMBERS[0]));
  const h = harness(sql);
  assert.equal(await R.main(['--apply'], h.deps), 1);
  assert.match(h.lines.join('\n'), /contact dup is a duplicate of c1/);
});

test('rekey: argument and SQL guards', () => {
  assert.throws(() => R.parseArgs(['--force']), /unknown option/);
  assert.deepEqual(R.parseArgs([]), {apply: false});
  assert.throws(() => R.sqlFor([{id: "x'; DROP TABLE advisor_contacts; --", oldHash: 'a'.repeat(64), newHash: 'b'.repeat(64), newEnc: 'A'.repeat(40)}]), /unexpected value/);
  assert.match(R.sqlFor([{id: 'c1', oldHash: 'a'.repeat(64), newHash: 'b'.repeat(64), newEnc: 'A'.repeat(40)}]), /WHERE id='c1' AND phone_hash='a{64}';/);
  assert.throws(() => R.parseRows(JSON.stringify([{results: [{id: 'c1', phone_hash: 'nothex', phone_enc: 'A'.repeat(40)}]}])), /unexpected row shape/);
  return assert.rejects(R.plan([], OLD, OLD), /new key is the old key/);
});
