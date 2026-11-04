// The launch-status report (scripts/advisor/preflight.mjs --report; 11 § Launch checklist and § Owner to-do):
// offline against a fake deployment and a temporary checkout. Every plan row and owner item gets exactly one of
// pass / fail / owner-only / blocked; nothing is "unknown", omitted or printed as a secret; a check never reads
// more ready than its evidence.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {launchStatus, parseArgs, parsePlan, runPreflight, PLAN_DOC, RUNBOOKS, PILOT_SPECIES} from '../scripts/advisor/preflight.mjs';

const BASE = 'https://example.test', SESSION = 'Ab1'.repeat(14) + 'Z', NOW = Date.parse('2026-10-20T16:00:00Z');
const PLAN = readFileSync(fileURLToPath(new URL(`../${PLAN_DOC}`, import.meta.url)), 'utf8');
const COOKIE_HEADER = '__Host-sc_session=';
const GOLDEN = n => () => ({status: 0, stdout: `# pass ${n}\n# fail 0\n`});

function checkout({plan = PLAN, runbooks = RUNBOOKS} = {}) {
  const root = mkdtempSync(join(tmpdir(), 'launch-status-'));
  for (const d of ['docs/operations/runbooks', 'docs/legal', 'docs/plans/text-advisor']) mkdirSync(join(root, d), {recursive: true});
  for (const name of runbooks) writeFileSync(join(root, `docs/operations/runbooks/${name}.md`), '# x\n');
  writeFileSync(join(root, 'docs/legal/threat-model.md'), '## Text Advisor\n');
  writeFileSync(join(root, PLAN_DOC), plan);
  return root;
}
function deployment(overrides = {}, boats = ['one', 'two', 'three']) {
  const health = {replies_enabled: true, relay: {state: 'up', failures: 0, checked_at: 'x'}, queue: {stale_queued: 0, held_outbound: 0}, vision: [{name: 'claude'}],
    caps: {llm: {used: 1, limit: 2000}, vision: {used: 1, limit: 400}}, media_jobs: {pending: 0}, meta: {configured: true, quota_usage: 1, quota_total: 50, page_token: 'EAAB' + 'q9Z'.repeat(20)}, inbox: {webhook_ready: true}};
  const routes = {
    '/api/health': [200, {build: 'b1'}], '/api/advisor/health': [200, {enabled: true, channel: 'bluebubbles', providers: ['claude']}], '/api/admin/health': [200, health],
    '/api/admin/rules?jurisdiction=california-central': [200, {rules: PILOT_SPECIES.map(k => ({species_key: k, status: 'active', due: false, reviewed_at: '2026-10-10T00:00:00Z', source_url: 'https://wildlife.ca.gov/x'}))}],
    '/api/admin/boats': [200, {boats: boats.map(slug => ({slug, status: 'verified'})).concat([{slug: 'invited', status: 'pending'}])}],
    '/contact.vcf': [200, 'BEGIN:VCARD'], '/text': [302, '', {location: 'sms:+15550100'}],
    '/privacy.html': [200, '<h2 id="text-advisor">x</h2><p>Automatic deletion.</p>'], ...Object.fromEntries(boats.map(s => [`/boats/${s}`, [200, '<html>']])), ...overrides,
  };
  return async url => { const [status, body, headers = {}] = routes[url.slice(BASE.length)] ?? [404, {}]; return new Response(typeof body === 'string' ? body : JSON.stringify(body), {status, headers}); };
}
const run = async (o = {}) => {
  const {plan, runbooks, boats, routes, ...rest} = o;
  const r = await launchStatus({base: BASE, cookie: SESSION, fetcher: deployment(routes, boats), root: checkout({plan, runbooks}), now: NOW, local: true, runGolden: GOLDEN(11), ...rest});
  return {...r, lines: r.text.split('\n'), row: id => r.text.split('\n').find(l => new RegExp(`^\\S+\\s+${id}  `).test(l))};
};
const stateOf = line => line?.split(/\s+/)[0];

