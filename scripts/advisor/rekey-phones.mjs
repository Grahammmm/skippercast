#!/usr/bin/env node
// Re-key every stored phone number to a new ADVISOR_PHONE_KEY
// (docs/operations/runbooks/secrets-rotation.md § ADVISOR_PHONE_KEY;
// docs/legal/threat-model.md § 9.8). ADVISOR_PHONE_KEY derives the key that
// hashes numbers (advisor_contacts.phone_hash, the lookup) and the key that
// encrypts them (phone_enc), so replacing it without this leaves every contact
// unreachable and every number unrecognised.
//
//   read -rs OLD_ADVISOR_PHONE_KEY; export OLD_ADVISOR_PHONE_KEY
//   read -rs NEW_ADVISOR_PHONE_KEY; export NEW_ADVISOR_PHONE_KEY
//   node scripts/advisor/rekey-phones.mjs            # dry run: reads, decrypts, checks, writes nothing
//   node scripts/advisor/rekey-phones.mjs --apply    # writes the new hashes and ciphertexts
//
// It reads every contact with a number (wrangler d1 execute --remote --json),
// decrypts each phone_enc with the old key, re-hashes and re-encrypts with the
// new one and checks the new ciphertext decrypts back to the same number. It
// refuses to write anything if any row cannot be decrypted with either key.
// The writes go to var/rekey-phones.sql and run with `wrangler d1 execute
// --remote --file`, which D1 applies as one transaction (its import refuses a
// BEGIN/COMMIT of its own for that reason): all rows or none. Each UPDATE is
// guarded by the old hash, so a second run changes nothing; rows already under
// the new key are skipped, so it can be re-run after an interruption. Pending
// web phone-link codes (job_state advisor.link.*, 10 minutes) are cleared with
// them. With --apply it reads the table again afterwards and fails unless every
// row now decrypts with the new key and hashes to its stored phone_hash.
//
// Numbers never reach the output: rows are named by contact id only. Needs
// Node 22.18+ (it imports server/advisor/contacts.ts directly) and Wrangler
// credentials for the account (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID).
import {spawnSync} from 'node:child_process';
import {mkdirSync, writeFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
import {deriveKeys, decryptPhone, encryptPhone, phoneHash} from '../../server/advisor/contacts.ts';

export const DATABASE = 'skippercast';
export const SQL_FILE = 'var/rekey-phones.sql';
const USAGE = 'usage: OLD_ADVISOR_PHONE_KEY=... NEW_ADVISOR_PHONE_KEY=... node scripts/advisor/rekey-phones.mjs [--apply]';
const ID = /^[\w-]{1,64}$/, HEX64 = /^[0-9a-f]{64}$/, B64 = /^[A-Za-z0-9+/=_-]{20,200}$/;
export const SELECT = 'SELECT id,phone_hash,phone_enc FROM advisor_contacts WHERE phone_enc IS NOT NULL ORDER BY id';

/** The argv for one remote D1 call. */
export const wranglerArgs = what => ['--yes', 'wrangler', 'd1', 'execute', DATABASE, '--remote', ...(what.file ? ['--file', what.file] : ['--json', '--command', what.command])];

/** Rows from `wrangler d1 execute --json` output ([{results: [...]}]). */
export function parseRows(stdout) {
  const data = JSON.parse(stdout);
  const results = Array.isArray(data) ? data.flatMap(d => d.results ?? []) : data.results ?? [];
  for (const r of results) if (!ID.test(String(r.id)) || (r.phone_hash !== null && !HEX64.test(String(r.phone_hash))) || !B64.test(String(r.phone_enc))) throw Error(`unexpected row shape for contact ${String(r.id).slice(0, 64)}`);
  return results;
}

/**
 * The plan for these rows: {updates: [{id, oldHash, newHash, newEnc}], done: [ids already under the new key],
 * failed: [{id, reason}], duplicates: [{id, of}]} (a new hash some other row already has: a contact made while
 * the switch was in progress, left for the owner to erase).
 */
export async function plan(rows, oldKey, newKey) {
  if (oldKey === newKey) throw Error('the new key is the old key');
  const [before, after] = await Promise.all([deriveKeys(oldKey), deriveKeys(newKey)]);
  const out = {updates: [], done: [], failed: [], duplicates: []};
  const taken = new Map(rows.map(r => [r.phone_hash, r.id]));
  for (const row of rows) {
    let number = null;
    try { number = await decryptPhone(after, row.phone_enc); } catch { number = null; }
    if (number && await phoneHash(after, number) === row.phone_hash) { out.done.push(row.id); continue; }
    try { number = await decryptPhone(before, row.phone_enc); } catch { out.failed.push({id: row.id, reason: 'decrypts with neither key'}); continue; }
    if (row.phone_hash && await phoneHash(before, number) !== row.phone_hash) { out.failed.push({id: row.id, reason: 'phone_hash does not match the old key'}); continue; }
    const newHash = await phoneHash(after, number), newEnc = await encryptPhone(after, number);
    if (await decryptPhone(after, newEnc) !== number) { out.failed.push({id: row.id, reason: 'round trip failed'}); continue; }
    const other = taken.get(newHash);
    if (other && other !== row.id) { out.duplicates.push({id: row.id, of: other}); continue; }
    out.updates.push({id: row.id, oldHash: row.phone_hash, newHash, newEnc});
  }
  return out;
}

/** The SQL file: one guarded UPDATE per contact, then the pending link codes. Values are checked shapes only. */
export function sqlFor(updates) {
  const q = v => `'${String(v).replace(/'/g, "''")}'`;
  const lines = updates.map(u => {
    if (!ID.test(u.id) || !HEX64.test(u.newHash) || !B64.test(u.newEnc) || (u.oldHash !== null && !HEX64.test(u.oldHash))) throw Error(`refusing an unexpected value for contact ${u.id}`);
    return `UPDATE advisor_contacts SET phone_hash=${q(u.newHash)},phone_enc=${q(u.newEnc)} WHERE id=${q(u.id)} AND ${u.oldHash === null ? 'phone_hash IS NULL' : `phone_hash=${q(u.oldHash)}`};`;
  });
  lines.push("DELETE FROM job_state WHERE key LIKE 'advisor.link.%';");
  return lines.join('\n') + '\n';
}

export function parseArgs(argv) {
  const flags = new Set(argv);
  for (const f of flags) if (f !== '--apply') throw Error(`unknown option ${f}\n${USAGE}`);
  return {apply: flags.has('--apply')};
}

function summary(p, log) {
  log(`contacts to re-key: ${p.updates.length}; already under the new key: ${p.done.length}; duplicates: ${p.duplicates.length}; cannot read: ${p.failed.length}`);
  for (const f of p.failed) log(`  cannot read contact ${f.id}: ${f.reason}`);
  for (const d of p.duplicates) log(`  contact ${d.id} is a duplicate of ${d.of} (made during the switch): erase it from the admin contact page, then run again`);
}

export async function main(argv, {run = spawnSync, env = process.env, log = console.log, write = writeFileSync} = {}) {
  const {apply} = parseArgs(argv);
  const oldKey = env.OLD_ADVISOR_PHONE_KEY, newKey = env.NEW_ADVISOR_PHONE_KEY;
  if (!oldKey || !newKey) throw Error(USAGE);
  const read = () => {
    const result = run('npx', wranglerArgs({command: SELECT}), {encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit']});
    if (result.status !== 0) throw Error('reading advisor_contacts failed');
    return parseRows(result.stdout);
  };
  const p = await plan(read(), oldKey, newKey);
  summary(p, log);
  if (p.failed.length) { log('Nothing written: fix or erase the rows above first.'); return 1; }
  if (!apply) { log(`Dry run: add --apply to write ${p.updates.length} row(s) in one transaction.`); return 0; }
  if (!p.updates.length) { log('Nothing to write.'); return p.duplicates.length ? 1 : 0; }
  mkdirSync('var', {recursive: true});
  write(SQL_FILE, sqlFor(p.updates), {mode: 0o600});
  const result = run('npx', wranglerArgs({file: SQL_FILE}), {stdio: 'inherit'});
  if (result.status !== 0) { log('The transaction failed: nothing was changed. The old key is still the live one.'); return result.status ?? 1; }
  write(SQL_FILE, '', {mode: 0o600});   // the file held ciphertexts and hashes only, but nothing needs it now
  const check = await plan(read(), oldKey, newKey);
  const ok = check.updates.length === 0 && check.failed.length === 0;
  log(ok ? `Re-keyed ${p.updates.length} contact(s). Now install the new key: wrangler secret put ADVISOR_PHONE_KEY, then gh secret set ADVISOR_PHONE_KEY.`
    : 'Check after writing found rows still under the old key: run again (a text may have arrived mid-way).');
  summary(check, log);
  return ok && !check.duplicates.length ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main(process.argv.slice(2)).then(code => { process.exitCode = code; }, e => { console.error(e.message); process.exitCode = 2; });
}
