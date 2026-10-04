#!/usr/bin/env node
// Grants (or with --revoke, removes) the Text Advisor admin role for one
// SkipperCast account (docs/plans/text-advisor/02-data-model.md § users).
// Admin is never self-serve: the owner runs this with their own Cloudflare
// credentials. Without --apply it only prints the SQL and the command.
//
//   node scripts/advisor/grant-admin.mjs <user-id> [--revoke] [--apply]
//
// The user id is users.id (shown by GET /api/privacy when signed in). It is
// checked against ^[\w-]{1,64}$ before it goes anywhere near a shell or SQL.
import {spawnSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';

export const DATABASE = 'skippercast';
const USER_ID = /^[\w-]{1,64}$/;
const USAGE = 'usage: node scripts/advisor/grant-admin.mjs <user-id> [--revoke] [--apply]';

/** The UPDATE for this user id; throws for an id that is not ^[\w-]{1,64}$. */
export function roleSql(userId, {revoke = false} = {}) {
  if (typeof userId !== 'string' || !USER_ID.test(userId)) throw Error('user id must match ^[\\w-]{1,64}$');
  return revoke ? `UPDATE users SET role=NULL WHERE id='${userId}' AND role='admin';` : `UPDATE users SET role='admin' WHERE id='${userId}';`;
}

/** The wrangler argv that runs `sql` against the remote D1 database. */
export const wranglerArgs = sql => ['--yes', 'wrangler', 'd1', 'execute', DATABASE, '--remote', '--command', sql];

/** Parses argv into {userId, revoke, apply}; throws with the usage line on anything unexpected. */
export function parseArgs(argv) {
  const flags = new Set(argv.filter(a => a.startsWith('--'))), ids = argv.filter(a => !a.startsWith('--'));
  for (const f of flags) if (!['--revoke', '--apply'].includes(f)) throw Error(`unknown option ${f}\n${USAGE}`);
  if (ids.length !== 1) throw Error(USAGE);
  return {userId: ids[0], revoke: flags.has('--revoke'), apply: flags.has('--apply')};
}

export function main(argv, {run = spawnSync, log = console.log} = {}) {
  const {userId, revoke, apply} = parseArgs(argv);
  const sql = roleSql(userId, {revoke}), args = wranglerArgs(sql);
  log(sql);
  log(`npx ${args.map(a => /^[\w./=-]+$/.test(a) ? a : `"${a}"`).join(' ')}`);
  if (!apply) { log('Dry run: add --apply to run it.'); return 0; }
  // An argv array, no shell: the SQL is one argument and the id was validated above.
  const result = run('npx', args, {stdio: 'inherit'});
  return result.status ?? 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (e) { console.error(e.message); process.exitCode = 2; }
}
