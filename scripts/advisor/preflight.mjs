#!/usr/bin/env node
// Text Advisor launch preflight (docs/plans/text-advisor/11-testing-rollout.md
// § Launch checklist, TA-P1). Reads a deployed SkipperCast and prints every
// launch-checklist item as PASS, FAIL or MANUAL, with what it saw or how to
// check it by hand. Read-only: GET requests only, nothing is sent, approved or
// written, and the session cookie is never printed.
//
//   SKIPPERCAST_SESSION=<the __Host-sc_session cookie value of an admin account> \
//     node scripts/advisor/preflight.mjs [--base https://skippercast.com] [--stage dark|live] [--local]
//
//   --base    the deployment (default https://skippercast.com)
//   --stage   dark: the advisor is on with ADVISOR_REPLIES_ENABLED=false (flip step 3), so replies
//             being off passes; live (default): replies must be on
//   --local   also run the golden conversations from this checkout (node --test)
//
// Without SKIPPERCAST_SESSION the admin items are FAIL ("no session"). The cookie
// comes from a signed-in browser: DevTools > Application > Cookies >
// __Host-sc_session (43 characters). Exit code: 0 when nothing failed, 1 when an
// item failed, 2 on a usage error. MANUAL items never fail the run.
import {existsSync, readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {join} from 'node:path';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
export const COOKIE = '__Host-sc_session';
const DAY = 86400000;
/** 11 § Launch checklist: the pilot species whose rules must be active and fresh. */
export const PILOT_SPECIES = ['rockfish', 'lingcod', 'cabezon', 'halibut', 'salmon', 'dungeness', 'white-seabass', 'yelloweye', 'cowcod', 'canary'];
export const PILOT_JURISDICTION = 'california-central';
export const PILOT_CAPS = {llm: 2000, vision: 400};
export const RULES_FRESH_DAYS = 30;
export const MIN_SKIPPERS = 3;
export const RUNBOOKS = ['advisor-relay-setup', 'advisor-relay-down', 'advisor-port-to-twilio', 'advisor-meta-app-review', 'advisor-queue-stuck'];
const CHECKLIST_DOC = 'docs/plans/text-advisor/11-testing-rollout.md#launch-checklist-ta-p1';

export function parseArgs(argv) {
  const out = {base: 'https://skippercast.com', stage: 'live', local: false, help: false};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--base') out.base = String(argv[++i] ?? '');
    else if (a === '--stage') out.stage = String(argv[++i] ?? '');
    else if (a === '--local') out.local = true;
    else if (a === '--help' || a === '-h') out.help = true;
    else throw Error(`unknown option ${a}`);
  }
  let url;
  try { url = new URL(out.base); } catch { throw Error(`--base must be a URL: ${out.base}`); }
  if (url.protocol !== 'https:' && url.hostname !== 'localhost' && url.hostname !== '127.0.0.1') throw Error('--base must be https (or localhost)');
  out.base = url.origin;
  if (!['dark', 'live'].includes(out.stage)) throw Error('--stage must be dark or live');
  return out;
}

/** GET a path; {status, json, text} (json null when the body is not JSON), or {status: 0, error} on a network failure. */
async function get(fetcher, base, path, cookie = null, {redirect = 'follow'} = {}) {
  try {
    const response = await fetcher(base + path, {headers: {Accept: 'application/json', ...(cookie ? {Cookie: `${COOKIE}=${cookie}`} : {})}, redirect, signal: AbortSignal.timeout(20000)});
    const text = await response.text();
    let json = null;
    try { json = JSON.parse(text); } catch { /* not JSON */ }
    return {status: response.status, json, text, location: response.headers.get('location')};
  } catch (error) {
    return {status: 0, error: String(error?.message ?? error).slice(0, 120)};
  }
}

const row = (id, title, status, detail, how = '') => ({id, title, status, detail, how});

