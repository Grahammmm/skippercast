#!/usr/bin/env node
// Opt-in live eval of the Text Advisor prompt (docs/plans/text-advisor/04-advisor-engine.md
// § Tests). Runs every recorded engine fixture's message (tests/fixtures/advisor/engine/*.json)
// through the real engine against the real Messages API, then prints, per case,
// the recorded reply next to the live one and the checks that fail, for a human
// to judge before a prompt change is merged. It never runs in CI and needs
// ANTHROPIC_API_KEY. Tools behave as in production (stubs answer "not built
// yet"); D1 is an in-memory SQLite with the committed migrations (Node 22.13+).
//
//   ANTHROPIC_API_KEY=... node scripts/advisor/eval.mjs [--case whats-biting] [--model claude-sonnet-5]
//
// Exit code: 0 when every case ran (whatever the diff says), 1 on a setup error.
import {readFileSync, readdirSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const root = new URL('../../', import.meta.url);
const read = p => JSON.parse(readFileSync(new URL(p, root)));

export function parseArgs(argv) {
  const out = {only: null, model: null, help: false};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--case') out.only = argv[++i];
    else if (a === '--model') out.model = argv[++i];
    else if (a === '--help' || a === '-h') out.help = true;
    else throw Error(`unknown option ${a}`);
  }
  return out;
}

/** The checks a live reply should pass, from the fixture's expect block (a subset: links and wording vary). */
export function judge(fixture, reply, intent) {
  const problems = [];
  if (reply.length > 480) problems.push(`over 480 characters (${reply.length})`);
  if (/\*\*|^#|\{\{/m.test(reply)) problems.push('markdown or an unresolved placeholder');
  if (fixture.expect.intent === 'refused' && intent !== 'refused') problems.push(`intent ${intent}, expected refused`);
  for (const s of fixture.expect.reply_not_contains ?? []) if (reply.includes(s)) problems.push(`contains "${s}"`);
  return problems;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) { console.log('ANTHROPIC_API_KEY=... node scripts/advisor/eval.mjs [--case <name>] [--model <id>]'); return 0; }
  if (!process.env.ANTHROPIC_API_KEY) { console.error('ANTHROPIC_API_KEY is not set; this eval calls the real model and never runs in CI.'); return 1; }
  globalThis.REGIONS = {'morro-bay': read('regions/morro-bay/region.json')};
  globalThis.DEPLOYMENT = read('deployments/production.json');
  globalThis.SHELLS = {'/': '/index.html'};
  globalThis.BUILD_ID = 'eval';
  const {advisorDatabase, sqliteUnavailable} = await import(new URL('tests/_advisor_d1.mjs', root));
  if (sqliteUnavailable) { console.error(sqliteUnavailable); return 1; }
  const {runTurn} = await import(new URL('server/advisor/engine.ts', root));
  const dir = new URL('tests/fixtures/advisor/engine/', root);
  const cases = readdirSync(dir).filter(f => f.endsWith('.json') && !f.startsWith('http-')).map(f => [f.replace(/\.json$/, ''), JSON.parse(readFileSync(new URL(f, dir)))])
    .filter(([name]) => !args.only || name === args.only);
  if (!cases.length) { console.error('no matching case'); return 1; }
  let flagged = 0;
  for (const [name, fixture] of cases) {
    const {sql, db} = advisorDatabase(), now = Date.now(), at = new Date(now).toISOString();
    sql.prepare(`INSERT INTO advisor_contacts(id,phone_hash,phone_enc,channel,last_seen_at,created_at,updated_at) VALUES('eval','h','ENC','imessage',?,?,?)`).run(at, at, at);
    if (!fixture.contact?.new) sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,status,created_at) VALUES('prev','eval','in','imessage','hi','done',?)`).run(new Date(now - 3600000).toISOString());
    sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,body,media_json,status,created_at) VALUES('cur','eval','in','imessage',?,?,'processing',?)`)
      .run(fixture.message, fixture.media ? '["m-eval"]' : null, at);
    const env = {DB: db, ANTHROPIC_API_KEY: process.env.ANTHROPIC_API_KEY, ADVISOR_NUMBER: '+15555550199', ...(args.model ? {ADVISOR_MODEL: args.model} : {})};
    const contact = sql.prepare("SELECT * FROM advisor_contacts WHERE id='eval'").get();
    const message = sql.prepare("SELECT * FROM advisor_messages WHERE id='cur'").get();
    const recorded = fixture.exchanges.at(-1).response.body?.content?.filter(b => b.type === 'text').map(b => b.text).join('') ?? '';
    let live = '', intent = '', problems = [];
    try {
      const result = await runTurn({env, contact, message, now});
      live = result.actions.filter(a => a.type === 'send_text').map(a => a.text).at(-1) ?? '';
      intent = result.intent;
      problems = judge(fixture, live, intent);
    } catch (error) { problems = [`error: ${String(error?.message ?? error).slice(0, 200)}`]; }
    if (problems.length) flagged++;
    console.log(`\n=== ${name} (${fixture.description})\n> ${fixture.message}\n--- recorded\n${recorded}\n+++ live (intent ${intent || '-'})\n${live}`);
    console.log(problems.length ? `!!! ${problems.join('; ')}` : 'checks: ok');
  }
  console.log(`\n${cases.length} cases, ${flagged} flagged. Read every diff before changing the prompt.`);
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) process.exit(await main());
