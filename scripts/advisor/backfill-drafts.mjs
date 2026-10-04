#!/usr/bin/env node
// Post drafts for photos queued before TA-S1 (docs/plans/text-advisor/09-social.md
// § Drafts, As built (TA-S1); 10 TA-S1). Phase 2 (TA-I2) put consented skipper
// photos in the feed queue without a draft; this makes the draft and its
// `post` review for each, through the same code the consumer runs
// (server/advisor/social/drafts.ts ensureMediaDraft): a boat's photo or video
// that is queued or approved, whose boat is not rejected and has active photo
// consent; an angler's photo the team approved. Media that already has a post
// is left alone, so a second run changes nothing.
//
//   node scripts/advisor/backfill-drafts.mjs            dry run: what it would draft (reads the remote D1)
//   node scripts/advisor/backfill-drafts.mjs --apply    make the drafts on the remote D1
//   add --local to use the local D1 of `wrangler dev` instead
//
// The owner runs it with their own Cloudflare credentials (wrangler). With
// ANTHROPIC_API_KEY in the environment each caption gets its model line
// (recorded nowhere: the Worker's analytics are not reachable from here, and
// the global LLM cap in D1 still counts each call); without it the fixed line.
// ADVISOR_NUMBER and ADVISOR_REGION_DEFAULT are read from the environment like
// the Worker's vars (the CTA number; the region of an angler without a home port).
import {spawnSync} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const root = new URL('../../', import.meta.url);
export const DATABASE = 'skippercast';
export const LIMIT = 500;
const USAGE = 'usage: node scripts/advisor/backfill-drafts.mjs [--apply] [--local]';

/** argv -> {apply, local}; throws with the usage line on anything else. */
export function parseArgs(argv) {
  for (const a of argv) if (a !== '--apply' && a !== '--local') throw Error(`unknown option ${a}\n${USAGE}`);
  return {apply: argv.includes('--apply'), local: argv.includes('--local')};
}

/** `sql` with each `?` outside a quoted literal replaced by the SQL literal of the next argument (wrangler takes no bindings). */
export function inline(sql, args) {
  let out = '', i = 0, quoted = false;
  for (const ch of sql) {
    if (ch === "'") quoted = !quoted;
    if (ch === '?' && !quoted) {
      if (i >= args.length) throw Error('more placeholders than arguments');
      const v = args[i++];
      out += v === null || v === undefined ? 'NULL' : typeof v === 'number' ? (Number.isFinite(v) ? String(v) : 'NULL') : typeof v === 'boolean' ? (v ? '1' : '0') : `'${String(v).replaceAll("'", "''")}'`;
    } else out += ch;
  }
  if (i !== args.length) throw Error('more arguments than placeholders');
  return out;
}

/** A D1-shaped database over `wrangler d1 execute --json` (one call per statement; a batch is one call). */
export function wranglerD1({local = false, run = spawnSync} = {}) {
  const exec = sql => {
    const r = run('npx', ['--yes', 'wrangler', 'd1', 'execute', DATABASE, local ? '--local' : '--remote', '--json', '--command', sql], {encoding: 'utf8', maxBuffer: 64 * 1024 * 1024});
    if (r.status !== 0) throw Error(`wrangler d1 execute failed: ${String(r.stderr || r.stdout).slice(0, 400)}`);
    return JSON.parse(r.stdout);
  };
  const statement = sql => ({
    args: [],
    bind(...a) { this.args = a; return this; },
    text() { return inline(sql, this.args); },
    async first() { return exec(this.text()).at(-1)?.results?.[0] ?? null; },
    async all() { return {results: exec(this.text()).at(-1)?.results ?? []}; },
    async run() { return {meta: {changes: exec(this.text()).at(-1)?.meta?.changes ?? 0}}; },
  });
  return {
    prepare: statement,
    async batch(statements) { return exec(statements.map(s => s.text()).join(';\n')).map(r => ({meta: {changes: r?.meta?.changes ?? 0}})); },
  };
}