/** The rules check: every pilot species has non-retired rows, all active, not due, reviewed within 30 days, with an https source. */
export function judgeRules(rules, now = Date.now(), species = PILOT_SPECIES) {
  const problems = [];
  const fresh = new Date(now - RULES_FRESH_DAYS * DAY).toISOString();
  for (const key of species) {
    const rows = rules.filter(r => r.species_key === key && r.status !== 'retired');
    if (!rows.length) { problems.push(`${key}: no row`); continue; }
    const bad = rows.filter(r => r.status !== 'active' || r.due || !(String(r.reviewed_at) >= fresh) || !/^https:\/\//.test(r.source_url ?? ''));
    if (bad.length) problems.push(`${key}: ${bad.length} of ${rows.length} not active, due, older than ${RULES_FRESH_DAYS} days or without a source`);
  }
  return problems;
}

/**
 * Every checklist item, in the order of 11 § Launch checklist. `fetcher` is
 * fetch (tests pass a fake); `root` is the checkout for the local file checks.
 */
export async function runPreflight({base, cookie = null, stage = 'live', local = false, fetcher = fetch, root = ROOT, now = Date.now(), runGolden = null} = {}) {
  const out = [];
  const add = (...a) => out.push(row(...a));

  // 1. Deployed.
  const health = await get(fetcher, base, '/api/health');
  if (health.status === 200 && health.json?.build) add('1', 'Deployed', 'pass', `build ${health.json.build}`);
  else add('1', 'Deployed', 'fail', `GET /api/health: ${health.status || health.error}`);
  add('1', 'The deployed build is the main commit with every Text Advisor PR', 'manual', '', 'Actions > Deploy to Cloudflare: the last run is green on the merge commit');

  // 2. Advisor on (public health), relay up.
  const pub = await get(fetcher, base, '/api/advisor/health');
  const on = pub.status === 200 && pub.json?.enabled === true;
  add('2', 'Advisor switched on (ENABLE_ADVISOR, TEXT_ADVISOR_ENABLED)', on ? 'pass' : 'fail',
    on ? `channel ${pub.json.channel}, vision ${(pub.json.providers ?? []).join(',')}` : `GET /api/advisor/health: ${pub.status || pub.error} (404 while TEXT_ADVISOR_ENABLED is off)`);

  // Admin health (needs an admin session).
  const admin = cookie ? await get(fetcher, base, '/api/admin/health', cookie) : null;
  const ah = admin?.status === 200 ? admin.json : null;
  const adminWhy = !cookie ? 'no session (set SKIPPERCAST_SESSION)' : `GET /api/admin/health: ${admin.status || admin.error}${admin.status === 404 ? ' (not an admin, or the advisor is off)' : ''}`;

  // 3. Relay.
  const relay = ah?.relay ?? pub.json?.relay ?? null;
  if (relay) add('3', 'Relay up now', relay.state === 'up' ? 'pass' : 'fail', `state ${relay.state}, checked ${relay.checked_at}${ah?.relay ? `, failures ${ah.relay.failures}` : ''}`);
  else add('3', 'Relay up now', 'fail', on ? 'no relay state yet (BLUEBUBBLES_URL unset, channel not bluebubbles, or no cron tick since the deploy)' : 'advisor off');
  add('3', 'relay-check.mjs PASS on three consecutive days; no advisor_relay_down in 72 h', 'manual', '', 'node scripts/advisor/relay-check.mjs (advisor-relay-setup.md § 11); Workers Logs filter advisor_relay_down');

  // 4. Secrets and variables visible from outside.
  const vcf = await get(fetcher, base, '/contact.vcf');
  add('4', 'ADVISOR_NUMBER set (contact card served)', vcf.status === 200 ? 'pass' : 'fail', `GET /contact.vcf: ${vcf.status || vcf.error}`);
  const text = await get(fetcher, base, '/text', null, {redirect: 'manual'});
  const sms = text.status >= 300 && text.status < 400 && /^sms:/.test(text.location ?? '');
  add('4', '/text deep link redirects to sms:', sms ? 'pass' : 'fail', `GET /text: ${text.status || text.error}`);
  if (ah) {
    add('4', 'Meta secrets set', ah.meta?.configured ? 'pass' : 'fail', ah.meta?.configured ? 'configured' : 'META_* not set');
    add('4', 'Vision provider chain has claude', (ah.vision ?? []).some(v => v.name === 'claude') ? 'pass' : 'fail', (ah.vision ?? []).map(v => `${v.name}${v.down_until ? ' (down)' : ''}`).join(', ') || 'none');
    add('4', 'Instagram webhook secrets (for the inbox, after App Review)', ah.inbox?.webhook_ready ? 'pass' : 'manual', ah.inbox?.webhook_ready ? 'set' : 'not set: needed only for TA-O5');
  } else add('4', 'Secrets seen by the admin health', 'fail', adminWhy);
  add('4', 'Every secret and variable in Owner to-do, D and E is set', 'manual', '', 'gh secret list; gh variable list');

  // 5. Replies and the queue.
  if (ah) {
    const want = stage === 'dark' ? false : true;
    add('5', `Replies ${want ? 'on' : 'off (dark stage)'} (ADVISOR_REPLIES_ENABLED)`, ah.replies_enabled === want ? 'pass' : 'fail', `replies_enabled ${ah.replies_enabled}`);
    const q = ah.queue ?? {};
    add('5', 'Queue healthy (no stale queued, no held outbound)', !q.stale_queued && !q.held_outbound ? 'pass' : 'fail',
      `stale queued ${q.stale_queued ?? '-'}, held outbound ${q.held_outbound ?? '-'}, failed today ${q.failed_today ?? '-'}`);
  } else add('5', 'Replies and queue', 'fail', adminWhy);

  // 6. Rules.
  if (cookie) {
    const rules = await get(fetcher, base, `/api/admin/rules?jurisdiction=${PILOT_JURISDICTION}`, cookie);
    if (rules.status === 200 && Array.isArray(rules.json?.rules)) {
      const problems = judgeRules(rules.json.rules, now);
      add('6', `Rules for the pilot species active and reviewed in the last ${RULES_FRESH_DAYS} days`, problems.length ? 'fail' : 'pass', problems.length ? problems.join('; ') : `${PILOT_SPECIES.length} species ok`);
    } else add('6', 'Rules', 'fail', `GET /api/admin/rules: ${rules.status || rules.error}`);
  } else add('6', 'Rules', 'fail', adminWhy);
  add('6', 'The owner read each pilot row against its CDFW page', 'manual', '', 'Admin > Rules: open the source link, then "Checked, no change" or edit');

  // 7. Wording reviews.
  add('7', 'Wording reviewed by the owner (system, daily and caption prompts, strings, cues, profile copy)', 'manual', '', 'Owner to-do, G; ANTHROPIC_API_KEY=... node scripts/advisor/eval.mjs');

  // 8. Caps.
  if (ah?.caps) {
    const ok = ah.caps.llm?.limit === PILOT_CAPS.llm && ah.caps.vision?.limit === PILOT_CAPS.vision;
    add('8', `Global caps ${PILOT_CAPS.llm} LLM / ${PILOT_CAPS.vision} vision a day`, ok ? 'pass' : 'fail', `llm ${ah.caps.llm?.used}/${ah.caps.llm?.limit}, vision ${ah.caps.vision?.used}/${ah.caps.vision?.limit}`);
  } else add('8', 'Global caps', 'fail', adminWhy);
  add('8', 'Per-contact caps 40 messages / 30 LLM calls a day', 'manual', '', 'gh variable list: ADVISOR_DAILY_MESSAGES_PER_CONTACT and ADVISOR_DAILY_LLM_PER_CONTACT unset (defaults) or 40 and 30');

  // 9. Golden conversations.
  if (local) {
    const result = runGolden ? runGolden(root) : spawnSync(process.execPath, ['--test', '--test-name-pattern', 'golden conversation', join(root, 'tests/test_advisor_engine.mjs')], {cwd: root, encoding: 'utf8'});
    const passed = /# pass (\d+)/.exec(result.stdout ?? '')?.[1], failed = /# fail (\d+)/.exec(result.stdout ?? '')?.[1];
    add('9', 'Golden conversations 1-9 green (this checkout)', result.status === 0 && Number(passed) > 0 ? 'pass' : 'fail', `pass ${passed ?? '-'}, fail ${failed ?? '-'}`);
  } else add('9', 'Golden conversations 1-9 green', 'manual', '', 'node scripts/advisor/preflight.mjs --local, or CI on main (tests/test_advisor_engine.mjs)');

  // 10. Admin.
  add('10', 'The owner has the admin role', ah ? 'pass' : 'fail', ah ? 'the session reads /api/admin/health' : adminWhy);
  add('10', 'Approve one seeded review on production; the admin-test text arrives', 'manual', '', 'Owner to-do, H');

  // 11. Skippers.
  if (cookie) {
    const boats = await get(fetcher, base, '/api/admin/boats', cookie);
    if (boats.status === 200 && Array.isArray(boats.json?.boats)) {
      const verified = boats.json.boats.filter(b => b.status === 'verified');
      const pages = [];
      for (const b of verified) pages.push([b.slug, (await get(fetcher, base, `/boats/${encodeURIComponent(b.slug)}`)).status]);
      const missing = pages.filter(([, s]) => s !== 200).map(([slug, s]) => `${slug} ${s}`);
      add('11', `At least ${MIN_SKIPPERS} verified boats, each with its page`, verified.length >= MIN_SKIPPERS && !missing.length ? 'pass' : 'fail',
        `${verified.length} verified${missing.length ? `; pages failing: ${missing.join(', ')}` : ''}; consent given on ${verified.filter(b => b.consent === 'given').length}`);
    } else add('11', 'Skippers', 'fail', `GET /api/admin/boats: ${boats.status || boats.error}`);
  } else add('11', 'Skippers', 'fail', adminWhy);

  // 12. Instagram and Facebook.
  if (ah?.meta) {
    const ok = ah.meta.configured && ah.meta.quota_total != null && !ah.meta.error;
    add('12', 'Publishing quota visible on health', ok ? 'pass' : 'fail', ok ? `${ah.meta.quota_usage}/${ah.meta.quota_total}` : `configured ${ah.meta.configured}, error ${ah.meta.error ?? '-'}`);
  } else add('12', 'Publishing quota', 'fail', adminWhy);
  add('12', 'Profile (name, bio, link, highlights) live; one test post published and deleted', 'manual', '', '09 § Instagram profile; advisor-meta-app-review.md is later');

  // 13. Media job.
  if (ah?.media_jobs) add('13', 'Media job keeping up (nothing pending)', ah.media_jobs.pending === 0 ? 'pass' : 'fail', `pending ${ah.media_jobs.pending}`);
  else add('13', 'Media job', 'fail', adminWhy);
  add('13', 'Last advisor-media run green; a Story image rendered from a test board; ffmpeg on the runner', 'manual', '', 'Actions > advisor-media; docs/operations/runners.md');

  // 14. Runbooks.
  const missingRunbooks = RUNBOOKS.filter(name => !existsSync(join(root, `docs/operations/runbooks/${name}.md`)));
  add('14', 'Runbooks present', missingRunbooks.length ? 'fail' : 'pass', missingRunbooks.length ? `missing: ${missingRunbooks.join(', ')}` : RUNBOOKS.join(', '));

  // 15. Privacy.
  const privacy = await get(fetcher, base, '/privacy.html');
  const notice = privacy.status === 200 && /id="text-advisor"/.test(privacy.text ?? '') && /Automatic deletion/.test(privacy.text ?? '');
  add('15', 'Privacy notice states the Text Advisor retention', notice ? 'pass' : 'fail', `GET /privacy.html: ${privacy.status || privacy.error}${privacy.status === 200 && !notice ? ' (no retention paragraph)' : ''}`);
  add('15', 'SEND ME MY DATA link and FORGET ME + DELETE tested end to end from the owner\'s phone', 'manual', '', 'Owner to-do, H');

  // 16. Threat model (TA-C5).
  let threat = '';
  try { threat = readFileSync(join(root, 'docs/legal/threat-model.md'), 'utf8'); } catch { /* missing */ }
  add('16', 'Threat model has the Text Advisor section (TA-C5)', /Text Advisor/.test(threat) ? 'pass' : 'fail', /Text Advisor/.test(threat) ? 'present' : 'docs/legal/threat-model.md has no Text Advisor section');

  // 17. Legal copy.
  const draft = /Draft — pending review by counsel/.test(privacy.text ?? '');
  add('17', 'Privacy notice approved by the owner and counsel', 'manual', draft ? 'the notice still carries the draft banner' : '', 'Owner to-do, F');

  // 18. Release.
  add('18', 'CHANGELOG line and a release tag', 'manual', '', 'git tag v0.4.0 on the launch commit (AGENTS.md § Releases)');
  return out;
}

export function formatResults(results) {
  const lines = results.map(r => `${r.status.toUpperCase().padEnd(6)} ${r.id.padStart(2)}  ${r.title}${r.detail ? ` — ${r.detail}` : ''}${r.status === 'manual' && r.how ? `\n            how: ${r.how}` : ''}`);
  const count = s => results.filter(r => r.status === s).length;
  lines.push('', `${count('pass')} pass, ${count('fail')} fail, ${count('manual')} manual. Checklist: ${CHECKLIST_DOC}`);
  return lines.join('\n');
}

async function main() {
  let args;
  try { args = parseArgs(process.argv.slice(2)); } catch (error) { console.error(error.message); return 2; }
  if (args.help) { console.log('SKIPPERCAST_SESSION=... node scripts/advisor/preflight.mjs [--base <url>] [--stage dark|live] [--local]'); return 0; }
  const cookie = (process.env.SKIPPERCAST_SESSION ?? '').trim() || null;
  if (cookie && !/^[\w-]{43}$/.test(cookie)) { console.error('SKIPPERCAST_SESSION must be the 43-character __Host-sc_session value'); return 2; }
  const results = await runPreflight({base: args.base, cookie, stage: args.stage, local: args.local});
  console.log(`Text Advisor preflight: ${args.base} (stage ${args.stage})\n`);
  console.log(formatResults(results));
  return results.some(r => r.status === 'fail') ? 1 : 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) process.exit(await main());
