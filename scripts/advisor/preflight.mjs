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
//   --report  launch status: every plan row and § Owner to-do item as pass, fail, blocked or owner-only
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
    else if (a === '--report') out.report = true;
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
export async function runPreflight({base, cookie = null, stage = 'live', local = false, fetcher = fetch, root = ROOT, now = Date.now(), runGolden = null, sink = []} = {}) {
  const out = sink; // --report passes its own array so rows already checked survive a check that throws
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

// ---- --report: one launch-status view (plan: 11 § Launch checklist and § Owner to-do) ----
export const PLAN_DOC = 'docs/plans/text-advisor/11-testing-rollout.md';
/** The golden conversations the plan numbers 1-9; fewer passing tests than this cannot be "1-9 green". */
export const MIN_GOLDEN = 9;
/** What a passing row does NOT prove; printed beside it. */
export const LIMITS = {
  9: 'proves the golden-conversation tests pass in THIS checkout; not that the deployed build matches it, nor how the live model behaves',
  11: 'proves enough boats are verified and their pages answer 200; not that invitations were sent or accepted, consent, the 3-5 upper bound, or that a boat is a real skipper',
};
const RANK = {fail: 0, blocked: 1, 'owner-only': 2, pass: 3};
const plain = s => s.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/[*`]/g, '').replace(/\s+/g, ' ').trim();
const shortName = s => { const t = plain(s).replace(/^B\d+\.\s*/, '').split(/:\s|;\s|\(| — /)[0].trim(); return t.length > 60 ? `${t.slice(0, 60).replace(/\s\S*$/, '')}…` : t; };

/** Mask the session value, the cookie assignment, +E.164 numbers and long secret-shaped tokens (ALL_CAPS variable names stay). */
export function redact(text, cookie = null) {
  let s = String(text ?? '');
  if (cookie) s = s.split(cookie).join('[redacted]');
  return s.replace(new RegExp(`${COOKIE}=[^\\s;,]+`, 'g'), `${COOKIE}=[redacted]`).replace(/\+\d{7,}/g, '[redacted]')
    .replace(/[A-Za-z0-9_-]{32,}/g, m => (/^[A-Z][A-Z0-9_]*$/.test(m) ? m : '[redacted]'));
}

/** Read the readiness table and the § Owner to-do items from the plan; throws naming a row it cannot read. */
export function parsePlan(md) {
  const section = title => { const m = new RegExp(`^## ${title}.*$`, 'm').exec(md); return m ? md.slice(m.index + m[0].length).split(/^## /m)[0] : ''; };
  const rows = [];
  for (const line of section('Launch checklist').split('\n').filter(l => l.startsWith('|'))) {
    const cells = line.replace(/^\||\|\s*$/g, '').split('|').map(c => c.trim());
    if (cells[0] === '#' || /^:?-+:?$/.test(cells[0])) continue;
    if (cells.length !== 4 || !/^\d{1,2}$/.test(cells[0]) || !cells[1] || !cells[2]) throw Error(`readiness table row could not be parsed: ${plain(line).slice(0, 90)}`);
    if (rows.some(r => r.id === cells[0])) throw Error(`readiness row ${cells[0]} appears twice`);
    rows.push({id: cells[0], name: shortName(cells[1]), byHand: plain(/by hand:\s*(.*)$/.exec(cells[2])?.[1] ?? '')});
  }
  if (!rows.length) throw Error(`no readiness rows parsed from ${PLAN_DOC} (§ Launch checklist table)`);
  const owner = [];
  let sec = '', n = 0;
  for (const line of section('Owner to-do').split('\n')) {
    const h = /^### ([A-Z])\./.exec(line);
    if (h) { sec = h[1]; n = 0; continue; }
    const m = /^- \[( |x)\] (.+)$/.exec(line);
    if (!m) continue;
    const id = /^B\d+(?=\.)/.exec(m[2])?.[0] ?? `${sec}${++n}`;
    owner.push({id, name: shortName(m[2]), step: `${m[1] === 'x' ? '(ticked in the plan, not verified) ' : ''}${plain(m[2])}${m[2].endsWith(':') ? ' (commands follow in the plan)' : ''}`});
  }
  if (!owner.length) throw Error(`no § Owner to-do items parsed from ${PLAN_DOC}`);
  return {rows, owner};
}

/** Fold the preflight results into one state per plan row: fail > blocked > owner-only > pass. */
export function buildReport({rows, owner}, results, {thrown = null, cookie = null} = {}) {
  const lastId = results.at(-1)?.id;
  const why = thrown ? `a check threw: ${redact(thrown, cookie).slice(0, 160)}` : null;
  const done = rows.map(r => {
    const parts = results.filter(x => x.id === r.id).map(x => {
      let state = x.status === 'manual' ? 'owner-only' : x.status === 'fail' && /^no session/.test(x.detail) ? 'blocked' : x.status, detail = x.detail;
      // The check only needs one passing test; the plan needs nine conversations. Judged here so --local keeps its behaviour.
      if (r.id === '9' && state === 'pass' && Number(/^pass (\d+)/.exec(x.detail)?.[1]) < MIN_GOLDEN) { state = 'fail'; detail += `; the plan needs at least ${MIN_GOLDEN} passing`; }
      return {state, text: state === 'owner-only' ? `by hand: ${x.how}${detail ? ` (${detail})` : ''}` : `check ${x.title}${detail ? ` (${detail})` : ''}`};
    });
    if (why && r.id === lastId) parts.push({state: 'fail', text: `this row may be incomplete, ${why}`});
    else if (why && !parts.length) parts.push({state: 'fail', text: `not checked, ${why}`});
    else if (!parts.length && !r.byHand) parts.push({state: 'fail', text: 'no preflight check covers this row'});
    // The plan names a by-hand step this row has not reported: the row is not done until a person does it.
    if (r.byHand && !parts.some(p => p.state === 'owner-only')) parts.push({state: 'owner-only', text: `by hand: ${r.byHand}`});
    const state = parts.reduce((w, p) => (RANK[p.state] < RANK[w] ? p.state : w), 'pass');
    const limit = state !== 'fail' && LIMITS[r.id] && parts.some(p => p.state === 'pass') ? ` ; does not prove: ${LIMITS[r.id]}` : '';
    return {id: r.id, name: r.name, state, text: parts.map(p => `[${p.state}] ${p.text}`).join(' ; ') + limit};
  });
  const items = owner.map(o => ({id: o.id, name: o.name, state: 'owner-only', text: `by hand: ${o.step}`}));
  const ordered = [...done.filter(r => r.state !== 'owner-only'), ...done.filter(r => r.state === 'owner-only'), ...items];
  return {rows: ordered, unplanned: [...new Set(results.map(x => x.id))].filter(id => !rows.some(r => r.id === id))};
}

export function formatReport({rows, unplanned}, cookie = null) {
  const count = s => rows.filter(r => r.state === s).length;
  const bad = count('fail') + count('blocked');
  const lines = rows.map(r => `${r.state.toUpperCase().padEnd(10)} ${r.id.padStart(3)}  ${r.name} :: ${r.text}`);
  lines.push('', `${count('pass')} pass, ${count('fail')} fail, ${count('blocked')} blocked, ${count('owner-only')} owner-only (plan rows and Owner to-do items).`);
  if (unplanned.length) lines.push(`Checks ran for rows not in the plan table (ignored): ${unplanned.join(', ')}`);
  lines.push(bad ? 'NOT READY: fix the fail and blocked lines first.' : count('owner-only') ? 'NOT READY: only owner-only steps remain; they are G\'s.' : 'READY');
  return redact(lines.join('\n'), cookie);
}

/** The --report run: {text, exitCode}. Throws (naming the row) when the plan cannot be parsed. */
export async function launchStatus({base, cookie = null, root = ROOT, ...rest} = {}) {
  const plan = parsePlan(readFileSync(join(root, PLAN_DOC), 'utf8'));
  const sink = [];
  let thrown = null;
  try { await runPreflight({base, cookie, root, sink, ...rest}); } catch (error) { thrown = `${error?.name ?? 'Error'}: ${error?.message ?? error}`; }
  const report = buildReport(plan, sink, {thrown, cookie});
  return {text: formatReport(report, cookie), exitCode: report.rows.some(r => r.state === 'fail' || r.state === 'blocked') ? 1 : 0};
}

async function main() {
  let args;
  try { args = parseArgs(process.argv.slice(2)); } catch (error) { console.error(error.message); return 2; }
  if (args.help) { console.log('SKIPPERCAST_SESSION=... node scripts/advisor/preflight.mjs [--base <url>] [--stage dark|live] [--local] [--report]'); return 0; }
  const cookie = (process.env.SKIPPERCAST_SESSION ?? '').trim() || null;
  if (cookie && !/^[\w-]{43}$/.test(cookie)) { console.error('SKIPPERCAST_SESSION must be the 43-character __Host-sc_session value'); return 2; }
  if (args.report) {
    try {
      const {text, exitCode} = await launchStatus({base: args.base, cookie, stage: args.stage, local: args.local});
      console.log(`Text Advisor launch status: ${args.base} (stage ${args.stage})\n`);
      console.log(text);
      return exitCode;
    } catch (error) { console.error(`Text Advisor launch status: ${redact(error.message, cookie)}`); return 1; }
  }
  const results = await runPreflight({base: args.base, cookie, stage: args.stage, local: args.local});
  console.log(`Text Advisor preflight: ${args.base} (stage ${args.stage})\n`);
  console.log(formatResults(results));
  return results.some(r => r.status === 'fail') ? 1 : 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) process.exit(await main());