export const CANDIDATES_SQL = `SELECT m.id,m.boat_id,m.kind,m.publish_state,b.status AS boat_status,b.consent_photos_at,b.consent_revoked_at,
    EXISTS (SELECT 1 FROM advisor_posts p WHERE EXISTS (SELECT 1 FROM json_each(p.media_json) j WHERE j.value=m.id)) AS has_post
  FROM advisor_media m LEFT JOIN advisor_boats b ON b.id=m.boat_id
  WHERE m.publish_state IN ('queued','approved') AND m.kind IN ('image','video') ORDER BY m.created_at,m.id LIMIT ${LIMIT}`;

const consentActive = b => Boolean(b.consent_photos_at) && (!b.consent_revoked_at || b.consent_revoked_at < b.consent_photos_at);
/** Why a candidate row gets no draft, or null when it gets one (ensureMediaDraft's checks, read-only). */
export function skipReason(row) {
  if (row.has_post) return 'has-post';
  if (row.boat_id) {
    if (!row.boat_status || row.boat_status === 'rejected') return 'boat';
    return consentActive(row) ? null : 'no-consent';
  }
  return row.publish_state === 'approved' ? null : 'not-approved';
}

/**
 * The backfill on a D1-shaped `env.DB`: the candidates, then (with apply)
 * ensureMediaDraft for each eligible one. Returns {candidates, eligible,
 * created, exists, skipped: {reason: n}}.
 */
export async function backfill(env, {apply = false, now = Date.now(), log = () => {}, fetcher} = {}) {
  const {ensureMediaDraft} = await import(new URL('server/advisor/social/drafts.ts', root).href);
  const rows = (await env.DB.prepare(CANDIDATES_SQL).all()).results;
  const out = {candidates: rows.length, eligible: 0, created: 0, exists: 0, skipped: {}};
  for (const row of rows) {
    const reason = skipReason(row);
    if (reason) { out.skipped[reason] = (out.skipped[reason] ?? 0) + 1; continue; }
    out.eligible++;
    if (!apply) { log(`would draft ${row.kind === 'video' ? 'a reel' : 'a post'} for media ${row.id}${row.boat_id ? ` (boat ${row.boat_id})` : ' (angler)'}`); continue; }
    const result = await ensureMediaDraft(env, row.id, {now, createdBy: 'engine', ...(fetcher ? {fetcher} : {})});
    if (result.status === 'skipped') out.skipped[result.reason] = (out.skipped[result.reason] ?? 0) + 1;
    else { out[result.status]++; log(`${result.status === 'created' ? 'drafted' : 'already had'} post ${result.postId} for media ${row.id}`); }
  }
  return out;
}

export async function main(argv, {env = process.env, db, log = console.log, now = Date.now()} = {}) {
  const {apply, local} = parseArgs(argv);
  const read = p => JSON.parse(readFileSync(new URL(p, root), 'utf8'));
  // The region manifests the Worker build injects (answers/regions.ts reads REGIONS for a boat's time zone).
  globalThis.REGIONS ??= {'morro-bay': read('regions/morro-bay/region.json')};
  const workerEnv = {DB: db ?? wranglerD1({local}), ANTHROPIC_API_KEY: env.ANTHROPIC_API_KEY, ADVISOR_NUMBER: env.ADVISOR_NUMBER,
    ADVISOR_REGION_DEFAULT: env.ADVISOR_REGION_DEFAULT, ADVISOR_MODEL: env.ADVISOR_MODEL, ADVISOR_GLOBAL_DAILY_LLM: env.ADVISOR_GLOBAL_DAILY_LLM};
  const result = await backfill(workerEnv, {apply, now, log});
  log(JSON.stringify(result));
  if (!apply) log(`Dry run: ${result.eligible} draft(s) to make. Add --apply to make them.`);
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  try { process.exit(await main(process.argv.slice(2))); }
  catch (e) { console.error(String(e?.message ?? e)); process.exit(1); }
}