test('the real plan parses: 18 numbered rows and the owner items, in the plan\'s order', () => {
  const {rows, owner} = parsePlan(PLAN);
  assert.deepEqual(rows.map(r => r.id), Array.from({length: 18}, (_, i) => String(i + 1)));
  assert.deepEqual(owner.slice(0, 2).map(o => o.id), ['A1', 'A2']);
  assert.ok(owner.some(o => o.id === 'B7') && owner.some(o => o.id === 'H1') && owner.length >= 40);
});

test('every row and owner item has one of the four states, none says unknown, owner-only rows come last, no secret value is printed', async () => {
  const {text, lines, exitCode, row} = await run();
  const entries = lines.filter(l => /^(PASS|FAIL|OWNER-ONLY|BLOCKED)\s/.test(l));
  assert.equal(entries.length, 18 + parsePlan(PLAN).owner.length);
  assert.ok(!/unknown/i.test(text));
  const states = entries.map(stateOf);
  assert.ok(states.every(s => ['PASS', 'FAIL', 'OWNER-ONLY', 'BLOCKED'].includes(s)));
  assert.ok(states.lastIndexOf('PASS') < states.indexOf('OWNER-ONLY'));
  assert.equal(exitCode, 0);
  assert.match(lines.at(-1), /^NOT READY: only owner-only steps remain/);
  assert.equal(stateOf(row('14')), 'PASS'); assert.equal(stateOf(row('5')), 'PASS');
  assert.ok(!text.includes(SESSION) && !text.includes('EAAB') && !/\+\d{7,}/.test(text), 'no cookie, token or number');
  for (const m of text.match(/[A-Za-z0-9_-]{32,}/g) ?? []) assert.match(m, /^[A-Z][A-Z0-9_]*$/, 'only ALL_CAPS variable names are long');
});

test('edge 1: a readiness row the parser cannot read fails the run naming that row', async () => {
  await assert.rejects(run({plan: PLAN.replace(/^\| 7 \| Wording reviewed by the owner \| by hand: .*$/m, '| 7 | Wording reviewed by the owner |')}), /could not be parsed: \| 7 \| Wording reviewed/);
  await assert.rejects(run({plan: PLAN.replace('| 9 | Golden', '| nine | Golden')}), /could not be parsed.*nine/);
});

test('edge 5: zero rows parsed, or no owner items, fails the run; an empty report is never a pass', async () => {
  await assert.rejects(run({plan: PLAN.replace(/^\| \d+ \|.*$/gm, '')}), /no readiness rows parsed/);
  await assert.rejects(run({plan: PLAN.replace(/^- \[.\] .*$/gm, '')}), /no § Owner to-do items parsed/);
});

test('a row removed from the plan leaves the report; a row added without a check is fail, with a by-hand step owner-only', async () => {
  const gone = await run({plan: PLAN.replace(/^\| 12 \|.*$/m, '')});
  assert.equal(gone.row('12'), undefined); assert.match(gone.text, /not in the plan table \(ignored\): 12/);
  const added = await run({plan: PLAN.replace(/^\| 18 \|.*$/m, m => `${m}\n| 19 | New row | preflight: nothing yet | x |\n| 20 | Hand row | by hand: do the thing | x |`)});
  assert.equal(stateOf(added.row('19')), 'FAIL'); assert.match(added.row('19'), /no preflight check covers this row/);
  assert.equal(stateOf(added.row('20')), 'OWNER-ONLY'); assert.match(added.row('20'), /by hand: do the thing/);
});

test('edge 2 and 3: a check that throws is a fail with its error, the cookie inside the error is masked, later rows are not dropped or passed', async () => {
  const {row, exitCode, text} = await run({runGolden: () => { throw new Error(`spawn failed for ${COOKIE_HEADER}${SESSION} at +15550100123`); }});
  assert.equal(exitCode, 1);
  assert.equal(stateOf(row('9')), 'FAIL'); assert.match(row('9'), /this row may be incomplete|not checked/);
  assert.equal(stateOf(row('10')), 'FAIL'); assert.match(row('10'), /not checked, a check threw: Error: spawn failed for/);
  assert.equal(stateOf(row('18')), 'FAIL');
  assert.ok(!text.includes(SESSION) && !text.includes('+15550100123'));
  const net = await run({fetcher: async () => { throw new Error(`socket reset sending ${COOKIE_HEADER}${SESSION}`); }});
  assert.ok(!net.text.includes(SESSION)); assert.equal(stateOf(net.row('1')), 'FAIL'); assert.match(net.row('1'), /socket reset/);
});

test('edge 4: a missing runbook is a row 14 fail naming the file', async () => {
  const {row} = await run({runbooks: RUNBOOKS.filter(n => n !== 'advisor-queue-stuck')});
  assert.equal(stateOf(row('14')), 'FAIL'); assert.match(row('14'), /missing: advisor-queue-stuck/);
});

test('edge 6: --local keeps its shape; --report only adds its flag and shares the checks', async () => {
  assert.deepEqual(parseArgs([]), {base: 'https://skippercast.com', stage: 'live', local: false, help: false});
  assert.equal(parseArgs(['--report']).report, true);
  const sink = [], results = await runPreflight({base: BASE, cookie: SESSION, fetcher: deployment(), root: checkout(), now: NOW, sink});
  assert.equal(results, sink); assert.ok(results.every(r => ['pass', 'fail', 'manual'].includes(r.status)));
});

test('golden conversations (row 9) never read greener than the evidence', async () => {
  assert.equal(stateOf((await run({runGolden: GOLDEN(11)})).row('9')), 'PASS');
  assert.match((await run()).row('9'), /does not prove: .*THIS checkout/);
  for (const result of [GOLDEN(1), GOLDEN(8), GOLDEN(0), () => ({status: 1, stdout: '# pass 11\n# fail 1\n'}), () => ({status: 0, stdout: ''})]) {
    const r = await run({runGolden: result});
    assert.equal(stateOf(r.row('9')), 'FAIL', JSON.stringify(result())); assert.equal(r.exitCode, 1);
  }
  const noLocal = await run({local: false});
  assert.equal(stateOf(noLocal.row('9')), 'OWNER-ONLY'); assert.match(noLocal.row('9'), /by hand: .*preflight\.mjs --local/);
});

test('invitations (row 11) never read greener than the evidence', async () => {
  assert.equal(stateOf((await run()).row('11')), 'PASS');
  assert.match((await run()).row('11'), /does not prove: .*invitations were sent or accepted/);
  assert.equal(stateOf((await run({boats: ['one', 'two']})).row('11')), 'FAIL', 'a pending invitation is not a verified boat');
  assert.equal(stateOf((await run({boats: []})).row('11')), 'FAIL');
  assert.equal(stateOf((await run({routes: {'/boats/two': [404, 'gone']}})).row('11')), 'FAIL');
  assert.equal(stateOf((await run({routes: {'/api/admin/boats': [500, 'oops']}})).row('11')), 'FAIL');
  const blocked = await run({cookie: null});
  assert.equal(stateOf(blocked.row('11')), 'BLOCKED'); assert.equal(blocked.exitCode, 1); assert.match(blocked.lines.at(-1), /^NOT READY: fix the fail and blocked/);
});

test('a row whose automatic check passes still waits when the plan names a by-hand step (row 16, 15)', async () => {
  const r = await run();
  assert.equal(stateOf(r.row('16')), 'OWNER-ONLY'); assert.match(r.row('16'), /\[pass\] check Threat model.*\[owner-only\] by hand: § Owner to-do, A/);
  assert.equal(stateOf(r.row('15')), 'OWNER-ONLY');
});
